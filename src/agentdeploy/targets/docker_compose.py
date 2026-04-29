"""
DockerComposeTarget — generates docker-compose.yml for local development
and staging. Includes the agent container, an optional Redis sidecar
for inter-agent state, and an OTEL collector sidecar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agentdeploy.core.app import AgentApp


@dataclass
class DockerComposeTarget:
    app: AgentApp
    output_dir: str = "."
    network: str = "agent-net"

    _redis: bool = field(default=False, init=False)
    _otel_collector: bool = field(default=False, init=False)
    _extra_services: dict = field(default_factory=dict, init=False)

    def with_redis(self) -> "DockerComposeTarget":
        """Add a Redis sidecar for shared agent state / queue."""
        self._redis = True
        return self

    def with_otel_collector(self) -> "DockerComposeTarget":
        """Add an OpenTelemetry collector sidecar for local trace collection."""
        self._otel_collector = True
        return self

    def with_service(self, name: str, definition: dict) -> "DockerComposeTarget":
        """Add an arbitrary extra service to the compose file."""
        self._extra_services[name] = definition
        return self

    def build(self) -> "DockerComposeResult":
        cfg = self.app.to_config()
        adapter = self.app._adapter
        out = Path(self.output_dir) / cfg.name
        out.mkdir(parents=True, exist_ok=True)

        dockerfile = self._generate_dockerfile(cfg, adapter)
        (out / "Dockerfile").write_text(dockerfile)

        server_code = adapter.entrypoint_code(cfg.name, self.app._port)
        (out / "server.py").write_text(server_code)

        compose = self._compose_manifest(cfg)
        compose_path = out / "docker-compose.yml"
        compose_path.write_text(yaml.dump(compose, default_flow_style=False))

        return DockerComposeResult(
            app_name=cfg.name,
            output_dir=str(out),
            compose_path=str(compose_path),
            next_steps=[
                f"cd {out}",
                "docker compose up --build",
                f"curl http://localhost:{self.app._port}{self.app._health_path}",
            ],
        )

    def _generate_dockerfile(self, cfg, adapter) -> str:
        extras = adapter.pip_extras()
        pip_install = " ".join(extras) if extras else ""
        return f"""FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn{(" " + pip_install) if pip_install else ""}
COPY . .
EXPOSE {self.app._port}
CMD ["python", "server.py"]
"""

    def _compose_manifest(self, cfg) -> dict:
        depends_on = []
        services: dict = {}

        agent_env = dict(cfg.env_vars)
        if self._redis:
            agent_env["REDIS_URL"] = "redis://redis:6379"
            depends_on.append("redis")
        if self._otel_collector:
            agent_env["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://otel-collector:4317"
            depends_on.append("otel-collector")

        agent_service: dict = {
            "build": ".",
            "ports": [f"{self.app._port}:{self.app._port}"],
            "environment": agent_env,
            "networks": [self.network],
            "restart": "unless-stopped",
            "healthcheck": {
                "test": [
                    "CMD", "curl", "-f",
                    f"http://localhost:{self.app._port}{self.app._health_path}"
                ],
                "interval": "30s",
                "timeout": "10s",
                "retries": 3,
            },
        }
        if depends_on:
            agent_service["depends_on"] = depends_on

        services[cfg.name] = agent_service

        if self._redis:
            services["redis"] = {
                "image": "redis:7-alpine",
                "networks": [self.network],
                "restart": "unless-stopped",
            }

        if self._otel_collector:
            services["otel-collector"] = {
                "image": "otel/opentelemetry-collector-contrib:latest",
                "networks": [self.network],
                "ports": ["4317:4317", "4318:4318"],
            }

        services.update(self._extra_services)

        return {
            "version": "3.9",
            "services": services,
            "networks": {self.network: {"driver": "bridge"}},
        }


@dataclass
class DockerComposeResult:
    app_name: str
    output_dir: str
    compose_path: str
    next_steps: list[str]

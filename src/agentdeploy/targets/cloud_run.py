"""
CloudRunTarget — generates a Dockerfile and Cloud Run service YAML
for GCP serverless deployment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agentdeploy.core.app import AgentApp


@dataclass
class CloudRunTarget:
    app: AgentApp
    project: str = ""
    region: str = "us-central1"
    service_name: str = ""

    _max_instances: int = field(default=10, init=False)
    _min_instances: int = field(default=0, init=False)
    _concurrency: int = field(default=80, init=False)
    _output_dir: str = field(default="./deploy", init=False)

    def with_scaling(
        self,
        *,
        min_instances: int = 0,
        max_instances: int = 10,
        concurrency: int = 80,
    ) -> CloudRunTarget:
        self._min_instances = min_instances
        self._max_instances = max_instances
        self._concurrency = concurrency
        return self

    def with_output_dir(self, path: str) -> CloudRunTarget:
        self._output_dir = path
        return self

    def build(self) -> CloudRunResult:
        cfg = self.app.to_config()
        adapter = self.app._adapter
        svc = self.service_name or cfg.name
        image = f"gcr.io/{self.project}/{svc}:{cfg.version}"

        out = Path(self._output_dir) / cfg.name
        out.mkdir(parents=True, exist_ok=True)

        extras = " ".join(adapter.pip_extras())
        dockerfile = f"""FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn {extras}
COPY . .
EXPOSE {self.app._port}
CMD ["python", "server.py"]
"""
        (out / "Dockerfile").write_text(dockerfile)
        server_code = adapter.entrypoint_code(cfg.name, self.app._port)
        (out / "server.py").write_text(server_code)

        service_yaml = self._service_manifest(cfg, svc, image)
        svc_path = out / "service.yaml"
        svc_path.write_text(yaml.dump(service_yaml, default_flow_style=False))

        return CloudRunResult(
            app_name=cfg.name,
            output_dir=str(out),
            image=image,
            next_steps=[
                f"gcloud builds submit --tag {image}",
                f"gcloud run services replace {svc_path} --region {self.region}",
                f"gcloud run services add-iam-policy-binding {svc} "
                f"--region {self.region} --member allUsers --role roles/run.invoker",
            ],
        )

    def _service_manifest(self, cfg, svc: str, image: str) -> dict:
        env_vars = [{"name": k, "value": v} for k, v in cfg.env_vars.items()]
        return {
            "apiVersion": "serving.knative.dev/v1",
            "kind": "Service",
            "metadata": {
                "name": svc,
                "annotations": {
                    "run.googleapis.com/ingress": "all",
                    "run.googleapis.com/region": self.region,
                },
            },
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "autoscaling.knative.dev/minScale": str(self._min_instances),
                            "autoscaling.knative.dev/maxScale": str(self._max_instances),
                        }
                    },
                    "spec": {
                        "containerConcurrency": self._concurrency,
                        "timeoutSeconds": cfg.timeout_seconds,
                        "containers": [{
                            "image": image,
                            "ports": [{"containerPort": self.app._port}],
                            "env": env_vars,
                            "resources": {
                                "limits": {
                                    "memory": f"{cfg.memory_mb}Mi",
                                    "cpu": "1000m",
                                }
                            },
                        }],
                    },
                }
            },
        }


@dataclass
class CloudRunResult:
    app_name: str
    output_dir: str
    image: str
    next_steps: list[str]

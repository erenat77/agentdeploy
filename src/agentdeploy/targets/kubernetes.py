"""
KubernetesTarget — generates production-ready Kubernetes manifests
and a Dockerfile from an AgentApp.

Outputs:
  ./deploy/<name>/Dockerfile
  ./deploy/<name>/k8s/deployment.yaml
  ./deploy/<name>/k8s/service.yaml
  ./deploy/<name>/k8s/hpa.yaml
  ./deploy/<name>/k8s/secret.yaml  (if secrets declared)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agentdeploy.core.app import AgentApp
from agentdeploy.core.hitl import HITLConfig
from agentdeploy.core.observability import OtelConfig


@dataclass
class KubernetesTarget:
    app: AgentApp
    namespace: str = "default"
    image: str = ""
    registry: str = ""

    _replicas: int = field(default=1, init=False)
    _autoscale_min: int = field(default=1, init=False)
    _autoscale_max: int = field(default=5, init=False)
    _autoscale_cpu_pct: int = field(default=70, init=False)
    _hitl: HITLConfig | None = field(default=None, init=False)
    _otel: OtelConfig | None = field(default=None, init=False)
    _output_dir: str = field(default="./deploy", init=False)
    _python_version: str = field(default="3.11", init=False)
    _base_image: str = field(default="python:3.11-slim", init=False)

    def with_replicas(self, count: int) -> KubernetesTarget:
        self._replicas = count
        return self

    def with_autoscale(
        self,
        *,
        min: int = 1,
        max: int = 10,
        cpu_percent: int = 70,
    ) -> KubernetesTarget:
        self._autoscale_min = min
        self._autoscale_max = max
        self._autoscale_cpu_pct = cpu_percent
        return self

    def with_hitl_gate(
        self,
        *,
        webhook: str = "",
        slack_channel: str = "",
        timeout_seconds: int = 3600,
    ) -> KubernetesTarget:
        self._hitl = HITLConfig(
            webhook=webhook,
            slack_channel=slack_channel,
            timeout_seconds=timeout_seconds,
        )
        return self

    def with_telemetry(
        self,
        *,
        endpoint: str = "http://otel-collector:4317",
        service_name: str = "",
    ) -> KubernetesTarget:
        self._otel = OtelConfig(
            endpoint=endpoint,
            service_name=service_name or self.app.name,
        )
        return self

    def with_output_dir(self, path: str) -> KubernetesTarget:
        self._output_dir = path
        return self

    def with_base_image(self, image: str) -> KubernetesTarget:
        self._base_image = image
        return self

    def build(self) -> BuildResult:
        """Generate all deployment artifacts and write them to disk."""
        cfg = self.app.to_config()
        adapter = self.app._adapter
        out = Path(self._output_dir) / cfg.name
        k8s_dir = out / "k8s"
        out.mkdir(parents=True, exist_ok=True)
        k8s_dir.mkdir(parents=True, exist_ok=True)

        files: list[Path] = []

        dockerfile = self._generate_dockerfile(cfg, adapter)
        df_path = out / "Dockerfile"
        df_path.write_text(dockerfile)
        files.append(df_path)

        server_code = adapter.entrypoint_code(cfg.name, self.app._port)
        server_path = out / "server.py"
        server_path.write_text(server_code)
        files.append(server_path)

        deploy_manifest = self._deployment_manifest(cfg)
        dep_path = k8s_dir / "deployment.yaml"
        dep_path.write_text(yaml.dump(deploy_manifest, default_flow_style=False))
        files.append(dep_path)

        svc_manifest = self._service_manifest(cfg)
        svc_path = k8s_dir / "service.yaml"
        svc_path.write_text(yaml.dump(svc_manifest, default_flow_style=False))
        files.append(svc_path)

        hpa_manifest = self._hpa_manifest(cfg)
        hpa_path = k8s_dir / "hpa.yaml"
        hpa_path.write_text(yaml.dump(hpa_manifest, default_flow_style=False))
        files.append(hpa_path)

        if cfg.secrets:
            secret_manifest = self._secret_placeholder(cfg)
            sec_path = k8s_dir / "secret.yaml"
            sec_path.write_text(yaml.dump(secret_manifest, default_flow_style=False))
            files.append(sec_path)

        kustomization = self._kustomization(cfg)
        kust_path = k8s_dir / "kustomization.yaml"
        kust_path.write_text(yaml.dump(kustomization, default_flow_style=False))
        files.append(kust_path)

        return BuildResult(
            app_name=cfg.name,
            target="kubernetes",
            output_dir=str(out),
            files=[str(f) for f in files],
            image=self.image,
            namespace=self.namespace,
            next_steps=self._next_steps(cfg),
        )

    def _generate_dockerfile(self, cfg, adapter) -> str:
        extras = adapter.pip_extras()
        pip_install = " ".join(extras) if extras else ""
        env_lines = "\n".join(
            f'ENV {k}="{v}"' for k, v in cfg.env_vars.items()
        )
        # Healthcheck uses stdlib urllib so we don't need curl — keeps the
        # image slim and avoids an apt-get layer + cache invalidation.
        probe_url = f"http://localhost:{self.app._port}{self.app._health_path}"
        healthcheck_probe = (
            "python -c \"import urllib.request,sys; "
            f"sys.exit(0 if urllib.request.urlopen('{probe_url}',timeout=5)"
            ".status==200 else 1)\""
        )
        return f"""FROM {self._base_image}

WORKDIR /app

COPY requirements.txt* ./
RUN pip install --no-cache-dir fastapi uvicorn{(" " + pip_install) if pip_install else ""} \\
    $(test -f requirements.txt && echo "-r requirements.txt" || echo "")

COPY . .

{env_lines}

EXPOSE {self.app._port}

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \\
    CMD {healthcheck_probe} || exit 1

CMD ["python", "server.py"]
"""

    def _deployment_manifest(self, cfg) -> dict:
        full_image = f"{self.registry}/{self.image}" if self.registry else self.image
        env_vars = [{"name": k, "value": v} for k, v in cfg.env_vars.items()]
        for secret_name in cfg.secrets:
            env_vars.append({
                "name": secret_name.upper().replace("-", "_"),
                "valueFrom": {
                    "secretKeyRef": {
                        "name": f"{cfg.name}-secrets",
                        "key": secret_name,
                    }
                },
            })
        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": cfg.name,
                "namespace": self.namespace,
                "labels": {"app": cfg.name, "version": cfg.version},
            },
            "spec": {
                "replicas": self._replicas,
                "selector": {"matchLabels": {"app": cfg.name}},
                "template": {
                    "metadata": {"labels": {"app": cfg.name, "version": cfg.version}},
                    "spec": {
                        "containers": [{
                            "name": cfg.name,
                            "image": full_image,
                            "imagePullPolicy": "Always",
                            "ports": [{"containerPort": self.app._port}],
                            "env": env_vars,
                            "resources": {
                                "requests": {
                                    "memory": f"{cfg.memory_mb // 2}Mi",
                                    "cpu": "250m",
                                },
                                "limits": {
                                    "memory": f"{cfg.memory_mb}Mi",
                                    "cpu": "1000m",
                                },
                            },
                            "livenessProbe": {
                                "httpGet": {"path": self.app._health_path, "port": self.app._port},
                                "initialDelaySeconds": 15,
                                "periodSeconds": 30,
                            },
                            "readinessProbe": {
                                "httpGet": {"path": self.app._health_path, "port": self.app._port},
                                "initialDelaySeconds": 5,
                                "periodSeconds": 10,
                            },
                        }],
                        "terminationGracePeriodSeconds": cfg.timeout_seconds,
                    },
                },
            },
        }

    def _service_manifest(self, cfg) -> dict:
        return {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": cfg.name, "namespace": self.namespace},
            "spec": {
                "selector": {"app": cfg.name},
                "ports": [{"port": 80, "targetPort": self.app._port, "protocol": "TCP"}],
                "type": "ClusterIP",
            },
        }

    def _hpa_manifest(self, cfg) -> dict:
        return {
            "apiVersion": "autoscaling/v2",
            "kind": "HorizontalPodAutoscaler",
            "metadata": {"name": f"{cfg.name}-hpa", "namespace": self.namespace},
            "spec": {
                "scaleTargetRef": {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "name": cfg.name,
                },
                "minReplicas": self._autoscale_min,
                "maxReplicas": self._autoscale_max,
                "metrics": [{
                    "type": "Resource",
                    "resource": {
                        "name": "cpu",
                        "target": {
                            "type": "Utilization",
                            "averageUtilization": self._autoscale_cpu_pct,
                        },
                    },
                }],
            },
        }

    def _secret_placeholder(self, cfg) -> dict:
        return {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": f"{cfg.name}-secrets",
                "namespace": self.namespace,
            },
            "type": "Opaque",
            "stringData": {s: f"<FILL_IN_{s.upper()}>" for s in cfg.secrets},
        }

    def _kustomization(self, cfg) -> dict:
        resources = ["deployment.yaml", "service.yaml", "hpa.yaml"]
        if cfg.secrets:
            resources.append("secret.yaml")
        return {
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization",
            "resources": resources,
        }

    def _next_steps(self, cfg) -> list[str]:
        full_image = f"{self.registry}/{self.image}" if self.registry else self.image
        steps = [
            f"1. docker build -t {full_image} ./deploy/{cfg.name}",
            f"2. docker push {full_image}",
            f"3. kubectl apply -k ./deploy/{cfg.name}/k8s/",
            f"4. kubectl rollout status deployment/{cfg.name} -n {self.namespace}",
        ]
        if cfg.secrets:
            steps.insert(2, f"   (fill in ./deploy/{cfg.name}/k8s/secret.yaml before applying)")
        return steps


@dataclass
class BuildResult:
    app_name: str
    target: str
    output_dir: str
    files: list[str]
    image: str
    namespace: str
    next_steps: list[str]

    def __repr__(self) -> str:
        files_str = "\n  ".join(self.files)
        steps_str = "\n  ".join(self.next_steps)
        return (
            f"\nBuildResult for '{self.app_name}' -> {self.target}\n"
            f"Output: {self.output_dir}\n"
            f"Files:\n  {files_str}\n"
            f"Next steps:\n  {steps_str}\n"
        )

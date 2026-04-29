"""
deploy() — the fluent builder that returns the right DeployTarget.

Usage:
    deploy(app).to_kubernetes(...).build()
    deploy(app).to_docker_compose(...).build()
    deploy(app).to_lambda(...).build()
    deploy(app).to_cloud_run(...).build()
"""

from __future__ import annotations

from agentdeploy.core.app import AgentApp
from agentdeploy.targets.kubernetes import KubernetesTarget
from agentdeploy.targets.docker_compose import DockerComposeTarget
from agentdeploy.targets.lambda_target import LambdaTarget
from agentdeploy.targets.cloud_run import CloudRunTarget


class DeployBuilder:
    """
    Fluent entry point returned by deploy(app).
    Choose a target then chain configuration methods.
    """

    def __init__(self, app: AgentApp) -> None:
        self._app = app

    def to_kubernetes(
        self,
        *,
        namespace: str = "default",
        image: str = "",
        registry: str = "",
    ) -> KubernetesTarget:
        return KubernetesTarget(
            app=self._app,
            namespace=namespace,
            image=image or f"{self._app.name}:{self._app.version}",
            registry=registry,
        )

    def to_docker_compose(
        self,
        *,
        output_dir: str = ".",
        network: str = "agent-net",
    ) -> DockerComposeTarget:
        return DockerComposeTarget(
            app=self._app,
            output_dir=output_dir,
            network=network,
        )

    def to_lambda(
        self,
        *,
        region: str = "us-east-1",
        function_name: str = "",
        role_arn: str = "",
    ) -> LambdaTarget:
        return LambdaTarget(
            app=self._app,
            region=region,
            function_name=function_name or self._app.name,
            role_arn=role_arn,
        )

    def to_cloud_run(
        self,
        *,
        project: str,
        region: str = "us-central1",
        service_name: str = "",
    ) -> CloudRunTarget:
        return CloudRunTarget(
            app=self._app,
            project=project,
            region=region,
            service_name=service_name or self._app.name,
        )


def deploy(app: AgentApp) -> DeployBuilder:
    """
    Start a deployment pipeline for an AgentApp.

    Returns a DeployBuilder — call .to_kubernetes(), .to_docker_compose(),
    .to_lambda(), or .to_cloud_run() to select your target.
    """
    if app._agent is None:
        raise ValueError(
            f"AgentApp '{app.name}' has no wrapped agent. "
            "Call app.wrap(your_agent) before deploying."
        )
    return DeployBuilder(app)

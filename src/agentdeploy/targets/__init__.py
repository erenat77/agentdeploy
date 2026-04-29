"""Deployment targets: Kubernetes, Docker Compose, AWS Lambda, Google Cloud Run."""

from agentdeploy.targets.cloud_run import CloudRunResult, CloudRunTarget
from agentdeploy.targets.docker_compose import DockerComposeResult, DockerComposeTarget
from agentdeploy.targets.kubernetes import BuildResult, KubernetesTarget
from agentdeploy.targets.lambda_target import LambdaResult, LambdaTarget

__all__ = [
    "KubernetesTarget",
    "BuildResult",
    "DockerComposeTarget",
    "DockerComposeResult",
    "LambdaTarget",
    "LambdaResult",
    "CloudRunTarget",
    "CloudRunResult",
]

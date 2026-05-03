"""
LambdaTarget — generates a Lambda-compatible handler + SAM template.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agentdeploy.core.app import AgentApp


@dataclass
class LambdaTarget:
    app: AgentApp
    region: str = "us-east-1"
    function_name: str = ""
    role_arn: str = ""

    _memory_mb: int = field(default=0, init=False)
    _timeout_seconds: int = field(default=0, init=False)
    _output_dir: str = field(default="./deploy", init=False)

    def with_output_dir(self, path: str) -> LambdaTarget:
        self._output_dir = path
        return self

    def build(self) -> LambdaResult:
        # Fail fast at build time rather than shipping a placeholder ARN that
        # turns into an obscure AWS deploy failure later.
        if not self.role_arn:
            raise ValueError(
                "LambdaTarget requires an IAM role ARN. Pass it via "
                "deploy(app).to_lambda(role_arn='arn:aws:iam::ACCOUNT:role/...'). "
                "The role must allow lambda.amazonaws.com to assume it and "
                "include AWSLambdaBasicExecutionRole at minimum."
            )
        if not self.role_arn.startswith("arn:aws:iam::"):
            raise ValueError(
                f"role_arn must be a full IAM role ARN starting with "
                f"'arn:aws:iam::ACCOUNT:role/...', got: {self.role_arn!r}"
            )

        cfg = self.app.to_config()
        adapter = self.app._adapter
        mem = self._memory_mb or cfg.memory_mb
        timeout = self._timeout_seconds or min(cfg.timeout_seconds, 900)

        out = Path(self._output_dir) / cfg.name
        out.mkdir(parents=True, exist_ok=True)

        handler_code = self._handler_code(cfg, adapter)
        (out / "handler.py").write_text(handler_code)

        sam = self._sam_template(cfg, mem, timeout)
        sam_path = out / "template.yaml"
        sam_path.write_text(yaml.dump(sam, default_flow_style=False))

        dockerfile = self._dockerfile(cfg, adapter)
        (out / "Dockerfile").write_text(dockerfile)

        return LambdaResult(
            app_name=cfg.name,
            output_dir=str(out),
            next_steps=[
                f"cd {out}",
                "sam build",
                f"sam deploy --region {self.region} --stack-name {self.function_name}",
            ],
        )

    def _handler_code(self, cfg, adapter) -> str:
        extras = adapter.pip_extras()
        return f"""
import json, os, asyncio

# Framework imports injected by adapter: {", ".join(extras)}
from agent import agent  # your agent module

def handler(event, context):
    \"\"\"AWS Lambda entrypoint. Accepts API Gateway or direct invocation.\"\"\"
    body = event.get("body", event)
    if isinstance(body, str):
        body = json.loads(body)

    user_input = body.get("input", body)

    try:
        result = asyncio.run(_invoke(user_input))
        return {{
            "statusCode": 200,
            "headers": {{"Content-Type": "application/json"}},
            "body": json.dumps({{"result": result}}),
        }}
    except Exception as e:
        return {{
            "statusCode": 500,
            "body": json.dumps({{"error": str(e)}}),
        }}

async def _invoke(user_input):
    if hasattr(agent, "ainvoke"):
        return await agent.ainvoke(user_input)
    elif hasattr(agent, "kickoff"):
        return str(agent.kickoff(inputs=user_input))
    elif callable(agent):
        result = agent(user_input)
        if asyncio.iscoroutine(result):
            return await result
        return result
    raise RuntimeError("Agent has no invocable method.")
"""

    def _sam_template(self, cfg, mem: int, timeout: int) -> dict:
        env = {k: v for k, v in cfg.env_vars.items()}
        return {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Transform": "AWS::Serverless-2016-10-31",
            "Description": cfg.description or cfg.name,
            "Resources": {
                cfg.name.replace("-", ""): {
                    "Type": "AWS::Serverless::Function",
                    "Properties": {
                        "FunctionName": self.function_name or cfg.name,
                        "Handler": "handler.handler",
                        "Runtime": "python3.11",
                        "MemorySize": mem,
                        "Timeout": timeout,
                        "Role": self.role_arn,
                        "Environment": {"Variables": env},
                        "Events": {
                            "Api": {
                                "Type": "Api",
                                "Properties": {
                                    "Path": "/invoke",
                                    "Method": "post",
                                },
                            }
                        },
                    },
                }
            },
        }

    def _dockerfile(self, cfg, adapter) -> str:
        extras = " ".join(adapter.pip_extras())
        return f"""FROM public.ecr.aws/lambda/python:3.11
RUN pip install --no-cache-dir {extras or ""}
COPY . ${{LAMBDA_TASK_ROOT}}
CMD ["handler.handler"]
"""


@dataclass
class LambdaResult:
    app_name: str
    output_dir: str
    next_steps: list[str]

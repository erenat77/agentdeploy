"""
Unit tests for AgentDeploy SDK core.
Run: pytest tests/ -v
"""

from pathlib import Path

import pytest


class MockCompiledStateGraph:
    async def ainvoke(self, input, config=None):
        return {"result": input}

class MockCrew:
    def kickoff(self, inputs=None):
        return "crew result"

class MockOpenAIAgent:
    pass


def _make_langgraph():
    obj = MockCompiledStateGraph()
    type(obj).__name__ = "CompiledStateGraph"
    type(obj).__module__ = "langgraph.graph.state"
    return obj

def _make_crewai():
    obj = MockCrew()
    type(obj).__name__ = "Crew"
    type(obj).__module__ = "crewai.crew"
    return obj

def _make_openai_agent():
    obj = MockOpenAIAgent()
    type(obj).__module__ = "openai.agents"
    return obj


class TestAgentApp:
    def test_wrap_langgraph_detects_framework(self):
        from agentdeploy import AgentApp
        app = AgentApp("test-app").wrap(_make_langgraph())
        assert app._adapter.framework_name == "langgraph"

    def test_wrap_crewai_detects_framework(self):
        from agentdeploy import AgentApp
        app = AgentApp("test-app").wrap(_make_crewai())
        assert app._adapter.framework_name == "crewai"

    def test_wrap_callable_fallback(self):
        from agentdeploy import AgentApp
        async def my_agent(x): return x
        app = AgentApp("test-app").wrap(my_agent)
        assert app._adapter.framework_name == "callable"

    def test_env_sets_plain_value(self):
        from agentdeploy import AgentApp
        app = AgentApp("test-app").wrap(_make_langgraph())
        app.env("LOG_LEVEL", "DEBUG")
        assert app._env["LOG_LEVEL"] == "DEBUG"

    def test_env_from_secret(self):
        from agentdeploy import AgentApp
        app = AgentApp("test-app").wrap(_make_langgraph())
        app.env("API_KEY", from_secret="my-secret")
        assert "my-secret" in app._secrets
        assert app._env["API_KEY"] == "secret:my-secret"

    def test_resources(self):
        from agentdeploy import AgentApp
        app = AgentApp("test-app").wrap(_make_langgraph())
        app.resources(memory_mb=4096, timeout_seconds=600)
        assert app._memory_mb == 4096
        assert app._timeout_seconds == 600

    def test_deploy_raises_without_wrap(self):
        from agentdeploy import AgentApp, deploy
        app = AgentApp("test-app")
        with pytest.raises(ValueError, match="no wrapped agent"):
            deploy(app)

    def test_repr(self):
        from agentdeploy import AgentApp
        app = AgentApp("my-agent").wrap(_make_langgraph())
        assert "langgraph" in repr(app)
        assert "my-agent" in repr(app)


class TestKubernetesTarget:
    def _make_app(self):
        from agentdeploy import AgentApp
        return (
            AgentApp("test-agent", version="1.0.0")
            .wrap(_make_langgraph())
            .env("LOG_LEVEL", "INFO")
            .env("SECRET_KEY", from_secret="test-secret")
            .resources(memory_mb=2048)
        )

    def test_build_creates_files(self, tmp_path):
        from agentdeploy import deploy
        app = self._make_app()
        (
            deploy(app)
            .to_kubernetes(namespace="test", image="test-agent:1.0.0")
            .with_output_dir(str(tmp_path))
            .build()
        )
        base = tmp_path / "test-agent"
        assert (base / "Dockerfile").exists()
        assert (base / "server.py").exists()
        assert (base / "k8s" / "deployment.yaml").exists()
        assert (base / "k8s" / "service.yaml").exists()
        assert (base / "k8s" / "hpa.yaml").exists()
        assert (base / "k8s" / "secret.yaml").exists()
        assert (base / "k8s" / "kustomization.yaml").exists()

    def test_deployment_yaml_has_correct_name(self, tmp_path):
        import yaml

        from agentdeploy import deploy
        app = self._make_app()
        (
            deploy(app)
            .to_kubernetes(namespace="prod")
            .with_output_dir(str(tmp_path))
            .build()
        )
        dep = yaml.safe_load((tmp_path / "test-agent" / "k8s" / "deployment.yaml").read_text())
        assert dep["metadata"]["name"] == "test-agent"
        assert dep["metadata"]["namespace"] == "prod"

    def test_hpa_respects_autoscale_config(self, tmp_path):
        import yaml

        from agentdeploy import deploy
        app = self._make_app()
        (
            deploy(app)
            .to_kubernetes()
            .with_autoscale(min=2, max=20, cpu_percent=50)
            .with_output_dir(str(tmp_path))
            .build()
        )
        hpa = yaml.safe_load((tmp_path / "test-agent" / "k8s" / "hpa.yaml").read_text())
        assert hpa["spec"]["minReplicas"] == 2
        assert hpa["spec"]["maxReplicas"] == 20

    def test_dockerfile_contains_pip_extras(self, tmp_path):
        from agentdeploy import deploy
        app = self._make_app()
        (
            deploy(app)
            .to_kubernetes()
            .with_output_dir(str(tmp_path))
            .build()
        )
        dockerfile = (tmp_path / "test-agent" / "Dockerfile").read_text()
        assert "langgraph" in dockerfile
        assert "langchain-core" in dockerfile

    def test_dockerfile_uses_urllib_healthcheck_not_curl(self, tmp_path):
        """Generated image should not need curl — stdlib urllib instead."""
        from agentdeploy import deploy
        app = self._make_app()
        deploy(app).to_kubernetes().with_output_dir(str(tmp_path)).build()
        dockerfile = (tmp_path / "test-agent" / "Dockerfile").read_text()
        assert "curl" not in dockerfile
        assert "apt-get" not in dockerfile
        assert "urllib.request" in dockerfile
        assert "HEALTHCHECK" in dockerfile

    def test_build_result_has_next_steps(self, tmp_path):
        from agentdeploy import deploy
        app = self._make_app()
        result = (
            deploy(app)
            .to_kubernetes(image="myimg:latest")
            .with_output_dir(str(tmp_path))
            .build()
        )
        assert len(result.next_steps) >= 4
        assert any("kubectl apply" in s for s in result.next_steps)


class TestDockerComposeTarget:
    def test_build_creates_compose_file(self, tmp_path):
        from agentdeploy import AgentApp, deploy
        app = AgentApp("compose-agent").wrap(_make_crewai())
        result = (
            deploy(app)
            .to_docker_compose(output_dir=str(tmp_path))
            .build()
        )
        assert Path(result.compose_path).exists()

    def test_redis_sidecar_added(self, tmp_path):
        import yaml

        from agentdeploy import AgentApp, deploy
        app = AgentApp("compose-agent").wrap(_make_crewai())
        result = (
            deploy(app)
            .to_docker_compose(output_dir=str(tmp_path))
            .with_redis()
            .build()
        )
        compose = yaml.safe_load(Path(result.compose_path).read_text())
        assert "redis" in compose["services"]

    def test_compose_healthcheck_uses_python_not_curl(self, tmp_path):
        """Compose healthcheck should use stdlib urllib via python -c, not curl."""
        import yaml

        from agentdeploy import AgentApp, deploy
        app = AgentApp("compose-agent").wrap(_make_crewai())
        result = (
            deploy(app)
            .to_docker_compose(output_dir=str(tmp_path))
            .build()
        )
        compose = yaml.safe_load(Path(result.compose_path).read_text())
        test = compose["services"]["compose-agent"]["healthcheck"]["test"]
        assert test[0:3] == ["CMD", "python", "-c"]
        assert "urllib.request" in test[3]
        assert "curl" not in " ".join(test)


class TestLambdaTarget:
    def _make_app(self):
        from agentdeploy import AgentApp
        return AgentApp("lambda-agent").wrap(_make_langgraph())

    def test_build_rejects_missing_role_arn(self):
        from agentdeploy import deploy
        with pytest.raises(ValueError, match="role_arn"):
            deploy(self._make_app()).to_lambda().build()

    def test_build_rejects_malformed_role_arn(self):
        from agentdeploy import deploy
        with pytest.raises(ValueError, match="arn:aws:iam::"):
            deploy(self._make_app()).to_lambda(role_arn="not-an-arn").build()

    def test_build_writes_role_arn_into_sam_template(self, tmp_path):
        import yaml

        from agentdeploy import deploy
        arn = "arn:aws:iam::123456789012:role/lambda-exec"
        deploy(self._make_app()).to_lambda(role_arn=arn).with_output_dir(
            str(tmp_path)
        ).build()
        sam = yaml.safe_load((tmp_path / "lambda-agent" / "template.yaml").read_text())
        role = sam["Resources"]["lambdaagent"]["Properties"]["Role"]
        assert role == arn
        assert "FILL_IN" not in role


class TestAdapterDetection:
    """Regression tests for module-substring false positives in adapter detection."""

    def test_langchain_agents_not_misdetected_as_openai(self):
        from agentdeploy.adapters.registry import AdapterRegistry

        class FakeLangChainAgent:
            def __call__(self, *a, **kw):  # real LC agents are callable
                return None
        FakeLangChainAgent.__module__ = "langchain.agents.tool_calling"

        adapter = AdapterRegistry.detect(FakeLangChainAgent())
        assert adapter.framework_name == "callable"

    def test_llama_index_agent_not_misdetected_as_openai(self):
        from agentdeploy.adapters.registry import AdapterRegistry

        class FakeLlamaIndexAgent:
            def __call__(self, *a, **kw):
                return None
        # contains both "openai" and "agent" substrings — the old code matched this
        FakeLlamaIndexAgent.__module__ = "llama_index.agent.openai_runner"

        adapter = AdapterRegistry.detect(FakeLlamaIndexAgent())
        assert adapter.framework_name == "callable"

    def test_real_openai_agent_still_detected(self):
        from agentdeploy.adapters.registry import AdapterRegistry

        class Agent:
            pass
        Agent.__module__ = "agents"
        adapter = AdapterRegistry.detect(Agent())
        assert adapter.framework_name == "openai-agents"

    def test_openai_agents_submodule_detected(self):
        from agentdeploy.adapters.registry import AdapterRegistry

        class Agent:
            pass
        Agent.__module__ = "openai.agents.runner"
        adapter = AdapterRegistry.detect(Agent())
        assert adapter.framework_name == "openai-agents"


class TestHITLGate:
    @pytest.mark.asyncio
    async def test_console_approve(self, monkeypatch):
        from agentdeploy import HITLDecision, HITLGate
        monkeypatch.setattr("builtins.input", lambda _: "approve")
        gate = HITLGate(console_fallback=True)
        result = await gate.checkpoint({"key": "value"}, description="test")
        assert result.decision == HITLDecision.APPROVE

    @pytest.mark.asyncio
    async def test_console_reject(self, monkeypatch):
        from agentdeploy import HITLDecision, HITLGate
        monkeypatch.setattr("builtins.input", lambda _: "reject")
        gate = HITLGate(console_fallback=True)
        result = await gate.checkpoint("state", description="test")
        assert result.decision == HITLDecision.REJECT

    @pytest.mark.asyncio
    async def test_no_channel_auto_approves(self):
        from agentdeploy import HITLDecision, HITLGate
        gate = HITLGate(console_fallback=False)
        result = await gate.checkpoint("state")
        assert result.decision == HITLDecision.APPROVE


class TestTelemetry:
    @pytest.mark.asyncio
    async def test_trace_context_manager(self):
        from agentdeploy import Telemetry
        telemetry = Telemetry("test-service", enabled=False)
        async with telemetry.trace("test-op", input="hello") as span:
            span.set_tokens(prompt=100, completion=50, model="gpt-4o-mini")
            assert span.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_trace_captures_exceptions(self):
        from agentdeploy import Telemetry
        telemetry = Telemetry("test-service", enabled=False)
        with pytest.raises(ValueError):
            async with telemetry.trace("failing-op"):
                raise ValueError("test error")

# Contributing to AgentDeploy

Thanks for your interest in contributing! This guide covers the basics
for getting set up and the conventions PRs are expected to follow.

## Development setup

```bash
git clone https://github.com/erenat77/agentdeploy
cd agentdeploy

# Create a virtualenv (uv recommended, but venv works fine)
uv venv
source .venv/bin/activate

# Install in editable mode with dev extras
uv pip install -e ".[dev]"

# Install git hooks
pre-commit install
```

## Running checks locally

```bash
ruff check src tests          # lint
ruff format src tests         # auto-format
mypy src/agentdeploy           # type-check
pytest tests/ -v --cov=agentdeploy   # tests + coverage
```

CI runs the same checks on every PR — running them locally before
opening a PR will save round-trips.

## Adding a new framework adapter

1. Add a class in `src/agentdeploy/adapters/registry.py` that
   subclasses `AgentAdapter` and implements `validate`,
   `entrypoint_code`, and `pip_extras`.
2. Add detection logic in `AdapterRegistry.detect`.
3. Add a test in `tests/test_core.py` mirroring the existing
   `test_wrap_*_detects_framework` cases.
4. Update the "Supported frameworks" table in `README.md`.

## Adding a new deploy target

1. Add a class in `src/agentdeploy/targets/<your_target>.py` that
   exposes `with_*` configuration methods and a `build()` method
   returning a result dataclass.
2. Wire a `to_<your_target>(...)` method on `DeployBuilder` in
   `src/agentdeploy/core/deploy.py`.
3. Add tests under `tests/` covering the artifact files and key
   manifest fields.
4. Add a section to the README's "Deploy targets".

## Commit messages

Conventional commits are encouraged but not enforced:

```
feat(targets): add Helm chart output
fix(hitl): timeout no longer rejects auto-approved checkpoints
docs(readme): clarify install with extras
```

## Releasing

Maintainers only. To cut a release:

1. Bump `version` in `pyproject.toml` and `src/agentdeploy/__init__.py`.
2. Update `CHANGELOG.md`: move `Unreleased` items into a new dated section.
3. Commit and tag: `git tag v0.1.1 && git push origin v0.1.1`.
4. The `release.yml` workflow publishes to PyPI on tag push.

## Code of Conduct

Participation in this project is governed by the
[Code of Conduct](CODE_OF_CONDUCT.md).

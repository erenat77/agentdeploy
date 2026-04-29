# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-04-28

### Added
- Initial release.
- `AgentApp` fluent builder with auto-detected framework adapters
  (LangGraph, CrewAI, OpenAI Agents SDK, any async callable).
- `deploy()` pipeline with four targets: Kubernetes, Docker Compose,
  AWS Lambda, Google Cloud Run.
- `HITLGate` human-in-the-loop checkpoint primitive with webhook,
  Slack, and console delivery channels.
- `Telemetry` OpenTelemetry tracing with built-in cost estimation
  for `gpt-4o`, `gpt-4o-mini`, `claude-sonnet-4-6`, `claude-opus-4-6`,
  `gemini-1.5-pro`.
- CLI: `agentdeploy init | validate | build | version`.
- Test suite covering core wrappers, Kubernetes target, Docker Compose
  target, HITL gate, and telemetry.

[Unreleased]: https://github.com/erenat77/agentdeploy/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/erenat77/agentdeploy/releases/tag/v0.1.0

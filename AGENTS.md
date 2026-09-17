# Repository Guidelines

## Project Structure & Module Organization

This repository provides a reusable audit DevContainer, not an application.
- `.devcontainer/`: Dockerfile, runtime configuration, and shared audit instructions in `CLAUDE.md`.
- `scripts/clone.sh`, `scripts/reset.sh`, and `scripts/audit-workflow.py`: container-only cloning, scans, and explicit cleanup.
- `Makefile`: provides `test` and default usage help.
- `tests/`: offline Python workflow regression tests and container smoke checks.
- `README.md`: current setup, workflow, and limitations.

Keep target repositories and generated audit reports outside this template's source tree.

## Build, Test, and Development Commands

- `npx --yes @devcontainers/cli build --workspace-folder .`: build the container image; requires Docker and network access.
- Open this sandbox with **Dev Containers: Reopen in Container**; inside it run `clone.sh <repo-url>`. Keep `/audit` as the VS Code workspace. Export reports before running `reset.sh`.
- `make test`: run host-side workflow regression tests with Python's `unittest`.
- `shellcheck scripts/*.sh tests/container-smoke.sh`: lint Bash scripts; ShellCheck is installed in the container.
- `bash /opt/audit/tests/container-smoke.sh`: verify tools, isolation, and synthetic scanner findings inside this repository's DevContainer.

## Coding Style & Naming Conventions

Use four-space indentation for Bash and Python, and two spaces for JSON. Keep Bash scripts compatible with macOS and Linux; use `set -euo pipefail`, quote path expansions, and preserve executable permissions on entry scripts. Use descriptive snake_case Python functions and `test_*.py` test filenames. Follow existing Dockerfile conventions and isolate Python tools in separate virtual environments.

## Testing Guidelines

Use Python's standard-library `unittest`; no coverage percentage is configured. Add regression cases for changed workflow behavior, particularly URL validation, scanner status handling, report placement, locking, and reset symlink safety. Tests must use temporary fixtures without real credentials, network requests, or commits. For image changes, rebuild and run container smoke checks; record the tested architecture and tool versions.

## Commit & Pull Request Guidelines

Do not commit or push without explicit user approval. When authorized, use concise imperative subjects. PRs should describe the problem, resulting behavior, validation commands, and security implications; link relevant issues and document untested platforms or limitations.

## Security & Configuration

Preserve non-root execution, dropped capabilities, and `no-new-privileges`. Never bake credentials into images or bypass agent permission checks. Forward only needed credentials through `remoteEnv`. Keep documentation synchronized with tool versions, Claude Code and Codex CLI authentication settings, and sandbox limitations.

Audit data lives only in the Docker volume at `/audit`, survives restarts, and is
deleted only by explicit reset. Target configuration stays intact but must not be
activated. Never add startup cleanup or mount target repositories from the host.
The shared operation lock must remain outside `/audit`.

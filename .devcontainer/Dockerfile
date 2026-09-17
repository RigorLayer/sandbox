# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS node
FROM ghcr.io/gitleaks/gitleaks:v8.30.1 AS gitleaks
FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
USER root

ARG CLAUDE_VERSION=2.1.274
ARG CODEX_VERSION=0.154.0
ARG SEMGREP_VERSION=1.177.0

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl git gh jq unzip ripgrep \
    python3 python3-pip python3-venv shellcheck \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/ /usr/local/
COPY --from=gitleaks /usr/bin/gitleaks /usr/local/bin/gitleaks

RUN npm install --global \
    "@anthropic-ai/claude-code@${CLAUDE_VERSION}" \
    "@openai/codex@${CODEX_VERSION}" \
    && npm cache clean --force \
    && python3 -m venv /opt/semgrep \
    && /opt/semgrep/bin/pip install --no-cache-dir "semgrep==${SEMGREP_VERSION}" \
    && ln -s /opt/semgrep/bin/semgrep /usr/local/bin/semgrep

ENV SEMGREP_SEND_METRICS=off \
    SEMGREP_ENABLE_VERSION_CHECK=0 \
    DISABLE_AUTOUPDATER=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# No passwordless elevation in the audit environment.
RUN rm -f /etc/sudoers.d/vscode \
    && mkdir -p /home/vscode/.claude /home/vscode/.codex \
    && chown -R vscode:vscode /home/vscode/.claude /home/vscode/.codex

COPY --chown=vscode:vscode CLAUDE.md /home/vscode/.claude/CLAUDE.md
COPY --chown=vscode:vscode CLAUDE.md /home/vscode/.codex/AGENTS.md
COPY --chown=vscode:vscode CLAUDE.md /opt/audit/INSTRUCTIONS.md

USER vscode
WORKDIR /workspaces
CMD ["sleep", "infinity"]

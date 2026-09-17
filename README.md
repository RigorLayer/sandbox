# Universal AI Audit Sandbox

A reusable VS Code DevContainer for security and code quality audits. Prepare a
disposable target workspace, run static analysis, then investigate findings with
Claude Code or Codex CLI.

## Prerequisites

- Docker Desktop, or Docker Engine on Linux, running with enough disk space for
  the AI tooling and Python dependencies. Start with 4 CPUs and 8 GB RAM.
- VS Code and the **Dev Containers** extension (`ms-vscode-remote.remote-containers`).
- Bash, Git, Make, and Python 3.8+ on the host. On Windows, use WSL2.
- Internet access for image builds, rule downloads, and AI services.

## Start an audit

1. Export only the credentials you need in the host shell used to launch VS Code:

   ```bash
   export ANTHROPIC_API_KEY='your-key'
   export OPENAI_API_KEY='your-key'
   export GH_TOKEN='your-scoped-token' # optional GitHub CLI access
   ```

   Keep credentials out of repository files. Omitted keys do not prevent a build
   or local static analysis. Fully quit and relaunch VS Code from this shell if an
   existing instance has an older environment. Reopen the container after changing
   keys. `remoteEnv` forwards them to VS Code terminals and Dev Containers CLI
   `exec` processes, not to arbitrary `docker exec` sessions.

2. From this template repository, prepare a target:

   ```bash
   make audit TARGET=https://github.com/OWNER/REPOSITORY.git
   # Or snapshot a local folder, including uncommitted and untracked files:
   make audit TARGET='/absolute/path/to/project'
   ```

   Run `make` for usage help. You can also invoke
   `./scripts/audit-setup.sh <repo-url-or-folder>` directly without Make.

   The script prints a unique `audit-<name>-<UTC timestamp>-<suffix>` directory
   and a `code` command. Set `AUDIT_WORKSPACE_ROOT` to keep workspaces somewhere
   durable; the default system temporary directory may be cleaned by the OS.
   The workspace parent must be outside both the target folder and this template's
   source tree. Workspace roots are private to the current user (mode `0700`).
   Local snapshots exclude `.git` metadata and preserve symlinks without following
   them. Remote clones include Git history but do not initialize submodules.
   Existing `.devcontainer`, `.devcontainer.json`, and `.vscode` entries are moved
   to `.audit-original-config-*` inside the copy. The original target is untouched.
   Other target agent configurations remain untrusted and need inspection.

3. Open the printed directory and run **Dev Containers: Reopen in Container**.
   The first build takes several minutes. There are no automatic target installs,
   scans, agent calls, or repository lifecycle commands.

4. In the container terminal, check the tools:

   ```bash
   claude --version
   codex --version
   semgrep --version
   gitleaks version
   gh --version
   ```

## Run static analysis

Run from the target root inside the container:

```bash
semgrep scan --config p/default --metrics=off --disable-version-check \
  --json --output semgrep-results.json .
gitleaks dir --redact --report-format json --report-path gitleaks.json .
```

Semgrep downloads the selected registry rules; use `--config /path/to/rules.yml`
for reviewed local rules and offline scans. Semgrep's default scan exit status is
zero even when it finds issues; inspect its JSON `results` and `errors`. Gitleaks
returns **1 for findings**, so preserve the report and distinguish that from a
tool failure. Reports can contain sensitive code excerpts even with secret
redaction. Check exit statuses and coverage before drawing conclusions.

For a cloned repository, scan Git history separately:

```bash
gitleaks git --redact --report-format json --report-path gitleaks-history.json .
```

Local folder snapshots have no Git history. Do not create a commit just to scan
them. Scanners may respect target-controlled ignores/configuration; review those
and record excluded files. Neither scanner proves the absence of vulnerabilities.

## Investigate with an agent

Read `/opt/audit/INSTRUCTIONS.md`, inspect target agent settings and hooks, and
choose an agent. AI requests send selected code/context to the chosen provider.

```bash
claude
# API-key login for Codex is explicit; no credentials are baked into the image:
printenv OPENAI_API_KEY | codex login --with-api-key
codex
```

Give the agent this initial task:

> Read /opt/audit/INSTRUCTIONS.md, semgrep-results.json, and gitleaks.json. Audit
> this repository and write AUDIT_REPORT.md with evidenced findings. Do not change
> application source, execute target code, commit, or push.

The image installs default instructions in Claude's `~/.claude/CLAUDE.md` and
Codex's `~/.codex/AGENTS.md`. `.devcontainer/CLAUDE.md` alone is not automatically
loaded from the workspace root. Instructions guide behavior but are not access
controls.

For Codex installation and login, see the
[official Codex CLI documentation](https://developers.openai.com/codex/cli/).

## Isolation and limitations

- Runtime uses non-root `vscode`, drops all Linux capabilities, and enables
  `no-new-privileges`. No privileged mode, Docker socket, or host home mount is
  configured. The image does not allow passwordless sudo.
- The audit workspace is a **writable host bind mount**. Changes there persist
  outside the container. Use the setup helper to work on a copy.
- Network access remains enabled for AI APIs and tooling. Any executed process
  with access to forwarded credentials can use or exfiltrate them. Use limited,
  disposable credentials; use a separate VM without credentials for hostile code.
- VS Code may forward Git credentials or an SSH agent independently of this
  template. Review your Dev Containers user settings and disable credential
  integration/forwarding when auditing untrusted targets.
- The container shares the Docker host kernel. It is not a malware-analysis VM,
  an egress firewall, or a read-only policy for agents. Nested agent sandboxes may
  depend on host namespace support; do not bypass permissions to work around it.
- Local snapshots include ignored/untracked files, including any `.env` files.
  Review the copy before opening it with agents. Absolute or escaping symlinks
  may resolve differently inside the container and are not dereferenced by setup.

## Build and maintain

```bash
npx --yes @devcontainers/cli build --workspace-folder .
make test
# Inside the container, from this template repository:
bash tests/container-smoke.sh
```

Ubuntu 24.04, Node.js 22, GitHub CLI, ShellCheck, and common build tools form the
base. Semgrep uses an isolated Python virtual environment. Claude Code, Codex CLI,
and Semgrep versions are Docker build arguments;
Gitleaks uses its versioned upstream binary image (including architecture
selection). Rebuild after updating versions.

This draft does not provide fully reproducible builds: base image tags, apt
packages and transitive dependencies may change.
Record tool versions with each audit; pin image digests and dependency hashes if
you need a repeatable long-term baseline.

Useful upstream references: [Claude Code setup](https://code.claude.com/docs/en/setup),
[Semgrep quickstart](https://semgrep.dev/docs/getting-started/quickstart), and
[Dev Container configuration](https://containers.dev/implementors/json_reference/).

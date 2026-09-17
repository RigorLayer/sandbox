# Universal AI Audit Sandbox

A reusable VS Code DevContainer for security and code quality audits. Open this
sandbox, clone a target inside the container, and review its static analysis
reports before investigating with an agent. Target repositories and reports live
in a Docker-managed volume at `/audit`; they survive container restarts.

## Start an audit

You need Docker, VS Code with the **Dev Containers** extension, and internet access
for image builds, Git clones, Semgrep registry rules, and any AI services you use.

1. Optionally export `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GH_TOKEN` from the
   shell used to launch VS Code. Forward only credentials you need; never put them
   in repository files. Fully relaunch VS Code if its environment is stale.
   `remoteEnv` supplies credentials to VS Code terminals and Dev Containers CLI
   exec sessions, not arbitrary `docker exec` processes.
2. Open **this sandbox repository** in VS Code and select **Dev Containers: Reopen
   in Container**. The first build takes several minutes. The workspace opens at
   `/audit`, without binding the host repository into the container.
3. In the container terminal:

   ```bash
   clone.sh https://github.com/OWNER/REPOSITORY.git
   # SSH is also supported:
   clone.sh git@github.com:OWNER/REPOSITORY.git
   ```

   HTTPS and SSH Git URLs are accepted. There are no local-folder imports. For
   private HTTPS repositories, configure a Git credential helper yourself;
   `GH_TOKEN` forwarding alone does not configure Git authentication. SSH requires
   a working SSH agent or keys and trusted host keys inside the container. VS Code
   can forward a host SSH agent; review that integration before exposing it to
   untrusted targets. Do not disable SSH host-key verification. URLs containing
   passwords, query strings, or whitespace are rejected.
4. Follow the printed `cd` command. Each invocation creates a private, unique
   `/audit/audit-<timestamp>-<suffix>/` containing `repo/` and `reports/`. Repeated
   clones never overwrite an earlier audit. Clone failures retain their directory
   and logs for inspection.

Clones include full Git history with hooks disabled. Submodules and Git LFS
contents are not fetched. No dependencies are installed and no target code or
agent is automatically invoked. Target `.devcontainer`, `.vscode`, and agent
configuration remains intact for inspection. Keep `/audit` as the VS Code
workspace; do not reopen the target as a separate workspace or activate its
Dev Container configuration.

## Read the reports

`clone.sh` automatically runs these checks from the cloned repository, writing
reports and separate logs to its sibling `reports/` directory:

| Check | JSON report | Log |
| --- | --- | --- |
| Semgrep `p/default` | `semgrep.json` | `semgrep.log` |
| Gitleaks current files | `gitleaks-files.json` | `gitleaks-files.log` |
| Gitleaks history, all refs | `gitleaks-history.json` | `gitleaks-history.log` |

Start with `../reports/summary.json`: it records revision, tool versions, scanner
commands, exit statuses, finding counts, incomplete scans, and coverage limits.
`clone.log` records cloning output. All scanners run even if another scanner fails.
Missing or malformed JSON and Semgrep report errors count as incomplete scanning.
An interrupted audit retains a summary with `complete: false`.

Exit status `0` means all scans completed, even with findings; `1` means cloning
or scanning failed (or the shared lock is busy); `2` means invalid arguments.
Gitleaks uses `--exit-code 10` internally to distinguish findings from errors.
An empty repository has no HEAD revision and is reported as incomplete.

Semgrep downloads `p/default` from the registry; these rules are not pinned and
network access is necessary. Metrics and version checks are disabled. For an
additional offline scan, manually supply reviewed local rules. Scanner defaults,
size limits, `.gitignore`, `.semgrepignore`, inline suppressions, `.gitleaks.toml`,
`.gitleaksignore`, and other target-controlled configuration can reduce coverage.
Review exclusions and logs before interpreting a clean result. Gitleaks redacts
secrets, but reports and logs can still contain sensitive paths and code excerpts.

See the [Semgrep CLI reference](https://docs.semgrep.dev/cli-reference) for scan
options and [Dev Containers workspace mounts](https://code.visualstudio.com/remote/advancedcontainers/change-default-source-mount)
for the volume configuration.

## Investigate and export

Read `/opt/audit/INSTRUCTIONS.md`, inspect target agent settings and hooks, and
then start your chosen agent from `repo/`. The image provides shared instructions
in Claude's `~/.claude/CLAUDE.md` and Codex's `~/.codex/AGENTS.md`. Instructions guide
behavior; they are not access controls. Agent login is manual. AI requests send
selected source/context to the chosen provider.

Suggested task:

> Read /opt/audit/INSTRUCTIONS.md and ../reports/summary.json, then review all
> three scanner reports. Audit this repository and write ../reports/AUDIT_REPORT.md
> with evidenced findings. Do not change application source, execute target code,
> commit, or push.

Reports are disposable until manually exported. Use VS Code's download action,
where available, or copy files from a host terminal:

```bash
docker ps # identify the sandbox container
# Substitute the actual container and audit directory printed by clone.sh:
docker cp CONTAINER:/audit/AUDIT_DIRECTORY/reports ./exported-audit-reports
```

## Reset and persistence

Inside the container, from `/audit`:

```bash
cd /audit
reset.sh       # type yes at the prompt
reset.sh --yes # explicit confirmation, required for noninteractive use
```

Reset removes **every entry in `/audit`**, including hidden files, all clones,
reports, and anything else saved there. It preserves `/audit` itself and does not
follow symlinks out of it. Clone and reset share a nonblocking lock: a competing
command fails immediately. There is no automatic startup cleanup.

Reset preserves installed tools, agent login state in the home directory, and
files outside `/audit`. A restart preserves both the container's writable layer
and volumes. Recreating the container replaces its writable layer, including
manual installs and agent login state; the named audit volume remains. Removing
Docker volumes is a separate, explicitly destructive operation. The volume name
is `audit-${devcontainerId}`, scoped to this Dev Container identity; moving the
sandbox or changing its identity may select a different volume. Old volumes
still require separate cleanup.

## Isolation and limitations

- Runs as non-root `vscode`, with all Linux capabilities dropped and
  `no-new-privileges`. There is no configured host home mount, Docker socket,
  privileged mode, or passwordless sudo. A stable container UID preserves volume
  ownership; no host source bind mount requires UID remapping.
- The workspace is a writable Docker volume. Audits share one container user and
  can read or change one another's files. The lock coordinates these commands,
  not arbitrary processes or manual edits.
- Network access remains enabled. Processes with access to forwarded credentials
  can use or exfiltrate them. Use limited credentials; use a separate VM without
  credentials for hostile code. VS Code may forward Git credentials or an SSH
  agent independently; review your Dev Containers settings.
- The container shares the Docker host kernel. It is not a malware-analysis VM,
  egress firewall, or agent permission bypass. Nested agent sandboxes depend on
  host namespace support; keep permission checks enabled.

## Build and maintain

```bash
npx --yes @devcontainers/cli build --workspace-folder . --image-name audit-sandbox:workflow-test
make test # offline host tests, Python 3.8+; no Docker or network needed
# Optional host lifecycle verification; creates and removes its own test volume:
bash tests/container-lifecycle.sh audit-sandbox:workflow-test
# Inside the container (tests and scripts are installed with the image):
shellcheck /opt/audit/scripts/*.sh /opt/audit/tests/container-smoke.sh
bash /opt/audit/tests/container-smoke.sh
python3 -m unittest discover -s /opt/audit/tests -v
```

Smoke checks use temporary synthetic fixtures and leave existing audits intact.
Test reset and restart persistence only in a separate disposable container/volume.
The source tree is deliberately excluded from the runtime workspace; rebuild to
pick up script changes. `.dockerignore` restricts the build context to image
instructions, scripts, and tests.

The base is Ubuntu 24.04 with Node.js 22, GitHub CLI, ShellCheck, and common build
tools. Semgrep uses an isolated Python virtual environment. Claude Code, Codex,
and Semgrep versions are build arguments; Gitleaks uses a versioned upstream
binary image. Base tags, apt packages, and transitive dependencies are not pinned
by digest, so builds are not fully reproducible. Record architecture and tool
versions when validating image changes; see `VALIDATION.md` for this change.

#!/usr/bin/env bash
# Run inside the DevContainer. No real credentials or external API calls needed.
set -euo pipefail

[[ $(id -un) == vscode ]]
[[ $(id -u) != 0 ]]
grep -Eq '^CapEff:[[:space:]]+0+$' /proc/self/status
grep -Eq '^NoNewPrivs:[[:space:]]+1$' /proc/self/status

claude --version
codex --version
semgrep --version
gitleaks version
gh --version

fixture=$(mktemp -d)
trap 'rm -rf -- "$fixture"' EXIT
cd "$fixture"
printf 'eval(user_input)\n' > example.py
cat > rules.yml <<'YAML'
rules:
  - id: audit-smoke-eval
    pattern: eval(...)
    message: Audit smoke fixture
    languages: [python]
    severity: WARNING
YAML
semgrep scan --config rules.yml --metrics=off --disable-version-check \
    --json --output semgrep-results.json example.py
jq -e '(.results | length == 1) and (.errors | length == 0)' semgrep-results.json >/dev/null

cat > gitleaks.toml <<'TOML'
[[rules]]
id = "audit-smoke-secret"
description = "Synthetic smoke-test marker"
regex = '''AUDIT_SMOKE_[A-Z]{12}'''
TOML
printf 'AUDIT_SMOKE_ABCDEFGHIJKL\n' > secret.txt
status=0
gitleaks dir --config gitleaks.toml --redact --report-format json \
    --report-path gitleaks.json . || status=$?
[[ $status == 1 ]]
jq -e 'length == 1 and .[0].Secret == "REDACTED"' gitleaks.json >/dev/null
printf '\nContainer isolation and scanner smoke checks passed.\n'

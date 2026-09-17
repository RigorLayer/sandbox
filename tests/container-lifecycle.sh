#!/usr/bin/env bash
# Run on the Docker host against a built image. Only disposable fixtures are reset.
set -euo pipefail
image=${1:-audit-sandbox:workflow-test}
fixture=$(mktemp -d)
name="audit-lifecycle-$(basename "$fixture" | tr '[:upper:]' '[:lower:]')"
volume="$name-data"
cleanup() {
    docker rm -f "$name" >/dev/null 2>&1 || true
    docker volume rm "$volume" >/dev/null 2>&1 || true
    rm -rf -- "$fixture"
}
trap cleanup EXIT
docker volume create "$volume" >/dev/null
start() {
    docker run -d --name "$name" --init --cap-drop=ALL \
        --security-opt=no-new-privileges:true \
        --mount "type=volume,source=$volume,target=/audit" "$image" >/dev/null
}
start
docker exec "$name" bash /opt/audit/tests/container-smoke.sh
docker exec "$name" bash -c 'shellcheck /opt/audit/scripts/*.sh /opt/audit/tests/*.sh'
docker exec "$name" python3 -m unittest discover -s /opt/audit/tests -v
# Check the installed wrappers, real mount permissions, and noninteractive reset.
docker exec "$name" bash -c '
    mkdir -p /audit/audit-persistence/repo /audit/audit-persistence/reports /audit/.hidden
    printf synthetic > /audit/audit-persistence/reports/marker
    printf synthetic > "$HOME/.claude/lifecycle-marker"
    ln -s "$HOME/.claude" /audit/.hidden/outside
    status=0
    reset.sh || status=$?
    [[ $status == 2 ]]
    [[ -f /audit/audit-persistence/reports/marker ]]
'
docker restart "$name" >/dev/null
docker exec "$name" test -f /audit/audit-persistence/reports/marker
docker exec "$name" test -f /home/vscode/.claude/lifecycle-marker
# Recreate with the same volume: audit persists, writable layer does not.
docker rm -f "$name" >/dev/null
start
docker exec "$name" bash -c '
    [[ -f /audit/audit-persistence/reports/marker ]]
    [[ ! -f "$HOME/.claude/lifecycle-marker" ]]
    printf synthetic > "$HOME/.claude/lifecycle-marker"
    reset.sh --yes
    [[ -z $(find /audit -mindepth 1 -maxdepth 1 -print -quit) ]]
    [[ -f "$HOME/.claude/lifecycle-marker" ]]
    command -v clone.sh reset.sh semgrep gitleaks
'
printf '\nRestart, recreation, and reset lifecycle checks passed.\n'

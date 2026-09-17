#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
    printf 'Usage: %s <target-repo-url-or-folder>\n' "${0##*/}"
    printf 'Set AUDIT_WORKSPACE_ROOT to choose the parent directory (default: system temp).\n'
}

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    usage
    exit 0
fi
if [[ $# -ne 1 || -z $1 || $1 == -* ]]; then
    usage >&2
    exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
template_dir=$(cd -- "$script_dir/../.devcontainer" && pwd -P)
project_dir=$(cd -- "$script_dir/.." && pwd -P)
target=$1
for command in git python3 mktemp; do
    command -v "$command" >/dev/null || { printf 'Missing prerequisite: %s\n' "$command" >&2; exit 1; }
done

if [[ -d $target ]]; then
    target=$(cd -- "$target" && pwd -P)
    mode=folder
elif [[ $target == https://* || $target == ssh://* || $target == git@*:* ]]; then
    mode=clone
else
    printf 'Target must be an existing folder or an HTTPS/SSH Git URL.\n' >&2
    exit 2
fi

name=${target%/}
name=${name##*/}
name=${name%.git}
name=$(printf '%s' "$name" | LC_ALL=C tr -cs 'A-Za-z0-9._-' '-' | cut -c1-60)
parent=${AUDIT_WORKSPACE_ROOT:-${TMPDIR:-/tmp}}
parent=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$parent")
if [[ $mode == folder && ( $parent == "$target" || $parent == "${target%/}/"* ) ]]; then
    printf 'Workspace parent must be outside the target folder.\n' >&2
    exit 2
fi
if [[ $parent == "$project_dir" || $parent == "$project_dir/"* ]]; then
    printf 'Workspace parent must be outside the template source tree.\n' >&2
    exit 2
fi
mkdir -p -- "$parent"
workspace=$(mktemp -d "$parent/audit-${name:-target}-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
complete=false
trap 'if [[ $complete != true ]]; then printf "Setup failed; incomplete workspace retained at: %s\n" "$workspace" >&2; fi' EXIT

if [[ $mode == clone ]]; then
    # No target submodules or hooks are run. Clone before installing the template,
    # because git requires an empty destination.
    git -c core.hooksPath=/dev/null clone --no-local \
        --config core.hooksPath=/dev/null --config submodule.recurse=false \
        -- "$target" "$workspace"
else
    # Snapshot includes dirty/untracked files, but not host Git metadata, hooks,
    # remotes or worktree pointers. Keep symlinks as links, never follow them.
    python3 - "$target" "$workspace" <<'PY'
import shutil
import sys
from pathlib import Path

# Copy children individually so copytree never replaces the private workspace
# root's permissions with those of the source, including on a failed copy.
source, destination = map(Path, sys.argv[1:])
for entry in source.iterdir():
    if entry.name == '.git':
        continue
    output = destination / entry.name
    if entry.is_symlink():
        shutil.copy2(entry, output, follow_symlinks=False)
    elif entry.is_dir():
        shutil.copytree(entry, output, symlinks=True,
                        ignore=shutil.ignore_patterns('.git'))
    else:
        shutil.copy2(entry, output)
PY
fi
chmod 700 "$workspace"

# Prevent target-controlled container commands and editor tasks from activating.
# Move even dangling symlinks rather than following them during the overlay.
backup=''
for entry in .devcontainer .devcontainer.json .vscode; do
    if [[ -e $workspace/$entry || -L $workspace/$entry ]]; then
        if [[ -z $backup ]]; then
            backup=$(mktemp -d "$workspace/.audit-original-config-XXXXXX")
        fi
        mv -- "$workspace/$entry" "$backup/$entry"
    fi
done
cp -R -- "$template_dir" "$workspace/.devcontainer"
complete=true

printf '\nAudit workspace ready: %s\n' "$workspace"
[[ -z $backup ]] || printf 'Original editor/container configuration saved in: %s\n' "$backup"
printf '\nOpen VS Code:\n  code %q\n' "$workspace"
printf '\nThen run “Dev Containers: Reopen in Container”.\n'
printf 'Read /opt/audit/INSTRUCTIONS.md inside the container before starting an agent.\n'

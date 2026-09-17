#!/usr/bin/env bash
set -euo pipefail
exec python3 /opt/audit/audit-workflow.py reset "$@"

.DEFAULT_GOAL := help

# Pass the target through the environment so paths are not interpolated into shell code.
export TARGET

.PHONY: help audit test

help:
	@printf '%s\n' \
	  'Usage: make audit TARGET=<repo-url-or-folder>' \
	  'Example: make audit TARGET="/path/to/project"' \
	  'Run host-side regression tests: make test' \
	  'Set AUDIT_WORKSPACE_ROOT to choose where audit workspaces are created.'

audit:
	@if [ -z "$$TARGET" ]; then \
	  printf '%s\n' 'Missing TARGET. Usage: make audit TARGET=<repo-url-or-folder>' >&2; \
	  exit 2; \
	fi
	@./scripts/audit-setup.sh "$$TARGET"

test:
	python3 -m unittest discover -s tests -v

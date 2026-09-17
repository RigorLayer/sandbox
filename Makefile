.DEFAULT_GOAL := help
.PHONY: help test

help:
	@printf '%s\n' \
	  'Open this sandbox in VS Code: Dev Containers: Reopen in Container.' \
	  'Inside the container: clone.sh <https-or-ssh-git-url>' \
	  'Delete all audit data: reset.sh [--yes]' \
	  'Run offline regression tests: make test'

test:
	python3 -m unittest discover -s tests -v

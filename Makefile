# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

.DEFAULT_GOAL := help
.PHONY: help verify test check release

help: ## List the available targets
	@echo "wa-a11y Makefile targets:"
	@echo "  make help                          this list"
	@echo "  make verify                        export + privacy guards (scripts/verify-export, scripts/pii-scan --all)"
	@echo "  make test                          web (pytest) + scanner + styles tests, then the AAA self-scan"
	@echo "  make check                         scripts/check — every repository check"
	@echo "  make release TAG=vX.Y.Z            full checks, then an annotated tag (never pushed)"

verify: ## Export and privacy guards
	scripts/verify-export && scripts/pii-scan --all

test: ## All test suites, then the AAA self-scan
	uv run --directory web pytest -q && pnpm -C scanner test && pnpm -C styles test && scripts/selfscan

check: ## Every repository check
	scripts/check

release: ## Tag a release after full checks (usage: make release TAG=vX.Y.Z)
	@test -n "$(TAG)" || { echo "release: TAG is empty — usage: make release TAG=vX.Y.Z"; exit 1; }
	@test -z "$$(git status --porcelain)" || { echo "release: the tree is dirty — commit or stash first"; exit 1; }
	@! git rev-parse -q --verify "refs/tags/$(TAG)" >/dev/null \
	  || { echo "release: tag $(TAG) already exists"; exit 1; }
	scripts/check
	$(MAKE) verify
	git tag -a "$(TAG)" -m "wa-a11y $(TAG) [AGPLv3 Corresponding Source]"
	@echo "release: tagged $(TAG) — not pushed; push it yourself when ready"
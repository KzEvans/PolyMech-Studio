# One-stop developer commands. `make check` is the gate before every commit.
.PHONY: sync check lint typecheck test cov web-test web-typecheck e2e api web literature desktop desktop-selftest

sync:
	uv sync
	pnpm -C apps/web install

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy

test:
	uv run pytest

cov:
	uv run pytest packages/mechanics --cov=polymech_mechanics --cov-report=term-missing --cov-fail-under=90

web-test:
	pnpm -C apps/web test

web-typecheck:
	pnpm -C apps/web typecheck

check: lint typecheck test cov web-typecheck web-test

e2e:
	pnpm -C apps/web e2e

desktop:  ## build PolyMech Studio.app + .dmg (needs Rust: ~/.cargo/bin)
	scripts/desktop/build.sh

desktop-selftest:  ## launch the built app with a temp data folder and check backend, downloads, quit
	scripts/desktop/selftest.sh

literature:  ## import curated literature records (POLYMECH_DATA_DIR or app default)
	uv run python scripts/import_literature.py

api:
	uv run uvicorn polymech_api.main:app --reload --port 8765

web:
	pnpm -C apps/web dev

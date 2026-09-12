.PHONY: setup lint typecheck test check run-paper run-shadow run-observability check-config docker-build soak-ci soak-24h

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

setup:
	python3.12 -m venv $(VENV)
	$(PIP) install -q -U pip
	$(PIP) install -q -e '.[dev]'

lint:
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

typecheck:
	$(VENV)/bin/mypy src

test:
	$(VENV)/bin/pytest --cov=traderstack --cov-report=term-missing --cov-fail-under=80

check: lint typecheck test

check-config:
	$(VENV)/bin/traderstack-check-config

run-paper:
	$(VENV)/bin/traderstack-paper --persistent-events \
		--checkpoint-path var/state/portfolio.json \
		--audit-path var/audit/runtime.jsonl

# Shadow-live: same decision/risk/meta-agent pipeline, no venue orders.
# Requires TRADING_MODE=shadow in the environment / .env.
run-shadow:
	$(VENV)/bin/traderstack-paper --persistent-events \
		--checkpoint-path var/state/portfolio.json \
		--audit-path var/audit/runtime.jsonl \
		--shadow-ledger-path var/audit/shadow_intents.jsonl

# Short soak for CI / local smoke. Archives var/soak-ci/report.json.
# This is not the 24-hour acceptance window.
soak-ci:
	$(VENV)/bin/traderstack-soak --preset ci --workdir var/soak-ci

# Operator 24h window. Do not treat a CI soak as a substitute.
soak-24h:
	$(VENV)/bin/traderstack-soak --preset full --cycle-seconds 5 --workdir var/soak

run-observability:
	docker compose --profile observability up -d

docker-build:
	docker build -t traderstack:local .

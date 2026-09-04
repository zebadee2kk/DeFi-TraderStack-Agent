.PHONY: setup lint typecheck test check run-paper run-observability check-config docker-build

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

run-observability:
	docker compose --profile observability up -d

docker-build:
	docker build -t traderstack:local .

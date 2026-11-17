PYTHON ?= python3
RUFF ?= ruff

.PHONY: test lint build check

test:
	$(PYTHON) -m unittest discover -s tests -t . -v

lint:
	$(RUFF) check labcheck tests
	$(RUFF) format --check labcheck tests

build:
	$(PYTHON) -m build

check: test lint

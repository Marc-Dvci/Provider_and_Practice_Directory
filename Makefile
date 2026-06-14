# Convenience targets. On Windows, run the underlying commands directly or use
# `make` via Git Bash / WSL. Each target maps to a one-liner documented in README.

.PHONY: install test lint format typecheck check demo backtest dashboard docs clean

install:
	pip install -e ".[dev,calibration,address,dashboard,docs]"

test:
	pytest --cov=directory_pipeline --cov-report=term-missing

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

typecheck:
	mypy

check: lint typecheck test  ## run everything CI runs

demo:
	directory-pipeline demo

backtest:
	directory-pipeline backtest

dashboard:
	streamlit run dashboard/app.py

docs:  ## regenerate the submission artifacts (diagram, dashboard, demo gif, proposal pdf)
	python docs/make_diagram.py
	directory-pipeline demo
	python docs/make_dashboard_shot.py
	python docs/make_demo_gif.py
	python docs/make_pdf.py

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	rm -f audit_log.jsonl review_decisions.jsonl
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

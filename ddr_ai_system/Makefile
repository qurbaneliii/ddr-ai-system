.PHONY: install audit process test lint run migrate

install:
	python -m pip install -e ".[dev,ocr]"

audit:
	python scripts/audit_inputs.py

process:
	python scripts/process_all.py

test:
	python -m pytest

lint:
	python -m ruff check .

migrate:
	python -m alembic upgrade head

run:
	python -m streamlit run streamlit_app.py


.PHONY: install migrate makemigrations run test lint fmt prefect-server prefect-serve prefect-concurrency

install:
	pip install -r requirements.txt

makemigrations:
	python manage.py makemigrations

migrate:
	python manage.py migrate

run:
	python manage.py runserver 0.0.0.0:8000

test:
	pytest

lint:
	ruff check .

fmt:
	ruff format .

# ── Local Prefect engine (design §6, #53) — run each in its own terminal ─────
# Then set PREFECT_DISPATCH=deployment + PREFECT_API_URL=http://127.0.0.1:4200/api
# in .env so uploads run on the engine (UI at http://localhost:4200).
prefect-server:
	prefect server start

prefect-serve:
	python manage.py prefect_serve

# Create the `gemini` task concurrency limit (used once the LLM steps are tasks, #54).
prefect-concurrency:
	prefect concurrency-limit create gemini $${PREFECT_GEMINI_CONCURRENCY:-8}

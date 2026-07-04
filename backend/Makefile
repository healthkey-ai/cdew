.PHONY: install migrate makemigrations run test lint fmt

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

.PHONY: up down logs test test-unit test-integration test-e2e lint shell migrate

up:
	docker compose up --build -d

down:
	docker compose down -v

logs:
	docker compose logs -f api worker

test:
	pip install -q -r requirements.txt aiosqlite
	pytest tests/ -v --tb=short

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

test-e2e:
	pip install -q aiosqlite
	pytest tests/e2e/ -v

migrate:
	docker compose exec api alembic upgrade head

shell:
	docker compose exec api bash

demo:
	@echo "=== Ingesting sample transcript ==="
	curl -s -X POST http://localhost:8000/transcripts \
		-H "Content-Type: application/json" \
		-d '{"content": "Alice met with Bob to discuss migrating their Python API to Kubernetes. Alice prefers PostgreSQL for the database. Bob mentioned he started learning machine learning last month.", "metadata": {"participants": ["Alice", "Bob"], "source": "demo"}}' | python3 -m json.tool
	@echo "\n=== Waiting for processing (3s) ==="
	sleep 3
	@echo "\n=== Listing memory root ==="
	curl -s "http://localhost:8000/memory/ls?path=/" | python3 -m json.tool
	@echo "\n=== Grepping for Kubernetes ==="
	curl -s "http://localhost:8000/memory/grep?pattern=kubernetes&ignore_case=true" | python3 -m json.tool

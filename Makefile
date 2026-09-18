.PHONY: help setup up down logs shell migrations migrate check test lint fmt rename

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup:      ## Crea el entorno virtual e instala dependencias
	uv sync --extra dev
	test -f .env || cp .env.example .env

up:         ## Levanta la pila completa (web, worker, db, redis)
	docker compose up -d --build

down:       ## Detiene la pila
	docker compose down

logs:       ## Sigue los logs de la aplicacion
	docker compose logs -f web worker

shell:      ## Shell de Django
	uv run src/manage.py shell

migrations: ## Genera migraciones
	uv run src/manage.py makemigrations

migrate:    ## Aplica migraciones
	uv run src/manage.py migrate

check:      ## Chequeo de integridad de Django
	uv run src/manage.py check

test:       ## Corre la bateria de pruebas
	uv run pytest

lint:       ## Revisa estilo
	uv run ruff check src

fmt:        ## Formatea
	uv run ruff format src && uv run ruff check --fix src

rename:     ## Renombra el producto:  make rename NEW=nuevonombre
	@test -n "$(NEW)" || (echo "Uso: make rename NEW=nuevonombre" && exit 1)
	@grep -rl --exclude-dir=.git --exclude-dir=.venv -e lares -e Lares -e LARES . \
		| xargs sed -i 's/LARES/$(shell echo $(NEW) | tr a-z A-Z)/g; s/Lares/$(shell echo $(NEW) | sed "s/./\U&/")/g; s/lares/$(NEW)/g'
	@git mv src/lares src/$(NEW) 2>/dev/null || mv src/lares src/$(NEW)
	@echo "Renombrado a $(NEW). Revisa el diff antes de confirmar."

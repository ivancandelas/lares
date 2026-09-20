.PHONY: help setup up down logs shell migrations migrate check test lint fmt rename \
        version build release deploy update backup restore-last

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

# --- Despliegue -------------------------------------------------------------

version:    ## Dice que version es esta copia
	@cat VERSION

build:      ## Construye la imagen con la version del archivo VERSION
	docker build --build-arg LARES_VERSION=$$(cat VERSION) \
		-t lares:$$(cat VERSION) -t lares:latest .

release:    ## Marca una version:  make release V=0.7.0
	@test -n "$(V)" || (echo "Uso: make release V=0.7.0" && exit 1)
	@echo "$(V)" > VERSION
	@sed -i 's/^version = ".*"/version = "$(V)"/' pyproject.toml
	@git add VERSION pyproject.toml
	@git commit -m "Version $(V)"
	@git tag -a v$(V) -m "Lares $(V)"
	@echo "Etiquetado v$(V). Falta empujarlo:  git push --follow-tags"

deploy:     ## Levanta el despliegue de produccion
	docker compose -f compose.prod.yaml up -d

update:     ## Actualiza a la ultima version:  make update [V=0.7.0]
	@LARES_TAG=$${V:-latest} ./docker/update.sh $${V:-latest}

backup:     ## Copia de seguridad de la base, ahora
	@mkdir -p data/backups
	@docker compose -f compose.prod.yaml exec -T db pg_dump -U lares lares \
		| gzip > data/backups/lares-$$(date +%Y%m%d-%H%M%S).sql.gz
	@ls -lh data/backups | tail -1

rename:     ## Renombra el producto:  make rename NEW=nuevonombre
	@test -n "$(NEW)" || (echo "Uso: make rename NEW=nuevonombre" && exit 1)
	@grep -rl --exclude-dir=.git --exclude-dir=.venv -e lares -e Lares -e LARES . \
		| xargs sed -i 's/LARES/$(shell echo $(NEW) | tr a-z A-Z)/g; s/Lares/$(shell echo $(NEW) | sed "s/./\U&/")/g; s/lares/$(NEW)/g'
	@git mv src/lares src/$(NEW) 2>/dev/null || mv src/lares src/$(NEW)
	@echo "Renombrado a $(NEW). Revisa el diff antes de confirmar."

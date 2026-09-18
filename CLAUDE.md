# Reglas del proyecto

## Repositorios

- **Este repo: solo código.** No se versiona documentación aquí.
- **La documentación vive en su propio repo**, con raíz en `docs/` (ignorado por
  este repositorio). Se commitea por separado.
- `README.md` es la excepción: es la portada del repo de código.

## Commits

- **Mensajes cortos.** Una línea, sin cuerpo salvo que aporte algo real.
- **Sin co-autor.** No añadir líneas `Co-authored-by` ni atribución a herramientas.
- Commitear solo cuando se pida explícitamente.

## Servidor de demostración

Tras **cada cambio relevante** hay que dejar el demo actualizado y comprobado:

```bash
uv run src/manage.py migrate
uv run src/manage.py seed_demo
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8010/
```

- Corre en **:8010** (el 8000 está ocupado por otra app) con autoreload, así que
  el código se recarga solo; migraciones y semilla no.
- **Los cambios en `.env` exigen reiniciar el proceso.** El autoreload hereda el
  entorno del padre y `read_env` no pisa lo que ya está en `os.environ`.
- Postgres del proyecto en **:5433** (el 5432 está ocupado).
- Si el cambio añade pantallas o datos, verificar que se ven, no solo que
  responde 200.

## Código

- Comentarios y nombres de dominio en español; identificadores técnicos en inglés.
- Ver `docs/` (repo de documentación) para arquitectura, modelo de dominio y ADRs.

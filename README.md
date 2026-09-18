# Lares

**Tu hogar, administrado.**

Lares es una plataforma *self-hosted* para administrar los recursos, obligaciones,
documentos, dinero y relaciones de una persona o una familia. La categoría es
**Personal Resource Planning (PRP)**: un ERP para la vida, no una app que junta
muchas cosas.

Responde, en cualquier momento:

> ¿Qué tengo, qué debo, qué estoy pagando, qué obligaciones tengo, qué está por
> vencer, quién está involucrado y qué tengo que hacer después?

## La diferencia

Un gestor de información personal **organiza y recupera**. Lares **relaciona,
anticipa y avisa**.

```
(Póliza GNP-4471) --asegura--> (Mazda CX-5) --propiedad de--> (Iván)
        │                            │
        │                            └──> obligaciones: verificación, refrendo, servicio
        ├──> vence 2027-10-15  →  obligación  →  avisos a −45/−20/−7/−1 días
        └──> se paga desde (Tarjeta ****1234)  →  coste real del vehículo
```

Y detecta lo que **no** registraste:

```
⚠ crítico   El Mazda CX-5 no tiene póliza asociada
⚠ normal    El Mazda CX-5 no tiene factura ni documentos
```

## Estado

**F0 (núcleo) completada.** Funcionan las siete primitivas del dominio, el sistema
de módulos, el aislamiento por hogar, el motor de obligaciones idempotente y el
detector de huecos, con un módulo de referencia (`vehicles`) que no toca el núcleo.

Ver la [hoja de ruta](docs/05-roadmap.md).

## Arranque rápido

```bash
make setup                 # entorno virtual, dependencias y .env
docker compose up -d db redis
make migrate
uv run src/manage.py bootstrap_household --name "Mi hogar"
uv run src/manage.py runserver
```

Con todo en contenedores:

```bash
make up && make logs
```

## Documentación

Vive en un **repositorio aparte**, que se clona en `docs/`. Por dónde empezar:

- [Visión y alcance](docs/00-vision.md) — qué es y, sobre todo, **qué no es**
- [Modelo de dominio](docs/01-domain-model.md) — las 7 primitivas. **Léelo antes de escribir código**
- [Sistema de módulos](docs/03-module-system.md) y [cómo escribir uno](docs/08-module-authoring.md)
- [Catálogo completo de features](docs/09-feature-catalog.md) — todo lo que puede llegar a hacer, por capas
- [Decisiones de arquitectura](docs/adr/) — el porqué de cada elección

## Principios

1. **El grafo es el producto.** Los módulos son consecuencia.
2. **Lo que no te avisa a tiempo, no sirve.**
3. **La captura es el cuello de botella.** Todo se juzga por la fricción que quita.
4. **El usuario es dueño de sus datos.** Exportación total desde el día uno.
5. **El núcleo no conoce a los módulos.** Hay una prueba que lo verifica.
6. **Nada se borra.** Se archiva.
7. **No competimos con lo especializado.** Paperless, Bitwarden, el calendario: se integran.

## Desarrollo

```bash
make test      # batería de pruebas
make lint      # estilo
make check     # chequeo de Django
make rename NEW=otronombre   # renombrar el producto
```

## Licencia

Por definir. Ver [ADR pendiente sobre sostenibilidad](docs/04-tenancy-and-saas.md#sostenibilidad).

<div align="center">

# Lares

**Tu hogar, administrado.**

Un ERP para la vida: la plataforma *self-hosted* que sabe qué tienes, qué debes,
qué estás pagando y qué se te vence la semana que viene.

[![Versión](https://img.shields.io/github/v/tag/ivancandelas/lares?label=versi%C3%B3n&color=2F6B4F)](https://github.com/ivancandelas/lares/releases)
[![Imagen](https://github.com/ivancandelas/lares/actions/workflows/release.yml/badge.svg)](https://github.com/ivancandelas/lares/actions/workflows/release.yml)
[![Licencia: AGPL v3](https://img.shields.io/badge/licencia-AGPL--3.0-A3231C)](LICENSE)
[![Django](https://img.shields.io/badge/Django-5.1-0C4B33)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB)](https://www.python.org/)

[Qué es](#qué-es) · [Instalar](#instalación) · [Actualizar](#actualizar) ·
[Módulos](#qué-trae-dentro) · [Configuración](#configuración) ·
[Desarrollo](#desarrollo)

</div>

---

## Qué es

Lares es **Personal Resource Planning (PRP)**: la administración de los recursos,
obligaciones, documentos, dinero y relaciones de una persona o una familia,
tratada como lo que es —un sistema— y no como una carpeta de apps sueltas.

Responde, en cualquier momento, a una sola pregunta larga:

> ¿Qué tengo, qué debo, qué estoy pagando, qué obligaciones tengo, qué está por
> vencer, quién está involucrado y qué tengo que hacer después?

### La diferencia

Un gestor de información personal **organiza y recupera**. Lares **relaciona,
anticipa y avisa**.

```
(Póliza GNP-4471) --asegura--> (Mazda CX-5) --propiedad de--> (Iván)
        │                            │
        │                            └──> obligaciones: verificación, refrendo, servicio
        ├──> vence 2027-10-15  →  obligación  →  avisos a −45/−30/−15/−7/−1 días
        └──> se paga desde (Tarjeta ****1234)  →  coste real del vehículo
```

Y detecta lo que **no** registraste, que es lo que de verdad hace daño:

```
⚠ crítico   El Mazda CX-5 no tiene póliza asociada
⚠ normal    El Mazda CX-5 no tiene factura ni documentos
```

## Qué trae dentro

El núcleo son siete primitivas —recurso, parte, relación, obligación, documento,
apunte y evento— y sobre ellas se enchufan módulos que el núcleo no conoce:

| Módulo | Para qué |
| --- | --- |
| **Inmuebles** | Casas, terrenos, predial, servicios |
| **Vehículos** | Refrendo, verificación, servicios, kilometraje |
| **Seguros** | Pólizas, vigencias, qué asegura cada una |
| **Dinero** | Cuentas, tarjetas, gastos, ingresos, presupuestos |
| **Préstamos** | Amortización, meses sin intereses, garantías |
| **Objetos** | Inventario, garantías, quién lo tiene prestado |
| **Mantenimiento** | Historial y periodicidad por recurso |
| **Contratado** | Suscripciones y servicios recurrentes |
| **Arrendamiento** | Rentas cobradas y pagadas |
| **Impuestos** | Perfiles fiscales y sus vencimientos |
| **Tareas** · **Metas** | Lo que hay que hacer y a dónde va |

Y transversalmente:

- **Motor de obligaciones** idempotente, con avisos escalonados antes de cada
  vencimiento.
- **Detector de huecos**: te dice qué falta, con severidad, sin que preguntes.
- **Bandeja de entrada** con conectores a **Paperless-ngx**, IMAP y carpeta
  vigilada: el documento entra, se clasifica y se propone dónde va.
- **Calendario ICS** y **contactos vCard** suscribibles desde el teléfono.
- **API** (`/api/v1/…`), **webhooks** y **exportación total** del hogar.
- **Sucesión**: un interruptor de hombre muerto. Si dejas de entrar, avisa
  primero y luego libera —solo lectura, secciones elegidas por ti— a quien
  hayas dicho. Volver a entrar lo revoca.
- **Multiusuario** con aislamiento por hogar, reparto de responsabilidades y
  bitácora de todo lo que pasa.

## Estado

**F0 (núcleo) completada.** Funcionan las siete primitivas, el sistema de
módulos, el aislamiento por hogar, el motor de obligaciones y el detector de
huecos, con un módulo de referencia (`vehicles`) que no toca el núcleo.

**La versión que corre se ve en el pie de todas las pantallas** y en
`GET /salud`. Después de actualizar, ahí se comprueba que lo que contesta es lo
nuevo.

---

# Instalación

Tres caminos. Los tres dejan lo mismo funcionando; elige por dónde vas a vivir.

| | Para quién | Actualiza con |
| --- | --- | --- |
| **[Proxmox](#proxmox-una-sola-orden)** | Tienes un nodo Proxmox | `lares-update` |
| **[Nativa](#debian-o-ubuntu-sin-docker)** | Cualquier Debian/Ubuntu limpio | `lares-update` |
| **[Docker](#docker)** | Ya vives en compose | `make update` |

## Antes de empezar

Los instaladores bajan **una versión publicada** del repositorio, así que antes
de instalar tiene que existir una:

```bash
make release V=0.7.0       # escribe VERSION y pyproject, commitea y etiqueta
git push --follow-tags
```

Eso dispara el workflow: corre la batería de pruebas, publica la imagen en
`ghcr.io` y crea el Release. Una imagen que no pasa las pruebas no se publica.

> [!NOTE]
> El instalador busca primero el Release y, si no hay ninguno, se conforma con
> la etiqueta más nueva. Empujar la etiqueta ya es suficiente para poder
> instalar, aunque el workflow todavía esté corriendo.

Si tu repositorio se llama distinto, pásalo por entorno —`LARES_REPO=usuario/repo`—
o cambia el valor por defecto en `deploy/native/install.sh`,
`deploy/native/update.sh` y `deploy/proxmox/ct/lares.sh`. El repositorio tiene
que ser **público**: `raw.githubusercontent.com` y `ghcr.io` se consultan sin
credenciales.

## Proxmox, una sola orden

Desde el shell del **nodo** Proxmox —no de un contenedor—:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/ivancandelas/lares/main/deploy/proxmox/ct/lares.sh)"
```

Crea un LXC Debian 13 sin privilegios: 2 vCPU, 2 GB de RAM y 20 GB de disco por
defecto, que el menú *Advanced* deja cambiar. Tarda un rato, porque compila
dependencias. Al terminar dice la IP.

Sigue en [Después de instalar](#después-de-instalar).

## Debian o Ubuntu, sin Docker

```bash
curl -fsSL https://raw.githubusercontent.com/ivancandelas/lares/main/deploy/native/install.sh | bash
```

Instala Postgres, Redis y tres unidades de systemd (`lares-web`, `lares-worker`,
`lares-beat`), genera los secretos solo y deja:

```
/opt/lares/releases/<versión>/   el código y su entorno, uno por versión
/opt/lares/current               enlace a la que corre ahora
/opt/lares/data/                 medios y el reloj de celery
/opt/lares/backups/              copias de la base, una antes de cada actualización
/opt/lares/lares.env             la configuración, con los secretos (modo 600)
```

**Una versión por carpeta y un enlace que apunta a la buena.** Es lo que hace
que volver atrás sea mover el enlace y reiniciar, en vez de restaurar una copia
y rezar. Cada versión lleva su propio entorno virtual, así que volver atrás
recupera también las dependencias de entonces.

Para una versión concreta: `… | bash -s -- 0.7.0`.

## Docker

```bash
git clone https://github.com/ivancandelas/lares && cd lares
cp .env.example .env          # y define POSTGRES_PASSWORD
make deploy                   # docker compose -f compose.prod.yaml up -d
```

Levanta imagen publicada y etiquetada, sin montar el código del disco: lo que
corre es lo que dice la etiqueta. Se reinicia solo, porque un servidor de casa
se apaga cuando se va la luz.

## Después de instalar

**1. Crea tu usuario.** En Proxmox, entra al contenedor desde el nodo con
`pct enter <vmid>`:

```bash
# Nativa y Proxmox
lares-manage createsuperuser

# Docker
docker compose -f compose.prod.yaml exec web python src/manage.py createsuperuser
```

**2. Entra** en `http://<IP>:8000` y sigue la pantalla de bienvenida.

**3. Fija la IP.** El instalador escribió la IP del momento en
`LARES_ALLOWED_HOSTS` y `LARES_SITE_URL`. Si el DHCP se la cambia, Django
responde `400` a todo y no dice por qué. Reserva la IP en el router o pon la del
contenedor estática.

> [!IMPORTANT]
> Si entras por IP en la red de casa, sin un proxy con HTTPS delante, hace falta
> `LARES_HTTPS=0` —los instaladores ya lo dejan así—. Con TLS exigido, todo
> responde 301 hacia una dirección que no existe y parece que la aplicación está
> rota. Con un proxy y dominio delante: `LARES_HTTPS=1` y
> `LARES_CSRF_TRUSTED_ORIGINS=https://tu.dominio`, o los formularios devuelven un
> 403 que tampoco explica nada.

> [!WARNING]
> Tocar `/opt/lares/lares.env` no basta:
> `systemctl restart lares-web lares-worker lares-beat`. La configuración se lee
> al arrancar y el entorno se hereda; no se relee sola.

---

# Actualizar

## El ciclo completo, desde un cambio tuyo

```bash
# 1. En tu máquina, con el cambio ya commiteado
make test

# 2. Marca la versión: escribe VERSION y pyproject.toml, commitea y etiqueta
make release V=0.7.1

# 3. Súbelo. El workflow prueba, publica la imagen y crea el Release
git push --follow-tags

# 4. En la máquina donde vive Lares
lares-update            # nativa y Proxmox
make update             # Docker
```

**5. Comprueba** que actualizó: el número del pie de cualquier pantalla, o

```bash
curl -s http://<IP>:8000/salud
{"ok": true, "version": "0.7.1"}
```

## Qué hace, y por qué en ese orden

1. **Copia de la base antes de tocar nada**, en `/opt/lares/backups/`.
2. Baja el código nuevo a su propia carpeta, con su propio entorno.
3. **Para los servicios** y migra con el código nuevo. Una migración aplicada
   mientras la versión vieja sigue sirviendo es la receta de los errores que
   nadie reproduce después.
4. Mueve el enlace `current` y arranca.
5. Comprueba que contesta. Si al minuto no lo hace, **te dice cómo volver** —no
   vuelve solo: deshacer una migración por su cuenta puede destruir datos, y a
   esa hora hace falta una instrucción clara, no automatismo.

Se conservan las tres últimas versiones en disco; las anteriores se borran.

## Volver atrás

| | Volver a la anterior |
| --- | --- |
| Nativa / Proxmox | `lares-update --rollback` |
| Docker | `LARES_TAG=<la de antes> make deploy` |

Es instantáneo, porque cada versión conserva su carpeta y su entorno. Si además
la migración cambió la base, restaura la copia:

```bash
ls /opt/lares/backups/
zcat /opt/lares/backups/lares-0.7.0-<sello>.sql.gz | sudo -u postgres psql lares
```

## Variantes

```bash
lares-update 0.7.0                                       # a una versión concreta
LARES_SOURCE_DIR=/ruta/al/clon lares-update 0.7.1-pre    # probar sin publicar nada
make backup                                              # copia de la base, ahora
```

Desde el nodo Proxmox también puedes volver a lanzar el one-liner: detecta la
instalación y ofrece el modo actualización, que por dentro llama a este mismo
script.

---

## Configuración

Todo se lee del entorno con el prefijo `LARES_`. La lista completa y comentada
está en [`.env.example`](.env.example); en una instalación nativa vive en
`/opt/lares/lares.env`. Lo que se toca de verdad:

| Variable | Para qué |
| --- | --- |
| `LARES_ALLOWED_HOSTS` | Por dónde se entra. Si no cuadra, `400` en todo |
| `LARES_HTTPS` | `0` por IP en red local, `1` con proxy y dominio delante |
| `LARES_SITE_URL` | Cómo se llega desde fuera; lo necesitan los correos con enlace |
| `LARES_EMAIL_URL` | Sin esto, los avisos de vencimiento no salen de la máquina |
| `LARES_TIME_ZONE` · `LARES_DEFAULT_COUNTRY` | Jurisdicción y calendario de obligaciones |
| `LARES_MODULES` | Qué módulos se cargan |

## Desarrollo

```bash
make setup                 # entorno virtual, dependencias y .env
docker compose up -d db redis
make migrate
uv run src/manage.py bootstrap_household --name "Mi hogar"
uv run src/manage.py runserver
```

```bash
make test      # batería de pruebas
make lint      # estilo
make check     # chequeo de Django
```

Con todo en contenedores: `make up && make logs`.

## Documentación

Vive en un **repositorio aparte** ([lares-docs]), que se clona en `docs/`. Por
dónde empezar:

- **Visión y alcance** — qué es y, sobre todo, qué no es
- **Modelo de dominio** — las 7 primitivas. *Léelo antes de escribir código*
- **Sistema de módulos** y cómo escribir uno
- **Catálogo de features** — todo lo que puede llegar a hacer, por capas
- **Decisiones de arquitectura** — el porqué de cada elección

## Principios

1. **El grafo es el producto.** Los módulos son consecuencia.
2. **Lo que no te avisa a tiempo, no sirve.**
3. **La captura es el cuello de botella.** Todo se juzga por la fricción que quita.
4. **El usuario es dueño de sus datos.** Exportación total desde el día uno.
5. **El núcleo no conoce a los módulos.** Hay una prueba que lo verifica.
6. **Nada se borra.** Se archiva.
7. **No competimos con lo especializado.** Paperless, Bitwarden, el calendario:
   se integran.

## Licencia

[GNU Affero General Public License v3.0](LICENSE).

Puedes usarlo, estudiarlo, cambiarlo y repartirlo. La condición es la de
siempre en AGPL y aquí es la que importa: **si ofreces esto como servicio a
otras personas por red, les debes el código fuente**, con tus cambios y bajo la
misma licencia. Alojarlo para ti y los tuyos no te obliga a nada.

[lares-docs]: https://github.com/ivancandelas/lares-docs

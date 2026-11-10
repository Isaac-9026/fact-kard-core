# Despliegue de Fact-Kard Core con Docker

Fact-Kard Core es el sistema **interno** (Kardex, inventario, comprobantes, finanzas y Formato 13.1), **sin emisión electrónica a SUNAT**. En el VPS convive con otros dos sistemas:

| Sistema | Repositorio | Stack Docker | Alias en `proxy_net` |
|---|---|---|---|
| Fact-Kard Core (este) | `fact-kard-core` | `factkard-core` | `factkard-core-web` |
| FACT-KARD (facturación SUNAT) | `fact-kard` | `factkard` | `factkard-web` |
| Sistema del turno mañana (PHP) | `sunat_asescon` | `sunat_asescon` | `asescon-app` |

El **proxy compartido** (Nginx + Let's Encrypt) vive en el repositorio `fact-kard`, en `deploy/docker/proxy/`. Es el único que abre los puertos 80/443 y reparte las visitas por dominio.

```
Internet ──80/443──► proxy compartido ──► factkard-core-web (Nginx + React)
                                                 │  red app
                                          backend (Django + Gunicorn)
                                                 │  red datos (internal)
                                          db (PostgreSQL 16) + redis      tareas (respaldo diario)
```

## Dos formas de usar Docker (no mezclarlas)

| Archivo | Para qué | Dónde |
|---|---|---|
| `docker-compose.yml` (raíz) + `.env.example` | **Desarrollo**: runserver, Vite, `DEBUG=True`, usuario demo | Solo laptop |
| `deploy/docker/compose.yaml` | **Producción**: Gunicorn, Nginx, Redis, respaldos, sin puertos | VPS |
| `deploy/docker/compose.local.yaml` | Probar la versión de producción en la laptop (`127.0.0.1:8083`) | Solo laptop |

Los archivos de `deploy/systemd`, `deploy/nginx` y `deploy/scripts` son la instalación antigua **sin Docker**. En el VPS compartido **no se usan**.

## Archivos de `deploy/docker/`

| Archivo | Para qué |
|---|---|
| `backend.Dockerfile` | Python 3.13 + Gunicorn + `pg_dump`/`pg_restore` 16. Usuario sin privilegios `factkard` (uid 10001). |
| `backend-entrypoint.sh` | Espera a PostgreSQL y ejecuta `collectstatic`. Migraciones solo a pedido. |
| `backend-healthcheck.py` | `GET /api/health/` (API + PostgreSQL + Redis). |
| `backend-tareas.sh` | Servicio `tareas`: respaldo completo diario a las 04:00 (base + media) con retención. |
| `web.Dockerfile` + `web-nginx.conf` | Compila React y lo sirve con Nginx; `/api/` va al backend. |
| `compose.yaml` | Stack `db`, `redis`, `backend`, `tareas`, `web`. **No publica puertos.** |
| `env.produccion.example` / `env.local.example` | Plantillas del `.env` del stack. |

## Reglas de seguridad

- **Docker se salta UFW:** ningún contenedor publica puertos en producción. La base y Redis solo existen en la red `datos` (interna).
- **Base de datos propia:** `fact_kard_core`, en el volumen `factkard-core_pgdata`. No comparte nada con FACT-KARD.
- **Nada sensible en las imágenes ni en Git:** `.env`, respaldos y `deploy/docker/datos/` están ignorados.
- **Cadena de proxies:** proxy → Nginx web → Gunicorn, por eso `NUM_PROXIES=2`.
- **Comandos demo bloqueados en producción:** `init_demo` y `seed_demo_ventas` fallan si `DEBUG=False`.
- **Memoria:** los límites suman ~2,4 GB (db 768 MB, backend 1 GB, tareas 384 MB, redis 128 MB, web 96 MB). El VPS necesita su swap de 4 GB.

## 1. Desarrollo en la laptop

```powershell
copy .env.example .env      # completar DEV_DB_PASSWORD y DEMO_PASSWORD (12+ caracteres)
docker compose up -d --build
```

Frontend en `http://localhost:5173`, API en `http://localhost:8000/api`. Para borrar todo, incluida la base: `docker compose down -v`.

## 2. Probar la versión de producción en la laptop

```powershell
cd deploy\docker
copy env.local.example .env          # completar SECRET_KEY y DB_PASSWORD
docker network create proxy_net      # una sola vez (si ya existe, ignorar el error)
docker compose -f compose.yaml -f compose.local.yaml up -d --build
docker compose run --rm backend python manage.py migrate
docker compose run --rm backend python manage.py seed_catalogos_sunat
docker compose -f compose.yaml -f compose.local.yaml ps   # todos "healthy"
```

Abrir `http://localhost:8083`. Para crear el administrador, ver la sección 3.

**Por el proxy:** en el `.env` del proxy (repositorio `fact-kard`) agregar `kardex.localhost=factkard-core-web:80` a `SITIOS`, ejecutar `docker compose up -d` y abrir `http://kardex.localhost`.

## 3. En el VPS

**Antes:** el servidor ya debe estar asegurado y tener Docker y la red `proxy_net` (ver la guía de FACT-KARD), y un registro **A** del subdominio apuntando a la IP del VPS.

```bash
sudo mkdir -p /srv/fact-kard-core && sudo chown $USER /srv/fact-kard-core
git clone https://github.com/Isaac-9026/fact-kard-core.git /srv/fact-kard-core/app
cd /srv/fact-kard-core/app/deploy/docker
cp env.produccion.example .env && chmod 600 .env && nano .env   # completar todo lo marcado <...>

mkdir -p datos/respaldos
sudo chown 10001:10001 datos/respaldos && chmod 700 datos/respaldos

docker compose build
docker compose up -d db redis
docker compose run --rm backend python manage.py migrate
docker compose run --rm backend python manage.py seed_catalogos_sunat
docker compose run --rm backend python manage.py check --deploy
docker compose up -d
docker compose ps        # backend, tareas y web "healthy"
```

**Primer administrador.** El sistema usa su propio modelo `Usuario`, no `createsuperuser`:

```bash
docker compose run --rm backend python manage.py shell -c "
from getpass import getpass
from django.contrib.auth.password_validation import validate_password
from apps.usuarios.models import Usuario
u = Usuario(username=input('Usuario: ').strip(), email=input('Correo: ').strip(), es_admin_global=True)
c = getpass('Contraseña: ')
assert c == getpass('Repetir contraseña: '), 'Las contraseñas no coinciden'
validate_password(c)
u.set_password(c); u.save(); print('Administrador creado:', u.username)"
```

## 4. Dominio y HTTPS (en el proxy compartido)

En `/srv/fact-kard/app/deploy/docker/proxy/.env`, agregar el sitio a la lista `SITIOS`, separado por espacio:

```
SITIOS=facturacion.asescon.net=factkard-web:80 kardex.asescon.net=factkard-core-web:80 sistema.asescon.net=asescon-app:80
```

```bash
cd /srv/fact-kard/app/deploy/docker/proxy
docker compose up -d --build
docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
    -d kardex.asescon.net --email <correo> --agree-tos --no-eff-email
docker compose restart proxy
curl -s https://kardex.asescon.net/api/health/
```

El servicio `renovador` del proxy renueva el certificado solo.

## 5. Operación diaria (en `deploy/docker`)

| Tarea | Comando |
|---|---|
| Estado | `docker compose ps` |
| Logs | `docker compose logs -f backend` (o `web`, `db`, `tareas`) |
| Actualizar | `git pull` → `docker compose build` → `docker compose run --rm backend python manage.py migrate` → `docker compose up -d` |
| Respaldo manual | `docker compose exec backend python manage.py respaldo crear` → queda en `datos/respaldos/` |
| Verificar respaldo | `docker compose exec backend python manage.py respaldo verificar /srv/fact-kard/datos/respaldos/<nombre>` |
| Respaldo automático | Servicio `tareas`, cada día a las 04:00 (Lima). Otra hora: `FK_RESPALDO_HORA=HH:MM` en `.env` |

**Copia externa:** copiar `datos/respaldos/` fuera del VPS (rsync o descarga). El `.env` se guarda aparte, en un gestor de contraseñas.

**Nunca:**
- `docker compose down -v` en producción: borra la base de datos;
- publicar `ports` en `db` o `redis`;
- ejecutar `init_demo` o `seed_demo_ventas` en el servidor;
- subir `.env` o `deploy/docker/datos/` a Git.

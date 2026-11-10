# syntax=docker/dockerfile:1
# Contenedor "web" de Fact-Kard Core: React compilado + Nginx interno.
#   /        → frontend (frontend/dist, compilado aquí con frontend/.env.production → VITE_API_URL=/api)
#   /api/    → backend (Gunicorn en backend:8001, red interna)
#   /static/ → collectstatic de Django (volumen compartido, solo lectura)
# No publica puertos: el proxy compartido (repositorio fact-kard, deploy/docker/proxy) le envía el tráfico de su dominio.
FROM node:22-bookworm-slim AS build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM nginx:1.28-alpine
COPY deploy/docker/web-nginx.conf /etc/nginx/conf.d/default.conf
RUN sed -i 's/\r$//' /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/nginx-health || exit 1

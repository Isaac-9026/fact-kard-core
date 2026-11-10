# SOLO DESARROLLO (docker-compose.yml de la raíz): servidor de Vite con recarga.
# La imagen de producción es deploy/docker/web.Dockerfile (build + Nginx).
FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

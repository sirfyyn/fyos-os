# Shell von FYOS: Astro-Build, ausgeliefert von nginx auf Port 8080.
# Beide Basisbilder sind öffentlich.

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Vorgabe-Name des Systems; zur Laufzeit überschreibbar über /fyos.config.json
ARG PUBLIC_FYOS_NAME=FYOS
ENV PUBLIC_FYOS_NAME=$PUBLIC_FYOS_NAME
RUN npm run build

FROM nginx:1.27-alpine
# Das nginx-Image setzt Dateien unter /etc/nginx/templates mit envsubst zu conf.d/*.conf um.
# Ersetzt werden nur Variablen mit diesem Präfix; $uri & Co bleiben nginx.
ENV NGINX_ENVSUBST_FILTER=FYOS_
ENV FYOS_HUB_UPSTREAM=http://hub:8080
ENV FYOS_AGENT_UPSTREAM=http://agent:18789
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
# Laufzeit-Konfiguration: diese Datei kann gemountet werden (ConfigMap, Volume).
COPY nginx/fyos.config.default.json /etc/fyos/fyos.config.json
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1

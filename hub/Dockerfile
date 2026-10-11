# FYOS-Hub — Image
#
# Bauen (Kontext = Ordner hub/):
#   docker build -t fyos-hub:latest hub/
#
# Weitere Plugins als eigene Pakete: ein abgeleitetes Image mit `RUN uv pip install --system fyos-plugin-...`
# oder ein Bau-Argument:
#   docker build --build-arg EXTRA_PIP="fyos-plugin-finanzen" -t fyos-hub:mit-finanzen hub/
#
# Installiert wird mit uv statt pip. Liegen die Plugin-Pakete in einem eigenen Paketindex (z. B. der PyPI-Registry
# eines Gitea), steht dessen Adresse als Bau-Argument FYOS_INDEX_URL VOR PyPI:
#   docker build --build-arg EXTRA_PIP="fyos-plugin-finanzen" \
#     --build-arg FYOS_INDEX_URL=https://registry.example.com/api/packages/org/pypi/simple -t fyos-hub:mit-finanzen hub/
# uv fragt die Indizes der Reihe nach (--index-strategy first-index) und nimmt ein Paket nur aus dem ersten Index, der
# es führt. Ein Paket gleichen Namens auf PyPI kann das eigene so nicht verdrängen; pip mit --extra-index-url nähme
# die höchste Version aus allen Indizes (Dependency Confusion).
FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="FYOS-Hub"
LABEL org.opencontainers.image.description="MCP-Hub von FYOS - For Your Own Sake: Plugins, Apps mit Oberflaeche, optionale OIDC-Anmeldung"

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# uv aus dem offiziellen Bild, in fester Version.
COPY --from=ghcr.io/astral-sh/uv:0.12.8 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY mcp_hub/ /app/mcp_hub/
RUN uv pip install --system --no-cache ".[suche]"

# Zusätzliche Plugin-Pakete; der eigene Index (falls gesetzt) steht vor PyPI, die Strategie bleibt first-index.
ARG EXTRA_PIP=""
ARG FYOS_INDEX_URL=""
RUN if [ -n "$EXTRA_PIP" ]; then \
      uv pip install --system --no-cache --index-strategy first-index \
        ${FYOS_INDEX_URL:+--index "$FYOS_INDEX_URL"} $EXTRA_PIP; \
    fi

COPY config.example.yaml /app/config.yaml
ENV MCP_HUB_CONFIG_PATH=/app/config.yaml

RUN useradd --uid 1000 --create-home --shell /bin/bash fyos && chown -R fyos:fyos /app

# Dateiablage (Plugin dateien): FYOS_DATEIEN zeigt hierher. Der Ordner gehört dem Hub-Nutzer, damit ein neues Volume
# (Docker) mit diesen Rechten entsteht; ein eingehängter Ordner des Hosts muss ihm (uid 1000) gehören.
ENV FYOS_DATEIEN=/data/dateien
RUN mkdir -p /data/dateien && chown fyos:fyos /data/dateien
USER fyos

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

CMD ["python3", "-m", "mcp_hub.server"]

# ---- stage 1: build the web bundle -------------------------------------
FROM node:22-alpine AS web

WORKDIR /build
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/contracts/package.json packages/contracts/package.json
RUN npm ci

COPY packages/contracts packages/contracts
COPY apps/web apps/web
RUN npm --workspace apps/web run build

# ---- stage 2: the app image --------------------------------------------
FROM python:3.12-slim AS app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY apps/api/pyproject.toml ./
COPY apps/api/kira ./kira
RUN pip install --no-cache-dir .

COPY apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic
COPY apps/api/docker-entrypoint.sh ./docker-entrypoint.sh

# The bundle lands beside the package, where create_app() looks for it.
COPY --from=web /build/apps/web/dist ./kira/static

RUN adduser --system --no-create-home kira && chown -R kira /app
USER kira

EXPOSE 8000
CMD ["./docker-entrypoint.sh"]

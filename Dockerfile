# Build the browser bundles (frontend/ -> static/dist)
FROM node:22-trixie-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-trixie

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY . /app
COPY --from=frontend /app/static/dist /app/static/dist

# Disable development dependencies
ENV UV_NO_DEV=1

# Sync the project into a new environment, asserting the lockfile is up to date
WORKDIR /app
RUN uv sync --locked

CMD ["sh", "-c", "uv run python app.py --workers 1"]

# syntax=docker/dockerfile:1

FROM node:22-slim AS console-build
WORKDIR /build/console
# Vite inlines these at BUILD time, so they cannot come from `fly secrets`. They are public
# by design — a SPA client id and a tenant domain ship to every browser anyway (FR-057).
ARG VITE_AUTH0_DOMAIN
ARG VITE_AUTH0_CLIENT_ID
ARG VITE_AUTH0_AUDIENCE
ENV VITE_AUTH0_DOMAIN=$VITE_AUTH0_DOMAIN \
    VITE_AUTH0_CLIENT_ID=$VITE_AUTH0_CLIENT_ID \
    VITE_AUTH0_AUDIENCE=$VITE_AUTH0_AUDIENCE
COPY console/ ./
RUN if [ -f package.json ]; then npm ci && npm run build; fi

FROM node:22-slim AS video-deps
WORKDIR /build/video
COPY video/ ./
RUN if [ -f package.json ]; then npm ci; fi

FROM python:3.13-slim AS base

# Headless Chrome for Remotion rendering, plus Node 22 for the same purpose.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        gnupg \
        chromium \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

COPY --from=console-build /build/console/dist ./console/dist
COPY --from=video-deps /build/video/node_modules ./video/node_modules

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

FROM ghcr.io/astral-sh/uv:0.11-debian-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# R9 (2026-11-27): Runaway-/Loop-Runs hart begrenzen — idle Session nach 1 h geerntet,
# Execution spaetestens nach 2 h abgebrochen (statt 24 h idle / 8 d Execution:
# beobachtete Loops liefen als CONTINUED_AS_NEW-Kette exakt 24 h bis zum Timeout).
ENV UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    PATH="/app/.venv/bin:$PATH" \
    AGENTS_SDK_IDLE_TIMEOUT_SECONDS=3600 \
    AGENTS_SDK_LIFETIME_LIMIT_SECONDS=604800 \
    AGENTS_SDK_EXECUTION_TIMEOUT_SECONDS=7200
WORKDIR /app
COPY . .
RUN uv sync --frozen --no-dev \
 && useradd --create-home --shell /usr/sbin/nologin agent \
 && chown -R agent:agent /app
USER agent
CMD ["agents", "run-worker"]

FROM ghcr.io/astral-sh/uv:0.11-debian-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# R9 (2026-11-27): Runaway-/Loop-Runs hart begrenzen — idle Session nach 1 h geerntet,
# Session-Lebenszeit (CONTINUED_AS_NEW-Kette) nach 1 h normal beendet
# (statt 24 h idle: beobachtete Loops liefen als Kette exakt 24 h bis zum Timeout).
# R12 (2026-11-27): SDK-Invariante mistralai-agents 1.1.0 (AppSettings, env prefix AGENTS_SDK_):
# lifetime_limit + limit_grace (Default 300) muss STRICT < execution_timeout sein, ebenso
# callback_timeout (Default 3600) und sandbox_provisioning_timeout (Default 9900) — sonst
# verweigert der Worker den Start mit ValidationError (Deployment phase=failed, beobachtet
# 2026-11-27 23:37Z mit lifetime=604800/exec=7200). Daher exec=10800 als reiner Temporal-Backstop.
ENV UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    PATH="/app/.venv/bin:$PATH" \
    AGENTS_SDK_IDLE_TIMEOUT_SECONDS=3600 \
    AGENTS_SDK_LIFETIME_LIMIT_SECONDS=3600 \
    AGENTS_SDK_EXECUTION_TIMEOUT_SECONDS=10800
WORKDIR /app
COPY . .
RUN uv sync --frozen --no-dev \
 && useradd --create-home --shell /usr/sbin/nologin agent \
 && chown -R agent:agent /app
USER agent
CMD ["agents", "run-worker"]

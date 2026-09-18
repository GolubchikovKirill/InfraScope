FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --python /usr/local/bin/python

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --python /usr/local/bin/python


# Reuse the same Python base as the build stage.  This is already present on
# the production host and avoids a second registry download during rollout.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

# iputils-ping backs the ICMP reachability fallback in app/services/device_poll.py:
# general-purpose media player boxes (nettop/twix) often answer only to ping,
# with every TCP port we scan and SNMP both closed by their own firewall.
# Debian's package installer sets cap_net_raw+p on the binary, which is enough
# for the unprivileged "app" user given the NET_RAW capability Docker grants
# containers by default - no extra --cap-add needed at deploy time.
#
# This host's container egress is known-flaky (see the docker-hub-egress
# incidents): short requests come back fine, but index/blob transfers stall
# mid-copy and apt never times out on its own, so each attempt gets a hard
# ceiling and a few tries instead of hanging the build indefinitely.
RUN for i in 1 2 3 4 5 6; do \
        timeout 90 sh -c 'apt-get update -o Acquire::Retries=3 -o Acquire::http::Timeout=15 && apt-get install -y --no-install-recommends iputils-ping' && break; \
        echo "apt-get attempt $i/6 failed, retrying in 5s..." >&2; \
        sleep 5; \
    done; \
    dpkg -s iputils-ping > /dev/null && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --shell /bin/bash --create-home app

COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY scripts/prestart.sh /app/scripts/prestart.sh
RUN sed -i 's/\r$//' /app/scripts/prestart.sh && chmod +x /app/scripts/prestart.sh

USER app

EXPOSE 8000

CMD ["sh", "-c", "/app/scripts/prestart.sh && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2}"]

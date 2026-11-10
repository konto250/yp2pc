FROM node:22-bookworm-slim AS javascript
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MEDIA_DIR=/data \
    HOME=/tmp

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=javascript /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install -r requirements.txt \
    && groupadd --gid 1000 yp2pc \
    && useradd --uid 1000 --gid 1000 --no-create-home yp2pc \
    && mkdir /data && chown yp2pc:yp2pc /data

COPY api/ ./api/
COPY yp2pc/ ./yp2pc/
COPY public/ ./public/
COPY dev.py ./
COPY scripts/smoke.py ./scripts/smoke.py
COPY scripts/set_password.py ./scripts/set_password.py
COPY tests/ ./tests/

USER yp2pc
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:3000/health', timeout=3).close()"
CMD ["python", "dev.py", "--host", "0.0.0.0", "--port", "3000"]

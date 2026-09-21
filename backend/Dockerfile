# One image, many roles. The role is the container command: `desk-api`, `desk-worker <role>`, `desk-seed`.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# librdkafka is bundled in the confluent-kafka wheel; psycopg[binary] ships its own libpq. No apt needed.
COPY pyproject.toml ./
COPY servicing_desk ./servicing_desk
RUN pip install --upgrade pip && pip install .

# Non-root. The only writable path is the document archive (a mounted volume in k8s).
RUN useradd -r -u 10001 desk && mkdir -p /app/documents && chown desk /app/documents
USER desk

EXPOSE 8000
CMD ["desk-api"]

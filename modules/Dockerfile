# Baobab application-service image: the Python layer in front of iDempiere
# (modules/) plus the psql client and SQL files needed to apply db/migrations.
# Build context is the repository root (see compose.yaml).
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --system --create-home --uid 1000 baobab

WORKDIR /app
COPY modules/ /app/
COPY db/ /db/
RUN pip install --no-cache-dir -e . \
    && chmod +x /app/scripts/dispatch_worker_loop.sh /app/scripts/inbox_worker_loop.sh /app/scripts/provisioning_worker_loop.sh \
    && chown -R baobab:baobab /app /db

ENV PYTHONUNBUFFERED=1
USER baobab
CMD ["python", "-m", "application.server"]

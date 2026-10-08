#!/usr/bin/env bash
# Periodic scheduler for application.provisioning_worker (ADR-ERP-019), mirroring inbox_worker_loop.sh: the worker is a one-shot
# process by design, so how often it runs is deployment configuration. A failed tick is logged and retried on the next tick;
# retries, backoff and failing of individual operations live in the worker and the operation rows, not in this loop.
set -euo pipefail

interval="${BAOBAB_PROVISIONING_INTERVAL_SECONDS:-30}"

while true; do
  if ! python -m application.provisioning_worker; then
    echo "provisioning_worker tick failed; retrying in ${interval}s" >&2
  fi
  sleep "${interval}"
done

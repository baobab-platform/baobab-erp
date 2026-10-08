#!/usr/bin/env bash
# Periodic scheduler for application.inbox_worker (ADR-ERP-006), mirroring dispatch_worker_loop.sh: the worker is a one-shot
# process by design, so how often it runs is deployment configuration. A failed tick is logged and retried on the next tick;
# retries, backoff and dead-lettering of individual events live in the worker and the inbox rows, not in this loop.
set -euo pipefail

interval="${BAOBAB_INBOX_INTERVAL_SECONDS:-15}"

while true; do
  if ! python -m application.inbox_worker; then
    echo "inbox_worker tick failed; retrying in ${interval}s" >&2
  fi
  sleep "${interval}"
done

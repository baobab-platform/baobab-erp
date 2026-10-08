-- FB-04b: scheduled, observable delivery of canonical events.
--
-- A retry used to be eligible again on the very next run of the dispatcher, whatever its backoff said. next_attempt_at makes the
-- backoff real: a row in 'retry' is picked up only once it is due. delivered_at and dead_lettered_at say when each ended, so an
-- operator and the delivery metrics can tell how long events waited and when they gave up.
ALTER TABLE baobab.event_outbox
    ADD COLUMN next_attempt_at   TIMESTAMPTZ,
    ADD COLUMN delivered_at      TIMESTAMPTZ,
    ADD COLUMN dead_lettered_at  TIMESTAMPTZ;

CREATE INDEX event_outbox_due_idx ON baobab.event_outbox (next_attempt_at, occurred_at)
    WHERE status IN ('pending', 'retry') AND envelope_format = 'cloudevents';

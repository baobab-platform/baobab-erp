-- ADR-ERP-023 BP-03/BP-04 experimental native PostgreSQL 17 verification.
-- A migration receipt is NOT evidence that authority/version guards are
-- still installed and enabled. No employee or payroll data is read here.
WITH migrations(filename) AS (
  VALUES ('people/P0001_workforce_proposal.sql'),
         ('people/P0002_payroll_draft.sql')
), triggers(table_name, trigger_name) AS (
  VALUES
    ('employment_proposal', 'employment_proposal_cas'),
    ('employment_proposal', 'employment_proposal_immutable'),
    ('employment_proposal', 'employment_proposal_no_truncate'),
    ('payroll_draft', 'payroll_draft_cas'),
    ('payroll_draft', 'payroll_draft_immutable'),
    ('payroll_draft', 'payroll_draft_no_truncate')
), missing_migrations AS (
  SELECT m.filename FROM migrations m
   WHERE NOT EXISTS (
    SELECT 1 FROM baobab.schema_migrations s WHERE s.filename = m.filename)
), missing_triggers AS (
  SELECT t.* FROM triggers t
  LEFT JOIN pg_namespace n ON n.nspname='baobab_people'
  LEFT JOIN pg_class c ON c.relnamespace=n.oid AND c.relname=t.table_name
  LEFT JOIN pg_trigger g ON g.tgrelid=c.oid AND g.tgname=t.trigger_name
      AND NOT g.tgisinternal AND g.tgenabled='O'
  WHERE g.oid IS NULL
)
SELECT (SELECT count(*) FROM missing_migrations)
     + (SELECT count(*) FROM missing_triggers)
     + CASE WHEN current_setting('server_version_num')::integer BETWEEN 170000 AND 179999
            THEN 0 ELSE 1 END AS missing_controls;

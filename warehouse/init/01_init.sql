-- Runs once, on first creation of the warehouse volume. Re-running it requires
-- `just nuke`, so keep it to bootstrapping that dbt cannot do itself.

-- Landing zone for ingested data; dbt creates its own schemas and reads here.
create schema if not exists raw;

comment on schema raw is
'Landing zone for ingested source data. Written by ingestion only; '
'dbt reads from here and never writes to it.';

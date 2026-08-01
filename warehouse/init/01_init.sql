-- Runs once, on first creation of the warehouse volume. Re-applying it requires
-- `just nuke`, so keep it to bootstrapping that dbt cannot do itself.

-- Landing zone for ingested data; dbt creates its own schemas and reads here.
create schema if not exists raw;

comment on schema raw is
'Landing zone for ingested source data. Written by ingestion only; '
'dbt reads from here and never writes to it.';

-- Landing tables for the ingestion in src/ingest.py. Both carry their natural
-- key as the primary key, so re-running an ingest upserts instead of appending.

-- Stored at the source's own 15-minute grain. Aggregating to hourly is a
-- modelling decision and belongs in dbt, not here.
create table raw.wholesale_prices_15m (
    bidding_zone text not null,
    interval_start_utc timestamptz not null,
    interval_end_utc timestamptz not null,
    price_eur_mwh numeric not null,
    loaded_at timestamptz not null default now(),
    primary key (bidding_zone, interval_start_utc)
);

comment on table raw.wholesale_prices_15m is
'Day-ahead wholesale prices at the source grain of 15 minutes, from '
'api.energy-charts.info. The bidding zone is part of the key so a second '
'zone cannot collide with DE-LU.';

comment on column raw.wholesale_prices_15m.interval_end_utc is
'Stored rather than derived so a row states its own duration, which keeps '
'history readable if the market resolution ever changes.';

comment on column raw.wholesale_prices_15m.loaded_at is
'Refreshed on every upsert, so it changes on a re-run even when no value did.';

-- Synthetic, generated deterministically from (customer_id, timestamp); see
-- src/ingest.py. Hourly, while prices are quarter-hourly.
create table raw.customer_consumption (
    customer_id integer not null,
    timestamp_utc timestamptz not null,
    consumption_kwh numeric not null,
    loaded_at timestamptz not null default now(),
    primary key (customer_id, timestamp_utc)
);

comment on table raw.customer_consumption is
'Synthetic hourly metered consumption. Values are reproducible from the '
'primary key alone, so re-ingesting a period cannot change history.';

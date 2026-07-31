# energy-margin-pipeline

[![ci](https://github.com/pkosel/energy-margin-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/pkosel/energy-margin-pipeline/actions/workflows/ci.yml)

Local Airflow + dbt + Postgres environment for energy margin analytics.

Status: infrastructure only. There are no dbt models and no ingestion yet — the
`smoke_test` DAG exists to prove that Airflow can reach dbt and dbt can reach the
warehouse.

## Layout

```
airflow/dags/        DAG definitions (bind-mounted into the containers)
airflow/Dockerfile   Airflow image, plus an isolated dbt venv
dbt/                 dbt project root; also the profiles dir
tests/               pytest suite, run inside the scheduler container
warehouse/init/      SQL applied once, on first creation of the warehouse volume
flake.nix            host-side tooling (psql, linters, just); not the runtime
justfile             command shortcuts
```

## Prerequisites

- Docker with Compose v2
- Nix with flakes, and optionally direnv — for the host-side tooling. Everything
  else runs in containers, so Nix is not required to bring the stack up.

## Setup

```sh
cp .env.example .env   # then fill in FERNET_KEY and AIRFLOW_JWT_SECRET
just up
```

`.env.example` documents how to generate each secret. Compose reads `.env`
automatically; `.envrc` also exports the warehouse credentials as `PG*` so a bare
`psql` on the host connects to the warehouse.

The first `just up` builds the image and runs migrations, which takes a few
minutes. Afterwards:

- Airflow UI: <http://localhost:8080>, credentials from `AIRFLOW_ADMIN_*`
- Warehouse: `localhost:${WAREHOUSE_DB_PORT}`, or just `psql`

New DAGs are paused at creation, so unpause `smoke_test` in the UI before
triggering it.

## Common commands

```sh
just              # list recipes
just dbt run      # any dbt command, in the scheduler container
just test         # pytest
just lint         # pre-commit across all files
just logs <svc>   # follow one service
just down         # stop; keeps volumes
just nuke         # stop and drop volumes (warehouse data and Airflow metadata)
```

## Design notes

**Two Postgres instances.** `postgres-airflow` holds Airflow metadata and is not
published to the host; `warehouse` holds the analytics data and is. Keeping them
separate means `just nuke` or a warehouse restore cannot damage scheduler state,
and the warehouse role needs no Airflow privileges.

**dbt in its own venv.** dbt and Airflow disagree on shared dependency versions.
The image installs Airflow under its official constraints file, then dbt into
`/opt/dbt-venv`, which is added to `PATH`. Consequently dbt is only callable as a
subprocess (`BashOperator`), not importable from DAG code.

**Schemas.** `warehouse/init/01_init.sql` creates `raw` for ingested data. dbt
writes to `DBT_SCHEMA` (default `analytics`), and per-directory `+schema` settings
make Postgres targets `analytics_staging` and `analytics_marts`. The init script
runs only when the volume is empty, so schema changes there require `just nuke`.

**Airflow parallelism** is capped at 4 tasks to keep a laptop responsive under
`LocalExecutor`.

## CI

`.github/workflows/ci.yml` runs pre-commit via `nix develop`, then brings the
full stack up on throwaway secrets and tests it at two levels: `pytest` for DAG
parsing and policy, and `airflow dags test smoke_test --use-executor` for one
end-to-end run through the executor. The cheap layer localises failures; the
expensive one proves the pieces are wired together.

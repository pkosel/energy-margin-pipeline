default:
    @just --list

# --------------------
# Stack lifecycle
# --------------------

up:
    docker compose up -d

down:
    docker compose down

# Drops warehouse data and Airflow metadata; the only way to re-apply warehouse/init.
nuke:
    docker compose down -v

# Only for image changes (Dockerfile, requirements); DAGs and dbt are bind-mounted.
rebuild:
    docker compose build

ps:
    docker compose ps

logs service="":
    docker compose logs -f {{ service }}

# --------------------
# Development
# --------------------

# Runs in the scheduler container, where dbt and the profile live.
dbt *args:
    docker compose exec airflow-scheduler dbt {{ args }}

# Plain Python, no Airflow. Example: just ingest --start 2026-05-01 --end 2026-07-31
ingest *args:
    docker compose exec airflow-scheduler python -m src.ingest {{ args }}

# Same container, so tests import the Airflow the DAGs actually run on.
test *args:
    docker compose exec airflow-scheduler pytest tests/ -v {{ args }}

# Host psql; .envrc points PG* at the warehouse.
psql *args:
    psql {{ args }}

lint:
    pre-commit run --all-files

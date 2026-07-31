default:
    @just --list

# --------------------
# Stack lifecycle
# --------------------

up:
    docker compose up -d

down:
    docker compose down

# Drops the volumes too: warehouse data, Airflow metadata and the admin user.
# Needed after editing warehouse/init.
nuke:
    docker compose down -v

# Only for image changes (Dockerfile, requirements). DAGs and dbt models are
# bind-mounted and need no rebuild.
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

# Same container, so tests import the Airflow the DAGs actually run on.
test *args:
    docker compose exec airflow-scheduler pytest tests/ -v {{ args }}

# Host psql; .envrc points PG* at the warehouse.
psql *args:
    psql {{ args }}

lint:
    pre-commit run --all-files

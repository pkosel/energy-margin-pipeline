"""Environment smoke test.

Runs `dbt debug` to confirm that a task can reach dbt and that dbt can reach
the warehouse. Trigger it manually after rebuilding the image or changing
warehouse credentials; a failure points at the environment, not at a model.

Rendered as the DAG documentation in the Airflow UI.
"""

from __future__ import annotations

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag


@dag(
    dag_id="smoke_test",
    # Manual only: this checks the environment, not a data dependency.
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["smoke", "infra"],
    doc_md=__doc__,
)
def smoke_test() -> None:
    # dbt lives in a separate venv and is only on PATH, so it has to be shelled
    # out to. DBT_PROFILES_DIR and DBT_PROJECT_DIR come from the environment.
    BashOperator(task_id="dbt_debug", bash_command="dbt debug")


smoke_test()

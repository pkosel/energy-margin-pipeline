"""Structural checks over every DAG; no task is executed.

Runs inside the scheduler container, against the same Airflow install the DAGs
run on.
"""

from __future__ import annotations

import pytest
from airflow.dag_processing.dagbag import DagBag

# Container path of the ./airflow/dags bind mount.
DAG_FOLDER = "/opt/airflow/dags"


@pytest.fixture(scope="session")
def dagbag() -> DagBag:
    return DagBag(dag_folder=DAG_FOLDER)


def test_no_import_errors(dagbag: DagBag) -> None:
    assert not dagbag.import_errors, f"DAG import failures: {dagbag.import_errors}"


def test_smoke_test_dag_is_present(dagbag: DagBag) -> None:
    assert "smoke_test" in dagbag.dags


def test_every_dag_has_tags(dagbag: DagBag) -> None:
    """Tags are the only way to filter the DAG list in the UI."""
    untagged = [dag_id for dag_id, dag in dagbag.dags.items() if not dag.tags]
    assert not untagged, f"DAGs without tags: {untagged}"

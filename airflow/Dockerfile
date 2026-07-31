# Build context is the repository root, so that both requirements files below
# are reachable.
FROM apache/airflow:3.3.0

# git is needed by `dbt deps` for packages installed from a repository.
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -o airflow -g 0 /opt/dbt-venv

USER airflow

# Airflow's constraints file pins the whole dependency tree for this exact
# Airflow/Python combination; without it, provider installs can break the image.
COPY airflow/requirements.txt /tmp/airflow-requirements.txt
RUN pip install --no-cache-dir -r /tmp/airflow-requirements.txt \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.3.0/constraints-3.13.txt"

# dbt goes into its own venv: it conflicts with Airflow's pins, and the
# constraints file above would hold those pins in place.
COPY dbt/requirements.txt /tmp/dbt-requirements.txt
RUN python -m venv /opt/dbt-venv \
    && /opt/dbt-venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/dbt-venv/bin/pip install --no-cache-dir -r /tmp/dbt-requirements.txt

# Puts `dbt` on PATH for BashOperator tasks. It stays un-importable from DAG
# code, which is the point of the split.
ENV PATH="${PATH}:/opt/dbt-venv/bin"

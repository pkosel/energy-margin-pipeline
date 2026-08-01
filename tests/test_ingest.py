"""Tests for the raw-layer ingestion.

Runs inside the scheduler container, where src/ is mounted and the warehouse is
reachable. Nothing here touches the network: fetch_prices is covered by actually
running the command, while parse_prices is tested against a recorded payload.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

from src.ingest import (
    BIDDING_ZONE,
    INTERVAL,
    connect,
    generate_consumption,
    iter_consumption,
    load_consumption,
    load_prices,
    parse_prices,
    weekly_chunks,
)

SOME_TIMESTAMP = datetime(2026, 5, 1, 18, 0, tzinfo=timezone.utc)

# Shape of a real /price response, trimmed to four intervals. The third price is
# null to cover a missing auction result.
PAYLOAD = {
    "license_info": "CC BY 4.0",
    "unix_seconds": [1777586400, 1777587300, 1777588200, 1777589100],
    "price": [115.99, 108.86, None, 99.1],
    "unit": "EUR / MWh",
    "deprecated": False,
}


def test_consumption_is_deterministic() -> None:
    assert generate_consumption(1, SOME_TIMESTAMP) == generate_consumption(
        1, SOME_TIMESTAMP
    )


def test_consumption_is_deterministic_across_processes() -> None:
    """The property that actually matters: re-running must not rewrite history.

    hash() is salted per process for anything containing a string, so an
    in-process assertion alone passes even when values differ between runs.
    Varying PYTHONHASHSEED reproduces exactly that condition.
    """
    snippet = (
        "from datetime import datetime, timezone;"
        "from src.ingest import generate_consumption;"
        "print(generate_consumption(1, datetime(2026, 5, 1, 18, tzinfo=timezone.utc)))"
    )
    values = {
        subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            check=True,
            env=os.environ | {"PYTHONHASHSEED": seed},
        ).stdout.strip()
        for seed in ("0", "1", "random")
    }
    assert len(values) == 1, f"value varies by process: {values}"


def test_consumption_is_non_negative() -> None:
    assert generate_consumption(1, SOME_TIMESTAMP) >= 0


@pytest.mark.parametrize("hour", range(24))
def test_consumption_is_non_negative_across_the_day(hour: int) -> None:
    """Off-peak hours sit near the noise floor, so the clamp matters there."""
    for customer_id in range(1, 21):
        timestamp = SOME_TIMESTAMP.replace(hour=hour)
        assert generate_consumption(customer_id, timestamp) >= 0


def test_parse_prices_maps_intervals() -> None:
    rows = parse_prices(PAYLOAD)

    assert len(rows) == 3, "the null price should be dropped"
    zone, start, end, price = rows[0]
    assert zone == BIDDING_ZONE
    assert start == datetime(2026, 4, 30, 22, 0, tzinfo=timezone.utc)
    assert end == start + INTERVAL
    assert price == 115.99


def test_parse_prices_rejects_unexpected_resolution() -> None:
    """A silent switch to hourly would otherwise be stored as 15-minute rows."""
    hourly = PAYLOAD | {"unix_seconds": [1777586400, 1777590000], "price": [1.0, 2.0]}

    with pytest.raises(ValueError, match="intervals"):
        parse_prices(hourly)


def test_weekly_chunks_do_not_overlap() -> None:
    chunks = list(weekly_chunks(date(2026, 5, 1), date(2026, 7, 31)))

    assert chunks[0] == (date(2026, 5, 1), date(2026, 5, 7))
    assert chunks[-1][1] == date(2026, 7, 31)
    for (_, earlier_end), (later_start, _) in zip(chunks, chunks[1:]):
        assert later_start == earlier_end + timedelta(days=1)


@pytest.fixture
def conn():
    """A warehouse connection whose work is rolled back.

    Loading into the real tables is the point — it exercises the actual DDL and
    conflict targets — so the transaction is discarded instead of committed.
    """
    connection = connect()
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def test_rerunning_load_does_not_duplicate_rows(conn) -> None:
    prices = parse_prices(PAYLOAD)
    usage = list(iter_consumption(date(2026, 1, 1), date(2026, 1, 1), customers=3))

    for _ in range(2):
        load_prices(conn, prices)
        load_consumption(conn, usage)

    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from raw.wholesale_prices_15m where interval_start_utc = any(%s)",
            ([row[1] for row in prices],),
        )
        assert cur.fetchone()[0] == len({row[1] for row in prices})

        cur.execute(
            "select count(*) from raw.customer_consumption where timestamp_utc = any(%s)",
            ([row[1] for row in usage],),
        )
        assert cur.fetchone()[0] == len({(row[0], row[1]) for row in usage})

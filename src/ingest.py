"""Load wholesale prices and synthetic consumption into the raw schema.

Deliberately free of Airflow imports: these are ordinary functions that a DAG
can call later, and that can be run by hand while developing.

    python -m src.ingest --start 2026-05-01 --end 2026-07-31

Both loads upsert on the natural key and the consumption values are a pure
function of that key, so re-running any period is a no-op.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import random
import sys
from collections.abc import Iterable, Iterator, Sequence
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

PRICE_API = "https://api.energy-charts.info/price"
BIDDING_ZONE = "DE-LU"

# The German day-ahead market settles in quarter-hours. parse_prices refuses
# anything else rather than silently mislabelling interval_end_utc.
INTERVAL = timedelta(minutes=15)

# The API interprets its date parameters in market-local time, and so must the
# consumption profile: an evening peak is only meaningful in local hours.
LOCAL_TZ = ZoneInfo("Europe/Berlin")

CUSTOMER_COUNT = 100
CHUNK = timedelta(days=7)

log = logging.getLogger("ingest")

PriceRow = tuple[str, datetime, datetime, float]
UsageRow = tuple[int, datetime, float]

UPSERT_PRICES = """
insert into raw.wholesale_prices_15m (
    bidding_zone,
    interval_start_utc,
    interval_end_utc,
    price_eur_mwh
)
values (%s, %s, %s, %s)
on conflict (bidding_zone, interval_start_utc)
do update set
    interval_end_utc = excluded.interval_end_utc,
    price_eur_mwh = excluded.price_eur_mwh,
    loaded_at = now();
"""

UPSERT_CONSUMPTION = """
insert into raw.customer_consumption (
    customer_id,
    timestamp_utc,
    consumption_kwh
)
values (%s, %s, %s)
on conflict (customer_id, timestamp_utc)
do update set
    consumption_kwh = excluded.consumption_kwh,
    loaded_at = now();
"""


def weekly_chunks(start: date, end: date) -> Iterator[tuple[date, date]]:
    """Split an inclusive date range into inclusive weekly ranges.

    The API treats `end` as a whole day, so the next chunk starts the day after
    the previous one ended; otherwise consecutive requests overlap by a day.
    """
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + CHUNK - timedelta(days=1), end)
        yield chunk_start, chunk_end
        chunk_start = chunk_end + timedelta(days=1)


def _session() -> requests.Session:
    """A session that waits out the API's rate limiting.

    Fetching a quarter in weekly chunks trips it reliably: the API answers 429
    with a Retry-After of around 15 seconds, which urllib3 honours on its own.
    """
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


SESSION = _session()


def fetch_prices(start: date, end: date) -> dict:
    """Return the raw API payload for an inclusive date range."""
    response = SESSION.get(
        PRICE_API,
        params={"bzn": BIDDING_ZONE, "start": start, "end": end},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def parse_prices(payload: dict, zone: str = BIDDING_ZONE) -> list[PriceRow]:
    """Zip the payload's parallel arrays into rows.

    The API returns `{"unix_seconds": [...], "price": [...]}` rather than a list
    of records. Prices may be null when an auction result is missing; those rows
    are dropped because the column is not nullable.
    """
    seconds: Sequence[int] = payload["unix_seconds"]
    prices: Sequence[float | None] = payload["price"]

    step = {b - a for a, b in zip(seconds, seconds[1:])}
    if step - {int(INTERVAL.total_seconds())}:
        raise ValueError(
            f"expected {INTERVAL.total_seconds():.0f}s intervals, got {sorted(step)}"
        )

    rows: list[PriceRow] = []
    for second, price in zip(seconds, prices):
        if price is None:
            continue
        start = datetime.fromtimestamp(second, tz=timezone.utc)
        rows.append((zone, start, start + INTERVAL, float(price)))
    return rows


def generate_consumption(customer_id: int, timestamp: datetime) -> float:
    """Return a customer's consumption in kWh for one hour.

    Seeded from a stable digest rather than hash(): hash() is salted per process
    for anything containing a string, so it would return different values on
    every run and break the guarantee that re-ingesting cannot rewrite history.
    """
    key = f"{customer_id}:{timestamp.isoformat()}".encode()
    seed = int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big")
    rng = random.Random(seed)

    base = 0.25
    local_hour = timestamp.astimezone(LOCAL_TZ).hour
    evening_peak = 0.5 if 17 <= local_hour <= 22 else 0
    return round(max(0, base + evening_peak + rng.uniform(-0.1, 0.1)), 3)


def iter_consumption(
    start: date,
    end: date,
    customers: int = CUSTOMER_COUNT,
) -> Iterator[UsageRow]:
    """Yield one row per customer per local hour, over an inclusive date range.

    Stepping in local time keeps the peak window aligned to local evenings; a
    DST transition therefore yields 23 or 25 hours for that day, which is the
    intended behaviour for metered data.
    """
    current = datetime.combine(start, datetime.min.time(), tzinfo=LOCAL_TZ)
    stop = datetime.combine(
        end + timedelta(days=1), datetime.min.time(), tzinfo=LOCAL_TZ
    )
    while current < stop:
        for customer_id in range(1, customers + 1):
            yield customer_id, current, generate_consumption(customer_id, current)
        current += timedelta(hours=1)


def load_prices(conn: psycopg.Connection, rows: Iterable[PriceRow]) -> int:
    """Upsert price rows. Takes a connection so callers own the transaction."""
    batch = list(rows)
    with conn.cursor() as cur:
        cur.executemany(UPSERT_PRICES, batch)
    return len(batch)


def load_consumption(conn: psycopg.Connection, rows: Iterable[UsageRow]) -> int:
    """Upsert consumption rows. Takes a connection so callers own the transaction."""
    batch = list(rows)
    with conn.cursor() as cur:
        cur.executemany(UPSERT_CONSUMPTION, batch)
    return len(batch)


def connect() -> psycopg.Connection:
    """Connect to the warehouse using the environment Compose provides.

    No defaults: every variable is always set by Compose, so a missing one is a
    misconfiguration and should name itself rather than fail as a bad login.
    """
    return psycopg.connect(
        host=os.environ["WAREHOUSE_DB_HOST"],
        dbname=os.environ["WAREHOUSE_DB_NAME"],
        user=os.environ["WAREHOUSE_DB_USER"],
        password=os.environ["WAREHOUSE_DB_PASSWORD"],
    )


def ingest(conn: psycopg.Connection, start: date, end: date) -> tuple[int, int]:
    """Load both sources for an inclusive date range, committing per chunk.

    Chunking bounds the size of a single request and of a single transaction, so
    an interruption leaves a consistent prefix rather than nothing.
    """
    prices = usage = 0
    for chunk_start, chunk_end in weekly_chunks(start, end):
        rows = parse_prices(fetch_prices(chunk_start, chunk_end))
        n_prices = load_prices(conn, rows)
        n_usage = load_consumption(conn, iter_consumption(chunk_start, chunk_end))
        conn.commit()

        prices += n_prices
        usage += n_usage
        log.info(
            "%s..%s: %d price intervals, %d consumption rows",
            chunk_start,
            chunk_end,
            n_prices,
            n_usage,
        )
    return prices, usage


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)

    if args.start > args.end:
        parser.error("--start must not be after --end")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    with connect() as conn:
        prices, usage = ingest(conn, args.start, args.end)

    log.info("total: %d price intervals, %d consumption rows", prices, usage)
    return 0


if __name__ == "__main__":
    sys.exit(main())

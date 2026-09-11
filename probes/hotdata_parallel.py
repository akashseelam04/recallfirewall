"""Gate 0, bullet 2: two independent Hotdata task databases.

Proves, against the live service:

  1. Each facility analysis runs in its own scoped instant database.
  2. The two analyses genuinely overlap in wall-clock time.
  3. Every result carries a coverage envelope (SPEC 5.2.2).
  4. Cross-catalog reads and ATTACH fail while the selected database stays fixed.

This legacy probe holds workspace credentials and CAN select another database.
It does not prove AC-07. See gateway_isolation.py for enforced task scope.

Quantities are parsed as Decimal, never float: SPEC forbids binary floating
point for lot quantities.
"""

from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal

# One scoped database per facility. The task is handed its database id; it does
# not get to choose one.
FACILITIES = {
    "PLANT-A": {
        "database": "dbidjps0n11vjay3m0asui84xazh9k",
        "catalog": "rf_plant_a_8g4i42",
    },
    "PLANT-B": {
        "database": "dbiday3wgs1w5ggd5isn1fmnz5lqkf",
        "catalog": "rf_plant_b_8g4i42",
    },
}

INGREDIENT = "ING-041"


@dataclass(frozen=True)
class Envelope:
    """SPEC 5.2.2 coverage envelope. Absence is never silently 'none'."""

    rows: int
    scope: str
    snapshot_or_revision: str
    complete: bool
    incomplete_reason: str | None


@dataclass(frozen=True)
class FacilityResult:
    facility: str
    lot_count: int
    total_kg: Decimal
    envelope: Envelope
    started_at: float
    ended_at: float


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["hotdata", *args, "--no-input"], capture_output=True, text=True
    )


def query_facility(facility: str) -> FacilityResult:
    target = FACILITIES[facility]
    catalog = target["catalog"]
    table = f"{catalog}.public.lot_consumption"
    # CAST to DECIMAL server-side so the sum is exact, not binary float.
    sql = (
        "SELECT COUNT(*) AS lot_count, "
        "SUM(CAST(qty_kg AS DECIMAL(18,3))) AS total_kg "
        f"FROM {table} WHERE ingredient_id = '{INGREDIENT}'"
    )

    started = time.monotonic()
    proc = _run(["query", "-d", target["database"], sql, "-o", "json"])
    ended = time.monotonic()

    if proc.returncode != 0:
        raise RuntimeError(f"{facility}: query failed: {proc.stderr.strip()}")

    # parse_float=Decimal keeps quantities exact through JSON decoding.
    payload = json.loads(proc.stdout, parse_float=Decimal)
    row = payload["rows"][0]
    columns = payload["columns"]
    lot_count = int(row[columns.index("lot_count")])
    total_kg = Decimal(str(row[columns.index("total_kg")]))

    truncated = bool(payload["truncated"])
    row_count = int(payload["row_count"])
    total_row_count = int(payload["total_row_count"])
    complete = not truncated and row_count == total_row_count

    envelope = Envelope(
        rows=row_count,
        scope=f"{facility}:{table}:ingredient_id={INGREDIENT}",
        snapshot_or_revision=payload["query_run_id"],
        complete=complete,
        incomplete_reason=None if complete else "truncated_preview",
    )
    return FacilityResult(facility, lot_count, total_kg, envelope, started, ended)


def assert_cannot_escape_assigned_database() -> tuple[str, str]:
    """AC-07: the task may not read, or attach, another facility's database."""
    borrowed = FACILITIES["PLANT-B"]["catalog"]
    assigned = FACILITIES["PLANT-A"]["database"]

    read = _run(
        [
            "query",
            "-d",
            assigned,
            f"SELECT COUNT(*) AS leaked FROM {borrowed}.public.lot_consumption",
            "-o",
            "json",
        ]
    )
    if read.returncode == 0:
        raise AssertionError("AC-07 VIOLATED: cross-database read succeeded")

    attach = _run(["databases", "attach", borrowed, "-d", assigned])
    if attach.returncode == 0:
        raise AssertionError("AC-07 VIOLATED: task attached another facility's catalog")

    return read.stderr.strip().splitlines()[0], attach.stderr.strip().splitlines()[0]


def main() -> None:
    wall_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(FACILITIES)) as pool:
        results = list(pool.map(query_facility, FACILITIES))
    wall_end = time.monotonic()

    for r in results:
        print(f"{r.facility}: {r.lot_count} lots, {r.total_kg} kg of {INGREDIENT}")
        print(
            f"  envelope rows={r.envelope.rows} complete={r.envelope.complete} "
            f"run={r.envelope.snapshot_or_revision}"
        )
        print(f"  scope={r.envelope.scope}")

    # Real overlap: the later query started before the earlier one finished.
    latest_start = max(r.started_at for r in results)
    earliest_end = min(r.ended_at for r in results)
    overlap = earliest_end - latest_start
    serial = sum(r.ended_at - r.started_at for r in results)
    wall = wall_end - wall_start

    print(f"\noverlap      : {overlap * 1000:.0f} ms ({'YES' if overlap > 0 else 'NO'})")
    print(f"sum of parts : {serial * 1000:.0f} ms")
    print(f"wall clock   : {wall * 1000:.0f} ms")

    read_err, attach_err = assert_cannot_escape_assigned_database()
    print("\nAC-07 cross-database read refused:")
    print(f"  {read_err}")
    print("AC-07 catalog attach refused:")
    print(f"  {attach_err}")

    assert overlap > 0, "queries did not actually overlap"
    # Facility totals must stay separate; a merged number means scoping leaked.
    totals = {r.facility: r.total_kg for r in results}
    assert totals["PLANT-A"] == Decimal("506.500"), totals
    assert totals["PLANT-B"] == Decimal("1030.750"), totals
    print("\nall assertions passed")


if __name__ == "__main__":
    main()

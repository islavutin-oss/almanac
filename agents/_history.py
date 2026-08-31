"""Daily snapshots of the catalogue, so change becomes answerable.

Everything else here reads a live snapshot, which can say what is true now and
nothing at all about what moved. "Three vendors cut prices this week" needs
last week, and no upstream endpoint provides it — so it is recorded here.

One row per model per day. At ~400 models that is ~150k rows a year, which
SQLite does not notice.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / ".cache" / "history.sqlite"

_DDL = """
CREATE TABLE IF NOT EXISTS snapshots (
    day        TEXT NOT NULL,
    model_id   TEXT NOT NULL,
    name       TEXT,
    vendor     TEXT,
    context    INTEGER,
    price_in   REAL,
    price_out  REAL,
    quality    REAL,
    speed      REAL,
    ttft       REAL,
    PRIMARY KEY (day, model_id)
);
CREATE INDEX IF NOT EXISTS ix_snapshots_model ON snapshots (model_id, day);
"""


def _connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript(_DDL)
    # A database created before ttft existed keeps its old shape, because
    # CREATE TABLE IF NOT EXISTS does not alter it.
    cols = {r[1] for r in con.execute("PRAGMA table_info(snapshots)")}
    if "ttft" not in cols:
        con.execute("ALTER TABLE snapshots ADD COLUMN ttft REAL")
        con.commit()
    return con


def take_snapshot(rows: list[dict], day: str | None = None) -> int:
    """Record today's catalogue. Idempotent — re-running replaces the day.

    Replacing rather than appending matters: the routine may fire more than
    once, and a duplicated day would show as a phantom change tomorrow.
    """
    # UTC, not local. The catalogue timestamps are UTC and the routine
    # fires on a UTC cron; keying a snapshot by local date would file two
    # rows for one day, or none, whenever the two disagree.
    d = day or datetime.now(timezone.utc).date().isoformat()
    with _connect() as con:
        con.execute("DELETE FROM snapshots WHERE day = ?", (d,))
        con.executemany(
            "INSERT INTO snapshots (day, model_id, name, vendor, context, price_in, "
            "price_out, quality, speed, ttft) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    d,
                    r.get("id"),
                    r.get("name"),
                    r.get("vendor"),
                    r.get("context"),
                    r.get("price_in"),
                    r.get("price_out"),
                    r.get("quality"),
                    r.get("speed"),
                    r.get("ttft"),
                )
                for r in rows
                if r.get("id")
            ],
        )
        con.commit()
        return int(con.execute("SELECT COUNT(*) FROM snapshots WHERE day = ?", (d,)).fetchone()[0])


def days() -> list[str]:
    with _connect() as con:
        return [r["day"] for r in con.execute("SELECT DISTINCT day FROM snapshots ORDER BY day")]


def compare(back: int = 7) -> dict:
    """What changed between the most recent snapshot and one ~`back` days older.

    Returns empty lists with `have_history=False` when there is not yet a
    second snapshot to compare against — a desk must be able to say "I cannot
    see change yet" rather than reporting no change, which is a different and
    misleading claim.
    """
    ds = days()
    if len(ds) < 2:
        return {
            "have_history": False,
            "from": None,
            "to": ds[-1] if ds else None,
            "added": [],
            "removed": [],
            "price_moves": [],
            "quality_moves": [],
            "latency_moves": [],
        }

    latest = ds[-1]
    older = min(
        ds[:-1], key=lambda d: abs((date.fromisoformat(latest) - date.fromisoformat(d)).days - back)
    )

    with _connect() as con:
        now = {
            r["model_id"]: dict(r)
            for r in con.execute("SELECT * FROM snapshots WHERE day = ?", (latest,))
        }
        then = {
            r["model_id"]: dict(r)
            for r in con.execute("SELECT * FROM snapshots WHERE day = ?", (older,))
        }

    added = [now[k] for k in now.keys() - then.keys()]
    removed = [then[k] for k in then.keys() - now.keys()]

    price_moves, quality_moves, latency_moves = [], [], []
    for k in now.keys() & then.keys():
        a, b = then[k], now[k]
        if a["price_in"] and b["price_in"] and a["price_in"] != b["price_in"]:
            pct = 100.0 * (b["price_in"] - a["price_in"]) / a["price_in"]
            if abs(pct) >= 1:
                price_moves.append({**b, "was": a["price_in"], "now": b["price_in"], "pct": pct})
        # Latency is the measurement most likely to move without any
        # announcement — a provider changes hardware or routing and nobody
        # posts about it. A 10% floor keeps ordinary measurement noise out.
        at, bt = (
            a["ttft"] if "ttft" in a.keys() else None,
            b["ttft"] if "ttft" in b.keys() else None,
        )
        if at and bt and at != bt:
            pct = 100.0 * (bt - at) / at
            if abs(pct) >= 10:
                latency_moves.append({**b, "was": at, "now": bt, "pct": pct})
        if a["quality"] is not None and b["quality"] is not None and a["quality"] != b["quality"]:
            quality_moves.append(
                {
                    **b,
                    "was": a["quality"],
                    "now": b["quality"],
                    "delta": b["quality"] - a["quality"],
                }
            )

    price_moves.sort(key=lambda r: r["pct"])
    quality_moves.sort(key=lambda r: -abs(r["delta"]))
    return {
        "have_history": True,
        "from": older,
        "to": latest,
        "added": added,
        "removed": removed,
        "price_moves": price_moves,
        "quality_moves": quality_moves,
        "latency_moves": latency_moves,
    }

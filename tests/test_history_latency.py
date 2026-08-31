"""Latency is the measurement most likely to move without an announcement —
a provider changes hardware or routing and nobody posts about it."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))


@pytest.fixture
def hist(tmp_path, monkeypatch):
    import _history as h

    monkeypatch.setattr(h, "DB", tmp_path / "history.sqlite")
    return importlib.reload(h) if False else h


def row(mid, price=1.0, quality=50.0, speed=100.0, ttft=1.0):
    return {
        "id": mid,
        "name": mid,
        "vendor": "v",
        "context": 1000,
        "price_in": price,
        "price_out": price * 2,
        "quality": quality,
        "speed": speed,
        "ttft": ttft,
    }


def test_ttft_survives_a_round_trip(hist):
    hist.take_snapshot([row("a", ttft=2.5)], day="2026-01-01")
    with hist._connect() as con:
        got = con.execute("SELECT ttft FROM snapshots WHERE model_id='a'").fetchone()[0]
    assert got == 2.5


def test_a_latency_regression_is_detected(hist):
    hist.take_snapshot([row("a", ttft=1.0)], day="2026-01-01")
    hist.take_snapshot([row("a", ttft=2.0)], day="2026-01-08")
    moves = hist.compare(7)["latency_moves"]
    assert len(moves) == 1
    assert moves[0]["was"] == 1.0 and moves[0]["now"] == 2.0
    assert round(moves[0]["pct"]) == 100


def test_noise_below_ten_percent_is_ignored(hist):
    hist.take_snapshot([row("a", ttft=1.00)], day="2026-01-01")
    hist.take_snapshot([row("a", ttft=1.05)], day="2026-01-08")
    assert hist.compare(7)["latency_moves"] == []


def test_an_unmeasured_side_is_not_a_move(hist):
    """Going from no measurement to a measurement is not a latency change."""
    hist.take_snapshot([row("a", ttft=None)], day="2026-01-01")
    hist.take_snapshot([row("a", ttft=3.0)], day="2026-01-08")
    assert hist.compare(7)["latency_moves"] == []


def test_zero_is_not_treated_as_a_measurement(hist):
    """The upstream API encodes 'unmeasured' as 0; a 0 -> 4s transition is not
    a 400% regression."""
    hist.take_snapshot([row("a", ttft=0.0)], day="2026-01-01")
    hist.take_snapshot([row("a", ttft=4.0)], day="2026-01-08")
    assert hist.compare(7)["latency_moves"] == []


def test_no_history_reports_latency_moves_as_a_key(hist):
    hist.take_snapshot([row("a")], day="2026-01-01")
    c = hist.compare(7)
    assert c["have_history"] is False
    assert c["latency_moves"] == []


def test_a_database_without_the_column_is_migrated(hist, tmp_path):
    """Existing installs predate ttft; CREATE TABLE IF NOT EXISTS will not add it."""
    import sqlite3

    db = tmp_path / "history.sqlite"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE snapshots (day TEXT NOT NULL, model_id TEXT NOT NULL, name TEXT, "
        "vendor TEXT, context INTEGER, price_in REAL, price_out REAL, quality REAL, "
        "speed REAL, PRIMARY KEY (day, model_id))"
    )
    con.commit()
    con.close()
    with hist._connect() as c2:
        cols = {r[1] for r in c2.execute("PRAGMA table_info(snapshots)")}
    assert "ttft" in cols

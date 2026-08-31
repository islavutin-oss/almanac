"""Snapshots, and the diff that makes change answerable.

Nothing upstream keeps history, so this is the only thing standing between
"prices fell 12% this week" and a guess.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
import _history as h  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "DB", tmp_path / "history.sqlite")


def row(mid="a/one", price=1.0, quality=40.0, name="One"):
    return {
        "id": mid,
        "name": name,
        "vendor": mid.split("/")[0],
        "context": 1000,
        "price_in": price,
        "price_out": (price * 3) if price is not None else None,
        "quality": quality,
        "speed": 100.0,
    }


def test_a_snapshot_round_trips():
    assert h.take_snapshot([row()], day="2026-08-01") == 1
    assert h.days() == ["2026-08-01"]


def test_re_recording_a_day_replaces_it():
    """The routine can fire twice. An appended duplicate would surface
    tomorrow as a change that never happened."""
    h.take_snapshot([row(), row("a/two")], day="2026-08-01")
    assert h.take_snapshot([row()], day="2026-08-01") == 1


def test_one_snapshot_cannot_report_change():
    """'I cannot see change yet' and 'nothing changed' are different claims,
    and only one of them is true on day one."""
    h.take_snapshot([row()], day="2026-08-01")
    c = h.compare(7)
    assert c["have_history"] is False
    assert c["added"] == [] and c["price_moves"] == []


def test_a_new_model_is_reported_as_added():
    h.take_snapshot([row()], day="2026-08-01")
    h.take_snapshot([row(), row("b/new")], day="2026-08-08")
    c = h.compare(7)
    assert [m["model_id"] for m in c["added"]] == ["b/new"]


def test_a_delisted_model_is_reported_as_removed():
    h.take_snapshot([row(), row("b/gone")], day="2026-08-01")
    h.take_snapshot([row()], day="2026-08-08")
    c = h.compare(7)
    assert [m["model_id"] for m in c["removed"]] == ["b/gone"]


def test_a_price_cut_is_reported_with_its_size():
    h.take_snapshot([row(price=2.0)], day="2026-08-01")
    h.take_snapshot([row(price=1.0)], day="2026-08-08")
    move = h.compare(7)["price_moves"][0]
    assert move["was"] == 2.0 and move["now"] == 1.0
    assert move["pct"] == pytest.approx(-50.0)


def test_a_trivial_price_move_is_not_news():
    """Sub-1% drift is rounding and exchange noise. Reporting it trains the
    reader to skip the section."""
    h.take_snapshot([row(price=1.000)], day="2026-08-01")
    h.take_snapshot([row(price=1.005)], day="2026-08-08")
    assert h.compare(7)["price_moves"] == []


def test_price_moves_are_ordered_deepest_cut_first():
    h.take_snapshot([row("a/x", price=10.0), row("a/y", price=10.0)], day="2026-08-01")
    h.take_snapshot([row("a/x", price=9.0), row("a/y", price=1.0)], day="2026-08-08")
    moves = h.compare(7)["price_moves"]
    assert [m["model_id"] for m in moves] == ["a/y", "a/x"]


def test_a_requality_is_reported():
    h.take_snapshot([row(quality=40.0)], day="2026-08-01")
    h.take_snapshot([row(quality=44.0)], day="2026-08-08")
    q = h.compare(7)["quality_moves"][0]
    assert q["delta"] == pytest.approx(4.0)


def test_it_compares_against_the_closest_day_to_the_window():
    """With daily snapshots, compare(7) should reach back about a week — not
    to the oldest row it happens to hold."""
    for d, p in (("2026-08-01", 4.0), ("2026-08-22", 2.0), ("2026-08-29", 1.0)):
        h.take_snapshot([row(price=p)], day=d)
    c = h.compare(7)
    assert c["from"] == "2026-08-22" and c["to"] == "2026-08-29"
    assert c["price_moves"][0]["pct"] == pytest.approx(-50.0)


def test_a_model_with_no_price_either_side_is_not_a_move():
    h.take_snapshot([row(price=None)], day="2026-08-01")
    h.take_snapshot([row(price=None)], day="2026-08-08")
    assert h.compare(7)["price_moves"] == []

"""A generated report leaves the conversation and gets circulated, so what it
claims has to survive without the chat around it."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "_catalogue" / "tools"))


def run(fn, **kw):
    return asyncio.run(fn.fn(**kw) if hasattr(fn, "fn") else fn(**kw))


def block(out: str) -> dict:
    m = re.search(r"```file\n(.*?)\n```", out, re.S)
    assert m, f"no file block: {out[:200]}"
    return json.loads(m.group(1))


class _Meta:
    def __init__(self, file_id):
        self.file_id = file_id


class _Storage:
    """Captures what would have been written."""

    def __init__(self):
        self.written = {}

    def put(self, tenant, name, data, content_type=""):
        self.written[name] = (data, content_type, tenant)
        return _Meta("fid-" + name)


@pytest.fixture
def report(monkeypatch):
    import agents._catalogue.tools.report as mod

    ROWS = [
        {
            "id": "v/a",
            "name": "Alpha",
            "vendor": "v",
            "context": 200000,
            "price": 0.05,
            "quality": 60.0,
            "ttft": 1.2,
            "speed": 300.0,
        },
        {
            "id": "v/b",
            "name": "Beta",
            "vendor": "v",
            "context": 8000,
            "price": 0.02,
            "quality": 20.0,
            "ttft": None,
            "speed": None,
        },
        {
            "id": "v/c",
            "name": "Gamma",
            "vendor": "w",
            "context": 500000,
            "price": 9.00,
            "quality": None,
            "ttft": 0.4,
            "speed": 120.0,
        },
    ]
    monkeypatch.setattr(mod, "_joined", lambda: (ROWS, None))
    store = _Storage()
    monkeypatch.setattr(mod, "_storage", lambda: store)
    mod._test_store = store
    return mod


# --- refusals ---------------------------------------------------------------


def test_unknown_kind_is_refused(report):
    assert "kind must be" in run(report.generate_report, kind="vibes")


def test_unknown_format_is_refused(report):
    assert "fmt must be" in run(report.generate_report, fmt="pdf")


def test_no_matches_writes_nothing(report):
    out = run(report.generate_report, min_quality=99)
    assert "no report to write" in out
    assert report._test_store.written == {}


def test_missing_storage_says_so_rather_than_pretending(report, monkeypatch):
    monkeypatch.setattr(report, "_storage", lambda: None)
    out = run(report.generate_report)
    assert "no file storage" in out
    assert "```file" not in out


def test_an_upstream_failure_is_reported_not_papered_over(report, monkeypatch):
    monkeypatch.setattr(report, "_joined", lambda: ([], "Artificial Analysis returned nothing"))
    out = run(report.generate_report)
    assert "Artificial Analysis returned nothing" in out
    assert "```file" not in out


# --- what lands in the file -------------------------------------------------


def test_csv_has_a_header_and_the_rows(report):
    run(report.generate_report)
    ((data, ctype, _),) = report._test_store.written.values()
    assert ctype == "text/csv"
    rows = list(csv.reader(io.StringIO(data.decode())))
    assert rows[0][0] == "Model"
    assert any(r and r[0] == "Alpha" for r in rows)


def test_unmeasured_is_written_as_a_word_not_a_zero(report):
    """A zero in a circulated spreadsheet reads as a measurement of zero."""
    run(report.generate_report)
    ((data, _, _),) = report._test_store.written.values()
    text = data.decode()
    assert "unmeasured" in text
    beta = [r for r in csv.reader(io.StringIO(text)) if r and r[0] == "Beta"][0]
    # Beta has neither a latency nor a throughput measurement. Both columns must
    # say so; a numeric zero in a circulated spreadsheet reads as a measurement.
    ttft, tokens_per_s = beta[5], beta[6]
    assert ttft == "unmeasured", f"TTFT column rendered {ttft!r}"
    assert tokens_per_s == "unmeasured", f"throughput column rendered {tokens_per_s!r}"


def test_the_file_states_its_provenance_and_its_limits(report):
    run(report.generate_report)
    ((data, _, _),) = report._test_store.written.values()
    text = data.decode()
    assert "OpenRouter" in text and "Artificial Analysis" in text
    assert "does not mean zero" in text


def test_the_footer_reports_matched_and_listed_separately(report):
    out = run(report.generate_report, limit=1)
    ((data, _, _),) = report._test_store.written.values()
    assert "3 models matched; 1 listed" in data.decode()
    assert "1 of 3" in out


def test_markdown_format_is_a_table(report):
    run(report.generate_report, fmt="markdown")
    ((data, ctype, _),) = report._test_store.written.values()
    assert ctype == "text/markdown"
    assert "| Model |" in data.decode()


def test_coverage_report_says_which_models_are_measured(report):
    run(report.generate_report, kind="coverage")
    ((data, _, _),) = report._test_store.written.values()
    rows = {r[0]: r for r in csv.reader(io.StringIO(data.decode())) if r}
    assert rows["Alpha"][2] == "yes" and rows["Alpha"][3] == "yes"
    assert rows["Gamma"][2] == "no", "Gamma has no quality score"
    assert rows["Beta"][3] == "no", "Beta has no latency measurement"


# --- the block ---------------------------------------------------------------


def test_the_block_points_at_the_workspace_file(report):
    spec = block(run(report.generate_report))
    assert spec["url"].startswith("/api/workspace/files/")
    assert spec["name"].endswith(".csv")
    assert spec["size"] > 0
    assert spec["kind"] == "csv"


def test_filters_are_applied(report):
    run(report.generate_report, max_input_price=1.0)
    ((data, _, _),) = report._test_store.written.values()
    text = data.decode()
    assert "Gamma" not in text, "a $9/M model must not survive a $1 ceiling"
    run(report.generate_report, min_context=100000)
    (data, _, _) = list(report._test_store.written.values())[-1]
    assert "Beta" not in data.decode(), "an 8k model must not survive a 100k floor"

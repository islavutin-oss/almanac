"""The advisor's shortlist is the front-office answer, so its ranking and its
refusals matter more than its happy path."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))


@pytest.fixture
def advise(monkeypatch):
    import _analysis as aa

    import agents.advisor.tools.advise as mod

    CATALOGUE = [
        # name,           id,          ctx,     $/M in
        ("Cheap Weak", "v/cheap", 128000, 0.10),
        ("Mid Value", "v/mid", 200000, 0.50),
        ("Pricey Strong", "v/strong", 1000000, 5.00),
        ("Free Small", "v/free", 32000, 0.00),
        ("Unmeasured", "v/unknown", 128000, 0.20),
        # Measured, and measured badly. Distinguishes "no measurement" from a
        # measurement of zero — `quality or 0` collapses the two.
        ("Measured Zero", "v/zero", 128000, 0.30),
        ("Zero Latency", "v/zerolat", 128000, 0.40),
    ]
    models = [
        {
            "id": i,
            "name": n,
            "context_length": c,
            "pricing": {"prompt": str(p / 1_000_000), "completion": str(p / 1_000_000)},
        }
        for n, i, c, p in CATALOGUE
    ]
    monkeypatch.setattr(mod, "models", lambda: models)
    # Quality: strong beats mid beats cheap; "Unmeasured" is deliberately absent.
    monkeypatch.setattr(
        aa,
        "index",
        lambda: {
            aa._norm("v/cheap"): {
                "artificial_analysis_intelligence_index": 20.0,
                "median_output_tokens_per_second": 300.0,
                "median_time_to_first_token_seconds": 0.20,
                "artificial_analysis_coding_index": 10.0,
                "terminalbench_v2_1": 0.10,
            },
            aa._norm("v/mid"): {
                "artificial_analysis_intelligence_index": 50.0,
                "median_output_tokens_per_second": 100.0,
                "median_time_to_first_token_seconds": 4.00,
                "artificial_analysis_coding_index": 70.0,
                "terminalbench_v2_1": 0.80,
            },
            aa._norm("v/strong"): {
                "artificial_analysis_intelligence_index": 80.0,
                "median_output_tokens_per_second": 40.0,
                "median_time_to_first_token_seconds": 9.00,
                "artificial_analysis_coding_index": 40.0,
                "terminalbench_v2_1": 0.30,
            },
            aa._norm("v/free"): {
                "artificial_analysis_intelligence_index": 10.0,
                "median_output_tokens_per_second": 500.0,
                "median_time_to_first_token_seconds": 0.10,
            },
            aa._norm("v/zero"): {
                "artificial_analysis_intelligence_index": 0.0,
                "median_output_tokens_per_second": 60.0,
                "median_time_to_first_token_seconds": 2.00,
                "artificial_analysis_coding_index": 0.0,
                "terminalbench_v2_1": 0.0,
            },
            aa._norm("v/zerolat"): {
                "artificial_analysis_intelligence_index": 45.0,
                "median_output_tokens_per_second": 0.0,
                "median_time_to_first_token_seconds": 0.0,
            },
        },
    )
    return mod


def run(fn, **kw):
    return asyncio.run(fn.fn(**kw) if hasattr(fn, "fn") else fn(**kw))


def table(out: str) -> dict:
    m = re.search(r"```datatable\n(.*?)\n```", out, re.S)
    assert m, f"no datatable in output: {out[:200]}"
    return json.loads(m.group(1))


def names(out: str) -> list[str]:
    return [r[0] for r in table(out)["rows"]]


# --- the columns exist at all ------------------------------------------------


def test_quality_and_speed_are_reported(advise):
    cols = table(run(advise.shortlist))["columns"]
    assert "Quality" in cols and "Tok/s" in cols


def test_unmeasured_model_shows_a_dash_not_a_zero(advise):
    rows = {r[0]: r for r in table(run(advise.shortlist, sort="price"))["rows"]}
    assert rows["Unmeasured"][4] == "—", "an unmeasured model must not read as quality 0"


# --- ranking -----------------------------------------------------------------


def test_value_ranks_quality_per_dollar_not_cheapest(advise):
    # Mid: 50/0.50 = 100. Cheap: 20/0.10 = 200. Strong: 80/5 = 16.
    assert names(run(advise.shortlist, sort="value"))[0] == "Cheap Weak"
    # and the cheapest-first order is genuinely different from value order
    assert names(run(advise.shortlist, sort="price"))[0] == "Free Small"


def test_quality_sort_puts_the_best_first(advise):
    assert names(run(advise.shortlist, sort="quality"))[0] == "Pricey Strong"


def test_speed_sort_puts_the_fastest_first(advise):
    assert names(run(advise.shortlist, sort="speed"))[0] == "Free Small"


def test_unmeasured_sorts_below_a_model_measured_at_zero(advise):
    """`quality or 0` would tie them; unmeasured is not the same as bad."""
    order = names(run(advise.shortlist, sort="quality"))
    assert order[-1] == "Unmeasured"
    assert order.index("Measured Zero") < order.index("Unmeasured")


def test_a_zero_measurement_still_prints_as_zero(advise):
    rows = {r[0]: r for r in table(run(advise.shortlist, sort="price"))["rows"]}
    assert rows["Measured Zero"][4] == "0", "a real 0 must not be shown as unmeasured"


# --- filters -----------------------------------------------------------------


def test_min_quality_drops_unmeasured_models(advise):
    got = names(run(advise.shortlist, min_quality=30))
    assert "Unmeasured" not in got and "Cheap Weak" not in got
    assert set(got) == {"Mid Value", "Pricey Strong", "Zero Latency"}


def test_context_floor_is_applied(advise):
    assert "Free Small" not in names(run(advise.shortlist, min_context=100000))


def test_price_ceiling_is_applied(advise):
    assert "Pricey Strong" not in names(run(advise.shortlist, max_input_price=1.0))


# --- refusals explain themselves --------------------------------------------


def test_impossible_constraints_say_which_to_relax(advise):
    out = run(advise.shortlist, min_context=10_000_000)
    assert "Nothing matches" in out
    assert "matters more" in out


def test_quality_floor_failure_explains_the_measurement_gap(advise):
    out = run(advise.shortlist, min_quality=99)
    assert "Nothing matches" in out
    assert "unmeasured" in out.lower(), (
        "must explain that a quality floor also drops unmeasured models"
    )


def test_output_states_the_limits_of_the_index(advise):
    """Every shortlist has to say who measured it and what that does not cover."""
    out = run(advise.shortlist)
    assert "does not settle it" in out
    assert "third party" in out
    assert "measured" in out


# --- monthly_cost ------------------------------------------------------------


def chart(out: str) -> dict:
    m = re.search(r"```chart\n(.*?)\n```", out, re.S)
    assert m, f"no chart in output: {out[:200]}"
    return json.loads(m.group(1))


def test_free_models_do_not_flatten_the_cost_chart(advise):
    """The bug this fixes: the cheapest models are free, so the chart drew six
    bars of zero and answered nothing."""
    out = run(
        advise.monthly_cost, input_tokens_per_month=50_000_000, output_tokens_per_month=5_000_000
    )
    rows = chart(out)["data"]
    assert rows, "expected priced models"
    assert all(r["usd"] > 0 for r in rows), f"free models leaked into the chart: {rows}"
    assert "Free Small" not in [r["model"] for r in rows]


def test_include_free_keeps_them(advise):
    out = run(
        advise.monthly_cost,
        input_tokens_per_month=50_000_000,
        output_tokens_per_month=5_000_000,
        include_free=True,
    )
    assert "Free Small" in [r["model"] for r in chart(out)["data"]]


def test_named_models_are_priced_in_order(advise):
    out = run(
        advise.monthly_cost,
        input_tokens_per_month=50_000_000,
        output_tokens_per_month=5_000_000,
        models_csv="Mid Value, Pricey Strong",
    )
    got = [r["model"] for r in chart(out)["data"]]
    assert got == ["Mid Value", "Pricey Strong"], got


def test_all_free_selection_explains_itself_instead_of_charting_zeros(advise):
    out = run(
        advise.monthly_cost,
        input_tokens_per_month=1_000_000,
        output_tokens_per_month=0,
        models_csv="Free Small",
    )
    assert "```chart" not in out
    assert "free at list price" in out


def test_unmatched_names_say_so(advise):
    out = run(
        advise.monthly_cost,
        input_tokens_per_month=1_000_000,
        output_tokens_per_month=0,
        models_csv="Nonexistent Model",
    )
    assert "None of those matched" in out


def test_chart_declares_dollars_not_euros(advise):
    out = run(
        advise.monthly_cost, input_tokens_per_month=50_000_000, output_tokens_per_month=5_000_000
    )
    assert chart(out)["currency"] == "$"


# --- latency and task-specific ranking -------------------------------------


def test_ttft_is_a_column(advise):
    assert "TTFT" in table(run(advise.shortlist))["columns"]


def test_ttft_sort_puts_the_fastest_to_first_token_first(advise):
    """TTFT is the constraint for anything interactive, and it is unrelated to
    quality — the cheapest model answers first, the strongest is slowest."""
    order = names(run(advise.shortlist, sort="ttft"))
    assert order[0] == "Free Small"
    assert order.index("Cheap Weak") < order.index("Mid Value") < order.index("Pricey Strong")
    # Everything without a real TTFT trails everything with one.
    unmeasured = {"Unmeasured", "Zero Latency"}
    assert set(order[-len(unmeasured) :]) == unmeasured


def test_latency_ceiling_drops_slow_models(advise):
    got = names(run(advise.shortlist, max_ttft=1.0))
    assert "Pricey Strong" not in got and "Mid Value" not in got
    assert "Free Small" in got and "Cheap Weak" in got


def test_latency_ceiling_drops_unmeasured(advise):
    assert "Unmeasured" not in names(run(advise.shortlist, max_ttft=5.0))


def test_impossible_latency_explains_the_collision(advise):
    out = run(advise.shortlist, max_ttft=0.01)
    assert "Nothing matches" in out and "latency ceiling" in out


def test_task_ranking_differs_from_the_composite_index(advise):
    """The whole point: Pricey Strong leads the composite index but Mid Value
    is the better coder, so a composite is a poor proxy for a real job."""
    assert names(run(advise.shortlist, sort="quality"))[0] == "Pricey Strong"
    assert names(run(advise.shortlist, task="coding", sort="quality"))[0] == "Mid Value"


def test_agentic_task_uses_terminalbench(advise):
    assert names(run(advise.shortlist, task="agentic", sort="quality"))[0] == "Mid Value"


def test_fractional_evals_are_reported_as_percentages(advise):
    rows = {r[0]: r for r in table(run(advise.shortlist, task="agentic", sort="quality"))["rows"]}
    # terminalbench 0.80 must read as 80, not 1.
    assert rows["Mid Value"][4] == "80"


def test_task_column_is_labelled_for_the_task(advise):
    assert "Coding" in table(run(advise.shortlist, task="coding"))["columns"]
    assert "Tool Use" in table(run(advise.shortlist, task="tool_use"))["columns"]


def test_unknown_task_is_refused_with_the_list(advise):
    out = run(advise.shortlist, task="vibes")
    assert "not a measured skill" in out and "coding" in out


def test_output_states_that_ttft_is_not_yours(advise):
    assert "not yours" in run(advise.shortlist)


# --- the endpoint encodes "unmeasured" as zero ------------------------------


def test_zero_ttft_is_treated_as_unmeasured(advise):
    """1154 of 1642 latency rows come back as a flat 0. A zero TTFT is not
    physically possible, and left alone it ranks every unmeasured model as the
    fastest thing in the catalogue."""
    rows = {r[0]: r for r in table(run(advise.shortlist, sort="price"))["rows"]}
    assert rows["Zero Latency"][5] == "—", "0s TTFT must not render as a measurement"
    assert rows["Zero Latency"][6] == "—", "0 tok/s must not render as a measurement"


def test_zero_latency_does_not_win_a_latency_sort(advise):
    assert names(run(advise.shortlist, sort="ttft"))[0] == "Free Small"
    assert names(run(advise.shortlist, sort="ttft"))[-1] in ("Unmeasured", "Zero Latency")


def test_latency_ceiling_excludes_zero_latency_models(advise):
    assert "Zero Latency" not in names(run(advise.shortlist, max_ttft=5.0))


def test_a_genuine_zero_eval_is_still_reported(advise):
    """Only the performance figures get the zero-means-missing treatment; a
    model really can score zero on a benchmark, on the composite index and on
    each task eval, and discarding that would hide a real result."""
    for task in ("", "coding", "agentic"):
        rows = {r[0]: r for r in table(run(advise.shortlist, task=task, sort="price"))["rows"]}
        assert rows["Measured Zero"][4] == "0", f"a real 0 was hidden for task={task!r}"

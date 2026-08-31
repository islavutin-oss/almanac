"""The models desk — what shipped, what it costs, and what it can hold."""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agentino import tool

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _openrouter import (  # noqa: E402
    fmt_context,
    fmt_price,
    is_free,
    launched,
    models,
    price_per_million,
    since,
    vendor,
)


@tool
async def whats_new(days: int = 7) -> str:
    """Models that appeared on OpenRouter in the last `days`.

    The core of the daily digest: what actually changed.

    Args:
        days: how far back to look.
    """
    new = since(days)
    if not new:
        return f"No new models in the last {days} days."

    rows = [
        [
            launched(m).strftime("%d %b"),
            m.get("name") or m["id"],
            vendor(m),
            fmt_context(m.get("context_length")),
            fmt_price(price_per_million(m, "prompt")),
        ]
        for m in new[:25]
    ]
    spec = {
        "title": f"New on OpenRouter — last {days} days ({len(new)} total)",
        "columns": ["Launched", "Model", "Vendor", "Context", "$/M in"],
        "rows": rows,
    }
    free = [m for m in new if is_free(m)]
    note = f"{len(new)} new models, {len(free)} of them free to call."
    return f"```datatable\n{json.dumps(spec)}\n```\n\n{note}"


@tool
async def launch_timeline(weeks: int = 16) -> str:
    """How many models launched per week, over time.

    Whether the field is accelerating is a question about the shape of a line,
    not a table.

    Args:
        weeks: how many recent weeks to plot.
    """
    now = datetime.now(timezone.utc)
    buckets: Counter[str] = Counter()
    for m in models():
        d = launched(m)
        if not d:
            continue
        age_weeks = (now - d).days // 7
        if 0 <= age_weeks < weeks:
            buckets[
                (now - __import__("datetime").timedelta(weeks=age_weeks)).strftime("%d %b")
            ] += 1

    if not buckets:
        return "No dated launches in that range."
    data = [
        {"week": k, "models": v}
        for k, v in sorted(
            buckets.items(),
            key=lambda kv: datetime.strptime(kv[0], "%d %b").replace(year=now.year),
        )
    ]
    spec = {
        "type": "area",
        "title": f"Models launched per week, last {weeks} weeks",
        "data": data,
        "xKey": "week",
        "yKey": "models",
    }
    peak = max(data, key=lambda d: d["models"])
    return (
        f"```chart\n{json.dumps(spec)}\n```\n\n"
        f"The busiest week was {peak['week']} with {peak['models']} launches."
    )


@tool
async def price_vs_context(limit: int = 120, max_price: float = 30.0) -> str:
    """Whether a bigger context window costs more, plotted model by model.

    The relationship is the point — the cheap million-token models are the
    interesting outliers, and a table hides them.

    Args:
        limit: how many models to plot.
        max_price: drop models above this $/M so the axis stays readable.
    """
    pts = []
    for m in models():
        p = price_per_million(m, "prompt")
        ctx = m.get("context_length")
        if p is None or not ctx or p > max_price:
            continue
        pts.append(
            {
                "context_k": round(ctx / 1000),
                "usd_per_million": round(p, 3),
                "model": m.get("name") or m["id"],
            }
        )
    pts.sort(key=lambda d: d["context_k"], reverse=True)
    if not pts:
        return "No models with both a price and a context length."

    # Count over everything that matched, then truncate for the plot. Counting
    # after the slice reports a property of the chart as a property of the
    # catalogue: this once published "15 models" where the real figure was 80.
    cheap_big = [d for d in pts if d["context_k"] >= 500 and d["usd_per_million"] <= 1]
    matched = len(pts)
    shown = pts[:limit]

    spec = {
        "type": "scatter",
        "title": f"Input price against context window ({len(shown)} of {matched} models)",
        "data": shown,
        "xKey": "context_k",
        "yKey": "usd_per_million",
    }
    note = (
        f"{len(cheap_big)} of {matched} listings pair 500K+ context with a dollar or "
        f"less per million input tokens."
        if cheap_big
        else "No model currently pairs a 500K+ context with sub-dollar input pricing."
    )
    if matched > len(shown):
        note += f" The chart plots the {len(shown)} largest-context of them."
    return f"```chart\n{json.dumps(spec)}\n```\n\n{note}"


@tool
async def vendor_share(top: int = 12) -> str:
    """How many models each vendor has on the platform.

    Args:
        top: how many vendors to show.
    """
    counts = Counter(vendor(m) for m in models())
    data = [{"vendor": v, "models": n} for v, n in counts.most_common(top)]
    spec = {
        "type": "treemap",
        "title": "Models per vendor",
        "data": data,
        "xKey": "vendor",
        "yKey": "models",
    }
    total = sum(counts.values())
    lead = data[0]
    share = round(100.0 * lead["models"] / total, 1)
    return (
        f"```chart\n{json.dumps(spec)}\n```\n\n"
        f"{lead['vendor']} lists the most ({lead['models']} models, {share}% of {total})."
    )


@tool
async def free_models(limit: int = 20) -> str:
    """Models with no charge for input tokens.

    Args:
        limit: how many to list.
    """
    free = [m for m in models() if is_free(m)]
    free.sort(key=lambda m: m.get("context_length") or 0, reverse=True)
    if not free:
        return "Nothing is free right now."
    spec = {
        "title": f"Free models ({len(free)})",
        "columns": ["Model", "Vendor", "Context"],
        "rows": [
            [m.get("name") or m["id"], vendor(m), fmt_context(m.get("context_length"))]
            for m in free[:limit]
        ],
    }
    biggest = free[0]
    return (
        f"```datatable\n{json.dumps(spec)}\n```\n\n"
        f"The largest free context is {fmt_context(biggest.get('context_length'))} "
        f"({biggest.get('name') or biggest['id']})."
    )


@tool
async def coverage() -> str:
    """How much of the catalogue is actually measured, and how wide the spread is.

    This replaced a standing row of four counts — models listed, new this week,
    free to call, largest context. Those are countable rather than useful: a
    catalogue size is a vanity figure, and a reader who notices the top of every
    digest does not matter learns to skip it. How thin public measurement is,
    on the other hand, is a real finding about this market.
    """
    all_models = models()
    rows, why = _joined()
    if why:
        return why
    quality = [r for r in rows if r["quality"] is not None]
    latency = [r for r in rows if r["ttft"] is not None]
    cards = [
        {
            "title": "Listed",
            "value": f"{len(all_models):,}",
            "subtitle": "models on OpenRouter",
        },
        {
            "title": "Quality measured",
            "value": f"{100 * len(quality) // max(len(all_models), 1)}%",
            "subtitle": f"{len(quality)} independently scored",
        },
        {
            "title": "Latency measured",
            "value": f"{100 * len(latency) // max(len(all_models), 1)}%",
            "subtitle": f"only {len(latency)} have a published TTFT",
        },
    ]
    note = ""
    if latency:
        tt = sorted(r["ttft"] for r in latency)
        # p10-p90 rather than min-max: a single stalled measurement at two
        # minutes turns the real spread into a number nobody can use.
        p10 = tt[max(0, int(0.10 * len(tt)) - 1)]
        p90 = tt[min(len(tt) - 1, int(0.90 * len(tt)))]
        median = tt[len(tt) // 2]
        cards.append(
            {
                "title": "TTFT, p10–p90",
                "value": f"{p10:.2f}s – {p90:.1f}s",
                "subtitle": f"median {median:.2f}s",
            }
        )
        note = (
            f"Time to first token runs {p90 / p10:.0f}x from the tenth to the ninetieth "
            f"percentile of the models anyone has measured, around a median of "
            f"{median:.2f}s. {len(all_models) - len(latency)} of {len(all_models)} "
            f"listings have no published latency at all — unmeasured, not fast."
        )
    return f"```kpi\n{json.dumps(cards)}\n```" + (f"\n\n{note}" if note else "")


def _joined() -> tuple[list[dict], str | None]:
    """OpenRouter listings paired with Artificial Analysis measurements.

    Returns (rows, reason_unavailable). A desk should report the reason rather
    than pretend the measurements are simply absent — "we cannot see" and
    "there is nothing there" are different findings.
    """
    import _analysis as aa

    if not aa.available():
        return [], (
            "Quality and speed measurements come from Artificial Analysis, which "
            "needs an API key. None is configured, so I only have price and "
            "context here."
        )
    idx = aa.index()
    if not idx:
        return [], (
            "Artificial Analysis is configured but returned nothing just now — "
            "price and context are still good."
        )
    rows = []
    for m in models():
        meas = idx.get(aa._norm(m.get("id", "")))
        mm = aa.metrics(meas)
        if not meas:
            continue
        price = price_per_million(m, "prompt")
        rows.append(
            {
                "id": m.get("id"),
                "name": m.get("name") or m.get("id"),
                "vendor": vendor(m),
                "context": m.get("context_length"),
                "price": price,
                # Through aa.metrics, not aa.metric: the endpoint encodes an
                # absent performance figure as 0, and only metrics() filters it.
                "quality": mm["quality"],
                "speed": mm["tokens_per_sec"],
                "ttft": mm["ttft"],
            }
        )
    if not rows:
        return [], (
            "No model matched between the two sources by name, so I cannot pair "
            "price with the measurements."
        )
    return rows, None


@tool
async def value_frontier(limit: int = 40) -> str:
    """Measured quality against price — which models are worth what they cost.

    Price alone ranks the cheap; quality alone ranks the good. The decision
    lives in the relationship, and the models above the diagonal are the ones
    giving away more than they charge for.

    Args:
        limit: how many models to plot.
    """
    rows, why = _joined()
    if why:
        return why
    pts = [r for r in rows if r["quality"] is not None and r["price"] is not None]
    if len(pts) < 2:
        return f"Only {len(pts)} models have both a price and a quality score."
    pts.sort(key=lambda r: r["price"])
    data = [
        {
            "usd_per_million": round(r["price"], 3),
            "quality": round(r["quality"], 1),
            "model": r["name"][:38],
        }
        for r in pts[:limit]
    ]
    spec = {
        "type": "scatter",
        "title": "Measured quality against input price",
        "data": data,
        "xKey": "usd_per_million",
        "yKey": "quality",
    }
    best = max(pts[:limit], key=lambda r: (r["quality"] or 0) / max(r["price"] or 0.001, 0.001))
    return (
        f"```chart\n{json.dumps(spec)}\n```\n\n"
        f"{best['name']} gives the most measured quality per dollar in this set — "
        f"{best['quality']:.0f} at {fmt_price(best['price'])} per million input tokens."
    )


@tool
async def speed_vs_price(limit: int = 40) -> str:
    """Latency and throughput against price — the other half of an inference budget.

    Two different numbers, and they do not move together. Time to first token is
    what a waiting person feels; tokens per second is what a long answer costs in
    wall-clock. A model can be quick to start and slow to finish, or the reverse.

    Args:
        limit: how many models to plot.
    """
    rows, why = _joined()
    if why:
        return why
    pts = [r for r in rows if r["speed"] is not None and r["price"] is not None]
    if len(pts) < 2:
        return f"Only {len(pts)} models have both a price and a throughput measurement."
    with_ttft = [r for r in pts if r.get("ttft") is not None]
    pts.sort(key=lambda r: -(r["speed"] or 0))
    data = [
        {
            "usd_per_million": round(r["price"], 3),
            "tokens_per_sec": round(r["speed"]),
            "ttft_seconds": round(r["ttft"], 2) if r.get("ttft") is not None else None,
            "model": r["name"][:38],
        }
        for r in pts[:limit]
    ]
    spec = {
        "type": "scatter",
        "title": "Output throughput against input price",
        "data": data,
        "xKey": "usd_per_million",
        "yKey": "tokens_per_sec",
    }
    fastest = pts[0]
    note = (
        f"The fastest to generate here is {fastest['name']} at "
        f"{fastest['speed']:.0f} tokens/sec, {fmt_price(fastest['price'])} per million in."
    )

    # The interesting question is whether anything is good at both, and that
    # needs the two measurements side by side rather than one scatter.
    if len(with_ttft) >= 2:
        quick_start = sorted(with_ttft, key=lambda r: r["ttft"])
        quick_finish = sorted(with_ttft, key=lambda r: -(r["speed"] or 0))
        top_start = {r["name"] for r in quick_start[: max(3, len(with_ttft) // 4)]}
        both = [r for r in quick_finish[: max(3, len(with_ttft) // 4)] if r["name"] in top_start]
        table = {
            "title": f"Time to first token against throughput ({len(with_ttft)} measured)",
            "columns": ["Model", "TTFT", "Tokens/s", "$/M in"],
            "rows": [
                [r["name"], f"{r['ttft']:.2f}s", f"{r['speed']:.0f}", fmt_price(r["price"])]
                for r in quick_start[:10]
            ],
        }
        note += f"\n\n```datatable\n{json.dumps(table)}\n```\n\n"
        if both:
            note += (
                f"{len(both)} model(s) sit in the top quartile of both: "
                + ", ".join(r["name"] for r in both[:4])
                + ". So the two are not strictly a trade-off."
            )
        else:
            note += (
                "Nothing sits in the top quartile of both here — on this slice, quick to "
                "start and quick to finish really are different models."
            )
        note += (
            f" Only {len(with_ttft)} of {len(pts)} priced models carry a latency "
            f"measurement; the rest are unmeasured, not instant."
        )
    else:
        note += (
            " No time-to-first-token measurements are available for this slice, so I "
            "cannot say anything about how quickly these start answering."
        )
    return f"```chart\n{json.dumps(spec)}\n```\n\n{note}"


@tool
async def best_value(min_quality: float = 0.0, limit: int = 10) -> str:
    """Models ranked by measured quality per dollar.

    Args:
        min_quality: ignore models scoring below this on the intelligence index.
        limit: how many to list.
    """
    rows, why = _joined()
    if why:
        return why
    pts = [
        r for r in rows if r["quality"] is not None and r["price"] and r["quality"] >= min_quality
    ]
    if not pts:
        return f"No measured model clears a quality score of {min_quality}."
    pts.sort(key=lambda r: -(r["quality"] / r["price"]))
    spec = {
        "title": f"Index points per dollar ({len(pts)} measured models)",
        "columns": ["Model", "Index", "$/M in", "Index pts / $", "Tokens/s"],
        "rows": [
            [
                r["name"],
                f"{r['quality']:.0f}",
                fmt_price(r["price"]),
                f"{r['quality'] / r['price']:.0f}",
                f"{r['speed']:.0f}" if r["speed"] else "—",
            ]
            for r in pts[:limit]
        ],
    }
    top = pts[0]
    return (
        f"```datatable\n{json.dumps(spec)}\n```\n\n"
        f"{top['name']} leads on measured quality per dollar. Worth saying plainly: "
        f"this ranks value, not fitness — whether it does *your* job still has to be "
        f"tested on your own examples."
    )


def _snapshot_rows() -> list[dict]:
    import _analysis as aa

    measured = aa.index()
    out = []
    for m in models():
        meas = measured.get(aa._norm(m.get("id", "")))
        mm = aa.metrics(meas)
        out.append(
            {
                "id": m.get("id"),
                "name": m.get("name") or m.get("id"),
                "vendor": vendor(m),
                "context": m.get("context_length"),
                "price_in": price_per_million(m, "prompt"),
                "price_out": price_per_million(m, "completion"),
                # A snapshot of 0 tok/s becomes a false "speed changed" tomorrow.
                "quality": mm["quality"],
                "speed": mm["tokens_per_sec"],
                "ttft": mm["ttft"],
            }
        )
    return out


@tool
async def record_today() -> str:
    """Record today's catalogue so tomorrow can be compared against it.

    **Only the daily snapshot routine calls this.** It writes. Answering a
    question about how fresh the data is by taking a fresh snapshot changes the
    thing being asked about — use `history_depth` and `coverage` for that.
    """
    import _history as hist

    n = hist.take_snapshot(_snapshot_rows())
    ds = hist.days()
    return f"Recorded {n} models for today. {len(ds)} day(s) of history now held" + (
        f", from {ds[0]} to {ds[-1]}."
        if len(ds) > 1
        else " — one more day and I can report change."
    )


def _price_cut_table(c: dict, cuts: list[dict]) -> str:
    """The cuts as a table. Shared by both branches of whats_changed — a quiet
    day with one moving category still deserves the detail."""
    spec = {
        "title": f"Price cuts since {c['from']}",
        "columns": ["Model", "Was", "Now", "Change"],
        "rows": [
            [
                m["name"] or m["model_id"],
                fmt_price(m["was"]),
                fmt_price(m["now"]),
                f"{m['pct']:.0f}%",
            ]
            for m in cuts[:10]
        ],
    }
    return f"```datatable\n{json.dumps(spec)}\n```"


@tool
async def whats_changed(days: int = 7) -> str:
    """What moved since roughly `days` ago — new models, price and quality shifts.

    Args:
        days: how far back to compare.
    """
    import _history as hist

    c = hist.compare(days)
    if not c["have_history"]:
        return (
            "I have only one snapshot so far, so I cannot report change yet — "
            "that is different from saying nothing changed. Another day of "
            "recording and this becomes answerable."
        )

    # Only categories that actually moved. A row reading "New 0, Gone 0,
    # Latency moves 0, Quality moves 0" is a masthead of non-events: it puts
    # three zeros above the one number that matters and teaches the reader that
    # the top of the digest is skippable.
    candidates = [
        (len(c["added"]), "New", "models appeared"),
        (len(c["removed"]), "Gone", "delisted"),
        (len(c["price_moves"]), "Price moves", "1% or more"),
        (len(c.get("latency_moves", [])), "Latency moves", "TTFT, 10%+"),
        (len(c["quality_moves"]), "Quality moves", "re-measured"),
    ]
    cards = [
        {"title": title, "value": str(n), "subtitle": sub} for n, title, sub in candidates if n
    ]
    # One card alone is not a dashboard row, it is a number that wandered into a
    # box. Below two, say it in the sentence instead.
    if len(cards) < 2:
        moved = ", ".join(f"{c['value']} {c['title'].lower()} ({c['subtitle']})" for c in cards)
        head = (
            f"Between {c['from']} and {c['to']}: {moved}."
            if cards
            else (
                f"Nothing moved between {c['from']} and {c['to']}: no listings added or "
                f"removed, no price change of 1% or more, no re-measured quality, and no "
                f"time-to-first-token shift past 10%."
            )
        )
        out = [head]
        cuts = [m for m in c["price_moves"] if m["pct"] < 0]
        if cuts:
            out.append(_price_cut_table(c, cuts))
        return "\n\n".join(out)
    if not cards:
        return (
            f"Nothing moved between {c['from']} and {c['to']}: no listings added or "
            f"removed, no price change of 1% or more, no re-measured quality, and no "
            f"time-to-first-token shift past 10%."
        )
    out = [f"```kpi\n{json.dumps(cards)}\n```"]

    cuts = [m for m in c["price_moves"] if m["pct"] < 0]
    if cuts:
        out.append(_price_cut_table(c, cuts))

    tail = f"Comparing {c['to']} against {c['from']}."
    if cuts:
        deepest = cuts[0]
        tail += (
            f" The deepest cut was {deepest['name']} at {deepest['pct']:.0f}%, "
            f"{fmt_price(deepest['was'])} to {fmt_price(deepest['now'])} per million."
        )
    return "\n\n".join(out) + f"\n\n{tail}"


@tool
async def history_depth() -> str:
    """How many days of history exist, and therefore what can be asked."""
    import _history as hist

    ds = hist.days()
    if not ds:
        return "No snapshots recorded yet. Call record_today to start the series."
    if len(ds) == 1:
        return f"One snapshot, {ds[0]}. Change questions need a second day."
    return (
        f"{len(ds)} snapshots, {ds[0]} to {ds[-1]}. "
        f"Change can be reported over any window inside that range."
    )

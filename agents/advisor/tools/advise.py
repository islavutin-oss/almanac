"""The advisor desk — narrowing the whole catalogue down to the two or three worth trying."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from agentino import tool

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _openrouter import (  # noqa: E402
    fmt_context,
    fmt_price,
    is_free,
    models,
    price_per_million,
    vendor,
)


@tool
async def shortlist(
    min_context: int = 0,
    max_input_price: float = 1000.0,
    free_only: bool = False,
    vendor_filter: str = "",
    min_quality: float = 0.0,
    max_ttft: float = 0.0,
    task: str = "",
    sort: str = "value",
    limit: int = 8,
) -> str:
    """Models matching a set of requirements, with measured quality and latency.

    Answer with this as soon as you have one real constraint. A shortlist built
    on a stated budget beats a clarifying question the person has to answer
    before they get anything.

    Args:
        min_context: minimum context window in tokens (e.g. 128000).
        max_input_price: ceiling on input cost, US dollars per million tokens.
        free_only: only models with no input charge.
        vendor_filter: restrict to one vendor slug, e.g. "openai".
        min_quality: floor on the measured intelligence index (0-100).
        max_ttft: ceiling on median time to first token, in seconds. Use this
            when the thing is interactive — it is usually the constraint that
            decides, and it is unrelated to how good the model is.
        task: rank on one measured skill instead of the composite index —
            "coding", "agentic", "tool_use", "reasoning", "long_context",
            "science" or "hard". A composite index is a poor proxy for a
            specific job, so prefer this when the job is known.
        sort: "value" (score per dollar), "quality", "price", "speed" or "ttft".
        limit: how many to return.
    """
    import _analysis as aa

    TASKS = {"coding", "agentic", "tool_use", "reasoning", "long_context", "science", "hard"}
    task = task.strip().lower()
    if task and task not in TASKS:
        return f"'{task}' is not a measured skill. Available: {', '.join(sorted(TASKS))}."
    score_key = task or "quality"

    measured = aa.index()
    out = []
    for m in models():
        # Price comes from the catalogue, never from the measurement source —
        # the two quote different providers and tiers for the same model, and
        # showing both would be two prices for one thing.
        p = price_per_million(m, "prompt")
        ctx = m.get("context_length") or 0
        if ctx < min_context:
            continue
        if free_only and not is_free(m):
            continue
        if vendor_filter and vendor(m) != vendor_filter.lower():
            continue
        if p is None or p > max_input_price:
            continue
        mm = aa.metrics(measured.get(aa._norm(m.get("id", ""))))
        if min_quality and (mm["quality"] is None or mm["quality"] < min_quality):
            continue
        if max_ttft and (mm["ttft"] is None or mm["ttft"] > max_ttft):
            continue
        out.append({"m": m, "price": p, "mm": mm, "score": mm[score_key]})

    if not out:
        if max_ttft:
            hint = (
                "A latency ceiling that tight usually collides with the context or "
                "price floor. Say which one gives and I will re-run it."
            )
        elif min_quality or task:
            hint = (
                "Only part of the catalogue is independently measured, so a quality "
                "floor or a task ranking also drops everything unmeasured. Say whether "
                "to keep unmeasured models and I will re-run it."
            )
        else:
            hint = (
                "The usual cause is a context floor and a price ceiling that cannot "
                "both hold — say which one matters more and I will re-run it."
            )
        return f"Nothing matches those constraints. {hint}"

    def value(r):
        if r["score"] is None or not r["price"]:
            return -1.0
        return r["score"] / r["price"]

    def low(v):  # sort ascending, unmeasured last
        return v if v is not None else float("inf")

    def high(v):  # sort descending, unmeasured last
        return -(v if v is not None else -1)

    keys = {
        "value": lambda r: (-value(r), r["price"]),
        "quality": lambda r: (high(r["score"]), r["price"]),
        "speed": lambda r: (high(r["mm"]["tokens_per_sec"]), r["price"]),
        "ttft": lambda r: (low(r["mm"]["ttft"]), r["price"]),
        "price": lambda r: (r["price"],),
    }
    out.sort(key=keys.get(sort, keys["value"]))

    label = task.replace("_", " ").title() if task else "Quality"
    rows = [
        [
            r["m"].get("name") or r["m"]["id"],
            vendor(r["m"]),
            fmt_context(r["m"].get("context_length")),
            fmt_price(r["price"]),
            f"{r['score']:.0f}" if r["score"] is not None else "—",
            f"{r['mm']['ttft']:.2f}s" if r["mm"]["ttft"] is not None else "—",
            f"{r['mm']['tokens_per_sec']:.0f}" if r["mm"]["tokens_per_sec"] is not None else "—",
        ]
        for r in out[:limit]
    ]
    spec = {
        "title": f"{len(out)} models match — top {len(rows)} by {sort}",
        "columns": ["Model", "Vendor", "Context", "$/M in", label, "TTFT", "Tok/s"],
        "rows": rows,
    }
    n_measured = sum(1 for r in out if r["score"] is not None)
    note = (
        f"{len(out)} of {len(models())} models clear those constraints; "
        f"{n_measured} have a measured {label.lower()} score. "
    )
    note += (
        "Measured by a third party on their own tasks — it narrows what to "
        "evaluate, it does not settle it. TTFT is a median under their load, "
        "not yours."
    )
    return f"```datatable\n{json.dumps(spec)}\n```\n\n{note}"


@tool
async def compare(models_csv: str) -> str:
    """Two or three named models side by side, on every measure there is.

    Use this the moment someone names models — "GLM 5.3 Flash vs DeepSeek V4
    Flash", "is Sonnet worth it over Haiku". `shortlist` answers "what should I
    look at"; this answers "which of these", which is a different question and
    the one people ask once they have a shortlist.

    Shows price, context, measured quality, the per-skill scores, first-token
    latency and throughput — and says plainly which figures are missing, because
    an unmeasured model is unmeasured, not fast.

    Args:
        models_csv: comma-separated model names or ids, e.g.
            "GLM 5.3 Flash, DeepSeek V4 Flash".
    """
    import _analysis as aa

    wanted = [w.strip().lower() for w in models_csv.split(",") if w.strip()]
    if not wanted:
        return "Name at least one model to compare."
    if len(wanted) > 4:
        return "Four at most — beyond that the table stops being readable."

    measured = aa.index()
    picked: list[dict] = []
    for w in wanted:
        hit = None
        for m in models():
            hay = f"{m.get('id', '')} {m.get('name', '')}".lower()
            if w in hay:
                # Prefer an exact-ish match over the first substring hit.
                if hit is None or len(m.get("name", "")) < len(hit.get("name", "")):
                    hit = m
        if hit is None:
            return f"No model in the catalogue matches '{w}'."
        if hit not in picked:
            picked.append(hit)

    def cell(v, suffix="", nd=2):
        return "unmeasured" if v is None else f"{v:.{nd}f}{suffix}"

    rows = []
    for m in picked:
        mm = aa.metrics(measured.get(aa._norm(m.get("name", ""))))
        rows.append(
            [
                m.get("name", m.get("id", "?")),
                vendor(m),
                fmt_context(m.get("context_length")),
                fmt_price(price_per_million(m, "prompt")),
                fmt_price(price_per_million(m, "completion")),
                cell(mm.get("quality"), nd=1),
                cell(mm.get("coding"), nd=1),
                cell(mm.get("ttft"), "s"),
                cell(mm.get("tokens_per_sec"), nd=0),
            ]
        )

    table = {
        "title": f"{len(rows)} models, side by side",
        "columns": [
            "Model",
            "Vendor",
            "Context",
            "$/M in",
            "$/M out",
            "Quality",
            "Coding",
            "TTFT",
            "Tok/s",
        ],
        "rows": rows,
    }
    missing = sum(1 for r in rows if "unmeasured" in r)
    note = ""
    if missing:
        note = (
            f"\n\n{missing} of these has no independent measurement. "
            "That is a gap in the data, not evidence about the model."
        )
    return f"```datatable\n{json.dumps(table, ensure_ascii=False)}\n```{note}"


@tool
async def monthly_cost(
    input_tokens_per_month: int,
    output_tokens_per_month: int,
    min_context: int = 0,
    models_csv: str = "",
    include_free: bool = False,
    limit: int = 6,
) -> str:
    """What a month costs, at list price, for a set of models.

    Pass `models_csv` with the names you just recommended — pricing the actual
    shortlist is what the person asked for. Left empty this prices the cheapest
    models meeting the context floor, which after the free tier is filtered out
    is a reasonable default.

    List price only — the number before caching, batching, routing or anything
    else that actually moves a bill.

    Args:
        input_tokens_per_month: expected prompt tokens per month.
        output_tokens_per_month: expected completion tokens per month.
        min_context: minimum context window in tokens.
        models_csv: comma-separated model names or ids to price exactly.
        include_free: keep models that cost nothing. Off by default, because
            a chart whose bars are all zero answers no question.
        limit: how many models to price when `models_csv` is empty.
    """
    wanted = [w.strip().lower() for w in models_csv.split(",") if w.strip()]

    def matches(m) -> bool:
        hay = f"{m.get('id', '')} {m.get('name', '')}".lower()
        return any(w in hay for w in wanted)

    priced = []
    for m in models():
        pin = price_per_million(m, "prompt")
        pout = price_per_million(m, "completion")
        if pin is None or pout is None:
            continue
        if (m.get("context_length") or 0) < min_context:
            continue
        if wanted and not matches(m):
            continue
        total = (
            pin * input_tokens_per_month / 1_000_000 + pout * output_tokens_per_month / 1_000_000
        )
        # A free model prices at zero and flattens the chart against everything
        # else on it. Keep it only when asked for by name or by include_free.
        if total == 0 and not include_free and not wanted:
            continue
        priced.append((total, m))

    if not priced:
        if wanted:
            return (
                f"None of those matched the catalogue: {models_csv}. "
                "Use the names exactly as the shortlist printed them."
            )
        return "No model has both prices published at that context floor."

    priced.sort(key=lambda t: t[0])
    keep = priced if wanted else priced[:limit]
    data = [{"model": (m.get("name") or m["id"])[:34], "usd": round(total, 2)} for total, m in keep]
    if all(d["usd"] == 0 for d in data):
        names = ", ".join(d["model"] for d in data)
        return (
            f"Every one of those is free at list price, so there is no chart to draw: "
            f"{names}. The cost question moves to rate limits and whether the free tier "
            f"holds at your volume — which is a measurement question, not a price one."
        )

    spec = {
        "type": "bar",
        "title": "Estimated monthly list price",
        "data": data,
        "xKey": "model",
        "yKey": "usd",
        "yFormat": "currency",
        "currency": "$",
    }
    cheapest, dearest = data[0], data[-1]
    spread = f"{dearest['usd'] / cheapest['usd']:.0f}\u00d7" if cheapest["usd"] else "a wide margin"
    return (
        f"```chart\n{json.dumps(spec)}\n```\n\n"
        f"At that volume the shortlist spans {spread} \u2014 ${cheapest['usd']:,.2f} to "
        f"${dearest['usd']:,.2f} a month at list price."
    )


@tool
async def talk_to_a_human(topic: str = "") -> str:
    """Point the person at Iliya, with his actual contact details.

    Call this when the question has genuinely left what public data can settle —
    what a bill does under real traffic, whether a model holds up on someone's
    own evaluation set, how to get latency down on hardware you already own,
    what to run at the edge. Those are measurement and engineering questions,
    and they are what he does for a living.

    Call it once, when it is earned. An offer attached to a question you
    answered well reads as an advert and costs the trust the answer just built.

    This deliberately collects nothing. There is no form and no address book:
    the visitor is given a way to reach him and decides for themselves. A demo
    that harvested contact details would need a lawful basis, a retention
    policy and somewhere safe to keep them, none of which a demo should have.

    Args:
        topic: the specific thing the person is trying to work out. It is shown
            back to them, so make it recognisably theirs rather than generic.
    """
    subject = topic.strip() or "what you are working on"
    email = os.getenv("ADVISOR_CONTACT_EMAIL", "").strip()
    telegram = os.getenv("ADVISOR_CONTACT_TELEGRAM", "").strip()
    linkedin = os.getenv("ADVISOR_CONTACT_LINKEDIN", "").strip()

    spec = {
        "kind": "opportunity",
        "headline": "This one is a measurement question, not a catalogue one",
        "body": (
            f"{subject[0].upper() + subject[1:]} depends on your traffic shape, your "
            "latency budget and the hardware you are already paying for — none of "
            "which is in a public price list. Iliya does this for a living: LLM and "
            "VLM deployment from edge to cloud, and getting inference bills and "
            "latency down once something is in production. He is happy to talk it "
            "through."
        ),
    }
    routes = []
    if email:
        routes.append(f"✉️  {email}")
    if telegram:
        routes.append(f"✈️  {telegram}")
    if linkedin:
        routes.append(f"in  {linkedin}")

    # A card rather than a list of addresses: this is the one moment in the
    # conversation where the next step is a person, and it should look like an
    # offer instead of a footer. cta drives the primary route; the rest sit in
    # the body so nobody has to hunt for the one they prefer.
    if routes:
        spec["body"] = spec["body"] + "\n\n" + "   ".join(routes)
    if email:
        spec["cta"] = {"label": "Email Iliya", "href": f"mailto:{email}"}
    elif telegram:
        handle = telegram.lstrip("@")
        spec["cta"] = {"label": "Message on Telegram", "href": f"https://t.me/{handle}"}
    elif linkedin:
        spec["cta"] = {"label": "Connect on LinkedIn", "href": linkedin}

    return f"```insight\n{json.dumps(spec, ensure_ascii=False)}\n```"

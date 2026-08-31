"""Generating a report the reader can take away.

A chat answer is read once and scrolled past. A question like "what should we
switch to" is usually asked on behalf of somebody who is not in the room, and
the useful artefact is a file that survives the conversation.

The report is written through the workspace's file storage and returned as a
`file` block, so it renders as a download row rather than a link buried in a
sentence.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from agentino import tool
from catalogue import _joined  # noqa: E402  (sibling tool module)


def _storage():
    """The workspace's file storage, or None outside a workspace process."""
    try:
        from protocols import get_file_storage

        return get_file_storage()
    except Exception:
        return None


def _tenant() -> str:
    try:
        from agentino.context import current_tenant  # type: ignore

        return current_tenant() or "default"
    except Exception:
        return "almanac"


@tool
async def generate_report(
    kind: str = "shortlist",
    min_quality: float = 0.0,
    max_input_price: float = 1000.0,
    min_context: int = 0,
    limit: int = 40,
    fmt: str = "csv",
) -> str:
    """Write a report of the measured catalogue and attach it for download.

    Use this when someone needs to take the answer away — to circulate it, to
    put it in front of a decision they are not making alone, or to diff it next
    month. Do not use it instead of answering: give the answer in the message,
    and attach the file as the thing they keep.

    Args:
        kind: "shortlist" (models with their measurements) or "coverage"
            (what is measured and what is not).
        min_quality: floor on the measured intelligence index.
        max_input_price: ceiling on input cost, dollars per million tokens.
        min_context: minimum context window in tokens.
        limit: how many rows.
        fmt: "csv" or "markdown".
    """
    kind = kind.strip().lower()
    fmt = fmt.strip().lower()
    if kind not in {"shortlist", "coverage"}:
        return "kind must be 'shortlist' or 'coverage'."
    if fmt not in {"csv", "markdown"}:
        return "fmt must be 'csv' or 'markdown'."

    rows, why = _joined()
    if why:
        return why

    picked = [
        r
        for r in rows
        if (r["price"] is not None and r["price"] <= max_input_price)
        and (r["context"] or 0) >= min_context
        and (not min_quality or (r["quality"] is not None and r["quality"] >= min_quality))
    ]
    if not picked:
        return "Nothing matches those constraints, so there is no report to write."

    if kind == "shortlist":
        picked.sort(key=lambda r: -(r["quality"] or -1))
        header = [
            "Model",
            "Vendor",
            "Context",
            "USD per M input",
            "Quality index",
            "TTFT s",
            "Tokens per s",
        ]
        table = [
            [
                r["name"],
                r["vendor"],
                r["context"] or "",
                f"{r['price']:.4f}" if r["price"] is not None else "",
                f"{r['quality']:.1f}" if r["quality"] is not None else "unmeasured",
                f"{r['ttft']:.2f}" if r["ttft"] is not None else "unmeasured",
                f"{r['speed']:.0f}" if r["speed"] is not None else "unmeasured",
            ]
            for r in picked[:limit]
        ]
    else:
        picked.sort(key=lambda r: r["name"].lower())
        header = ["Model", "Vendor", "Quality measured", "Latency measured", "USD per M input"]
        table = [
            [
                r["name"],
                r["vendor"],
                "yes" if r["quality"] is not None else "no",
                "yes" if r["ttft"] is not None else "no",
                f"{r['price']:.4f}" if r["price"] is not None else "",
            ]
            for r in picked[:limit]
        ]

    stamp = datetime.now(timezone.utc)
    note = (
        f"Generated {stamp:%Y-%m-%d %H:%M} UTC from the OpenRouter catalogue and "
        f"Artificial Analysis measurements. {len(picked)} models matched; "
        f"{len(table)} listed. 'unmeasured' means nobody has published that "
        f"figure — it does not mean zero."
    )

    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        w.writerows(table)
        w.writerow([])
        w.writerow([note])
        body = buf.getvalue().encode("utf-8")
        name = f"almanac-{kind}-{stamp:%Y%m%d}.csv"
        content_type = "text/csv"
    else:
        lines = [
            f"# Almanac {kind} report",
            "",
            note,
            "",
            "| " + " | ".join(header) + " |",
            "|" + "|".join(["---"] * len(header)) + "|",
        ]
        lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in table]
        body = ("\n".join(lines) + "\n").encode("utf-8")
        name = f"almanac-{kind}-{stamp:%Y%m%d}.md"
        content_type = "text/markdown"

    storage = _storage()
    if storage is None:
        return (
            "I built the report but there is no file storage configured in this "
            "process, so there is nothing to attach. Ask again from the workspace."
        )
    meta = storage.put(_tenant(), name, body, content_type=content_type)
    spec = {
        "name": name,
        "url": f"/api/workspace/files/{meta.file_id}",
        "kind": "csv" if fmt == "csv" else "markdown",
        "size": len(body),
        "caption": note,
    }
    return (
        f"```file\n{json.dumps(spec)}\n```\n\n"
        f"{len(table)} of {len(picked)} matching models, newest measurements. "
        f"Unmeasured fields say so rather than reading as zero."
    )

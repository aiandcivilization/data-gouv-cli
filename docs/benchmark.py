#!/usr/bin/env python3
"""Render docs/benchmark.svg from benchmarks/mcp-vs-cli.json.

The chart is generated, never hand-edited: the numbers in the README and the
numbers in the SVG come from the same measured transcript.

Style: a tall translucent "before" bar, a short solid "after" bar, and one
straight arrow carrying the delta.

Usage:
    python docs/benchmark.py benchmarks/mcp-vs-cli.json docs/benchmark.svg [a|b]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PAPER = "#F0EEE6"
IVORY = "#FAF9F5"
INK = "#141413"
SLATE = "#3D3D3A"
CLOUD = "#87867F"
CLAY = "#D97757"
CLAY_DEEP = "#C6613F"
LINE = "#D8D2C4"

W, H = 1600, 900
BASELINE = 720
TALL_H = 400
BAR_W = 170

QUESTIONS = {
    "a": "How many inhabitants does Biot (06018) have?",
    "b": "What is the median price per m² in Biot in 2024?",
}
OUTCOMES = {
    "a": ("9 880 (stale)", "10 511"),
    "b": ("no answer", "6 142 €/m²"),
}


def esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def render(report: dict, task_key: str = "b") -> str:
    task = report[f"task_{task_key}"]
    question = QUESTIONS[task_key]
    mcp = dict(task["mcp"], label="data.gouv MCP")
    cli = dict(task["cli"], label="french-gov-cli")
    date = report.get("date", "").split("T")[0]
    tokenizer = report.get("tokenizer", "o200k_base")

    # Task B was measured in the same session as A, so the schema was already
    # paid for. A standalone B session pays it again; add it back and say so.
    schema = report["task_a"]["mcp"]["tokens_breakdown"]["schema"]
    if task_key == "b":
        mcp["tokens"] += schema

    mcp_out, cli_out = OUTCOMES[task_key]
    token_delta = round((1 - cli["tokens"] / mcp["tokens"]) * 100)
    step_delta = round((1 - cli["steps"] / mcp["steps"]) * 100)
    title = (
        "One question. One path answers."
        if "no answer" in mcp_out
        else f"The same answer, {token_delta} % lighter."
    )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img">',
        "<defs>",
        '<marker id="drop" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5.5" markerHeight="5.5" orient="auto">',
        f'<path d="M 0 0 L 10 5 L 0 10 Z" fill="{CLAY_DEEP}"/>',
        "</marker>",
        "</defs>",
        f'<rect width="{W}" height="{H}" fill="{PAPER}"/>',
        f'<text x="96" y="110" font-family="DejaVu Sans Mono, monospace" font-size="19" letter-spacing="3" fill="{CLOUD}">SAME QUESTION · {esc(date).upper()}</text>',
        f'<text x="96" y="186" font-family="DejaVu Serif, serif" font-size="58" font-weight="700" fill="{INK}">{title}</text>',
        f'<text x="96" y="234" font-family="DejaVu Sans, sans-serif" font-size="25" fill="{SLATE}">{esc(question)}</text>',
    ]

    groups = [
        ("STEPS", "tool calls", mcp["steps"], cli["steps"], step_delta, mcp_out, cli_out),
        ("TOKENS", f"tiktoken {tokenizer}", mcp["tokens"], cli["tokens"], token_delta, mcp_out, cli_out),
    ]

    for index, (label, unit, high, low, delta, high_out, low_out) in enumerate(groups):
        cx = 430 + index * 700
        tall_x = cx - BAR_W - 24
        short_x = cx + 24
        short_h = max(34, TALL_H * low / high)
        tall_top = BASELINE - TALL_H
        short_top = BASELINE - short_h

        parts.append(
            f'<rect x="{tall_x}" y="{tall_top}" width="{BAR_W}" height="{TALL_H}" rx="10" '
            f'fill="{CLAY}" fill-opacity="0.10" stroke="{CLAY}" stroke-opacity="0.55" stroke-width="2" stroke-dasharray="7 7"/>'
        )
        parts.append(
            f'<rect x="{short_x}" y="{short_top}" width="{BAR_W}" height="{short_h}" rx="10" fill="{CLAY}"/>'
        )

        parts.append(
            f'<text x="{tall_x + BAR_W / 2}" y="{tall_top + 58}" text-anchor="middle" '
            f'font-family="DejaVu Sans Mono, monospace" font-size="40" fill="{INK}">{fmt(high)}</text>'
        )
        if short_h >= 70:
            parts.append(
                f'<text x="{short_x + BAR_W / 2}" y="{short_top + 50}" text-anchor="middle" '
                f'font-family="DejaVu Sans Mono, monospace" font-size="38" fill="{IVORY}">{fmt(low)}</text>'
            )
        else:
            parts.append(
                f'<text x="{short_x + BAR_W + 18}" y="{short_top + short_h / 2 + 12}" '
                f'font-family="DejaVu Sans Mono, monospace" font-size="36" fill="{CLAY_DEEP}">{fmt(low)}</text>'
            )

        start_x = tall_x + BAR_W - 14
        end_x = short_x + BAR_W / 2
        start_y = tall_top + 84
        end_y = short_top - 26
        mid_y = (start_y + end_y) / 2
        parts.append(
            f'<line x1="{start_x}" y1="{start_y}" x2="{end_x}" y2="{end_y}" '
            f'stroke="{CLAY_DEEP}" stroke-width="5" stroke-linecap="round" marker-end="url(#drop)"/>'
        )
        parts.append(
            f'<text x="{end_x + 24}" y="{mid_y}" font-family="DejaVu Sans Mono, monospace" '
            f'font-size="31" fill="{CLAY_DEEP}">−{delta} %</text>'
        )

        parts.append(
            f'<line x1="{tall_x - 20}" y1="{BASELINE}" x2="{short_x + BAR_W + 20}" y2="{BASELINE}" '
            f'stroke="{LINE}" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{tall_x + BAR_W / 2}" y="{BASELINE + 34}" text-anchor="middle" '
            f'font-family="DejaVu Sans, sans-serif" font-size="19" fill="{SLATE}">{esc(mcp["label"])}</text>'
        )
        parts.append(
            f'<text x="{short_x + BAR_W / 2}" y="{BASELINE + 34}" text-anchor="middle" '
            f'font-family="DejaVu Sans, sans-serif" font-size="19" fill="{SLATE}">{esc(cli["label"])}</text>'
        )
        high_color = CLAY_DEEP if "no answer" in high_out else CLOUD
        parts.append(
            f'<text x="{tall_x + BAR_W / 2}" y="{BASELINE + 60}" text-anchor="middle" '
            f'font-family="DejaVu Sans Mono, monospace" font-size="16" fill="{high_color}">{esc(high_out)}</text>'
        )
        parts.append(
            f'<text x="{short_x + BAR_W / 2}" y="{BASELINE + 60}" text-anchor="middle" '
            f'font-family="DejaVu Sans Mono, monospace" font-size="16" fill="{CLAY_DEEP}">{esc(low_out)}</text>'
        )
        parts.append(
            f'<text x="{tall_x}" y="{tall_top - 26}" font-family="DejaVu Sans Mono, monospace" '
            f'font-size="21" letter-spacing="3" fill="{CLOUD}">{label}</text>'
        )
        parts.append(
            f'<text x="{tall_x}" y="{tall_top - 2}" font-family="DejaVu Sans Mono, monospace" '
            f'font-size="14" fill="{CLOUD}">{esc(unit)}</text>'
        )

    schema_note = " · MCP includes the 2,673-token tool schema" if task_key == "b" else ""
    parts.extend(
        [
            f'<line x1="96" y1="806" x2="1504" y2="806" stroke="{LINE}" stroke-width="1"/>',
            f'<text x="96" y="846" font-family="DejaVu Sans Mono, monospace" font-size="15" fill="{CLOUD}">'
            f'raw transcript: benchmarks/mcp-vs-cli.json{schema_note} · zero-based axis</text>',
        ]
    )
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> int:
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        return 2
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    task_key = sys.argv[3] if len(sys.argv) == 4 else "b"
    report = json.loads(source.read_text(encoding="utf-8"))
    target.write_text(render(report, task_key), encoding="utf-8")
    print(f"{target} ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

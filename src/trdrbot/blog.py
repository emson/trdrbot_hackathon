"""One markdown trade story per position, for outside review (D-097).

Not the machine record - the journal and the position pages already are that,
and they stay exactly as they are. This is the same underlying facts, told
once as prose, for a reader who is not going to grep `journal.jsonl`: what was
decided, why, what was rejected instead, what fed it in, and - once the
position resolves - how it actually went.

Written at two moments in a position's life. `write_entry` at record time,
with everything `record_position` and `simulate_experiments` already computed
this cycle (D-037: derived, not re-declared - nothing here is asked of the
model a second time). `write_outcome` at resolution, from whichever detector
got there first (an agent-initiated close, an automated exit rule, or
reconcile finding the position gone) - it appends to the same file rather than
writing a second one, so a reader sees the whole story in one place.

Both functions are synchronous (plain file I/O, matching `PositionStore.save`)
and swallow their own failures: publishing a trade's story must never be able
to interrupt the tick that trade is part of. A failure is printed and, when a
journal is supplied, left as a `degraded` row - visible to `trdrbot health`,
never fatal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import health, store
from .local_tools import RecordedTrade, SimStructure
from .positions import Position


def path_for(blog_dir: Path, position_id: str) -> Path:
    return blog_dir / f"{position_id}.md"


def _usd(v: float | None) -> str:
    return f"${v:,.2f}" if v is not None else "unknown"


def _pct(v: float | None) -> str:
    return f"{v:+.1%}" if v is not None else "unknown"


def _legs_table(pos: Position) -> str:
    if not pos.legs:
        return "_no legs recorded._"
    rows = ["| side | qty | symbol |", "|---|---|---|"]
    rows += [f"| {leg.get('side', '?')} | {leg.get('qty', '?')} | {leg.get('symbol', '?')} |"
             for leg in pos.legs]
    return "\n".join(rows)


def _exit_rules_table(pos: Position) -> str:
    if not pos.exit_rules:
        return ("_none authored this cycle - the implicit deadline, time-stop and "
                "leg-divergence rules still apply to every position._")
    rows = ["| rule | detail |", "|---|---|"]
    for r in pos.exit_rules:
        kind = r.get("type", "?")
        detail = ", ".join(f"{k} {v}" for k, v in r.items() if k != "type")
        rows.append(f"| {kind} | {detail} |")
    return "\n".join(rows)


def _structure_row(st: SimStructure, *, chosen: bool) -> str:
    payoff = f"{st.payoff_ratio:.2f}" if st.payoff_ratio is not None else "n/a"
    mark = "**chosen**" if chosen else ""
    return (f"| {st.name} | {_usd(st.entry_cost)} | {_usd(st.max_profit)} | "
            f"{_usd(st.max_loss)} | {payoff} | {mark} |")


def _alternatives_section(trade: RecordedTrade) -> str:
    if not trade.alternatives and trade.matched is None:
        return ("_No simulated alternatives are on record for this trade - "
                "`simulate_experiments` was not called, or not before this position "
                "was recorded, so what else was considered isn't known.)_")
    rows = ["| structure | entry cost | max profit | max loss | payoff ratio | |",
            "|---|---:|---:|---:|---:|---|"]
    if trade.matched is not None:
        rows.append(_structure_row(trade.matched, chosen=True))
    rows += [_structure_row(st, chosen=False) for st in trade.alternatives]
    return "\n".join(rows)


def _sources_section(pos: Position) -> str:
    if not pos.sources:
        return "_No sources recorded for this position._"
    lines = []
    for s in pos.sources:
        author = s.get("author", "?")
        resource = s.get("resource", s.get("id", "?"))
        lines.append(f"- **{author}** — `{resource}`")
    return "\n".join(lines)


def _thesis_section(pos: Position) -> str:
    if not pos.thesis_claim and not pos.thesis:
        return ("_No thesis was recorded at entry for this position - it predates "
                "the pre-registration ledger being wired into the decide loop, or "
                "the model skipped `simulate_experiments`. This is a known, honest "
                "gap, not a hidden one._")
    parts = []
    if pos.thesis_claim:
        parts.append(f"**Claim:** {pos.thesis_claim}")
    if pos.thesis_horizon:
        band = ""
        if pos.thesis_band_low is not None or pos.thesis_band_high is not None:
            lo = pos.thesis_band_low if pos.thesis_band_low is not None else "–"
            hi = pos.thesis_band_high if pos.thesis_band_high is not None else "–"
            band = f", band [{lo}, {hi}]"
        parts.append(f"**Resolves:** {pos.thesis_horizon}{band}")
    if pos.thesis_drift:
        parts.append(f"**Expected drift:** {_pct(pos.thesis_drift)}")
    if pos.thesis_vol_view is not None:
        parts.append(f"**Vol view:** {pos.thesis_vol_view:.1%} annualized realized")
    if pos.thesis:
        parts.append(f"\n{pos.thesis}")
    return "\n\n".join(parts)


def _frontmatter(pos: Position, *, decision_ref: str, batch: str, model: str,
                 served: list[str], confidence: float | None) -> str:
    opened = pos.opened or ""
    date, _, time = opened.partition("T")
    lines = [
        "---",
        f'title: "{pos.underlying} {pos.strategy.replace("_", " ")}"',
        f"position_id: {pos.position_id}",
        f"date: {date or 'unknown'}",
        f'time: "{time or "unknown"}"',
        f"underlying: {pos.underlying}",
        f"strategy: {pos.strategy}",
        f"status: {pos.status}",
        f"expiry: {pos.expiry or 'none'}",
        f"max_loss_usd: {pos.max_loss_usd if pos.max_loss_usd is not None else 'null'}",
        f"confidence: {confidence if confidence is not None else 'null'}",
        f"decision_ref: {decision_ref}",
        f"batch: {batch}",
        f"model: {model}",
        f"model_served: {served!r}",
        "---",
        "",
    ]
    return "\n".join(lines)


def write_entry(
    trade: RecordedTrade,
    *,
    summary_text: str,
    decision_ref: str,
    batch: str,
    model: str,
    served: list[str],
    blog_dir: Path,
    journal: Any = None,
) -> Path | None:
    """Write the entry-time story for one newly-recorded position.

    Everything here is either a fact already on the Position (legs, risk,
    exit rules, sources) or the agent's own words this cycle (`summary_text`,
    the SAME text the journal's `execution` row stores) - nothing is
    paraphrased or re-summarized, so the blog can never quietly say something
    the trade itself did not.
    """
    pos = trade.position
    try:
        title = f"{pos.underlying} {pos.strategy.replace('_', ' ')}"
        body = _frontmatter(pos, decision_ref=decision_ref, batch=batch, model=model,
                            served=served, confidence=trade.confidence) + "\n".join([
            f"# {title}",
            "",
            f"Opened **{pos.opened or 'unknown time'}** — "
            f"max loss {_usd(pos.max_loss_usd)}, expiry {pos.expiry or 'none stated'}.",
            "",
            "## The thesis",
            "",
            _thesis_section(pos),
            "",
            "## Why this trade",
            "",
            summary_text.strip() or "_no reasoning captured this cycle._",
            "",
            "## Structures considered",
            "",
            _alternatives_section(trade),
            "",
            "## Sources",
            "",
            _sources_section(pos),
            "",
            "## Position details",
            "",
            "**Legs**",
            "",
            _legs_table(pos),
            "",
            "**Exit rules**",
            "",
            _exit_rules_table(pos),
            "",
            "## Outcome",
            "",
            "_Open - this section fills in when the position resolves._",
            "",
        ])
        path = path_for(blog_dir, pos.position_id)
        store.write_atomic(path, body)
        if journal is not None:
            journal.append("blog_entry", position_id=pos.position_id, path=str(path))
        return path
    except Exception as exc:  # noqa: BLE001 - publishing a story must never break a tick
        print(f"[blog] failed to write entry for {pos.position_id}: {exc!r}")
        if journal is not None:
            health.degraded(journal, "blog.write_entry", repr(exc), position_id=pos.position_id)
        return None


def write_outcome(
    pos: Position,
    *,
    close_reason: str,
    why: str,
    pnl_fraction: float | None,
    blog_dir: Path,
    journal: Any = None,
) -> bool:
    """Append how a position resolved to its existing entry - or, if no entry
    exists (the position predates this mechanism, or its entry write failed),
    write a minimal standalone outcome page rather than losing the resolution."""
    try:
        path = path_for(blog_dir, pos.position_id)
        outcome = "\n".join([
            f"**Closed:** {close_reason}",
            "",
            f"**Why:** {why}" if why else "",
            "",
            f"**Result:** {_pct(pnl_fraction)} of net entry cost"
            if pnl_fraction is not None else "**Result:** not observed at close.",
        ])
        if path.exists():
            text = path.read_text(encoding="utf-8")
            marker = "## Outcome"
            if marker in text:
                head, _, _ = text.partition(marker)
                text = f"{head}{marker}\n\n{outcome}\n"
            else:
                text = f"{text.rstrip()}\n\n{marker}\n\n{outcome}\n"
        else:
            # No entry page exists for this position (it predates this
            # mechanism, or its own write failed) - an outcome with no story
            # is still worth publishing rather than silently dropped.
            text = "\n".join([
                f"---\nposition_id: {pos.position_id}\nunderlying: {pos.underlying}\n"
                f"status: closed\n---\n",
                f"# {pos.underlying} {pos.strategy.replace('_', ' ')}",
                "",
                "_No entry story is on record for this position._",
                "",
                "## Outcome",
                "",
                outcome,
                "",
            ])
        store.write_atomic(path, text)
        if journal is not None:
            journal.append("blog_outcome", position_id=pos.position_id,
                           close_reason=close_reason, path=str(path))
        return True
    except Exception as exc:  # noqa: BLE001 - advisory, same reason as write_entry
        print(f"[blog] failed to write outcome for {pos.position_id}: {exc!r}")
        if journal is not None:
            health.degraded(journal, "blog.write_outcome", repr(exc), position_id=pos.position_id)
        return False

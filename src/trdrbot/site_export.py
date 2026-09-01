"""Export the agent's own record into `web/src/lib/data/snapshot.json`.

Not a second system. This module reads exactly the files the trading loop
already writes - journal, ledger, wiki, blog, dev journals, specs - and
reshapes them into one JSON file the website reads at build time. Nothing
here is computed that the trading code didn't already compute; where real
math is needed (a payoff curve) it calls `optmath` directly rather than
re-deriving option pricing a second time (D-037: derive, never re-declare).

Three guards run before anything is written, because this is the one export
in the whole project that is outward-facing and irreversible once published:

  1. **Redaction scan (hard fail).** Every string bound for the snapshot is
     checked against credential-shaped patterns AND the literal values in
     `.env`. Any hit aborts the export with nothing written.
  2. **Prose sanitizer (drop and report).** A `no_op` summary is occasionally
     a base64 thinking-signature blob instead of prose (observed: 1 of 84
     live). Rejected summaries are dropped and counted, never silently kept
     and never silently discarded without a trace - `integrity.
     summaries_dropped` carries the count into the published site itself.
  3. **Monotonicity guard (refuse and log).** If position/journal/thesis
     counts have gone DOWN since the last snapshot, something read a
     half-written file - refuse rather than publish a shrinking record.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import markdown as _md
import yaml

from . import config as config_mod
from . import ledger as ledger_mod
from . import optmath
from .attribution import _horizon_passed  # noqa: F401 (documents the horizon rule reused below)
from .calibration import CalibrationStore
from .experiments import (
    THESIS_RIGHT_EXPRESSION_RIGHT,
    THESIS_RIGHT_EXPRESSION_WRONG,
    THESIS_WRONG_EXPRESSION_FAITHFUL,
    THESIS_WRONG_PROFITED_ANYWAY,
    UNSCOREABLE,
)
from .journal import Journal
from .positions import Position, PositionStore

ROOT = config_mod.ROOT
DEFAULT_OUT = ROOT / "web" / "src" / "lib" / "data" / "snapshot.json"
PREV_SNAPSHOT_GLOB = "snapshot.json"

#: Hackathon rule (submission_and_judging.md), not a derived figure - the
#: account is required to start at exactly this balance. Labelled as such in
#: the output rather than presented as measured.
REQUIRED_START_EQUITY = 100_000.0

MD_EXT = ["tables", "fenced_code", "sane_lists", "nl2br"]


#: A markdown link whose target isn't a real URL/anchor - e.g. `specs/issues.md`
#: or `notes/017_x.md`, relative to the SOURCE REPO's own layout, not this
#: site's routes. Left as a real link it becomes an internal-looking href the
#: prerender crawler follows and 404s on. De-linked to plain text instead of
#: guessing a route or a GitHub URL that may not exist (repoUrl can be unset).
_RELATIVE_MD_LINK = re.compile(r"\[([^\]]+)\]\((?!https?://|mailto:|#)[^)]+\)")


def md(text: str | None) -> str:
    if not text:
        return ""
    text = _RELATIVE_MD_LINK.sub(r"\1", text.strip())
    return _md.markdown(text, extensions=MD_EXT)


# --------------------------------------------------------------- redaction

_SECRET_PATTERNS = [
    re.compile(p) for p in (
        r"sk-[A-Za-z0-9]{16,}",
        r"pk_[A-Za-z0-9]{16,}",
        r"PK[A-Z0-9]{16,}",           # Alpaca paper key id shape
        r"AKIA[A-Z0-9]{12,}",
        r"ghp_[A-Za-z0-9]{20,}",
        r"xox[baprs]-[A-Za-z0-9-]{10,}",
        r"Bearer\s+[A-Za-z0-9._-]{10,}",
        r"(?i)(?:api[_-]?key|secret|token|password)\W{0,3}[:=]\W{0,3}[A-Za-z0-9/+_.-]{12,}",
    )
]


def _load_env_secrets(root: Path) -> list[str]:
    """Literal values from `.env`, so a leaked key is caught even if it
    doesn't match a known shape. Never logs the values themselves."""
    env_path = root / ".env"
    if not env_path.exists():
        return []
    out = []
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        _, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if len(value) >= 8 and value.lower() not in ("true", "false"):
            out.append(value)
    return out


def _walk_strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk_strings(v)


def redaction_scan(snapshot: dict[str, Any], root: Path) -> list[str]:
    """Every match found, as short human-readable locations. Empty = clean."""
    secrets = _load_env_secrets(root)
    hits: list[str] = []
    for s in _walk_strings(snapshot):
        if not s:
            continue
        for pat in _SECRET_PATTERNS:
            if pat.search(s):
                hits.append(f"pattern {pat.pattern!r} matched in a string starting {s[:24]!r}")
        for secret in secrets:
            if secret in s:
                hits.append("a literal .env value appears in an exported string")
    return hits


# --------------------------------------------------------------- prose guard

def clean_prose(text: str | None) -> str | None:
    """None if `text` looks like a base64 blob rather than written prose.

    Observed live: 1 of 84 `no_op.summary` rows is a thinking-signature blob
    with no whitespace and no sentence structure. Publishing it as "the
    agent's reasoning" would be worse than omitting the row.
    """
    if not text or not isinstance(text, str):
        return None
    head = text.strip()
    if not head:
        return None
    if " " not in head[:80] and "\n" not in head[:80]:
        return None
    sample = head[:200]
    b64_chars = sum(1 for c in sample if c.isalnum() or c in "+/=")
    if len(sample) > 40 and b64_chars / len(sample) > 0.85 and " " not in sample:
        return None
    if head[0] not in "#*-ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789\"'([":
        return None
    return text


# --------------------------------------------------------------- git / meta

def _git(args: list[str]) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:
        return ""


def _git_meta() -> dict[str, Any]:
    sha = _git(["rev-parse", "HEAD"])
    dirty = bool(_git(["status", "--porcelain"]))
    return {"git_sha": sha, "git_dirty": dirty}


# --------------------------------------------------------------- payoff

def derive_payoff(pos: Position) -> dict[str, Any]:
    """Payoff at expiry, derived from the RECORDED legs and max_loss_usd.

    No price is stored per leg, so the net entry cost is solved for
    algebraically rather than guessed: the structure's raw (zero-cost)
    intrinsic value at its worst terminal price, plus the recorded
    `max_loss_usd`, pins the one unknown constant exactly - for any defined
    risk structure the allocation of that constant across legs doesn't
    matter, because `entry_cost` only ever uses the sum. Refuses rather than
    approximates: a calendar (mixed expiries), an unparseable leg, or an
    unbounded raw loss all come back `derivable: false` with a stated reason.
    """
    empty = {"derivable": False, "reason": "no legs recorded"}
    if not pos.legs:
        return empty
    parsed = [optmath.Leg.from_position_leg(d) for d in pos.legs]
    if any(leg is None for leg in parsed):
        return {"derivable": False, "reason": "a leg's option symbol did not parse"}
    legs: list[optmath.Leg] = parsed  # type: ignore[assignment]
    try:
        optmath.require_single_expiry(legs)
    except optmath.MultiExpiryError:
        return {
            "derivable": False,
            "reason": "legs span more than one expiry (a calendar) - refused by "
                      "design, the same reason the agent itself refuses to price one",
        }
    if pos.max_loss_usd is None:
        return {"derivable": False, "reason": "no recorded max loss to anchor the entry cost"}

    # `max_profit_loss` returns SIGNED bounds on pnl(S) itself (min_S pnl(S)
    # for the second element) - not a positive "loss magnitude". With every
    # leg priced at 0, pnl(S) IS the raw combined intrinsic value, so this is
    # min_S(raw(S)), still signed (0 for a spread that can never lose money
    # before paying for it, very negative for a naked short).
    _, raw_min_pnl = optmath.max_profit_loss(legs)  # legs still have price=0.0
    if raw_min_pnl is None:
        return {"derivable": False, "reason": "the structure's loss is unbounded"}

    # True min_S pnl(S) = min_S raw(S) - entry_cost, and by definition that
    # equals -max_loss_usd (the recorded loss magnitude, always >= 0):
    #   raw_min_pnl - entry_cost = -max_loss_usd  =>  entry_cost = raw_min_pnl + max_loss_usd
    entry_cost = raw_min_pnl + pos.max_loss_usd
    leg0 = legs[0]
    # Put the whole (possibly negative, for a net credit) cost on one leg.
    # `entry_cost()` only ever sums `sign*price*qty*100` across legs, so the
    # split doesn't matter - only the total does.
    price0 = entry_cost / (leg0.sign * leg0.qty * optmath.CONTRACT_MULTIPLIER)
    priced_leg0 = optmath.Leg(
        right=leg0.right, strike=leg0.strike, side=leg0.side, qty=leg0.qty,
        price=price0, expiry=leg0.expiry, iv=leg0.iv,
    )
    priced_legs = [priced_leg0, *legs[1:]]

    max_profit, max_loss = optmath.max_profit_loss(priced_legs)
    if max_loss is None or abs(-max_loss - pos.max_loss_usd) > 1.0:
        return {
            "derivable": False,
            "reason": "the derived payoff didn't reconcile with the recorded max "
                      "loss - flagged rather than shown as fact",
        }

    strikes = sorted({leg.strike for leg in legs})
    lo, hi = strikes[0] * 0.85, strikes[-1] * 1.15
    n = 160
    points = []
    seen_x = set()
    xs = sorted({round(lo + (hi - lo) * i / n, 4) for i in range(n + 1)} | set(strikes))
    for x in xs:
        if x in seen_x or x <= 0:
            continue
        seen_x.add(x)
        points.append([round(x, 2), round(optmath.pnl_at(priced_legs, x), 2)])

    breakevens = optmath.breakevens(priced_legs)
    return {
        "derivable": True,
        "net_cost": round(entry_cost, 2),
        "is_debit": entry_cost >= 0,
        "max_profit": round(max_profit, 2) if max_profit is not None else None,
        "max_profit_unbounded": max_profit is None,
        "max_loss": round(abs(max_loss), 2),
        "breakevens": breakevens,
        "points": points,
        "strikes": strikes,
    }


# --------------------------------------------------------------- positions

def export_position(pos: Position, blog_text: str | None) -> dict[str, Any]:
    legs = [
        {**leg, "parsed": optmath.parse_occ(leg.get("symbol", ""))}
        for leg in pos.legs
    ]
    payoff = derive_payoff(pos)
    attribution_label = {
        THESIS_RIGHT_EXPRESSION_RIGHT: "view right, structure right",
        THESIS_RIGHT_EXPRESSION_WRONG: "view right, structure wrong",
        THESIS_WRONG_EXPRESSION_FAITHFUL: "view wrong, structure faithful",
        THESIS_WRONG_PROFITED_ANYWAY: "view wrong, profited anyway (luck)",
        UNSCOREABLE: "unscoreable",
    }.get(pos.attribution, "")
    return {
        "id": pos.position_id,
        "underlying": pos.underlying,
        "strategy": pos.strategy,
        "status": pos.status,
        "opened": pos.opened,
        "expiry": pos.expiry,
        "close_reason": pos.close_reason,
        "max_loss_usd": pos.max_loss_usd,
        "last_pnl_pct": pos.last_pnl_pct,
        "entry_spot": pos.entry_spot,
        "entry_iv": pos.entry_iv,
        "greeks_at_entry": pos.greeks_at_entry,
        "decision_ref": pos.decision_ref,
        "provenance": pos.provenance,
        "generated_by": pos.generated_by,
        "legs": legs,
        "exit_rules": pos.exit_rules,
        "exit_state": pos.exit_state,
        "sources": pos.sources,
        "thesis": {
            "claim": pos.thesis_claim or pos.thesis,
            "horizon": pos.thesis_horizon,
            "band_low": pos.thesis_band_low,
            "band_high": pos.thesis_band_high,
            "drift": pos.thesis_drift,
            "vol_view": pos.thesis_vol_view,
        },
        "attribution": pos.attribution,
        "attribution_label": attribution_label,
        "payoff": payoff,
        "story_html": md(blog_text) if blog_text else "",
        "wiki_path": f"data/wiki/positions/{pos.position_id}.md",
        "blog_path": f"data/blog/{pos.position_id}.md" if blog_text is not None else None,
    }


# --------------------------------------------------------------- ledger stream

def _strip_leading_h1(text: str) -> str:
    """Drop a document's own opening `# Title` line.

    Every page that calls this already shows the same title as a styled
    Svelte `<h1>` above the rendered body - trade pages, dev journals - so
    without this the title renders TWICE, once styled and once as plain
    markdown prose immediately below it.
    """
    lines = text.split("\n")
    out, skipped = [], False
    for line in lines:
        if not skipped and line.startswith("# "):
            skipped = True
            continue
        out.append(line)
    return "\n".join(out)


def _strip_blog_header(body: str) -> str:
    """`_strip_leading_h1` plus the "Opened **...** - max loss ..." line
    `blog.write_entry` always writes right after its title - also already
    shown as styled chips on the trade page."""
    lines = _strip_leading_h1(body).split("\n")
    out, skipped_opened = [], False
    for line in lines:
        if not skipped_opened and line.startswith("Opened **"):
            skipped_opened = True
            continue
        out.append(line)
    return "\n".join(out).strip()


def _frontmatter_body(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    try:
        _, fm, body = text.split("---", 2)
        return (yaml.safe_load(fm) or {}), body.strip()
    except ValueError:
        return {}, text


def build_ledger_items(
    journal_rows: list[dict[str, Any]],
    theses: list[Any],
    positions_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """The merged, newest-first decision stream (README/the brief's central
    index). Returns (items, summaries_dropped)."""
    items: list[dict[str, Any]] = []
    dropped = 0

    # Theses first, so their position_ids are known before the execution
    # rows are scanned - a traded position already represented by its own
    # thesis row (the richer of the two: it carries the actual claim) must
    # not ALSO appear as a bare "position opened" row from the execution
    # journal entry. Only positions with no ledger thesis (the two that
    # predate D-052) rely on the execution row to appear at all.
    traded_position_ids: set[str] = set()
    for t in theses:
        title = f"{t.underlying} - {t.claim}"[:140]
        kind = "traded" if t.traded else ("rejected" if t.rejected_by else "thesis")
        if t.traded and t.position_id:
            traded_position_ids.add(t.position_id)
        items.append({
            "ts": t.created, "kind": kind, "tick": None, "model": None,
            "tool_calls": [], "title": title,
            "body_html": md(t.claim),
            "position_id": t.position_id,
            "meta": {
                "probability": t.probability, "horizon": t.horizon,
                "band_low": t.band_low, "band_high": t.band_high,
                "outcome": t.outcome, "rejected_by": t.rejected_by,
                "metric": t.metric, "probability_stated": t.probability_stated,
            },
        })

    for r in journal_rows:
        if r.get("kind") == "no_op":
            summary = clean_prose(r.get("summary"))
            if summary is None:
                if r.get("summary"):
                    dropped += 1
                continue
            items.append({
                "ts": r["ts"], "kind": "declined", "tick": r.get("tick"),
                "model": r.get("model"), "tool_calls": r.get("tool_calls") or [],
                "title": "Declined - no action taken", "body_html": md(summary),
                "position_id": None,
            })
        elif r.get("kind") == "execution":
            match = next((p for p in positions_by_id.values()
                          if p.get("decision_ref") == r.get("decision_ref")), None)
            if not match or match["id"] in traded_position_ids:
                # No recorded position to link to (an order replace, a close,
                # or an attempt that never became a position), or already
                # represented by its own thesis row, above - either way there
                # is nothing here for a reader to click through to.
                continue
            items.append({
                "ts": r["ts"], "kind": "traded", "tick": r.get("tick"),
                "model": r.get("model"), "tool_calls": r.get("tool_calls") or [],
                "title": f"Opened {match['underlying']} {match['strategy']}".replace("_", " "),
                "body_html": "",
                "position_id": match["id"],
            })

    for r in journal_rows:
        if r.get("kind") == "forecast_resolved":
            items.append({
                "ts": r["ts"], "kind": "forecast_resolved", "tick": None, "model": None,
                "tool_calls": [],
                "title": f"{r.get('underlying', '?')} forecast resolved "
                         f"{'held' if r.get('held') else 'failed'}",
                "body_html": "",
                "position_id": None,
                "meta": {
                    "stated": r.get("stated"), "held": r.get("held"),
                    "traded": r.get("traded"),
                    "price_at_horizon": r.get("price_at_horizon"),
                },
            })

    items.sort(key=lambda x: x["ts"], reverse=True)
    return items, dropped


# --------------------------------------------------------------- notes / journals

_NOTE_DIRS = {
    "technique": ("Technique", "data/wiki/technique"),
    "research": ("Company dossier", "data/wiki/research"),
}


def build_notes(wiki_dir: Path) -> list[dict[str, Any]]:
    out = []
    for kind, (label, rel) in _NOTE_DIRS.items():
        d = wiki_dir / kind
        if not d.exists():
            continue
        for p in sorted(d.glob("*.md")):
            fm, body = _frontmatter_body(p)
            # These files' own first heading is a SECTION label ("# Rule",
            # "# What it is"), not a title - every technique note starts
            # "# Rule" and every dossier starts "# What it is". The filename
            # is the real title: the ticker as-is for a dossier, the
            # hyphenated phrase turned into a sentence for a technique note.
            title = p.stem if kind == "research" else p.stem.replace("-", " ").capitalize()
            out.append({
                "slug": f"{kind}-{p.stem}", "kind": kind, "kind_label": label,
                "type": fm.get("type", ""), "title": title,
                "html": md(body), "source_path": f"{rel}/{p.name}",
            })
    for name, label in (("lessons.md", "Lessons"), ("log.md", "Log")):
        p = wiki_dir / name
        if p.exists():
            fm, body = _frontmatter_body(p)
            out.append({
                "slug": f"wiki-{p.stem}", "kind": "wiki", "kind_label": label,
                "type": fm.get("type", ""), "title": label,
                "html": md(body), "source_path": f"data/wiki/{name}",
            })
    regime = wiki_dir / "context" / "regime.md"
    if regime.exists():
        fm, body = _frontmatter_body(regime)
        out.append({
            "slug": "context-regime", "kind": "context", "kind_label": "Market context",
            "type": fm.get("type", ""), "title": "Regime",
            "html": md(body), "source_path": "data/wiki/context/regime.md",
        })
    return out


def build_journals(dev_journals_dir: Path) -> list[dict[str, Any]]:
    out = []
    for p in sorted(dev_journals_dir.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else p.stem
        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", p.stem)
        paras = [ln for ln in text.split("\n\n") if ln.strip() and not ln.startswith("#")]
        standfirst = re.sub(r"\s+", " ", paras[0]).strip()[:280] if paras else ""
        out.append({
            "slug": p.stem, "date": date_match.group(1) if date_match else "",
            "title": title, "standfirst": standfirst, "html": md(_strip_leading_h1(text)),
            "source_path": f"docs/dev_journals/{p.name}",
        })
    out.sort(key=lambda j: j["slug"], reverse=True)
    return out


# --------------------------------------------------------------- decisions/issues

def build_decisions_index(decisions_path: Path) -> list[dict[str, Any]]:
    if not decisions_path.exists():
        return []
    text = decisions_path.read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r"^## (D-\d+)(?: - |: )(.+)$", text, re.MULTILINE):
        did, title = m.group(1), m.group(2).strip()
        tail = text[m.end():m.end() + 400]
        date_m = re.search(r"\*\*Date:\*\*\s*(\S+)", tail)
        status_m = re.search(r"\*\*Status:\*\*\s*(\w+)", tail)
        out.append({
            "id": did, "title": title,
            "date": date_m.group(1) if date_m else "",
            "status": status_m.group(1) if status_m else "",
        })
    return out


def build_open_issues(issues_path: Path) -> str:
    if not issues_path.exists():
        return ""
    text = issues_path.read_text(encoding="utf-8")
    m = re.search(r"^## Open\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return md(m.group(1)) if m else ""


# --------------------------------------------------------------- gauges / calibration

def build_calibration(cfg) -> dict[str, Any]:
    fstore = CalibrationStore(cfg.paths.state / "forecasts.jsonl")
    book = ledger_mod.Ledger(cfg.paths.state / "ledger.jsonl")
    cal = fstore.score(ledger_mod.as_forecasts(book.resolved()))
    return {
        "n": cal.n, "brier": cal.brier, "reliability": cal.reliability,
        "resolution": cal.resolution, "uncertainty": cal.uncertainty,
        "base_rate": cal.base_rate, "n_eff": cal.n_eff,
        "concentration": cal.concentration, "sample_note": cal.sample_note(),
        "verdict": cal.verdict(),
    }


def build_attribution(positions: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        THESIS_RIGHT_EXPRESSION_RIGHT: 0, THESIS_RIGHT_EXPRESSION_WRONG: 0,
        THESIS_WRONG_EXPRESSION_FAITHFUL: 0, THESIS_WRONG_PROFITED_ANYWAY: 0,
        UNSCOREABLE: 0, "": 0,
    }
    for p in positions:
        counts[p.get("attribution", "")] = counts.get(p.get("attribution", ""), 0) + 1
    return {
        "held_profit": counts[THESIS_RIGHT_EXPRESSION_RIGHT],
        "held_loss": counts[THESIS_RIGHT_EXPRESSION_WRONG],
        "failed_loss": counts[THESIS_WRONG_EXPRESSION_FAITHFUL],
        "failed_profit": counts[THESIS_WRONG_PROFITED_ANYWAY],
        "unscoreable": counts[UNSCOREABLE],
        "unattributed": counts[""],
        "total": len(positions),
    }


# --------------------------------------------------------------- monotonicity

def _check_monotonic(prev_path: Path, counts: dict[str, int]) -> str | None:
    if not prev_path.exists():
        return None
    try:
        prev = json.loads(prev_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    prev_counts = prev.get("counts") or {}
    for key in ("positions", "journal_rows", "theses"):
        if key in prev_counts and counts.get(key, 0) < prev_counts[key]:
            return (f"{key} shrank from {prev_counts[key]} to {counts.get(key, 0)} "
                    f"versus the last snapshot - refusing to publish a smaller record")
    return None


# --------------------------------------------------------------- main export

def export(out: Path = DEFAULT_OUT, *, strict: bool = True) -> int:
    cfg = config_mod.load()
    cfg.paths.ensure()

    journal_rows = list(Journal(cfg.paths.journal).read())
    pos_store = PositionStore(cfg.paths.wiki)
    positions_raw = pos_store.all()

    book = ledger_mod.Ledger(cfg.paths.state / "ledger.jsonl")
    theses = book.all()

    blog_dir = cfg.paths.blog
    positions = []
    for pos in sorted(positions_raw, key=lambda p: p.opened, reverse=True):
        blog_path = blog_dir / f"{pos.position_id}.md"
        blog_body = _strip_blog_header(_frontmatter_body(blog_path)[1]) if blog_path.exists() else None
        positions.append(export_position(pos, blog_body))
    positions_by_id = {p["id"]: p for p in positions}

    ledger_items, summaries_dropped = build_ledger_items(journal_rows, theses, positions_by_id)

    comp_rows = [r for r in journal_rows if r.get("kind") == "competence"]
    book_rows = [r for r in journal_rows if r.get("kind") == "book_risk"]
    latest_comp = comp_rows[-1] if comp_rows else {}
    latest_book = book_rows[-1] if book_rows else {}

    equity = latest_comp.get("equity")
    high_water = latest_comp.get("high_water")
    pnl_usd = (equity - REQUIRED_START_EQUITY) if equity is not None else None
    pnl_pct = (pnl_usd / REQUIRED_START_EQUITY) if pnl_usd is not None else None

    forecasts_resolved = [
        r for r in journal_rows if r.get("kind") == "forecast_resolved"
    ]

    tick_path = cfg.paths.state / "tick_count"
    tick = int(tick_path.read_text().strip()) if tick_path.exists() else None

    open_positions = sum(1 for p in positions if p.get("status") == "open")
    traded = sum(1 for t in theses if t.traded)
    declined = sum(1 for it in ledger_items if it["kind"] == "declined")

    counts = {
        "positions": len(positions),
        "positions_open": open_positions,
        "traded": traded,
        "declined": declined,
        "theses": len(theses),
        "forecasts_resolved": len(forecasts_resolved),
        "ticks": tick or 0,
        "journal_rows": len(journal_rows),
        "notes": None,  # filled below
        "journals": None,
        "decisions_logged": None,
    }

    notes = build_notes(cfg.paths.wiki)
    journals = build_journals(ROOT / "docs" / "dev_journals")
    decisions_index = build_decisions_index(ROOT / "specs" / "decisions.md")
    counts["notes"] = len(notes)
    counts["journals"] = len(journals)
    counts["decisions_logged"] = len(decisions_index)

    mono_error = _check_monotonic(out, counts)
    if mono_error:
        print(f"[site_export] REFUSED: {mono_error}", file=sys.stderr)
        return 1

    run_started = journal_rows[0]["ts"] if journal_rows else None

    snapshot: dict[str, Any] = {
        "generated_at": None,  # stamped just before write
        "tick": tick,
        **_git_meta(),
        "run_started": run_started,

        "account": {
            "equity": equity, "start": REQUIRED_START_EQUITY,
            "start_note": "hackathon rule - required starting balance, not measured",
            "pnl_usd": pnl_usd, "pnl_pct": pnl_pct,
            "high_water": high_water,
            "drawdown": latest_comp.get("drawdown"),
            "as_of": latest_comp.get("ts"),
        },
        "competence": {
            "tier": latest_comp.get("tier"), "resolved": latest_comp.get("resolved"),
            "reliability": latest_comp.get("reliability"),
            "attributable_rate": latest_comp.get("attributable_rate"),
            # APPLIED, not earned. These three carry the operator's risk
            # appetite (D-099), so at 0.50 the site would show a 10% book cap
            # for an agent that earned 20% - a ladder appearing to demote with
            # no drawdown and no tier change. The appetite ships beside them so
            # the page can say which number it is showing.
            "kelly_multiplier": latest_comp.get("kelly_multiplier"),
            "seed_fraction": latest_comp.get("seed_fraction"),
            "book_cap": latest_comp.get("book_cap"),
            "appetite": latest_comp.get("appetite"),
            "realised_appetite": latest_comp.get("realised_appetite"),
            "as_of": latest_comp.get("ts"),
        },
        "book": {
            "positions": latest_book.get("positions"),
            "delta_dollars": latest_book.get("delta_dollars"),
            "beta_weighted_delta": latest_book.get("beta_weighted_delta"),
            "vega_dollars": latest_book.get("vega_dollars"),
            "theta_dollars": latest_book.get("theta_dollars"),
            "pct_equity_per_1pct_spy": latest_book.get("pct_equity_per_1pct_spy"),
            "as_of": latest_book.get("ts"),
        },
        "calibration": build_calibration(cfg),
        "attribution": build_attribution(positions),
        "equity_curve": [
            {"ts": r["ts"], "equity": r.get("equity"), "high_water": r.get("high_water")}
            for r in comp_rows
        ],

        "positions": positions,
        "ledger_items": ledger_items,
        "forecasts_resolved": [
            {
                "ts": r["ts"], "underlying": r.get("underlying"),
                "stated": r.get("stated"), "held": r.get("held"),
                "traded": r.get("traded"), "price_at_horizon": r.get("price_at_horizon"),
            }
            for r in forecasts_resolved
        ],
        "notes": notes,
        "journals": journals,
        "docs": {
            "submission_html": md((ROOT / "SUBMISSION.md").read_text(encoding="utf-8"))
                                if (ROOT / "SUBMISSION.md").exists() else "",
            "readme_html": md((ROOT / "README.md").read_text(encoding="utf-8"))
                           if (ROOT / "README.md").exists() else "",
            "open_issues_html": build_open_issues(ROOT / "specs" / "issues.md"),
            "decisions_index": decisions_index,
        },
        "counts": counts,
        "integrity": {
            "summaries_dropped": summaries_dropped,
        },
    }

    from .ids import utc_now
    snapshot["generated_at"] = utc_now().isoformat()

    hits = redaction_scan(snapshot, ROOT)
    if hits:
        print("[site_export] REFUSED - possible secret(s) in export:", file=sys.stderr)
        for h in hits[:10]:
            print(f"  - {h}", file=sys.stderr)
        return 1
    snapshot["integrity"]["redaction_scan"] = "clean"
    snapshot["integrity"]["patterns_checked"] = len(_SECRET_PATTERNS)

    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(snapshot, indent=None, separators=(",", ":"), default=str)
    out.write_text(text, encoding="utf-8")
    print(f"[site_export] wrote {out} ({len(text):,} bytes) - "
          f"{counts['positions']} positions, {counts['theses']} theses, "
          f"{counts['journal_rows']} journal rows, {summaries_dropped} summaries dropped")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="trdrbot site export")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)
    return export(out=args.out)


if __name__ == "__main__":
    raise SystemExit(main())

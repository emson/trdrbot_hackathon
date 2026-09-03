"""The human's steering surface - one self-contained HTML page (D-088).

The Coach acts without asking. That trade is only honest if what it did is
easy to see afterwards, so this renders the gauge time-series with the Coach's
own actions overlaid as markers: "survival rose after promotion v0 -> v3" as a
picture rather than a claim.

Steering is by editing state, never by approving an action - so the page tells
you where the levers live and what pausing one does, and then gets out of the
way.

Self-contained by construction: inline CSS, inline SVG, no external request of
any kind. A report that needs the network is a report that is blank exactly
when something has gone wrong.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from . import coach, ids, store

W, H, PAD = 260, 48, 4


def _spark(points: list[float]) -> str:
    """A sparkline as inline SVG. Flat or single-point series render as a line
    rather than dividing by a zero range."""
    if not points:
        return '<span class="dim">no data</span>'
    if len(points) == 1:
        points = points * 2
    lo, hi = min(points), max(points)
    span = (hi - lo) or 1.0
    step = (W - 2 * PAD) / (len(points) - 1)
    coords = " ".join(
        f"{PAD + i * step:.1f},{H - PAD - (v - lo) / span * (H - 2 * PAD):.1f}"
        for i, v in enumerate(points))
    return (f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" class="spark">'
            f'<polyline points="{coords}"/></svg>')


def _num(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    return html.escape(str(v))


def _rows(path: Path) -> list[dict[str, Any]]:
    """The seventh JSONL reader, now the same one as the other six (D-091)."""
    return store.read_jsonl(path)[0]


def build(cfg: Any) -> str:
    metrics = _rows(coach.metrics_path(cfg))
    evs = coach.events(cfg)
    snaps = [r for r in metrics if r.get("kind") == "snapshot"]
    marks = [r for r in metrics if r.get("kind") == "marker"]

    series: dict[str, list[float]] = {}
    for s in snaps:
        for k, v in (s.get("gauges") or {}).items():
            if isinstance(v, (int, float)):
                series.setdefault(k, []).append(float(v))

    opened = [r for r in evs if r.get("kind") == "experiment_opened"]
    closed = [r for r in evs if r.get("kind") == "experiment_closed"]
    fired = [r for r in evs if r.get("kind") == "sentinel_fired"]
    promotions = [r for r in closed if r.get("outcome") == "promoted"]
    closed_ids = {r.get("exp_id") for r in closed}
    open_now = [r for r in opened if r.get("exp_id") not in closed_ids]

    p: list[str] = []
    add = p.append
    add("<title>trdrbot - the Coach</title>")
    add("""<style>
:root{--bg:#fbfaf8;--fg:#1c1b19;--dim:#78716c;--line:#e7e2dc;--card:#fff;
--good:#15803d;--bad:#b91c1c;--warn:#b45309;--accent:#3730a3}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#16151a;
--fg:#eae8e4;--dim:#a1998f;--line:#2e2b32;--card:#1e1d23;--good:#4ade80;
--bad:#f87171;--warn:#fbbf24;--accent:#a5b4fc}}
:root[data-theme=dark]{--bg:#16151a;--fg:#eae8e4;--dim:#a1998f;--line:#2e2b32;
--card:#1e1d23;--good:#4ade80;--bad:#f87171;--warn:#fbbf24;--accent:#a5b4fc}
body{background:var(--bg);color:var(--fg);font:15px/1.55 ui-sans-serif,-apple-system,
"Segoe UI",system-ui,sans-serif;margin:0;padding:2rem 1.25rem;max-width:60rem;
margin-inline:auto}
h1{font-size:1.45rem;margin:0 0 .2rem}h2{font-size:1.05rem;margin:2rem 0 .6rem;
letter-spacing:.02em;text-transform:uppercase;color:var(--dim);font-weight:600}
.sub{color:var(--dim);margin:0 0 1.5rem;font-size:.9rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:.85rem 1rem;margin-bottom:.6rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(17rem,1fr));gap:.6rem}
.g-name{font-size:.8rem;color:var(--dim);font-family:ui-monospace,monospace}
.g-val{font-size:1.5rem;font-weight:600;line-height:1.1}
.spark{width:100%;height:48px;margin-top:.4rem;overflow:visible}
.spark polyline{fill:none;stroke:var(--accent);stroke-width:1.6;
vector-effect:non-scaling-stroke}
table{border-collapse:collapse;width:100%;font-size:.88rem}
th,td{text-align:left;padding:.42rem .6rem;border-bottom:1px solid var(--line);
vertical-align:top}
th{color:var(--dim);font-weight:600;font-size:.78rem;text-transform:uppercase}
code{font-family:ui-monospace,monospace;font-size:.85em}
.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.dim{color:var(--dim)}.wrap{overflow-x:auto}
.empty{color:var(--dim);font-style:italic;padding:.5rem 0}
</style>""")
    add("<h1>The Coach</h1>")
    add(f'<p class="sub">Autonomous subsystem improvement. Generated '
        f'{html.escape(ids.utc_now().isoformat(timespec="seconds"))}. '
        f'{len(snaps)} snapshot(s), {len(opened)} experiment(s), '
        f'{len(promotions)} promotion(s).</p>')

    # --- what changed ---------------------------------------------------
    add("<h2>What changed</h2>")
    recent = sorted(promotions + [r for r in closed if r.get("outcome") != "promoted"]
                    + fired, key=lambda r: str(r.get("ts", "")), reverse=True)[:12]
    if not recent:
        add('<p class="empty">Nothing yet. The Coach opens its first experiment '
            'once the muse has run and the mutation cooldown has elapsed.</p>')
    else:
        add('<div class="wrap"><table><tr><th>when</th><th>what</th><th>detail</th></tr>')
        for r in recent:
            if r.get("kind") == "sentinel_fired":
                what = f'<span class="warn">sentinel {html.escape(str(r.get("sentinel")))}</span>'
                detail = (f'{_num(r.get("value"))} against a limit of '
                          f'{_num(r.get("limit"))} - {html.escape(str(r.get("meaning", "")))}')
            else:
                out = str(r.get("outcome", ""))
                cls = "good" if out == "promoted" else "dim"
                what = (f'<span class="{cls}">{html.escape(out)}</span> '
                        f'<code>{html.escape(str(r.get("lever", "")))}</code>')
                detail = html.escape(str(r.get("reason", ""))[:220])
            add(f'<tr><td class="dim">{html.escape(str(r.get("ts", ""))[:16])}</td>'
                f'<td>{what}</td><td>{detail}</td></tr>')
        add("</table></div>")

    # --- open experiments ------------------------------------------------
    add("<h2>Open experiments</h2>")
    if not open_now:
        add('<p class="empty">None open. This is a normal resting state - the '
            'incumbent runs unchallenged until the next challenger is generated.</p>')
    for r in open_now:
        t = coach.tally(cfg, str(r.get("exp_id")))
        fl = r.get("floors") or {}
        if not t:
            continue
        need_runs = max(0, int(fl.get("min_runs", coach.MIN_RUNS)) - t.runs)
        need_c = max(0, int(fl.get("min_candidates", coach.MIN_CANDIDATES)) - min(t.n_i, t.n_c))
        add(f'<div class="card"><b><code>{html.escape(t.lever)}</code></b>: '
            f'<code>{html.escape(t.challenger)}</code> challenging '
            f'<code>{html.escape(t.incumbent)}</code><br>'
            f'<span class="dim">P(challenger better)</span> '
            f'<b>{t.posterior:.3f}</b> after {t.runs} paired run(s) - '
            f'challenger {t.s_c}/{t.n_c}, incumbent {t.s_i}/{t.n_i}'
            f'{f", {t.voided} voided" if t.voided else ""}<br>'
            f'<span class="dim">needs {need_runs} more run(s), {need_c} more '
            f'candidate(s), and P &ge; {fl.get("promote_at", coach.PROMOTE_AT)} '
            f'to promote</span></div>')

    # --- gauges ----------------------------------------------------------
    add("<h2>Gauges</h2>")
    # What to read first, and in what order. Without this the panel is a wall of
    # equally-weighted numbers, and a reader steering the system has no way to
    # know which one improvement is FOR. One north star, few guardrails: each
    # extra guardrail measurably inflates false alarms, so the list stops at
    # three deliberately (notes/023).
    add('<p class="sub"><strong>North star:</strong> <code>calibration.brier</code> '
        'with its sample count - the one number improvement is for, because a '
        'lucky week cannot move it and a well-calibrated view can. '
        '<strong>Guardrails</strong> (must not degrade, both directions): '
        '<code>sizing.refused_rate</code> and <code>exit.uncorroborated_decisives</code> '
        '(rule compliance - a seam losing the conditional payoff, or a stop firing on '
        'quote noise), the trade/decline balance behind '
        '<code>attribution.attributable_rate</code> (always-trading and never-trading '
        'are both drift, and this book has measured both), and '
        '<code>coach.cost_usd_today</code> with <code>model.cal_age_days</code> '
        '(cost and staleness). Everything else here is diagnostic.</p>')
    if not series:
        add('<p class="empty">No snapshots yet.</p>')
    else:
        add('<div class="grid">')
        for name in sorted(series):
            vals = series[name]
            add(f'<div class="card"><div class="g-name">{html.escape(name)}</div>'
                f'<div class="g-val">{_num(vals[-1])}</div>'
                f'{_spark(vals)}'
                f'<div class="g-name">min {_num(min(vals))} / max {_num(max(vals))} '
                f'/ n={len(vals)}</div></div>')
        add("</div>")

    if marks:
        add('<p class="sub">Coach actions on the same series: '
            + ", ".join(
                f'<code>{html.escape(str(m.get("label")))}</code> '
                f'{html.escape(str(m.get("detail", m.get("sentinel", ""))))} '
                f'({html.escape(str(m.get("ts", ""))[:10])})'
                for m in marks[-8:]) + "</p>")

    # --- levers ----------------------------------------------------------
    add("<h2>Levers and how to steer</h2>")
    add('<div class="wrap"><table><tr><th>lever</th><th>incumbent</th>'
        '<th>since</th><th>state</th></tr>')
    for lv in coach.LEVERS:
        st = coach.load_state(cfg, lv.name, "")
        flag = st.blocked or "running"
        cls = "warn" if st.blocked else "good"
        add(f'<tr><td><code>{html.escape(lv.name)}</code></td>'
            f'<td><code>{html.escape(st.incumbent.id)}</code> '
            f'<span class="dim">{html.escape(st.incumbent.fingerprint)}</span></td>'
            f'<td class="dim">{html.escape(str(st.incumbent.since)[:16] or "seed")}</td>'
            f'<td class="{cls}">{html.escape(flag)}</td></tr>')
    add("</table></div>")
    add('<p class="sub">Variants live in <code>data/state/levers/*.json</code>. '
        'Set <code>"paused": true</code> to stop experimenting on a lever - it '
        'closes any open experiment and freezes the incumbent, which is how you '
        'hold behaviour still for a demo. '
        'Editing the incumbent text by hand is supported; the fingerprint is '
        'recomputed from the text on load. Nothing here can reach code, gate '
        'thresholds, sizing, or the constitution.</p>')
    return "\n".join(p)


def write(cfg: Any, path: Path | None = None) -> Path:
    out = path or (Path(cfg.paths.data) / "report.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(cfg), encoding="utf-8")
    return out

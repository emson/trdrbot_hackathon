// Pure view-model helpers for /demo (notes/028). No DOM, no fetch, no clock -
// every function here is deterministic given its arguments, which is what
// makes the page's own build deterministic and this file node-testable
// without a browser (see scripts/demo.test.mjs).

/** `dec_abc123` -> `#cycle-dec_abc123`. The URL hash is the demo's only
 * client-side state that survives a reload or a shared link. */
export function hashFor(cycle) {
	return cycle ? `#cycle-${cycle.id}` : '';
}

/** Which cycle a `location.hash` names, or the latest (`cycles[0]`) when the
 * hash is empty, unrecognised, or names a cycle that fell out of the reel
 * since the link was shared - never an error, always a cycle if one exists. */
export function selectCycle(cycles, hash) {
	if (!cycles || !cycles.length) return null;
	const id = (hash || '').replace(/^#cycle-/, '');
	return cycles.find((c) => c.id === id) || cycles[0];
}

/** The thesis a cycle's Think frame opens on: the one that got traded, else
 * the one with structures priced for it, else the first recorded. */
export function defaultThesis(cycle) {
	const theses = cycle?.think?.theses || [];
	if (!theses.length) return null;
	return (
		theses.find((t) => t.position_id) ||
		theses.find((t) => t.candidates_ref) ||
		theses[0]
	);
}

/** The candidate row a Think frame's payoff opens on: the one actually
 * chosen (traded or sized), else the first survivor, else the first row. */
export function defaultCandidateRow(rows) {
	if (!rows || !rows.length) return null;
	return rows.find((r) => r.chosen) || rows.find((r) => r.fate === 'candidate') || rows[0];
}

/** The candidate block belonging to a given thesis entry id, or null. */
export function candidatesFor(cycle, entryId) {
	return (cycle?.think?.candidates || []).find((c) => c.entry_id === entryId) || null;
}

const FRAME_HEADING = {
	traded: 'What it did, and how big.',
	acted: 'What it did.',
	declined: 'Why it did nothing.',
	error: 'What went wrong.'
};

/** Act frame's heading, keyed off the cycle's own recorded outcome - never a
 * guess about what "should" have happened. */
export function frameHeading(outcome) {
	return FRAME_HEADING[outcome] || 'What happened.';
}

/** Calendar days between two ISO dates, computed from `generatedAt` (the
 * snapshot's own stamp) rather than the viewer's clock, so the build stays
 * deterministic and a horizon does not silently change day-count between a
 * publish and someone reading it hours later. Negative once the horizon has
 * passed. */
export function daysUntil(horizonIso, generatedAtIso) {
	if (!horizonIso || !generatedAtIso) return null;
	const horizon = Date.parse(`${horizonIso}T00:00:00Z`);
	const now = Date.parse(generatedAtIso);
	if (Number.isNaN(horizon) || Number.isNaN(now)) return null;
	return Math.round((horizon - now) / 86400000);
}

/** Resolved forecasts with a STATED probability, bucketed into ten-point
 * deciles, non-empty buckets only - a code-default 0.5 is never plotted or
 * counted here (it is not a claim anyone made). Returns
 * `{ buckets: [{decile, n, held}], excluded }`. */
export function deciles(forecasts) {
	const stated = (forecasts || []).filter(
		(f) => f.probability_stated !== false && typeof f.stated === 'number'
	);
	const byDecile = new Map();
	for (const f of stated) {
		const d = Math.min(9, Math.floor(f.stated * 10));
		const bucket = byDecile.get(d) || { decile: d, n: 0, held: 0 };
		bucket.n += 1;
		if (f.held) bucket.held += 1;
		byDecile.set(d, bucket);
	}
	const buckets = [...byDecile.values()].sort((a, b) => a.decile - b.decile);
	return { buckets, excluded: (forecasts || []).length - stated.length };
}

// ---------------------------------------------------------------------------
// The modelled forward cone.
//
// Everything below is MODELLED, and the page labels it so. It is the same
// lognormal the agent's own playbook scores a structure against - drift zero,
// no skew, no term structure - which is why it is the honest curve to draw
// next to a claim rather than a fancier one the agent never used.
// ---------------------------------------------------------------------------

/** Annualised implied vol scaled to a horizon, in the trading-day convention
 * the rest of this project uses (`iv / sqrt(252)` per day). Returns null when
 * either input is missing, which is how a cycle with no priced chain ends up
 * drawing a band and no cone rather than a guess. */
export function sigmaT(ivPct, days) {
	if (typeof ivPct !== 'number' || typeof days !== 'number') return null;
	if (!(ivPct > 0) || !(days > 0)) return null;
	return ivPct * Math.sqrt(days / 252);
}

/** Standard normal CDF, Abramowitz and Stegun 26.2.17. Max error ~7.5e-8,
 * which is far below anything this page displays. */
export function normCdf(x) {
	if (x < 0) return 1 - normCdf(-x);
	const t = 1 / (1 + 0.2316419 * x);
	const poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
	return 1 - 0.39894228 * Math.exp((-x * x) / 2) * poly;
}

/** Modelled probability the close at the horizon lands inside the claimed
 * band. A null edge is open-ended (the claim really is one-sided), not
 * missing data. Returns null without a sigma, never a made-up number. */
export function pBandHolds(spot, low, high, st) {
	if (!(spot > 0) || !(st > 0)) return null;
	const d = (k) => (Math.log(k / spot) + 0.5 * st * st) / st;
	const hi = typeof high === 'number' ? normCdf(d(high)) : 1;
	const lo = typeof low === 'number' ? normCdf(d(low)) : 0;
	return Math.max(0, Math.min(1, hi - lo));
}

/** The one- and two-sigma envelopes the underlying's own implied vol projects
 * forward, as `steps + 1` points from the decision day (width zero) to the
 * horizon. Empty when there is no sigma to project. */
export function coneBounds(spot, ivPct, days, steps = 12) {
	const st = sigmaT(ivPct, days);
	if (!st || !(spot > 0) || steps < 1) return [];
	const out = [];
	for (let i = 0; i <= steps; i += 1) {
		const s = st * Math.sqrt(i / steps);
		const at = (k) => spot * Math.exp(-0.5 * s * s + k * s);
		out.push({ step: i, up1: at(1), dn1: at(-1), up2: at(2), dn2: at(-2) });
	}
	return out;
}

/** One implied standard deviation in dollars - what the market says the move
 * is worth by the horizon. */
export function impliedMove(spot, st) {
	if (!(spot > 0) || !(st > 0)) return null;
	return spot * st;
}

/** Half the claimed band in dollars, which is what the claim has to be right
 * about. A one-sided claim measures from spot to the single edge. */
export function claimHalfWidth(spot, low, high) {
	const hasLow = typeof low === 'number', hasHigh = typeof high === 'number';
	if (hasLow && hasHigh) return (high - low) / 2;
	if (hasHigh) return Math.abs(high - spot);
	if (hasLow) return Math.abs(spot - low);
	return null;
}

/** Calendar days from a decision to its horizon, both taken from the record's
 * own stamps. Zero or negative once the horizon has arrived.
 *
 * The decision is truncated to its DATE before the subtraction, because that
 * is the convention the agent itself records: a 3 Sep decision against an
 * 11 Sep expiry is `days: 8` in the cycle's own `sense.market` block, and
 * subtracting the 17:54 timestamp instead rounds it to 7. The cone's width
 * scales with sqrt(days), so an off-by-one here would draw every cone
 * slightly narrower than the chain the agent actually priced. */
export function horizonDays(decisionIso, horizonIso) {
	if (!decisionIso || !horizonIso) return null;
	const from = Date.parse(`${String(decisionIso).slice(0, 10)}T00:00:00Z`);
	const to = Date.parse(`${horizonIso}T00:00:00Z`);
	if (Number.isNaN(from) || Number.isNaN(to)) return null;
	return Math.round((to - from) / 86400000);
}

/** The market context a cycle recorded, preferring the chain it actually
 * priced and falling back to the position it opened - so a traded cycle can
 * still draw its cone from `entry_iv` when no candidate row carried a market
 * block. Null when neither exists, and the cone is then simply not drawn. */
export function marketFor(cycle, positions) {
	const m = cycle?.sense?.market;
	if (m && typeof m.spot === 'number' && typeof m.iv_pct === 'number') {
		return { spot: m.spot, ivPct: m.iv_pct / 100, source: 'the chain it priced' };
	}
	const id = cycle?.act?.position_id;
	const pos = id ? (positions || []).find((p) => p.id === id) : null;
	if (pos && typeof pos.entry_spot === 'number' && typeof pos.entry_iv === 'number') {
		return { spot: pos.entry_spot, ivPct: pos.entry_iv, source: 'the position it opened' };
	}
	return null;
}

/** Position opens placed on the equity curve by timestamp, for the annotated
 * curve. Each marker is the curve index closest to the open, so a marker can
 * never sit off the drawn line.
 *
 * Positions opened minutes apart land on the same tick, so markers are GROUPED
 * by index and one dot carries however many opens happened there. Drawing them
 * separately stacks two circles on one pixel, which looks like a rendering
 * fault and makes the hover target ambiguous about which position it means. */
export function equityMarkers(positions, series) {
	if (!series?.length) return [];
	const times = series.map((p) => Date.parse(p.ts));
	const byIndex = new Map();
	for (const p of positions || []) {
		if (!p.opened) continue;
		const t = Date.parse(p.opened);
		if (Number.isNaN(t)) continue;
		let best = 0, bestGap = Infinity;
		for (let i = 0; i < times.length; i += 1) {
			const gap = Math.abs(times[i] - t);
			if (gap < bestGap) { bestGap = gap; best = i; }
		}
		const group = byIndex.get(best) || { index: best, positions: [] };
		group.positions.push({
			id: p.id, underlying: p.underlying, strategy: p.strategy,
			status: p.status, opened: p.opened
		});
		byIndex.set(best, group);
	}
	return [...byIndex.values()].sort((a, b) => a.index - b.index);
}

const ATTR_ROWS = [
	['held_profit', 'reinforce both', 'the thesis held and the position paid'],
	['held_loss', 'structure wrong', 'the view was fine, the strikes or the stop were not'],
	['failed_loss', 'correct the view', 'the thesis broke and the structure was faithful'],
	['failed_profit', 'learn nothing', 'a profit on a wrong thesis, which is luck'],
	['unscoreable', 'unscoreable', 'never filled, or no price to score it against']
];

/** The attribution counts as ordered display rows, widest first by the fixed
 * order of the table in the README - not sorted by count, because the point of
 * the table is the four cases, not their ranking. */
export function attributionBars(attribution) {
	const a = attribution || {};
	const rows = ATTR_ROWS.map(([key, label, note]) => ({ key, label, note, n: a[key] || 0 }));
	const scored = rows.reduce((sum, r) => sum + r.n, 0);
	return { rows, scored, awaiting: a.unattributed || 0, total: a.total || 0 };
}

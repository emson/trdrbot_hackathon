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

import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	hashFor, selectCycle, defaultThesis, defaultCandidateRow, candidatesFor,
	frameHeading, daysUntil, deciles, sigmaT, normCdf, pBandHolds, coneBounds,
	impliedMove, claimHalfWidth, horizonDays, marketFor, equityMarkers, attributionBars
} from '../src/lib/demo.js';

const CYCLES = [
	{ id: 'dec_new', tick: 3, think: { theses: [], candidates: [] } },
	{
		id: 'dec_traded', tick: 2,
		think: {
			theses: [
				{ entry_id: 'fc1', position_id: null, candidates_ref: null },
				{ entry_id: 'fc2', position_id: 'pos1', candidates_ref: 'row1' }
			],
			candidates: [
				{
					entry_id: 'fc2', ref: 'row1',
					rows: [
						{ name: 'a', fate: 'rejected: edge too small', chosen: false },
						{ name: 'b', fate: 'candidate', chosen: true },
						{ name: 'c', fate: 'candidate', chosen: false }
					]
				}
			]
		}
	},
	{ id: 'dec_old', tick: 1, think: { theses: [], candidates: [] } }
];

test('selectCycle falls back to the latest when the hash is empty or unknown', () => {
	assert.equal(selectCycle(CYCLES, '').id, 'dec_new');
	assert.equal(selectCycle(CYCLES, '#cycle-does-not-exist').id, 'dec_new');
	assert.equal(selectCycle([], '#cycle-dec_new'), null);
});

test('selectCycle finds the cycle named in the hash', () => {
	assert.equal(selectCycle(CYCLES, '#cycle-dec_old').id, 'dec_old');
});

test('hashFor round-trips through selectCycle', () => {
	const cycle = CYCLES[1];
	assert.equal(selectCycle(CYCLES, hashFor(cycle)).id, cycle.id);
	assert.equal(hashFor(null), '');
});

test('defaultThesis prefers the traded one, then the priced one, then the first', () => {
	assert.equal(defaultThesis(CYCLES[1]).entry_id, 'fc2', 'traded wins');
	assert.equal(defaultThesis(CYCLES[0]), null, 'no theses this cycle');
	const noTraded = { think: { theses: [{ entry_id: 'a' }, { entry_id: 'b', candidates_ref: 'r' }] } };
	assert.equal(defaultThesis(noTraded).entry_id, 'b', 'priced wins over plain first');
	const onlyPlain = { think: { theses: [{ entry_id: 'a' }, { entry_id: 'b' }] } };
	assert.equal(defaultThesis(onlyPlain).entry_id, 'a', 'first, when nothing else distinguishes');
});

test('defaultCandidateRow prefers chosen, then a survivor, then the first row', () => {
	const rows = CYCLES[1].think.candidates[0].rows;
	assert.equal(defaultCandidateRow(rows).name, 'b', 'chosen wins even over row order');
	const noChosen = [
		{ name: 'x', fate: 'rejected: unbounded loss', chosen: false },
		{ name: 'y', fate: 'candidate', chosen: false }
	];
	assert.equal(defaultCandidateRow(noChosen).name, 'y', 'first survivor when nothing is chosen');
	const allRejected = [{ name: 'x', fate: 'rejected: unbounded loss', chosen: false }];
	assert.equal(defaultCandidateRow(allRejected).name, 'x', 'first row as the last resort');
	assert.equal(defaultCandidateRow([]), null);
});

test('candidatesFor finds the block for a given thesis entry id', () => {
	assert.equal(candidatesFor(CYCLES[1], 'fc2').ref, 'row1');
	assert.equal(candidatesFor(CYCLES[1], 'fc1'), null);
	assert.equal(candidatesFor(CYCLES[0], 'fc1'), null);
});

test('frameHeading is keyed off the recorded outcome, not guessed', () => {
	assert.equal(frameHeading('traded'), 'What it did, and how big.');
	assert.equal(frameHeading('declined'), 'Why it did nothing.');
	assert.equal(frameHeading('acted'), 'What it did.');
	assert.equal(frameHeading('error'), 'What went wrong.');
	assert.equal(frameHeading('unrecognised'), 'What happened.');
});

test('daysUntil is computed from generatedAt, never the caller clock', () => {
	assert.equal(daysUntil('2026-09-10', '2026-09-03T12:00:00Z'), 7);
	assert.equal(daysUntil('2026-09-01', '2026-09-03T12:00:00Z'), -2, 'a passed horizon is negative');
	assert.equal(daysUntil('2026-09-03', '2026-09-03T00:00:00Z'), 0);
	assert.equal(daysUntil(null, '2026-09-03T00:00:00Z'), null);
	assert.equal(daysUntil('2026-09-03', null), null);
});

test('deciles buckets only stated probabilities, excludes code defaults', () => {
	const forecasts = [
		{ stated: 0.62, probability_stated: true, held: true },
		{ stated: 0.68, probability_stated: true, held: false },
		{ stated: 0.5, probability_stated: false, held: true }, // code default - excluded
		{ stated: 0.05, probability_stated: true, held: false }
	];
	const { buckets, excluded } = deciles(forecasts);
	assert.equal(excluded, 1);
	assert.deepEqual(
		buckets.map((b) => b.decile),
		[0, 6]
	);
	const d6 = buckets.find((b) => b.decile === 6);
	assert.equal(d6.n, 2);
	assert.equal(d6.held, 1);
});

test('deciles clamps a stated probability of exactly 1.0 into the top bucket', () => {
	const { buckets } = deciles([{ stated: 1.0, probability_stated: true, held: true }]);
	assert.equal(buckets[0].decile, 9);
});

// --- the modelled cone -----------------------------------------------------

test('sigmaT scales annualised vol into the trading-day convention', () => {
	// 31.5% IV over 8 days: 0.315 * sqrt(8/252).
	assert.ok(Math.abs(sigmaT(0.315, 8) - 0.315 * Math.sqrt(8 / 252)) < 1e-12);
});

test('sigmaT returns null rather than a guess when the record lacks an input', () => {
	assert.equal(sigmaT(null, 8), null);
	assert.equal(sigmaT(0.3, null), null);
	assert.equal(sigmaT(0, 8), null);
	assert.equal(sigmaT(0.3, 0), null);
});

test('normCdf matches the standard normal at known points', () => {
	assert.ok(Math.abs(normCdf(0) - 0.5) < 1e-6);
	assert.ok(Math.abs(normCdf(1.96) - 0.975) < 1e-3);
	assert.ok(Math.abs(normCdf(-1.96) - 0.025) < 1e-3);
});

test('pBandHolds is a probability, and a one-sided claim is open-ended not missing', () => {
	const st = sigmaT(0.315, 8);
	const twoSided = pBandHolds(230.2, 232, 245, st);
	assert.ok(twoSided > 0 && twoSided < 1);
	// Open above: everything over 232 counts, so it must exceed the closed band.
	assert.ok(pBandHolds(230.2, 232, null, st) > twoSided);
	// Open below: everything under 245 counts, likewise.
	assert.ok(pBandHolds(230.2, null, 245, st) > twoSided);
});

test('pBandHolds refuses to invent a number without a sigma', () => {
	assert.equal(pBandHolds(230.2, 232, 245, null), null);
	assert.equal(pBandHolds(0, 232, 245, 0.05), null);
});

test('coneBounds opens from zero width at the decision and widens monotonically', () => {
	const c = coneBounds(100, 0.3, 10, 8);
	assert.equal(c.length, 9);
	assert.ok(Math.abs(c[0].up1 - c[0].dn1) < 1e-9, 'no width on the decision day');
	for (let i = 1; i < c.length; i += 1) {
		assert.ok(c[i].up1 - c[i].dn1 > c[i - 1].up1 - c[i - 1].dn1, 'widens with time');
		assert.ok(c[i].up2 > c[i].up1 && c[i].dn2 < c[i].dn1, 'two sigma contains one');
	}
});

test('coneBounds is empty when there is nothing to project', () => {
	assert.deepEqual(coneBounds(100, null, 10), []);
	assert.deepEqual(coneBounds(100, 0.3, 0), []);
});

test('impliedMove and claimHalfWidth measure the same thing in dollars', () => {
	assert.ok(Math.abs(impliedMove(100, 0.05) - 5) < 1e-9);
	assert.equal(claimHalfWidth(100, 96, 104), 4);
	assert.equal(claimHalfWidth(100, null, 104), 4); // one-sided measures from spot
	assert.equal(claimHalfWidth(100, 96, null), 4);
	assert.equal(claimHalfWidth(100, null, null), null);
});

test('horizonDays counts from the decision stamp, never a caller clock', () => {
	assert.equal(horizonDays('2026-09-03T17:54:00Z', '2026-09-11'), 8);
	assert.equal(horizonDays('2026-09-03T17:54:00Z', '2026-09-03'), 0);
	assert.equal(horizonDays(null, '2026-09-11'), null);
});

test('marketFor prefers the priced chain, then the opened position, then nothing', () => {
	const chain = { sense: { market: { spot: 64.96, iv_pct: 28 } } };
	assert.deepEqual(marketFor(chain, []), { spot: 64.96, ivPct: 0.28, source: 'the chain it priced' });

	const traded = { sense: {}, act: { position_id: 'pos_1' } };
	const positions = [{ id: 'pos_1', entry_spot: 230.2, entry_iv: 0.315 }];
	assert.deepEqual(marketFor(traded, positions),
		{ spot: 230.2, ivPct: 0.315, source: 'the position it opened' });

	assert.equal(marketFor({ sense: {}, act: {} }, []), null);
});

test('equityMarkers land on the curve index closest to each open', () => {
	const series = [
		{ ts: '2026-09-01T00:00:00Z', equity: 100 },
		{ ts: '2026-09-02T00:00:00Z', equity: 110 },
		{ ts: '2026-09-03T00:00:00Z', equity: 120 }
	];
	const positions = [
		{ id: 'p1', opened: '2026-09-02T01:00:00Z', underlying: 'NVDA', strategy: 'bull_call_spread' },
		{ id: 'p2', opened: '2026-09-03T23:00:00Z', underlying: 'SPY', strategy: 'iron_condor' }
	];
	const out = equityMarkers(positions, series);
	assert.deepEqual(out.map((m) => m.index), [1, 2]);
	assert.equal(out[0].positions[0].underlying, 'NVDA');
});

test('equityMarkers groups opens that land on the same tick into one marker', () => {
	const series = [
		{ ts: '2026-09-01T00:00:00Z', equity: 100 },
		{ ts: '2026-09-02T00:00:00Z', equity: 110 }
	];
	// Two positions opened minutes apart both snap to the 2 Sep tick.
	const positions = [
		{ id: 'p1', opened: '2026-09-02T00:05:00Z', underlying: 'NVDA', strategy: 'bull_call_spread' },
		{ id: 'p2', opened: '2026-09-02T00:11:00Z', underlying: 'PLTR', strategy: 'bear_put_spread' }
	];
	const out = equityMarkers(positions, series);
	assert.equal(out.length, 1, 'one dot, not two stacked on the same pixel');
	assert.deepEqual(out[0].positions.map((p) => p.underlying), ['NVDA', 'PLTR']);
});

test('equityMarkers is empty without a curve, and skips positions never opened', () => {
	assert.deepEqual(equityMarkers([{ id: 'p' }], []), []);
	assert.deepEqual(equityMarkers([{ id: 'p' }], [{ ts: '2026-09-01T00:00:00Z', equity: 1 }]), []);
});

test('attributionBars keeps the four cases in the table order, not by count', () => {
	const { rows, scored, awaiting } = attributionBars({
		held_profit: 1, held_loss: 0, failed_loss: 1, failed_profit: 2,
		unscoreable: 1, unattributed: 8, total: 13
	});
	assert.deepEqual(rows.map((r) => r.key),
		['held_profit', 'held_loss', 'failed_loss', 'failed_profit', 'unscoreable']);
	assert.deepEqual(rows.map((r) => r.n), [1, 0, 1, 2, 1]);
	assert.equal(scored, 5);
	assert.equal(awaiting, 8);
});

test('attributionBars survives a record with no attribution block at all', () => {
	const { rows, scored, awaiting } = attributionBars(undefined);
	assert.equal(rows.length, 5);
	assert.equal(scored, 0);
	assert.equal(awaiting, 0);
});

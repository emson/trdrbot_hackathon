import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	hashFor, selectCycle, defaultThesis, defaultCandidateRow, candidatesFor,
	frameHeading, daysUntil, deciles
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

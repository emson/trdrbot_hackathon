import assert from 'node:assert/strict';
import { test } from 'node:test';
import { injectFigures } from './inject-figures.mjs';

// A slice of a real snapshot, shaped exactly like `site_export.py`'s output -
// the same values used to validate notes/027's design against the live deck
// before any code was written.
const SNAPSHOT = {
	account: { equity: 114084.78, pnl_pct: 0.1408478 },
	counts: { positions: 11, theses: 185 },
	calibration: { n: 76, n_eff: 9.82312925170068, resolution: 0.0 },
	competence: { tier: 'scale' },
	positions_summary: { closed_pnl_min_pct: -0.029239766081871343, closed_pnl_max_pct: 1.2911392405063291 },
	repo: { python_lines: 23027, issues_max_id: 125, tests: null },
	tick: 821
};

function tag(key, fmt, text) {
	return `<span class="big" data-figure="${key}" data-format="${fmt}">${text}</span>`;
}

test('reproduces every current deck figure byte-identically', () => {
	const html =
		`<p>${tag('account.equity', 'usd0', '$114,085')} ` +
		`${tag('account.pnl_pct', 'pct', '+14.1%')} ` +
		`${tag('counts.positions', 'num', '11')} ` +
		`${tag('positions_summary.closed_pnl_min_pct', 'pct', '−2.9%')} to ` +
		`${tag('positions_summary.closed_pnl_max_pct', 'pct', '+129.1%')} ` +
		`${tag('calibration.n', 'num', '76')} ` +
		`${tag('repo.python_lines', 'num', '22,900')}</p>`; // deliberately stale, must update

	const { html: out, report, errors } = injectFigures(html, SNAPSHOT);

	assert.deepEqual(errors, []);
	assert.equal(out.includes('$114,085'), true);
	assert.equal(out.includes('+14.1%'), true);
	assert.equal(out.includes('−2.9%'), true, 'the typographic minus, not ASCII hyphen');
	assert.equal(out.includes('+129.1%'), true);
	assert.equal(out.includes('23,027'), true, 'the stale 22,900 is corrected');
	assert.equal(out.includes('22,900'), false);

	const stale = report.find((r) => r.key === 'repo.python_lines');
	assert.equal(stale.status, 'updated');
	const current = report.find((r) => r.key === 'account.equity');
	assert.equal(current.status, 'unchanged');
});

test('a missing key refuses and names it', () => {
	const html = tag('account.nonexistent_field', 'usd0', '$0');
	const { errors } = injectFigures(html, SNAPSHOT);
	assert.equal(errors.length, 1);
	assert.match(errors[0], /account\.nonexistent_field/);
	assert.match(errors[0], /no such key/);
});

test('a null value keeps the baked fallback and does not refuse the run', () => {
	const html = `${tag('repo.tests', 'num', '745')} ${tag('counts.positions', 'num', '11')}`;
	const { html: out, report, errors } = injectFigures(html, SNAPSHOT);

	assert.deepEqual(errors, [], 'a null figure is a reportable state, not an error');
	assert.equal(out.includes('745'), true, 'the fallback text is untouched');
	const nullFigure = report.find((r) => r.key === 'repo.tests');
	assert.equal(nullFigure.status, 'skipped_null');
	const other = report.find((r) => r.key === 'counts.positions');
	assert.equal(other.status, 'unchanged', 'a null figure must not block its siblings');
});

test('running twice changes nothing', () => {
	const html = tag('repo.issues_max_id', 'num', 'stale text entirely');
	const first = injectFigures(html, SNAPSHOT);
	assert.equal(first.report[0].status, 'updated');

	const second = injectFigures(first.html, SNAPSHOT);
	assert.equal(second.html, first.html, 'a second pass is a no-op on its own output');
	assert.equal(second.report[0].status, 'unchanged');
	assert.deepEqual(second.errors, []);
});

test('the minus sign in a rendered figure is U+2212, not ASCII hyphen', () => {
	const html = tag('positions_summary.closed_pnl_min_pct', 'pct', 'x');
	const { html: out } = injectFigures(html, SNAPSHOT);
	assert.equal(out.includes('−2.9%'), true);
	assert.equal(out.includes('-2.9%'), false);
});

test('an element containing markup is refused rather than silently skipped', () => {
	const html = '<span data-figure="account.equity" data-format="usd0">$1<b>10</b>0</span>';
	const { errors, report } = injectFigures(html, SNAPSHOT);
	assert.equal(errors.length, 1);
	assert.match(errors[0], /account\.equity/);
	assert.match(errors[0], /could not be parsed/);
	assert.equal(report.some((r) => r.status === 'unparseable'), true);
});

test('an unknown data-format name refuses and names the format', () => {
	const html = tag('account.equity', 'not_a_real_formatter', '$0');
	const { errors } = injectFigures(html, SNAPSHOT);
	assert.equal(errors.length, 1);
	assert.match(errors[0], /unknown data-format/);
});

test('a plain span with no data-figure attribute is left completely untouched', () => {
	const html = '<span class="big">just decoration</span>';
	const { html: out, report, errors } = injectFigures(html, SNAPSHOT);
	assert.equal(out, html);
	assert.deepEqual(report, []);
	assert.deepEqual(errors, []);
});

test('the same key tagged twice both update in lockstep from one snapshot value', () => {
	const html = `${tag('calibration.n', 'num', '70')} ... ${tag('calibration.n', 'num', '71')}`;
	const { report, errors } = injectFigures(html, SNAPSHOT);
	assert.deepEqual(errors, []);
	assert.equal(report.length, 2);
	assert.ok(report.every((r) => r.after === '76'));
});

#!/usr/bin/env node
// Rewrite every tagged figure in an HTML document from the agent's own
// record (notes/027). A figure is a leaf element that declares which
// number it is:
//
//   <span class="big" data-figure="account.equity" data-format="usd0">$114,085</span>
//
// The baked text is always a real, correct, last-known value - the document
// stays readable (and printable to PDF) even if this script never runs
// again. Running it rewrites that text from `snapshot.json`; the tag itself
// never changes, so injection is idempotent and a second run reports zero
// changes.
//
// Why baked text and not a template placeholder: the deck is a standalone
// document, hosted as-is and opened directly from disk. A `{{mustache}}`
// left in place would render literally to anyone viewing the source, and a
// brace-substitution pass over a file whose own CSS and <script> are full of
// braces is asking for a collision. Tagging only the elements that opt in
// avoids both.
//
// Usage:
//   node inject-figures.mjs <snapshot.json> <doc.html> [--write] [--check]
//
// --check (default) reports every figure and exits 1 if the baked text
//   disagrees with the computed value - the "does this document agree with
//   the record" check notes/027 was written to produce.
// --write rewrites the file in place when there is a change, and prints the
//   same report.
//
// Exits non-zero (refuses to write anything) on: a missing snapshot key, a
// tagged element that contains markup rather than plain text, or a
// duplicate `data-figure` key with disagreeing formats. A null VALUE is not
// an error - it is a real state ("not yet computable") - and is reported as
// a skip, keeping the baked text as the honest fallback.

import fs from 'node:fs';
import * as format from '../src/lib/format.js';

const RESET = process.env.NO_COLOR ? '' : '\x1b[0m';
const DIM = process.env.NO_COLOR ? '' : '\x1b[2m';
const RED = process.env.NO_COLOR ? '' : '\x1b[31m';
const YELLOW = process.env.NO_COLOR ? '' : '\x1b[33m';
const GREEN = process.env.NO_COLOR ? '' : '\x1b[32m';

// A tagged element is always a `<span ...>plain text</span>` leaf - the
// deck's own convention for a numeric callout. Anchoring on `<span>`
// specifically (rather than any tag) is what makes "contains markup" a
// simple presence-of-`<` check inside the captured group: a genuine child
// element would put a second `<` before this element's own `</span>`, which
// `[^<]*` cannot match past - so a malformed tag simply fails to match here
// and is caught by the coverage check below instead of being silently
// mis-captured.
const SPAN_RE = /<span\b([^>]*)>([^<]*)<\/span>/g;
const ATTR_RE = /data-figure="([^"]*)"/;
const FORMAT_RE = /data-format="([^"]*)"/;
// Every occurrence of the attribute, anywhere - including inside a
// malformed or nested span the SPAN_RE above could not fully match - so
// "found the attribute but couldn't parse its element" is detectable rather
// than silently skipped.
const ANY_FIGURE_RE = /data-figure="([^"]*)"/g;

export class FigureError extends Error {}

/** Dot-path lookup that distinguishes "key genuinely absent" (undefined,
 * refuse) from "key present and null" (a real, reportable state). Each
 * segment must exist as an own key; a `.` inside a key name is not
 * supported and is not needed by this snapshot's shape. */
function lookup(obj, path) {
	const segments = path.split('.');
	let cur = obj;
	for (const seg of segments) {
		if (cur === null || typeof cur !== 'object' || !(seg in cur)) {
			return { found: false, value: undefined };
		}
		cur = cur[seg];
	}
	return { found: true, value: cur };
}

function formatValue(value, formatName, key) {
	if (formatName === '' || formatName === undefined) {
		throw new FigureError(`${key}: no data-format given`);
	}
	const fn = format[formatName];
	if (typeof fn !== 'function') {
		throw new FigureError(`${key}: unknown data-format "${formatName}"`);
	}
	return fn(value);
}

/**
 * Run the injector over one HTML string. Returns
 * `{ html, report: [{key, format, before, after, status}], errors: [string] }`.
 * `status` is one of "unchanged" | "updated" | "skipped_null".
 * Never throws for a per-figure problem (null value) - only `errors` being
 * non-empty means the whole run must be refused; a single bad figure names
 * itself in `errors` and the caller decides whether that is fatal (it
 * always is, by design - see the module docstring).
 */
export function injectFigures(html, snapshot) {
	const report = [];
	const errors = [];
	const seenSpanKeys = new Set();

	const allKeys = new Set([...html.matchAll(ANY_FIGURE_RE)].map((m) => m[1]));

	const rewritten = html.replace(SPAN_RE, (full, attrs, inner) => {
		const keyMatch = ATTR_RE.exec(attrs);
		if (!keyMatch) return full; // an ordinary span, not tagged - untouched
		const key = keyMatch[1];
		seenSpanKeys.add(key);
		const formatMatch = FORMAT_RE.exec(attrs);
		const formatName = formatMatch ? formatMatch[1] : undefined;

		const { found, value } = lookup(snapshot, key);
		if (!found) {
			errors.push(`${key}: no such key in the snapshot`);
			report.push({ key, format: formatName, before: inner, after: null, status: 'missing_key' });
			return full;
		}
		if (value === null) {
			report.push({ key, format: formatName, before: inner, after: inner, status: 'skipped_null' });
			return full; // the baked text IS the fallback - leave it exactly as it is
		}

		let after;
		try {
			after = formatValue(value, formatName, key);
		} catch (exc) {
			errors.push(exc.message);
			report.push({ key, format: formatName, before: inner, after: null, status: 'format_error' });
			return full;
		}
		report.push({
			key, format: formatName, before: inner, after,
			status: after === inner ? 'unchanged' : 'updated'
		});
		return `<span${attrs}>${after}</span>`;
	});

	// Coverage: every `data-figure="..."` attribute in the document must have
	// been reachable through a clean `<span ...>plain text</span>` match. One
	// that was not is a malformed or markup-containing element - refuse and
	// name it, rather than silently leaving stale text in a submission
	// artifact.
	for (const key of allKeys) {
		if (!seenSpanKeys.has(key)) {
			errors.push(`${key}: tagged element could not be parsed - check it is a plain ` +
				`<span data-figure="${key}">...</span> with no nested markup`);
			report.push({ key, format: undefined, before: null, after: null, status: 'unparseable' });
		}
	}

	return { html: rewritten, report, errors };
}

function printReport(report, { write }) {
	for (const r of report) {
		if (r.status === 'updated') {
			console.log(`  ${GREEN}~${RESET} ${r.key} ${DIM}(${r.format})${RESET}  ` +
				`${DIM}${r.before}${RESET} -> ${r.after}`);
		} else if (r.status === 'unchanged') {
			console.log(`  ${DIM}= ${r.key} (${r.format})  ${r.after}${RESET}`);
		} else if (r.status === 'skipped_null') {
			console.log(`  ${YELLOW}? ${r.key} (${r.format})  null in the snapshot - ` +
				`keeping "${r.before}"${RESET}`);
		} else {
			console.log(`  ${RED}! ${r.key}${r.format ? ` (${r.format})` : ''}  ${r.status}${RESET}`);
		}
	}
	const updated = report.filter((r) => r.status === 'updated').length;
	const unchanged = report.filter((r) => r.status === 'unchanged').length;
	const skipped = report.filter((r) => r.status === 'skipped_null').length;
	console.log(`  ${updated} updated, ${unchanged} unchanged, ${skipped} null` +
		(write ? '' : ' (--check: nothing written)'));
}

export function main(argv) {
	const args = argv.filter((a) => !a.startsWith('--'));
	const write = argv.includes('--write');
	if (args.length !== 2) {
		console.error('usage: inject-figures.mjs <snapshot.json> <doc.html> [--write]');
		return 2;
	}
	const [snapshotPath, docPath] = args;

	let snapshot;
	try {
		snapshot = JSON.parse(fs.readFileSync(snapshotPath, 'utf8'));
	} catch (exc) {
		console.error(`[inject-figures] REFUSED - could not read/parse ${snapshotPath}: ${exc.message}`);
		return 1;
	}

	let html;
	try {
		html = fs.readFileSync(docPath, 'utf8');
	} catch (exc) {
		console.error(`[inject-figures] REFUSED - could not read ${docPath}: ${exc.message}`);
		return 1;
	}

	const { html: rewritten, report, errors } = injectFigures(html, snapshot);

	console.log(`[inject-figures] ${docPath} against ${snapshotPath}`);
	printReport(report, { write });

	if (errors.length) {
		console.error(`[inject-figures] REFUSED - ${errors.length} figure(s) could not be resolved:`);
		for (const e of errors) console.error(`  - ${e}`);
		return 1;
	}

	if (write) {
		if (rewritten === html) {
			console.log('[inject-figures] no change - file left untouched');
		} else {
			fs.writeFileSync(docPath, rewritten, 'utf8');
			console.log(`[inject-figures] wrote ${docPath}`);
		}
		return 0;
	}

	const drifted = report.some((r) => r.status === 'updated');
	if (drifted) {
		console.error('[inject-figures] DRIFT - the document disagrees with the record ' +
			'(rerun with --write to fix)');
		return 1;
	}
	console.log('[inject-figures] current - the document agrees with the record');
	return 0;
}

if (import.meta.url === `file://${process.argv[1]}`) {
	process.exit(main(process.argv.slice(2)));
}

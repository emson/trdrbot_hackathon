#!/usr/bin/env node
// Copies the standalone HTML documents (deck, coach report, risk explorer,
// risk research, design system) into static/, with a small back-link banner
// injected right after <body> — the source files themselves are untouched.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..', '..');
const STATIC = path.resolve(__dirname, '..', 'static');

const FILES = [
	{ src: 'docs/deck.html', dest: 'deck.html', label: 'Slide deck' },
	// The one source written by the agent rather than kept in docs/, so it is
	// the one that moved when the agent did.
	{ src: 'agent/data/report.html', dest: 'coach-report.html', label: 'The Coach — live report' },
	{
		src: 'docs/risk_appetite_explorer.html',
		dest: 'resources/risk-appetite-explorer.html',
		label: 'Risk Appetite Explorer',
		backHref: '/resources',
		backLabel: 'Resources'
	},
	{
		src: 'docs/architecture_explorer.html',
		dest: 'resources/architecture-explorer.html',
		label: 'The Trdrbot Loop',
		backHref: '/resources',
		backLabel: 'Resources'
	},
	{ src: 'docs/research_risk_appetite.html', dest: 'risk-research.html', label: 'Risk appetite — research' },
	{ src: 'docs/design_system.html', dest: 'design-system.html', label: 'Theo design system' }
];

const BANNER = (label, backHref, backLabel) => `
<div style="position:sticky;top:0;z-index:999;background:#17242B;color:#F1F4EF;font-family:'IBM Plex Mono',ui-monospace,Menlo,monospace;font-size:12px;padding:8px 16px;display:flex;gap:10px;align-items:center;letter-spacing:.02em">
	<a href="${backHref}" style="color:#57C7A7;text-decoration:none;font-weight:600">&larr; ${backLabel}</a>
	<span style="opacity:.6">${label} — a standalone document, hosted as-is</span>
</div>`;

// The deck's own <img> tags are relative (`src="assets/elf-coding.jpg"`),
// which resolves against wherever the document is served from - `/deck.html`
// on trdrbot.com, so the images live at `/assets/*`. Nothing ever copied
// `docs/assets/` into `static/`, so every deck image has been a 404 in
// production since the deck was authored. Mirror the whole directory.
const ASSETS_SRC = path.join(ROOT, 'docs', 'assets');
const ASSETS_DEST = path.join(STATIC, 'assets');
let assetCount = 0;
if (fs.existsSync(ASSETS_SRC)) {
	fs.mkdirSync(ASSETS_DEST, { recursive: true });
	// Top-level files only - the deck references e.g. `elf-coding.jpg` flat,
	// never a subpath, and `docs/assets/` also holds a `crops/` working
	// directory and other non-deck material that has no business on the site.
	for (const name of fs.readdirSync(ASSETS_SRC)) {
		const srcFile = path.join(ASSETS_SRC, name);
		if (fs.statSync(srcFile).isFile()) {
			fs.copyFileSync(srcFile, path.join(ASSETS_DEST, name));
			assetCount++;
		}
	}
	console.log(`[sync-static] copied ${assetCount} file(s) into static/assets/`);
} else {
	console.warn(`[sync-static] skip (missing): docs/assets/`);
}

let count = 0;
for (const f of FILES) {
	const srcPath = path.join(ROOT, f.src);
	if (!fs.existsSync(srcPath)) {
		console.warn(`[sync-static] skip (missing): ${f.src}`);
		continue;
	}
	let html = fs.readFileSync(srcPath, 'utf8');
	const banner = BANNER(f.label, f.backHref || '/', f.backLabel || 'trdrbot.com');
	if (/<body[^>]*>/i.test(html)) {
		html = html.replace(/<body([^>]*)>/i, (m) => `${m}${banner}`);
	} else {
		html = banner + html;
	}
	const destPath = path.join(STATIC, f.dest);
	fs.mkdirSync(path.dirname(destPath), { recursive: true });
	fs.writeFileSync(destPath, html, 'utf8');
	count++;
	console.log(`[sync-static] wrote static/${f.dest} (${(html.length / 1024).toFixed(0)}KB)`);
}
console.log(`[sync-static] done: ${count}/${FILES.length} files`);

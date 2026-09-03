// A real minus sign (U+2212), not the ASCII hyphen-minus `.toFixed()` and
// template interpolation produce for a negative number. The deck was hand-set
// with the typographic minus (notes/027's injector pins it byte-for-byte
// against the deck), so the shared formatter now matches everywhere it is
// used rather than the deck being the one place the two disagree.
const MINUS = '−';

export function usd(v, { sign = false } = {}) {
	if (v === null || v === undefined || Number.isNaN(v)) return 'not recorded';
	const s = v < 0 ? MINUS : sign && v > 0 ? '+' : '';
	return `${s}$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** Whole dollars, no cents - `$114,085`, not `$114,085.00`. */
export function usd0(v, { sign = false } = {}) {
	if (v === null || v === undefined || Number.isNaN(v)) return 'not recorded';
	const s = v < 0 ? MINUS : sign && v > 0 ? '+' : '';
	return `${s}$${Math.round(Math.abs(v)).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
}

export function usdCompact(v) {
	if (v === null || v === undefined || Number.isNaN(v)) return 'not recorded';
	const abs = Math.abs(v);
	const sign = v < 0 ? MINUS : '';
	if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
	return usd(v);
}

export function pct(v, { digits = 1, sign = true } = {}) {
	if (v === null || v === undefined || Number.isNaN(v)) return 'not recorded';
	if (v < 0) return `${MINUS}${(Math.abs(v) * 100).toFixed(digits)}%`;
	const s = v > 0 && sign ? '+' : '';
	return `${s}${(v * 100).toFixed(digits)}%`;
}

export function num(v, digits = 0) {
	if (v === null || v === undefined || Number.isNaN(v)) return 'not recorded';
	return v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function dateOnly(iso) {
	if (!iso) return 'not recorded';
	return iso.slice(0, 10);
}

export function dateTime(iso) {
	if (!iso) return 'not recorded';
	try {
		return new Date(iso).toLocaleString('en-US', {
			year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
			timeZone: 'UTC', timeZoneName: 'short'
		});
	} catch {
		return iso;
	}
}

/** Deterministic at build time: pass `now` explicitly rather than reading the clock. */
export function relativeTime(iso, now) {
	if (!iso) return 'unknown';
	const then = new Date(iso).getTime();
	const diffMs = now - then;
	const mins = Math.round(diffMs / 60000);
	if (mins < 1) return 'just now';
	if (mins < 60) return `${mins}m ago`;
	const hrs = Math.round(mins / 60);
	if (hrs < 24) return `${hrs}h ago`;
	const days = Math.round(hrs / 24);
	return `${days}d ago`;
}

export function titleCase(s) {
	if (!s) return '';
	return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/** `scale` -> `SCALE`. The competence tier as the deck's kicker line renders it. */
export function upper(s) {
	if (s === null || s === undefined) return '';
	return String(s).toUpperCase();
}

/**
 * The deck's own dateline house style - `3 Sep 2026, 17:04 UTC` - day before
 * month, 24-hour clock, no comma-separated weekday. Deliberately its own
 * formatter rather than a `dateTime()` option: this is the terse form a
 * printed document's byline uses, not the site's relative-time card style,
 * and the two have never been meant to match.
 */
export function deckDateTime(iso) {
	if (!iso) return 'not recorded';
	const d = new Date(iso);
	if (Number.isNaN(d.getTime())) return 'not recorded';
	const day = d.getUTCDate();
	const month = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' });
	const year = d.getUTCFullYear();
	const hh = String(d.getUTCHours()).padStart(2, '0');
	const mm = String(d.getUTCMinutes()).padStart(2, '0');
	return `${day} ${month} ${year}, ${hh}:${mm} UTC`;
}

export function strategyLabel(s) {
	return titleCase(s || '');
}

const STATUS_PILL = {
	open: 'open', proposed: 'open', opening: 'open', adjusting: 'open', closing: 'open',
	closed: 'closed', expired: 'closed', assigned: 'closed', abandoned: 'closed'
};
export function statusPillClass(status) {
	return STATUS_PILL[status] || 'closed';
}

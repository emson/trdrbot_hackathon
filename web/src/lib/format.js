export function usd(v, { sign = false } = {}) {
	if (v === null || v === undefined || Number.isNaN(v)) return 'not recorded';
	const s = v < 0 ? '-' : sign && v > 0 ? '+' : '';
	return `${s}$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function usdCompact(v) {
	if (v === null || v === undefined || Number.isNaN(v)) return 'not recorded';
	const abs = Math.abs(v);
	const sign = v < 0 ? '-' : '';
	if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
	return usd(v);
}

export function pct(v, { digits = 1, sign = true } = {}) {
	if (v === null || v === undefined || Number.isNaN(v)) return 'not recorded';
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

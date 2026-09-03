<script>
	let { cycles = [], selectedId = '', onselect = () => {} } = $props();

	const OUTCOME_PILL = { traded: 'traded', acted: 'closed', declined: 'declined', error: 'gap' };

	// A compact chip dateline - not `dateTime()`, which is built for a card
	// caption's width, not a scrolling strip of thirty of these.
	function chipWhen(iso) {
		const d = new Date(iso);
		if (Number.isNaN(d.getTime())) return 'not recorded';
		const day = d.getUTCDate();
		const month = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' });
		const hh = String(d.getUTCHours()).padStart(2, '0');
		const mm = String(d.getUTCMinutes()).padStart(2, '0');
		return `${day} ${month} ${hh}:${mm}`;
	}

	function cycleLabel(c) {
		const names = (c.think.theses || []).map((t) => t.underlying);
		const acted = c.act.position_id ? (c.think.theses.find((t) => t.position_id === c.act.position_id)?.underlying) : null;
		const who = acted || names[0] || 'holding';
		return who;
	}

	function onkeydown(e, i) {
		if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
		e.preventDefault();
		const next = e.key === 'ArrowRight' ? Math.min(i + 1, cycles.length - 1) : Math.max(i - 1, 0);
		onselect(cycles[next]);
		document.getElementById(`reel-chip-${cycles[next].id}`)?.focus();
	}
</script>

<div class="reel" role="toolbar" aria-label="Choose a decide cycle to replay">
	{#each cycles as c, i}
		<button
			id="reel-chip-{c.id}"
			class="reel-chip"
			type="button"
			aria-pressed={c.id === selectedId}
			onclick={() => onselect(c)}
			onkeydown={(e) => onkeydown(e, i)}
		>
			<span class="fine">tick {c.tick ?? '?'} · {chipWhen(c.ts)}</span>
			<span class="reel-chip-name">{cycleLabel(c)}</span>
			<span class="pill {OUTCOME_PILL[c.outcome] || 'declined'}">{c.outcome}</span>
		</button>
	{/each}
</div>

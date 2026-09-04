<script>
	import { num3, pct } from '$lib/format.js';
	import PosteriorTrace from './PosteriorTrace.svelte';

	// One Coach lever, replayed exactly as `trdrbot coach status` reports it -
	// same tally, same floors, same verdict - so the page and the terminal can
	// never disagree (notes/028).
	let { lever = {} } = $props();

	// What each lever actually controls, in a reader's words. Keyed off the
	// lever's own `subsystem`, so a lever the Coach grows later falls through
	// to its recorded name rather than borrowing someone else's description.
	const CONTROLS = {
		muse: 'The prompt the muse uses to collide unrelated concepts into candidate claims.',
		playbook: 'The catalogue of option structures the playbook prices a claim with.'
	};

	let exp = $derived(lever.experiment);
	let ch = $derived(exp?.challenger);
	let inc = $derived(exp?.incumbent);
	let chRate = $derived(ch?.n ? ch.survived / ch.n : null);
	let incRate = $derived(inc?.n ? inc.survived / inc.n : null);
	let lead = $derived(chRate !== null && incRate !== null ? chRate - incRate : null);

	// The three conditions that gate a promotion. Showing them as a checklist
	// is the only thing that answers "so why hasn't it changed anything yet".
	let checks = $derived(
		!exp?.floors
			? []
			: [
					{
						label: 'evidence',
						ok: exp.posterior >= exp.floors.promote_at,
						have: num3(exp.posterior),
						need: `${exp.floors.promote_at} confidence`
					},
					{
						label: 'paired runs',
						ok: exp.runs >= exp.floors.min_runs,
						have: String(exp.runs),
						need: `${exp.floors.min_runs} minimum`
					},
					{
						label: 'candidates per arm',
						ok: (ch?.n ?? 0) >= exp.floors.min_candidates,
						have: String(ch?.n ?? 0),
						need: `${exp.floors.min_candidates} minimum`
					}
				]
	);
	let blocking = $derived(checks.filter((c) => !c.ok));
</script>

<div class="card pad-lg">
	<div class="head">
		<h3>{lever.name}</h3>
		<span class="tag {lever.paused ? 'warn' : 'neutral'}">{lever.paused ? 'paused' : lever.state}</span>
	</div>
	<p class="muted" style="font-size:.9rem">{CONTROLS[lever.subsystem] || `The ${lever.kind} for ${lever.subsystem}.`}</p>

	<div class="versions">
		<span class="ver">
			<span class="lbl">running now</span>
			<span class="id">{lever.incumbent?.id} · {lever.incumbent?.fingerprint}</span>
			<span class="fine">{lever.incumbent?.origin}{lever.incumbent?.since ? `, since ${lever.incumbent.since.slice(0, 10)}` : ''}</span>
		</span>
		<span class="ver">
			<span class="lbl">on trial</span>
			{#if lever.challenger}
				<span class="id">{lever.challenger.id} · {lever.challenger.fingerprint}</span>
				<span class="fine">{lever.challenger.origin}{lever.challenger.since ? `, since ${lever.challenger.since.slice(0, 10)}` : ''}</span>
			{:else}
				<span class="id muted">nothing</span>
				<span class="fine">the incumbent stands unchallenged</span>
			{/if}
		</span>
	</div>

	{#if exp}
		<h4 class="sub">How the two are doing</h4>
		<p class="fine">
			Both saw the same inputs. Only the incumbent's verdicts counted; the challenger ran as a
			shadow and wrote nothing.
		</p>
		<div class="h2h">
			<div class="arm">
				<span class="arm-top"><span>challenger</span><span class="num">{pct(chRate, { sign: false })}</span></span>
				<span class="bar"><i class="ch" style="width:{((chRate ?? 0) * 100).toFixed(1)}%"></i></span>
				<span class="fine">{ch?.survived} of {ch?.n} candidates survived</span>
			</div>
			<div class="arm">
				<span class="arm-top"><span>incumbent</span><span class="num">{pct(incRate, { sign: false })}</span></span>
				<span class="bar"><i style="width:{((incRate ?? 0) * 100).toFixed(1)}%"></i></span>
				<span class="fine">{inc?.survived} of {inc?.n} candidates survived</span>
			</div>
		</div>
		{#if lead !== null}
			<p class="fine">
				The challenger is {Math.abs(lead * 100).toFixed(1)} points {lead >= 0 ? 'ahead' : 'behind'}
				after {exp.runs} scored run{exp.runs === 1 ? '' : 's'}{#if exp.voided}, and {exp.voided}
					more were voided because the two arms did not see identical quotes{/if}.
			</p>
		{/if}

		<h4 class="sub">How sure that lead is real</h4>
		<PosteriorTrace
			series={exp.posterior_series || []}
			promoteAt={exp.floors?.promote_at ?? 0.9}
			futilityAt={exp.floors?.futility_at ?? 0.05}
		/>
		<p class="fine">
			A small lead over few runs is luck; the same lead over many is skill. This line is the
			Coach's own probability that the challenger is genuinely better, recomputed after every
			scored run, and it moves both ways.
		</p>

		{#if checks.length}
			<h4 class="sub">What promotion still needs</h4>
			<ul class="checks">
				{#each checks as c}
					<li class:ok={c.ok}>
						<span class="mk">{c.ok ? '✓' : '✗'}</span>
						<span class="ck">{c.label}</span>
						<span class="fine">{c.have} of {c.need}</span>
					</li>
				{/each}
			</ul>
			<p class="fine">
				{#if exp.verdict?.outcome}
					{exp.verdict.outcome}: {exp.verdict.reason}
				{:else if blocking.length}
					Not promoted: {blocking.map((c) => c.label).join(' and ')} still short. It keeps running
					until it clears the bar, drops to {exp.floors.futility_at}, or hits {exp.floors.cap_runs} runs.
				{:else}
					Every condition is met.
				{/if}
			</p>
		{/if}

		{#if exp.mutation_rationale}
			<div class="quote" style="padding:.7rem .9rem">
				<p style="font-size:.86rem">{exp.mutation_rationale}</p>
				<cite>the Coach's own reason for this challenger</cite>
			</div>
		{/if}
	{:else}
		<p class="muted" style="font-size:.9rem; margin-top:.6rem">
			No trial is open on this lever, so nothing about it is changing. The Coach opens one when it
			has a mutation worth testing.
		</p>
	{/if}

	<h4 class="sub">The score it cannot reach</h4>
	<div class="quote" style="padding:.7rem .9rem">
		<p style="font-size:.84rem">{lever.reward_description}</p>
		<cite>the reward, in the Coach's own words · {(lever.reward_modules || []).join(', ')}</cite>
	</div>
</div>

<style>
	.head { display: flex; justify-content: space-between; align-items: baseline; gap: .6rem;
		flex-wrap: wrap; }
	.head h3 { font-family: var(--mono); font-size: 1rem; }
	.sub { font-size: .95rem; margin: 1.3rem 0 .4rem; }

	.versions { display: grid; grid-template-columns: 1fr 1fr; gap: .8rem; margin: .9rem 0 .2rem;
		padding: .7rem 0; border-top: 1px solid var(--paper-line);
		border-bottom: 1px solid var(--paper-line); }
	.ver { display: flex; flex-direction: column; gap: .1rem; }
	.ver .lbl { font-family: var(--mono); font-size: .6rem; letter-spacing: .1em;
		text-transform: uppercase; color: var(--ink-faint); }
	.ver .id { font-family: var(--mono); font-size: .85rem; font-weight: 600; }

	.h2h { display: flex; flex-direction: column; gap: .7rem; margin-top: .6rem; }
	.arm { display: flex; flex-direction: column; gap: .25rem; }
	.arm-top { display: flex; justify-content: space-between; gap: 1rem; font-size: .88rem;
		font-weight: 600; }
	.arm-top .num { font-family: var(--mono); }
	.bar { display: block; height: 10px; background: var(--paper-sunk);
		border: 1px solid var(--paper-line); border-radius: 5px; overflow: hidden; }
	.bar i { display: block; height: 100%; background: var(--ink-faint); }
	.bar i.ch { background: var(--accent); }

	.checks { list-style: none; padding: 0; margin: .5rem 0 .6rem; display: flex;
		flex-direction: column; gap: .35rem; }
	.checks li { display: flex; align-items: baseline; gap: .55rem; font-size: .88rem; }
	.checks .mk { font-family: var(--mono); font-weight: 700; color: var(--danger); width: 1em;
		flex: none; }
	.checks li.ok .mk { color: var(--accent); }
	.checks .ck { font-weight: 600; }
	.checks .fine { margin-left: auto; }

	@media (max-width: 620px) { .versions { grid-template-columns: 1fr; } }
</style>

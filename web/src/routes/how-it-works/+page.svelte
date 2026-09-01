<script>
	import Icon from '$lib/components/Icon.svelte';
</script>

<svelte:head><title>How it works — trdrbot</title></svelte:head>

<section class="block ledger">
	<div class="wrap">
		<span class="kicker">The machine</span>
		<h1 style="margin:.5rem 0 .8rem">Five stages, looped so the system can learn from itself.</h1>
		<p class="standfirst">
			A scheduler wakes the agent every 60 seconds. Cheap deterministic work runs every tick;
			the one LLM decision cycle runs roughly every 15 minutes. What comes back from Learn feeds
			forward into Think through calibration and attribution — the size the <em>next</em> trade
			is allowed depends on how honestly the last ones were explained.
		</p>
	</div>
</section>

<section class="block ledger" style="padding-top:0">
	<div class="wrap">
		<div class="cols c5">
			<div class="card stage"><span class="fine">01</span><h3>Sense</h3>
				<p class="muted">Prices, positions, news, odds, technicals.</p>
				<p class="fine">every 60s · no LLM</p></div>
			<div class="card stage"><span class="fine">02</span><h3>Think</h3>
				<p class="muted">Form a falsifiable view; price ≥2 ways to express it.</p>
				<p class="fine">~15 min · LLM + arithmetic</p></div>
			<div class="card stage"><span class="fine">03</span><h3>Act</h3>
				<p class="muted">Place the multi-leg order, verify against broker truth.</p>
				<p class="fine">Alpaca MCP</p></div>
			<div class="card stage"><span class="fine">04</span><h3>Learn</h3>
				<p class="muted">Guard the position deterministically; judge it honestly.</p>
				<p class="fine">every 60s · no LLM</p></div>
			<div class="card stage"><span class="fine">05</span><h3>Remember</h3>
				<p class="muted">Route what was learned to the store shaped to hold it.</p>
				<p class="fine">four stores</p></div>
		</div>
		<p class="muted" style="margin-top:1.1rem">
			Prefer to explore it? <a href="/resources/system-architecture">The Trdrbot Loop</a> is the
			same system as a clickable diagram, with one real trade stepped through end to end.
		</p>
	</div>
</section>

<section class="block ledger">
	<div class="wrap">
		<span class="kicker">Stage 2 · Think</span>
		<h2 style="margin:.4rem 0 .8rem">Three independent ways to have an idea — then one narrow job for the model.</h2>
		<div class="cols c3">
			<div class="card"><h3>research</h3><p class="muted">Daily, top-down. Technicals + news +
				prediction-market odds &rarr; a regime page and company dossiers &rarr; falsifiable opportunities.</p></div>
			<div class="card"><h3>discovery</h3><p class="muted">Bottom-up. <em>The news nominates the
				companies.</em> Every nominee must clear a deterministic gauntlet — technicals, forecast,
				fundamentals, options liquidity — before an LLM writes anything up.</p></div>
			<div class="card"><h3>the muse</h3><p class="muted">Creative collision. Random wiki concepts
				× news × odds, argued into domino chains, every candidate pre-registered and adversarially
				gated. The top two graduate.</p></div>
		</div>
		<div class="cols c2" style="margin-top:1rem">
			<div class="card"><span class="tag ai">what the LLM decides</span>
				<ul class="clean">
					<li>A <strong>falsifiable thesis</strong> — a claim with a date and a level</li>
					<li>At least <strong>two structurally different</strong> ways to express it</li>
					<li>An honest <strong>probability</strong>, and a vol view if the trade is about vol</li>
				</ul></div>
			<div class="card"><span class="tag code">what the code decides</span>
				<ul class="clean">
					<li><code>simulate_experiments</code> prices every candidate under <strong>one declared
						measure</strong> — the thesis's own drift and vol, market pricing shown beside it</li>
					<li><code>size_position</code> computes Kelly from the <strong>conditional</strong>
						payoff and shrinks the claim by measured calibration</li>
					<li>A no-op is a logged, legitimate answer. Theo declines far more often than it trades.</li>
				</ul></div>
		</div>
	</div>
</section>

<section class="block ledger">
	<div class="wrap">
		<span class="kicker">Stage 3 · Act</span>
		<h2 style="margin:.4rem 0 .8rem">Place the order, then double-check it against the broker.</h2>
		<div class="cols side">
			<ul class="clean">
				<li><strong>The model authors every tool argument.</strong> A guard rewrites the order id
					before it leaves — without it, idempotency is whatever the model invented.</li>
				<li><strong>Risk is repriced from the fill</strong>, not the model's word. Every book cap
					sums <code>max_loss_usd</code>; if that came from a model and never met a fill, every
					later cap is denominated in fiction.</li>
				<li><strong>A whole-book close is refused</strong> above one open position, and an orphan
					found at the broker is adopted into the managed set rather than just logged.</li>
			</ul>
			<div class="card">
				<span class="tag code">a real order</span>
				<div class="scroll"><table><tbody>
					<tr><td class="muted">class</td><td><code>mleg</code> — one ticket, both legs</td></tr>
					<tr><td class="muted">type</td><td>limit, net debit, day</td></tr>
					<tr><td class="muted">id</td><td><code>client_order_id</code>, derived deterministically</td></tr>
				</tbody></table></div>
				<p class="fine">Every position traces back to its reasoning through one
					<code>position_id</code> — journal, wiki, memory, and back to the broker.</p>
			</div>
		</div>
	</div>
</section>

<section class="block ledger">
	<div class="wrap">
		<span class="kicker">Stage 4 · Learn</span>
		<h2 style="margin:.4rem 0 .8rem">Guard the position without consulting the agent. Then judge it honestly.</h2>
		<div class="cols c2">
			<div class="card"><span class="tag code">the guard — every 60 seconds</span>
				<p class="muted">Exit rules are the agent's own commitments, executed deterministically.
					One signal registry: every rule reads a signal, compares to a threshold, debounces.
					Thesis-level stops watch the <strong>underlying</strong>, not the noisy option mark.</p></div>
			<div class="card"><span class="tag code">the scoring — at the thesis horizon</span>
				<p class="muted">Attribution asks the two questions once the horizon named in the thesis
					passes. A profit on a wrong view is recorded as <strong>luck</strong> and teaches
					nothing. Calibration then scores every stated probability with a Brier score and its
					Murphy decomposition.</p></div>
		</div>
		<div class="quote" style="margin-top:1rem">
			<p>Attribution is deliberately expensive to earn: promotion past the second rung requires
				that most resolved theses were actually explicable. A book of luck is not competence,
				however good the P&amp;L looks.</p>
		</div>
	</div>
</section>

<section class="block ledger">
	<div class="wrap">
		<span class="kicker">Stage 5 · Remember</span>
		<h2 style="margin:.4rem 0 .8rem">Four stores, one for each kind of knowledge.</h2>
		<div class="cols c4">
			<div class="card stage"><h3>journal</h3><p class="muted">Append-only events. What
				happened, when, and which model said so. Never rewritten.</p></div>
			<div class="card stage"><h3>wiki</h3><p class="muted">Stable reference that rewrites
				itself: position pages, company dossiers, the regime page.</p></div>
			<div class="card stage"><h3>elfmem</h3><p class="muted">Evolving memory with decay and
				reinforcement — credited by verdict, never by raw P&amp;L.</p></div>
			<div class="card stage"><h3>ledger</h3><p class="muted">Every falsifiable claim ever
				made, traded or not — the trial count a multiple-testing correction needs.</p></div>
		</div>
		<p class="lead" style="margin-top:1rem">The ledger is the quiet one that matters most.
			<strong>Forecasts on setups declined are scored too</strong>, at zero capital risk — the
			only realistic route to a calibration sample that means anything inside a week.</p>
	</div>
</section>

<section class="block ledger">
	<div class="wrap">
		<span class="kicker">Technology implementation</span>
		<h2 style="margin:.4rem 0 .8rem">How Alpaca is used — and three things that were harder than they look.</h2>
		<div class="cols c3">
			<div class="card"><h3>MCP, one session per tick</h3>
				<p class="muted">Alpaca's MCP server runs as a local stdio subprocess. The adapter's
					default spawns a fresh process <em>per tool call</em> — six calls cost 12.3s. Sharing
					one session across the tick cut it to 2.75s.</p>
				<p class="fine">−78% wall clock, measured</p></div>
			<div class="card"><h3>Real multi-leg options orders</h3>
				<p class="muted">Verticals go as <code>mleg</code> tickets with per-leg
					<code>position_intent</code>. Calendars and diagonals are <strong>refused</strong>,
					not approximated — pricing the far leg needs a model this deliberately does not have.</p>
				<p class="fine">a confident wrong payoff is worse than a refusal</p></div>
			<div class="card"><h3>Only 19 of 72 tools bound</h3>
				<p class="muted">Binding all 72 MCP tools cost ~21k tokens of schema <em>per call</em>,
					71% of it for tools never used once — and a bigger menu measurably worsens tool
					selection.</p>
				<p class="fine">$3.46 &rarr; $1.32 per decide cycle</p></div>
		</div>
		<div class="card" style="border-left:3px solid var(--caution); margin-top:1rem">
			<p><strong>The lesson that generalises.</strong> All three of those had already shipped as
				code that ran and did nothing — each looked healthy in the logs. That is why
				<code>trdrbot health</code> exists and asks a different question from the tests:
				<em>"you ran, but did you produce anything?"</em></p>
		</div>
	</div>
</section>

<section class="block ledger">
	<div class="wrap">
		<div class="cols c3">
			<div>
				<span class="kicker">Go deeper</span>
				<h2 style="margin-top:.5rem">Risk &amp; sizing.</h2>
				<p class="standfirst" style="margin-top:.6rem">Kelly on the conditional payoff, the
					calibration shrink, the three caps, and the two rules the agent cannot override.</p>
				<a class="btn ghost sm" style="margin-top:.9rem" href="/how-it-works/risk">
					Read the risk model <Icon name="arrowRight" size={14} /></a>
			</div>
			<div>
				<span class="kicker">See it live</span>
				<h2 style="margin-top:.5rem">The Coach.</h2>
				<p class="standfirst" style="margin-top:.6rem">Subsystems that improve themselves —
					paired A/B trials on the muse's prompt, promoted only on real evidence.</p>
				<a class="btn ghost sm" style="margin-top:.9rem" href="/coach-report.html" target="_blank" rel="noopener noreferrer">
					Open the live report <Icon name="external" size={14} /></a>
			</div>
			<div>
				<span class="kicker">The record</span>
				<h2 style="margin-top:.5rem">Every decision.</h2>
				<p class="standfirst" style="margin-top:.6rem">Trades, declines and resolved forecasts,
					newest first, in the agent's own words.</p>
				<a class="btn ghost sm" style="margin-top:.9rem" href="/ledger">
					Open the ledger <Icon name="arrowRight" size={14} /></a>
			</div>
		</div>
	</div>
</section>

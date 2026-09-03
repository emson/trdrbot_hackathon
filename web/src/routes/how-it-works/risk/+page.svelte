<script>
	import Term from '$lib/components/Term.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
</script>

<svelte:head><title>Risk & sizing — trdrbot</title></svelte:head>

<section class="block ledger">
	<div class="wrap">
		<PageHeader kicker="Risk" back={{ href: '/how-it-works', label: 'how it works' }}>
			{#snippet heading()}There is no approval gate. The math is the guardrail.{/snippet}
			No separate step vetoes an LLM decision after the fact. What replaces it is stricter:
			<strong>the agent cannot execute a mistake the sizing math itself refuses to compute.</strong>
			A "no trade" verdict from any gate is a correct answer, not a fallback.
		</PageHeader>
	</div>
</section>

<section class="block ledger" style="padding-top:0">
	<div class="wrap">
		<div class="cols c2">
			<div class="card pad-lg">
				<h3>Kelly, on the conditional payoff</h3>
				<p class="muted">Sized from <Term name="Conditional payoff" /> — E[win|win] /
					E[loss|loss] — rather than the naive max/max ratio, which is measurably biased toward
					buying premium. The probability that feeds it is not what the agent stated; it is
					that number <strong>shrunk toward the agent's own measured calibration</strong>. A
					90%-caller who's right half the time gets cut down hard. A 70%-caller whose 70%s
					actually land 70% of the time earns the full fraction.</p>
			</div>
			<div class="card pad-lg">
				<h3>Unbounded loss is refused outright</h3>
				<p class="muted">Kelly refuses any structure with unbounded <em>loss</em> — a naked
					short is never sizeable, full stop. Unbounded <em>profit</em> is fine: a long call is
					not a naked short, and the asymmetry runs entirely one direction on purpose.</p>
			</div>
			<div class="card pad-lg">
				<h3>Capped three ways at once</h3>
				<p class="muted">Per-position, per-underlying, and whole-book, all denominated in
					dollars of defined max loss — nested so a position can never exceed its underlying's
					share, which can never exceed the book's. A payoff the sizing tool can't verify
					against a real simulated structure <strong>refuses to size at all</strong>, rather than
					falling back to an optimistic estimate.</p>
			</div>
			<div class="card pad-lg">
				<h3>Exit rules are the agent's own commitments</h3>
				<p class="muted">One signal registry: every rule reads a signal, compares to a
					threshold, debounces against quote artifacts. Thesis-level stops watch the
					<strong>underlying</strong>, not the noisy option mark — a percent-of-debit stop is
					routinely a coin flip on path noise if it's expressed as a percent of the wrong base.</p>
			</div>
		</div>
	</div>
</section>

<section class="block ledger">
	<div class="wrap">
		<h2>Two rules the agent cannot override.</h2>
		<p class="standfirst" style="margin-top:.5rem">Every other exit rule is authored by the agent
			itself, per position. These two are not — they exist regardless of what any thesis claims.</p>
		<div class="cols c2" style="margin-top:1.2rem">
			<Callout eyebrow="Competition-deadline sweep">
				Every position is closed before the competition deadline, no exceptions — holding into
				an event the record can't be scored past is not a risk worth taking for its own sake.
			</Callout>
			<Callout eyebrow="A vanished leg closes the position outright" tone="caution">
				If a leg disappears at the broker (early assignment), the survivor of a broken spread
				can be an <strong>unbounded naked position</strong> — worse than the one it replaced.
				This rule exists so that scenario is never left open, deliberately or by omission.
			</Callout>
		</div>
	</div>
</section>

<section class="block ledger">
	<div class="wrap">
		<h2>One number the operator sets, and the agent cannot.</h2>
		<p class="standfirst" style="margin-top:.5rem">
			Everything above is <em>earned</em> — the ladder decides how much size the record
			justifies. <strong>Risk appetite</strong> is the one quantity on that posture the agent
			did not earn and may not touch: a single scalar in <span class="code">agent/config.yaml</span>,
			clamped to <span class="code">[0.25, 2.0]</span>, where 1.0 means "the posture the ladder
			alone would choose".
		</p>
		<div class="cols c2" style="margin-top:1.2rem">
			<div class="card pad-lg">
				<h3>One multiplication, four scopes</h3>
				<p class="muted">It scales the book cap, and the per-name cap, per-position cap and
					exploration floor all <strong>derive</strong> from that — so one number reaches every
					risk scope at once and they cannot drift apart. Two clamps in the original design
					were dropped after measurement: one provably could never fire, and the other became
					wrong once the floor derived. What remains is a single absolute ceiling on the share
					of the account that can be at risk at all. <strong>The lever moves the
					growth/variance tradeoff; it never moves the ruin bound.</strong></p>
			</div>
			<div class="card pad-lg">
				<h3>It scales size, not selectivity</h3>
				<p class="muted">The EV gate sits <em>upstream</em> of every multiplication, so no
					setting buys a trade that isn't worth taking — maximum appetite on a structure with
					no claimed edge still returns zero contracts. Turning it down does not make the agent
					pickier, and that is deliberate: a lever that loosened the gate would buy bets with
					<em>lower</em> expected return <em>and</em> higher variance. There is no curve to sit
					on there.</p>
			</div>
			<div class="card pad-lg">
				<h3>A knob that cannot silently do nothing</h3>
				<p class="muted">Above 1.75× the book cap pins at its absolute ceiling and further
					turns are absorbed. So the posture reports its <strong>realised</strong> appetite
					beside the requested one, the health check flags a divergence, and the sizer now names
					<em>which</em> of five limits set every size. This project's most expensive bug class
					is code that runs and does nothing; a risk knob is a prime candidate for it.</p>
			</div>
			<div class="card pad-lg">
				<h3>Never a self-improvement lever</h3>
				<p class="muted">The Coach can change prompts. It cannot reach this: it writes only to
					its own lever directory, never to config, and the rule that nothing it can move may
					score its own trial makes that structural rather than a policy. <strong>Risk appetite
					is the principal's preference, not the agent's.</strong> The agent is told the number
					so its reasoning matches its budget — and told plainly that it scales size, not what
					is worth trading.</p>
			</div>
		</div>
		<p class="standfirst" style="margin-top:1.2rem">
			It currently sits at <strong>0.50×</strong>, and the arithmetic is the argument: it
			reproduces the book's existing position size exactly at its current rung, so the mechanism
			landed without changing a single trade. The honest case for going lower is on the table and
			deliberately not taken yet — at neutral, a &gt;20% drawdown becomes more likely than not
			<em>even when the thesis is right</em>, and for a book that has resolved forecasts but
			<strong>zero attributed positions</strong>, the growth-maximising setting is the minimum.
		</p>
	</div>
</section>

<section class="block ledger">
	<div class="wrap">
		<h2>Facts and models, never mixed.</h2>
		<p class="standfirst" style="margin-top:.5rem">
			Payoff at expiry, max loss, and breakevens are arithmetic on the contract — labelled
			<strong>FACT</strong> everywhere they appear on this site, exactly as on every trade page.
			Probability of profit and expected value need a distribution and are labelled
			<strong>MODELLED</strong>. The agent sees them under separate headings, on purpose, so
			neither is mistaken for the other.
		</p>
		<h2 style="margin-top:2rem">Costs are charged before the decision.</h2>
		<p class="standfirst" style="margin-top:.5rem">
			Two expected-value columns sit side by side: EV under the market's own drift — where a
			fairly priced structure is worth about nothing, so after friction it's negative for
			everything, always — and EV under the drift the thesis actually claims. A thesis that
			can't move the second column is decorative.
		</p>
	</div>
</section>

<section class="block ledger">
	<div class="wrap">
		<div class="cols c2">
			<a class="card" href="/resources/risk-appetite-explorer.html">
				<span class="tag code">Interactive</span>
				<h3>Risk Appetite Explorer</h3>
				<p class="muted">Drag the risk lever and watch what happens to the money over 50
					trades — the asymmetry between winning bigger and losing your seat entirely.</p>
			</a>
			<a class="card" href="/risk-research.html" target="_blank" rel="noopener noreferrer">
				<span class="tag code">Research</span>
				<h3>Risk appetite — the write-up</h3>
				<p class="muted">The full reasoning behind where the risk lever sits, and why.</p>
			</a>
		</div>
	</div>
</section>

<script>
	import Term from '$lib/components/Term.svelte';
	import Callout from '$lib/components/Callout.svelte';
</script>

<svelte:head><title>Risk & sizing — trdrbot</title></svelte:head>

<section class="block ledger">
	<div class="wrap">
		<a href="/how-it-works" class="fine" style="text-decoration:none">&larr; how it works</a>
		<span class="kicker" style="display:block; margin-top:1rem">Risk</span>
		<h1 style="margin:.5rem 0 .8rem">There is no approval gate. The math is the guardrail.</h1>
		<p class="standfirst">
			No separate step vetoes an LLM decision after the fact. What replaces it is stricter:
			<strong>the agent cannot execute a mistake the sizing math itself refuses to compute.</strong>
			A "no trade" verdict from any gate is a correct answer, not a fallback.
		</p>
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
			<a class="card" href="/resources/risk-appetite-explorer">
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

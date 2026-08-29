# Are "cognitive modules" the right frame for this system?

**Question.** Should subsystems like the muse, coach, decider, memory and calibration become
explicit cognitive modules that can each be independently improved and evolved? Is identifying
and carefully structuring subsystems the way to think about a system like this?

**Researched 2026-08-29** (web, decision mode). Feeds the refactoring plan.

---

## Answer

**Yes - with one inversion.** The literature strongly supports organising an LLM agent as
modules mapped to cognitive functions (this system is already accidentally CoALA-shaped).
But the thing that makes a module *evolvable* is not the module boundary - it is the
**evaluator attached to it**. Modularity is the precondition; the metric + trial harness +
owned policy state is the mechanism. A refactor that produces beautiful module boundaries
without per-module metrics buys nothing; one that gives each module its own measurable
policy surface generalises what the Coach already proved on one lever.

And the **evolvable unit should be the module's policy artifacts (prompts, thresholds,
config), never its code** - which independently confirms the Coach's existing
touches-data-never-code rule as the correct design, not just the cautious one.

## Evidence

### 1. The cognitive-module frame is the established one (CoALA)

[CoALA - Cognitive Architectures for Language Agents](https://arxiv.org/abs/2309.02427)
(Sumers, Yao, Narasimhan, Griffiths) is the canonical framework: an agent = **memory modules**
(working + episodic/semantic/procedural long-term), a **structured action space** (internal:
retrieval / reasoning / learning; external: grounding), and a **decision procedure** cycling
over them. Mapping trdrbot onto it is almost mechanical:

| CoALA concept | trdrbot today |
|---|---|
| Episodic memory | journal, ledger |
| Semantic memory | wiki (dossiers, techniques, regime) |
| Procedural memory | prompts, constitution, lessons, lever state |
| Retrieval actions | elfmem recall, wiki reads |
| Reasoning/proposal | muse, research, discovery |
| Grounding actions | Alpaca MCP tools |
| Learning actions | attribution, lessons, calibration, coach |
| Decision procedure | tick's decide cycle |

The lineage (SOAR/ACT-R) adds the warning that module boundaries should sit at **memory and
action seams**, not at reasoning microsteps.

### 2. The evolvable unit is policy-as-data, validated by an evaluator

- [DSPy](https://dspy.ai/) is the cleanest production statement: **signatures** (the module
  contract) stay fixed; **optimizers** tune prompts and few-shot demos **against a metric on a
  devset**. The module is the stable unit; the prompt is the evolvable one; the metric is what
  makes evolution possible at all.
- [AlphaEvolve](https://arxiv.org/abs/2506.13131) does evolve code - but every write-up,
  including [OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve) and the
  [architecture analyses](https://www.emergentmind.com/topics/alphaevolve-paradigm), converges
  on the same point: *"the most important architectural decision is not the LLM or the
  selection strategy. It is the evaluator."* AlphaEvolve affords code evolution only because
  its evaluators are cheap, deterministic and perfectly discriminating. Trading has the
  opposite evaluator: slow, noisy, expensive (weeks per resolved thesis, n=1 calibration). So
  code-evolution is out of reach here and prompt/config evolution is the right ceiling.
- The [self-evolving agents survey](https://arxiv.org/abs/2507.21046) (what/when/how to
  evolve) taxonomises the evolvable components as model, prompts, memory, tools,
  workflow/architecture - and the feedback signal (scalar reward vs textual feedback) as the
  design choice that shapes everything else. The Coach's gate-survival fraction is a scalar
  reward; attribution's held/failed verdicts are textual-feedback raw material.
- Voyager's evolvable unit is a growing library of *verified* code skills, validated by the
  game environment `[from training data - verify if load-bearing]` - same pattern: the
  evolvable artifact is data (a skill library), admitted only by an evaluator.

### 3. Production practice agrees, and warns against the failure mode

- Anthropic's [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents):
  simple composable patterns beat frameworks; add complexity only when it demonstrably wins;
  know when a fixed **workflow** (predefined path) beats an **agent** (dynamic control).
  trdrbot's deterministic gauntlets, exit-rule evaluator and sensors are workflows; only
  decide/muse/research/discovery are agents - the refactor should keep that split crisp.
- [12-Factor Agents](https://www.humanlayer.dev/12-factor-agents): own your prompts, own your
  context window, small focused agents, mostly deterministic code with LLM decision points.
  trdrbot already complies unusually well; prompt fingerprinting (D-045) is "own your prompts"
  taken further than most.
- 2026 eval-harness practice ([Confident AI](https://www.confident-ai.com/blog/llm-agent-evaluation-complete-guide),
  [TDS 12-metric framework](https://towardsdatascience.com/building-an-evaluation-harness-for-production-ai-agents-a-12-metric-framework-from-100-deployments/)):
  evaluate at component level AND trajectory level; regression datasets grow from production
  failures (exactly what test_regressions.py already is); the teams shipping agents
  successfully "aren't the ones with the best models - they're the ones with the best
  evaluation infrastructure."
- The [bitter-lesson critique](https://www.lowtouch.ai/rethinking-ai-agent-scaffolding-embracing-the-bitter-lesson-for-scalable-automation/):
  elaborate cognitive scaffolding gets washed away by better models. Implication: put module
  boundaries at seams that *survive model improvement* - data stores, metrics, evaluation,
  provenance - not at reasoning microstructure. A better model makes a hand-built
  plan-then-critique-then-revise pipeline obsolete; it makes a calibration ledger MORE
  valuable.

### 4. The coordination pattern is already right

The inbox is a textbook **blackboard**: independent knowledge sources (research, discovery,
muse, sensors) post typed items to a shared workspace; a consumer drains it. 2025-26 work on
[blackboard multi-agent systems](https://arxiv.org/abs/2510.01285) finds this outperforms
coordinator-driven ("master-slave") designs for heterogeneous sources - 13-57% relative
end-to-end gains in their benchmarks. Keep the inbox as the seam; resist any temptation to
have sources call each other.

## What this means for the refactor

A **cognitive module** here should mean something precise, not decorative:

1. **A stable contract** - typed inputs/outputs at its seam (inbox items in, verdicts out),
   so a module can be rewritten without touching its neighbours.
2. **An owned policy surface** - its prompt(s), thresholds and config live as versioned,
   fingerprinted data the module reads at runtime (the Coach's lever files, generalised).
3. **Its own metric** - a number that says whether it is doing its job, computable without
   waiting for P&L where possible (gauntlet survival rate, calibration Brier, attribution
   rate, candidates-per-run). No metric → not evolvable → be honest that it's a fixed
   workflow, which is fine.
4. **Its own heartbeat, separate from its output** (the existing health rule) and its own
   regression tests.
5. **An optional trial-harness hook** - registering a policy artifact as a Coach lever should
   be cheap and uniform, not bespoke per lever.

The boundary test: *a module is correctly drawn iff it can be improved without editing another
module's code, judged by its own metric, and rolled back by reverting its own state.*

What NOT to do, per the same sources: no plugin framework, no message-bus middleware, no
module base-class hierarchy, no splitting things that always change together. Anthropic's rule
stands - the simplest composable shape that gives each module the five properties above.

## What would change this conclusion

- If a much stronger model made single-prompt end-to-end trading decisively better than the
  pipeline (bitter-lesson scenario), module boundaries at the reasoning level would dissolve -
  but the data/metric/provenance seams would survive and become the new system's substrate.
- If the Coach's forward audit (I-28) showed gauntlet-survival optimising the wrong thing,
  "per-module proximate metrics" would need re-grounding against horizon outcomes before
  being generalised to more modules.

## Sources

- [CoALA: Cognitive Architectures for Language Agents (arXiv 2309.02427)](https://arxiv.org/abs/2309.02427)
- [DSPy](https://dspy.ai/) · [Pipelines & Prompt Optimization with DSPy (dbreunig)](https://www.dbreunig.com/2024/12/12/pipelines-prompt-optimization-with-dspy.html)
- [AlphaEvolve (arXiv 2506.13131)](https://arxiv.org/abs/2506.13131) · [OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve) · [AlphaEvolve paradigm analysis](https://www.emergentmind.com/topics/alphaevolve-paradigm)
- [A Survey of Self-Evolving Agents (arXiv 2507.21046)](https://arxiv.org/abs/2507.21046) · [Awesome-Self-Evolving-Agents](https://github.com/XMUDeepLIT/Awesome-Self-Evolving-Agents)
- [Anthropic - Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)
- [12-Factor Agents (HumanLayer)](https://www.humanlayer.dev/12-factor-agents) · [HN discussion](https://news.ycombinator.com/item?id=43699271)
- [LLM-Based Multi-Agent Blackboard System (arXiv 2510.01285)](https://arxiv.org/abs/2510.01285)
- [Rethinking AI Agent Scaffolding / bitter lesson (lowtouch.ai)](https://www.lowtouch.ai/rethinking-ai-agent-scaffolding-embracing-the-bitter-lesson-for-scalable-automation/)
- [LLM Agent Evaluation Metrics 2026 (Confident AI)](https://www.confident-ai.com/blog/llm-agent-evaluation-complete-guide) · [12-metric eval harness framework (TDS)](https://towardsdatascience.com/building-an-evaluation-harness-for-production-ai-agents-a-12-metric-framework-from-100-deployments/)

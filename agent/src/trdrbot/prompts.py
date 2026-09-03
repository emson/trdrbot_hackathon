"""Prompt inventory and fingerprinting (D-045).

The prompt surface is ~3,100 tokens across eight artefacts, and it is NOT
homogeneous - which is why "move all prompts into a prompts/ directory" is the
wrong shape:

  free-standing (4)  SYSTEM_PROMPT, RESEARCH, NOMINATE, SYNTH. Pure text.
                     Safely extractable; nothing but the LLM reads them.
  tool contracts (3) simulate_experiments / size_position / record_position
                     docstrings. 1,100 tokens - a third of the surface - but
                     each is the documented contract of a live function
                     signature. Moving one to a file lets it drift from the
                     parameters it describes, which is this project's most
                     familiar failure class: a thing that reads correct and
                     silently is not.
  ratified (1)       the constitution. Already external, in elfmem, with its
                     own change control and human ratification (D-041). It
                     must not acquire a second home.

So this module does the one thing that is genuinely needed now and CANNOT be
added retroactively: it fingerprints what was actually in play, so every
journalled decision carries the identity of the prompts that produced it. A
decision recorded today without that label can never be compared against
tomorrow's - provenance is the part of A/B testing with a deadline, and the
variant machinery is the part that can wait for a real second variant.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


def fingerprint(text: str) -> str:
    """THE prompt-identity hash. `coach.fingerprint` delegates here - a second
    scheme is how two identities for one artefact begin, and lever state files
    on disk already carry this one's output."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


@dataclass(frozen=True)
class PromptRef:
    name: str
    kind: str  # free_standing | tool_contract | ratified
    text: str

    @property
    def fingerprint(self) -> str:
        """Stable 8-hex digest of the exact text sent to the model."""
        return fingerprint(self.text)

    @property
    def tokens(self) -> int:
        return len(self.text) // 4


def _active_muse_prompt(config: Any = None) -> str:
    """The muse prompt variant currently live, falling back to the seed.

    `config` is PASSED now. Self-loading here meant `config.load(quiet=True)` -
    and therefore `load_dotenv(override=True)` plus a mkdir of every path - ran
    inside `fingerprints()`, which runs on EVERY decision write. A hashing
    helper had become one of the tick's filesystem writers.

    Never raises: an inventory that cannot be produced would take `trdrbot
    prompts` and every journalled decision's provenance down with it, and the
    seed is always a truthful answer to "what would run if the Coach were not
    here".
    """
    from .muse import MUSE_PROMPT

    try:
        from . import coach
        from . import config as _cm

        cfg = config if config is not None else _cm.load(quiet=True)
        return coach.load_state(cfg, "muse.prompt", MUSE_PROMPT).incumbent.text
    except Exception:  # noqa: BLE001
        return MUSE_PROMPT


def _active_lever_text(config: Any, lever_name: str, module: str, attr: str) -> str:
    """`_active_muse_prompt`, generalised: the lever's live incumbent, falling
    back to its in-code seed. Never raises, for the same reason."""
    import importlib

    seed = str(getattr(importlib.import_module(module), attr, ""))
    try:
        from . import coach
        from . import config as _cm

        cfg = config if config is not None else _cm.load(quiet=True)
        return coach.load_state(cfg, lever_name, seed).incumbent.text
    except Exception:  # noqa: BLE001
        return seed


def inventory(tools: list[Any] | None = None, config: Any = None) -> list[PromptRef]:
    """Everything authored that a model reads. Tools passed in when available."""
    from .constitution import PRINCIPLES
    from .discovery import NOMINATE_PROMPT, SYNTH_PROMPT
    from .llm import SYSTEM_PROMPT
    from .research import RESEARCH_PROMPT

    refs = [
        PromptRef("decide.system", "free_standing", SYSTEM_PROMPT),
        PromptRef("research.daily", "free_standing", RESEARCH_PROMPT),
        PromptRef("discovery.nominate", "free_standing", NOMINATE_PROMPT),
        PromptRef("discovery.synthesise", "free_standing", SYNTH_PROMPT),
        # The muse's prompt is a Coach LEVER, so the artefact actually in play
        # is whatever variant is currently incumbent - not the in-code default,
        # which after one promotion is merely the seed it started from. Reading
        # the constant here would fingerprint a prompt nothing is running, and
        # a provenance record that names the wrong artefact is worse than none.
        PromptRef("muse.collide", "free_standing", _active_muse_prompt(config)),
        # The playbook's catalogue is the second lever, and for the same
        # reason the artefact in play is the state incumbent, not the seed.
        PromptRef("playbook.catalogue", "free_standing", _active_lever_text(
            config, "playbook.catalogue", "trdrbot.playbook", "SEED_CATALOGUE")),
    ]
    # The two artefacts this inventory used to omit while its own docstring
    # claimed eight. Neither is a lever: the mutation prompt is the Coach's own
    # instrument and the extraction prompt is a fixed cheap-model contract.
    from .coach import MUTATE_PROMPT
    from .news_extract import EXTRACT_PROMPT

    refs.append(PromptRef("coach.mutate", "free_standing", MUTATE_PROMPT))
    refs.append(PromptRef("news.extract", "free_standing", EXTRACT_PROMPT))
    for t in tools or []:
        refs.append(PromptRef(f"tool.{t.name}", "tool_contract", t.description or ""))
    refs.append(PromptRef(
        "constitution", "ratified",
        "\n".join(p.text for p in PRINCIPLES),
    ))
    return refs


def fingerprints(tools: list[Any] | None = None, config: Any = None) -> dict[str, str]:
    """{name: fingerprint} for journalling on a decision.

    Called with no tools at decision time - the tool objects are built after
    the decision row is written, and referencing them there was a NameError
    waiting for the next decide cycle. Tool contracts are stable per release
    anyway; `trdrbot prompts` reports them in full.
    """
    return {r.name: r.fingerprint for r in inventory(tools, config)}


def render_inventory(refs: list[PromptRef]) -> str:
    by_kind: dict[str, list[PromptRef]] = {}
    for r in refs:
        by_kind.setdefault(r.kind, []).append(r)
    lines = ["", "=== prompt inventory ===", ""]
    total = 0
    for kind in ("free_standing", "tool_contract", "ratified"):
        group = by_kind.get(kind, [])
        if not group:
            continue
        lines.append(f"{kind} ({len(group)}):")
        for r in group:
            lines.append(f"  {r.name:<28} {r.fingerprint}  ~{r.tokens:>4} tok")
            total += r.tokens
        lines.append("")
    lines.append(f"{len(refs)} artefacts, ~{total} tokens of authored prompt surface.")
    lines.append("")
    return "\n".join(lines)

"""Config, secrets and storage paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Paths:
    root: Path
    data: Path
    inbox_pending: Path
    inbox_processed: Path
    inbox_failed: Path
    journal: Path
    wiki: Path
    state: Path
    #: One markdown story per position, for outside review - not the machine
    #: record (that's the journal/positions), a human-readable one meant to be
    #: published (D-097).
    blog: Path

    @classmethod
    def build(cls, root: Path) -> Paths:
        data = root / "data"
        return cls(
            root=root,
            data=data,
            inbox_pending=data / "inbox" / "pending",
            inbox_processed=data / "inbox" / "processed",
            inbox_failed=data / "inbox" / "failed",
            journal=data / "journal.jsonl",
            wiki=data / "wiki",
            state=data / "state",
            blog=data / "blog",
        )

    def ensure(self) -> None:
        for p in (
            self.inbox_pending,
            self.inbox_processed,
            self.inbox_failed,
            self.wiki / "positions",
            self.wiki / "context",
            self.state,
            self.blog,
        ):
            p.mkdir(parents=True, exist_ok=True)
        self.journal.touch(exist_ok=True)


@dataclass(frozen=True)
class Config:
    raw: dict[str, Any]
    paths: Paths

    @property
    def model(self) -> str:
        # The primary of the default chain. Kept because it is journalled on
        # every decision as the model that made it - but note the chain may
        # fall through, so `usage.jsonl` records the model that ACTUALLY
        # served, which is the billing-accurate one (D-062).
        llm = self.raw.get("llm") or {}
        if llm.get("model"):
            return str(llm["model"])
        chain = self.model_chain("decide")
        return chain[0] if chain else ""

    @property
    def max_tokens(self) -> int:
        return int(self.raw["llm"].get("max_tokens", 8000))

    @property
    def watchlist(self) -> list[str]:
        return list(self.raw["trading"]["watchlist"])

    @property
    def deadline(self) -> str | None:
        """A hard stop, or None to run indefinitely (D-101).

        None is a FIRST-CLASS state, not a degraded one: `can_open` is inert
        without it, the deadline exit rule reads an unobservable signal and
        holds, and `forecast_window` still returns a window because short
        horizons are a property of good forecasting rather than of a
        competition. What None must never mean is "unbounded horizons".

        A present-but-unparseable date raises here, at process start, before
        any trade - the same rule `risk_appetite` follows. Silently treating a
        typo as "no deadline" would disarm the force-close sweep and every
        expiry gate at once, which is the loudest thing in this file.
        """
        raw = (self.raw.get("trading") or {}).get("deadline")
        if raw in (None, "", False):
            return None
        from datetime import date as _date
        try:
            _date.fromisoformat(str(raw))
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                f"trading.deadline is {raw!r}, which is not an ISO date "
                f"(YYYY-MM-DD). Remove the key or set it to null to run with "
                f"no hard stop; do not leave it unparseable."
            ) from exc
        return str(raw)

    @property
    def risk_appetite(self) -> float:
        """The operator's size preference. 1.0 = the posture the competence
        ladder alone would choose (D-099).

        Clamped in `competence.assess`, deliberately NOT here: one clamp, at the
        point of use, so no caller can hold an unclamped value and no second
        place has to agree about the range.

        An ABSENT key means 1.0, never 0 - the same rule `coach` states, for the
        same reason. A non-numeric value raises here, at process start, before
        any trade: that is where a config typo should stop things.

        `bool` is rejected explicitly because YAML's `true` is a plausible typo
        for a numeric knob and `float(True)` is 1.0 - which would read as
        "neutral" and change the book's risk in silence.
        """
        raw = (self.raw.get("trading") or {}).get("risk_appetite", 1.0)
        if isinstance(raw, bool):
            raise RuntimeError(
                f"trading.risk_appetite is {raw!r}; it is a number in "
                f"[{0.25}, {2.0}] where 1.0 is neutral, not a flag."
            )
        return float(raw)

    @property
    def max_retries(self) -> int:
        return int(self.raw["inbox"]["max_retries"])

    @property
    def watchdog_seconds(self) -> float:
        # float, not int: this bounds an `asyncio.wait_for`, and a test that
        # wants a sub-second watchdog should not have it silently truncated
        # to zero. Production values are whole seconds either way.
        return float(self.raw["tick"]["watchdog_seconds"])

    def model_chain(self, role: str = "decide") -> list[str]:
        """Ordered fallback chain for a role (D-062).

        Resolution order: `llm.roles.<role>` -> `llm.models` -> the legacy
        single `llm.model`. The legacy key still works untouched, so an
        existing config keeps running with no edit and picks up fallback only
        when it opts in.
        """
        llm = self.raw.get("llm") or {}
        roles = llm.get("roles") or {}
        chain = roles.get(role) or llm.get("models") or []
        if isinstance(chain, str):
            chain = [chain]
        if not chain and llm.get("model"):
            chain = [llm["model"]]
        return [str(m) for m in chain if m]

    def resolve_model_spec(self, spec: str) -> tuple[str, dict[str, Any]]:
        """A configured `"prefix:model"` -> the spec `init_chat_model` accepts,
        plus any connection kwargs (`base_url`, `api_key`) to pass alongside it.

        `init_chat_model`'s provider table (`_BUILTIN_PROVIDERS`) is a fixed
        set baked into langchain-core - `"openai"`, `"anthropic"`, etc. - and
        every model behind one prefix shares one endpoint and one API key by
        construction. That breaks the moment a SECOND OpenAI-COMPATIBLE
        service needs to sit in the same chain as real OpenAI: OpenCode Zen
        serves GLM-5.2 over the identical `/v1/chat/completions` contract
        `ChatOpenAI` already speaks, but at its own base_url and its own key,
        and `openai:gpt-5` in the same `llm.models` list must keep hitting
        OpenAI's real endpoint unchanged.

        `llm.providers.<name>` names the langchain provider that actually
        SERVES the traffic (`openai` for any OpenAI-compatible gateway) plus
        `base_url` and `api_key_env`. A spec prefixed with a declared provider
        name - `"opencode_zen:glm-5.2"` - resolves to `("openai:glm-5.2",
        {"base_url": ..., "api_key": <env value>})`; every other spec passes
        through untouched, so `"anthropic:claude-opus-5"` and `"openai:gpt-5"`
        are unaffected. This is the ONE place that resolution happens - both
        `build_model()` and `doctor`'s independent probe loop call it, so they
        cannot silently diverge on what a spec means.
        """
        prefix, _, model = spec.partition(":")
        providers = (self.raw.get("llm") or {}).get("providers") or {}
        entry = providers.get(prefix)
        if entry:
            real_provider = entry.get("langchain_provider", "openai")
            kwargs: dict[str, Any] = {}
            if entry.get("base_url"):
                kwargs["base_url"] = entry["base_url"]
            key_env = entry.get("api_key_env")
            if key_env:
                key = os.environ.get(key_env)
                if not key:
                    raise RuntimeError(
                        f"{spec}: provider {prefix!r} needs {key_env} set (see .env.example)."
                    )
                kwargs["api_key"] = key
            real_spec = f"{real_provider}:{model}"
        else:
            real_spec, kwargs = spec, {}

        # A model-specific construction quirk, keyed on the spec AS WRITTEN in
        # `models`/`roles` - not the resolved one - because that is the string
        # an operator actually reads and writes in config.yaml. Composes with
        # the provider override above rather than replacing it.
        #
        # The motivating case: gpt-5.6-sol refuses tool calls on the classic
        # Chat Completions endpoint the moment reasoning is active - a live
        # 400 named the exact fix: `use_responses_api=True`
        # (langchain_openai's own flag) or `reasoning_effort="none"`.
        # use_responses_api was chosen because it keeps full reasoning; NONE
        # of this is a `providers:` concern - it is one model's own API
        # surface, and applying it globally would break `ChatAnthropic`,
        # which has no such kwarg, the moment Claude shared a chain with it.
        opts = ((self.raw.get("llm") or {}).get("model_options") or {}).get(spec) or {}
        return real_spec, {**kwargs, **opts}

    @property
    def pricing(self) -> dict:
        """{model: {input, output}} in USD per MILLION tokens. Operator-supplied."""
        return (self.raw.get("llm") or {}).get("pricing") or {}

    @property
    def coach(self) -> dict[str, Any]:
        """Self-improvement loop settings (D-088). An ABSENT block means
        defaults, never OFF - a missing config section that silently disables a
        subsystem is the absence-as-zero class this project keeps finding."""
        return dict(self.raw.get("coach") or {})

    @property
    def decide_tools(self) -> list[str]:
        """MCP tools bound to the decide agent. Empty list = bind everything
        (the pre-D-065 behaviour, kept as the fallback so a missing config
        section degrades to working-but-expensive, never to broken)."""
        return list((self.raw.get("decide") or {}).get("tools") or [])

    @property
    def events(self) -> list[dict]:
        return list(self.raw.get("events") or [])

    @property
    def research_universe(self) -> list[str]:
        return list((self.raw.get("research") or {}).get("universe") or self.watchlist)

    @property
    def polymarket_queries(self) -> list[str]:
        return list((self.raw.get("polymarket") or {}).get("queries") or [])

    @property
    def decide_every_n_ticks(self) -> int:
        return int(self.raw["tick"].get("decide_every_n_ticks", 1))

    def alpaca_mcp_server(self) -> dict[str, Any]:
        """Config block for MultiServerMCPClient: a local stdio subprocess.

        Alpaca's hosted MCP endpoint authenticates via interactive browser
        OAuth, so a headless service cannot use it. The open-source server
        takes API keys from the environment instead.
        """
        a = self.raw["alpaca"]
        key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
        if not key or not secret:
            raise RuntimeError(
                "ALPACA_API_KEY / ALPACA_SECRET_KEY not set. Copy .env.example to "
                ".env and fill them in. (Note: the MCP server uses ALPACA_*, not "
                "the APCA_* names from the REST SDK.)"
            )
        return {
            "command": a["command"],
            "args": list(a["args"]),
            "transport": "stdio",
            "env": {
                "ALPACA_API_KEY": key,
                "ALPACA_SECRET_KEY": secret,
                "ALPACA_PAPER_TRADE": "true" if a.get("paper", True) else "false",
            },
        }


#: Secrets whose shell value silently shadowing .env is a confusing failure.
_SHADOWABLE = ("ANTHROPIC_API_KEY", "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "OPENAI_API_KEY")


def load(root: Path | None = None, *, quiet: bool = False) -> Config:
    """Load config, with the project's .env authoritative over the shell.

    `load_dotenv` defaults to override=False, so an exported shell variable
    silently wins over the .env file. That cost a debugging session: a stale
    exported ANTHROPIC_API_KEY shadowed a freshly-rotated valid key in .env,
    and every edit to .env appeared to do nothing.

    The project's .env is the project's configuration, so it wins - and when it
    overrides a *different* shell value we say so, because a silent override is
    the same class of confusion in the opposite direction.
    """
    root = root or ROOT
    env_path = root / ".env"

    before = {k: os.environ.get(k) for k in _SHADOWABLE}
    load_dotenv(env_path, override=True)

    if not quiet:
        for k, old in before.items():
            new = os.environ.get(k)
            if old and new and old != new:
                print(f"[config] .env overrode a different shell value for {k}")

    with (root / "config.yaml").open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    paths = Paths.build(root)
    paths.ensure()
    return Config(raw=raw, paths=paths)

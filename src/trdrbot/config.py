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

    @classmethod
    def build(cls, root: Path) -> "Paths":
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
        )

    def ensure(self) -> None:
        for p in (
            self.inbox_pending,
            self.inbox_processed,
            self.inbox_failed,
            self.wiki / "positions",
            self.wiki / "context",
            self.state,
        ):
            p.mkdir(parents=True, exist_ok=True)
        self.journal.touch(exist_ok=True)


@dataclass(frozen=True)
class Config:
    raw: dict[str, Any]
    paths: Paths

    @property
    def model(self) -> str:
        return self.raw["llm"]["model"]

    @property
    def max_tokens(self) -> int:
        return int(self.raw["llm"].get("max_tokens", 8000))

    @property
    def watchlist(self) -> list[str]:
        return list(self.raw["trading"]["watchlist"])

    @property
    def deadline(self) -> str:
        return self.raw["trading"]["deadline"]

    @property
    def max_retries(self) -> int:
        return int(self.raw["inbox"]["max_retries"])

    @property
    def watchdog_seconds(self) -> int:
        return int(self.raw["tick"]["watchdog_seconds"])

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

    with (root / "config.yaml").open() as f:
        raw = yaml.safe_load(f)
    paths = Paths.build(root)
    paths.ensure()
    return Config(raw=raw, paths=paths)

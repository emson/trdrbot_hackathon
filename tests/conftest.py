"""Shared fixtures and fakes.

Two rules this file exists to enforce, both from the testing principles:

- **Fresh fixtures, never a shared mutable directory.** Five call sites used
  to pass `Path("/tmp")` and really did create `/tmp/state` on the developer's
  machine.
- **Fake at the adapter boundary, never inside the module under test.**
  `FakeMem` stands in for `ElfmemAdapter` and honours its real contract; every
  store below is the REAL store on `tmp_path`, so a test exercises production
  code paths rather than a mock of them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from datetime import timedelta

from trdrbot import config as config_mod
from trdrbot import ids
from trdrbot.elfmem_adapter import ContextResult
from trdrbot.positions import Position


@pytest.fixture
def paths(tmp_path: Path) -> config_mod.Paths:
    """Real Paths, real directory tree, thrown away after the test."""
    p = config_mod.Paths.build(tmp_path)
    p.ensure()
    return p


def days_out(n: int) -> str:
    """An ISO date `n` days from the code's own today. D-032's rule for tests.

    Eight tests hardcoded "2026-09-02" as a horizon and "2026-09-03" as an
    expiry, which were tomorrow and the day after when written - and became
    TODAY and ONE DAY OUT when the calendar rolled, crossing the zero-day
    horizon branch and the 1-day implicit time stop. The suite failed on a
    clean tree the morning after, on every test that said "nothing should
    close". A fixture date is derived from today or it is a countdown.
    """
    return (ids.today() + timedelta(days=n)).isoformat()


def occ(underlying: str, expiry_iso: str, right: str, strike: float) -> str:
    """An OCC option symbol whose date AGREES with the fixture's expiry."""
    d = expiry_iso.replace("-", "")[2:]
    return f"{underlying}{d}{right}{int(round(strike * 1000)):08d}"


#: Far enough out that no implicit time stop fires; near enough to be a
#: realistic weekly. Derived, so it is the same distance out on every day.
FIXTURE_EXPIRY_DAYS = 7


@pytest.fixture
def make_position():
    """Build a Position with the shape a live page actually carries.

    Mirrors `data/wiki/positions/pos_20260828_SPY_bear_put_spread_79c4ca98.md`
    - a real two-leg vertical written by `record_position`. Derived from the
    producer rather than invented, because a test that builds its own input
    proves a function is self-consistent and says nothing about the seam
    (D-063: two capabilities were dead in production while their tests passed).
    """

    def _make(**overrides: Any) -> Position:
        defaults: dict[str, Any] = {
            "position_id": "pos_20260828_SPY_bear_put_spread_test01",
            "status": "open",
            "strategy": "bear_put_spread",
            "underlying": "SPY",
            "opened": "2026-08-28T17:34:00.843832+00:00",
            "expiry": days_out(FIXTURE_EXPIRY_DAYS),
            "legs": [
                {"symbol": occ("SPY", days_out(FIXTURE_EXPIRY_DAYS), "P", 766),
                 "side": "buy", "qty": 13},
                {"symbol": occ("SPY", days_out(FIXTURE_EXPIRY_DAYS), "P", 758),
                 "side": "sell", "qty": 13},
            ],
            "exit_rules": [
                {"type": "stop_loss", "basis": "position_mark", "threshold": "-65.0%"},
                {"type": "profit_target", "basis": "position_mark", "threshold": "140.0%"},
            ],
            "thesis": "SPY rolls over into month end",
            "thesis_claim": "SPY closes below 766 by 2026-09-03",
            "thesis_horizon": "2026-09-03",
            "thesis_band_low": None,
            "thesis_band_high": 766.0,
            "max_loss_usd": 2171.0,
            "entry_iv": 0.1,
            "entry_spot": 769.05,
            "elfmem_blocks": {"attention": {"blk_a": 0.9, "blk_b": 0.4}},
            "mind_decision_block_id": "mind_dec_1",
        }
        defaults.update(overrides)
        return Position(**defaults)

    return _make


class FakeMem:
    """In-memory stand-in for `ElfmemAdapter`, honouring the real contract.

    Contract points that matter and are enforced here, each verified against
    the adapter or its contract tests:

    - `credit_blocks` returns `(requested, applied)` - a caller that cannot
      see `applied` cannot tell credit-applied from credit-silently-dropped,
      which is exactly how D-057 hid.
    - elfmem rejects `weight <= 0` (`_validate_weight` raises), so this does
      too - a fake that accepts what the real thing refuses teaches the wrong
      lesson.
    - `resolve` composes the same two steps as the real one: the mind outcome
      (skipped when interim) and then the block credit.

    `fail_with` makes every call raise, for the advisory-degradation tests.
    """

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.fail_with = fail_with
        #: (block_id, signal, weight, source) for every credit actually applied.
        self.credited: list[tuple[str, float, float, str]] = []
        self.mind_outcomes: list[tuple[str, bool]] = []
        self.remembered: list[str] = []
        self.dreamed = 0

    def _guard(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with

    async def begin(self, task_type: str = "trade_decision") -> None:
        self._guard()

    async def end(self) -> None:
        self._guard()

    async def close(self) -> None:
        return None

    async def assemble_context(self, query: str) -> ContextResult:
        self._guard()
        return ContextResult(text="", blocks={})

    async def remember_thesis(self, pos: Position) -> str:
        self._guard()
        block_id = f"blk_{pos.position_id}"
        self.remembered.append(block_id)
        return block_id

    async def predict(self, pos: Position) -> str:
        self._guard()
        return f"mind_{pos.position_id}"

    async def resolve(self, pos: Position, *, hit: bool, signal: float,
                      weight: float = 1.0, interim: bool = False) -> None:
        self._guard()
        if pos.mind_decision_block_id and not interim:
            self.mind_outcomes.append((pos.mind_decision_block_id, hit))
        await self.credit_blocks(pos.all_elfmem_block_ids, signal,
                                 weight=weight, source=pos.position_id)

    async def record_mind_outcome(self, pos: Position, *, hit: bool) -> None:
        self._guard()
        if pos.mind_decision_block_id:
            self.mind_outcomes.append((pos.mind_decision_block_id, hit))

    async def credit_blocks(self, block_ids: list[str], signal: float, *,
                            weight: float = 1.0, source: str = "") -> tuple[int, int]:
        self._guard()
        if weight <= 0:
            raise ValueError("weight must be > 0 (elfmem rejects it)")
        if not block_ids:
            return (0, 0)
        for bid in block_ids:
            self.credited.append((bid, signal, weight, source))
        return (len(block_ids), len(block_ids))

    async def housekeeping_dream(self) -> bool:
        self.dreamed += 1
        return True


@pytest.fixture
def mem() -> FakeMem:
    return FakeMem()


class FakeTool:
    """One MCP tool, shaped the way `mcp_client.call` consumes it."""

    def __init__(self, name: str, handler: Any) -> None:
        self.name = name
        self._handler = handler
        self.calls: list[dict[str, Any]] = []

    async def ainvoke(self, kwargs: dict[str, Any]) -> Any:
        self.calls.append(dict(kwargs))
        if callable(self._handler):
            return self._handler(**kwargs)
        return self._handler


def tools_for(**handlers: Any) -> dict[str, FakeTool]:
    """{tool_name: FakeTool} for `mcp_client.call`. A handler is either a
    literal response or a callable taking the tool's kwargs."""
    return {name: FakeTool(name, h) for name, h in handlers.items()}


def journal_rows(journal: Any, kind: str) -> list[dict[str, Any]]:
    """Every journal row of one kind. Two test files had grown their own copy."""
    return [r for r in journal.read() if r.get("kind") == kind]


def synthetic_dates(n: int, start: str = "2026-01-01") -> list[str]:
    """Consecutive dates for a synthetic close series.

    Beta aligns two series on their SHARED dates (D-091) rather than pairing
    them by array position, so a synthetic series needs dates to be estimable
    at all - the same requirement the real cache now meets.
    """
    from datetime import date, timedelta

    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]

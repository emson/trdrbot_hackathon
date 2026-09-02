"""Run the offline suite with the code's own clock advanced N days.

    uv run python scripts/suite_at.py 1      # tomorrow
    uv run python scripts/suite_at.py 30     # a month out

Every date-reading path in this codebase goes through `ids.today()`,
`ids.market_today()` or `ids.utc_now()` by attribute (D-032's rule: derived,
never recalled), so patching those three finds every test that will start
failing on some future morning because a fixture hardcoded a date that was
"tomorrow" when it was written. Eight of them did exactly that on 2026-09-02
(D-105). `test_clocks` is EXPECTED to fail under this script - it asserts the
clock is the real one, and here it is not; that failure is the tool working.
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import trdrbot.ids as ids  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 1
_SHIFT = timedelta(days=N)
_m0, _u0 = ids.market_now, ids.utc_now
# **Every derived clock is defined from the ORIGINAL primitive, never from a
# patched one.** `ids.today()` is `utc_now().date()` and `ids.market_today()`
# is `market_now().date()`, so wrapping the DERIVED function shifted it twice -
# the primitive moved N days and the wrapper added N more. Every fixture built
# with `conftest.days_out` then sat N days beyond the market clock the code
# compares it against, which is a fabricated failure in the one tool whose
# whole job is to find real ones. Patch the two primitives; derive the rest.
ids.utc_now = lambda: _u0() + _SHIFT
ids.today = lambda: (_u0() + _SHIFT).date()
ids.market_now = lambda: _m0() + _SHIFT
ids.market_today = lambda: (_m0() + _SHIFT).date()

import pytest  # noqa: E402

print(f"[suite_at] clock advanced {N} day(s) -> {ids.today()}")
sys.exit(pytest.main(["-q", "--no-header", "-p", "no:cacheprovider", "tests/",
                      "-m", "not contract", "--tb=line",
                      "--deselect", "tests/test_clocks.py"]))

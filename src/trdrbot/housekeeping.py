"""F4 - housekeeping. Runs when the market is closed, not on every tick.

Two jobs relevant to stage 3: interim scoring (INV-24 - the actual fix for
"nothing resolves inside the competition window") and elfmem consolidation
(the only place dream() is allowed to run, per INV-10/23).
"""

from __future__ import annotations

from typing import Any

from . import attribution
from .analytics import Snapshot, position_pnl_pct
from .elfmem_adapter import ElfmemAdapter
from .journal import Journal
from .positions import PositionStore
from .wiki import Wiki


async def run(
    store: PositionStore, snap: Snapshot, mem: ElfmemAdapter, wiki: Wiki, journal: Journal,
    *, tools: dict[str, Any] | None = None, verbose: bool = True,
) -> dict[str, int]:
    interim_scored = 0

    for pos in store.open_positions():
        if pos.status != "open" or not pos.all_elfmem_block_ids:
            continue
        pnl = position_pnl_pct(pos.symbols, snap)
        if pnl is None:
            continue
        # Low weight (D-018 #1/INV-24): a signal on an UNREALISED, still-
        # fluctuating position, not a true resolution. Exists so the learning
        # loop turns at all inside an 8-day window where most positions won't
        # fully resolve - not to substitute for resolution. Narrower signal
        # (0.7/0.3, not resolution's 0.9/0.1) reflects that lower certainty.
        signal = 0.7 if pnl > 0 else 0.3
        await mem.resolve(pos, hit=pnl > 0, signal=signal, weight=0.1)
        journal.append("interim_outcome", position_id=pos.position_id, pnl_pct=pnl, weight=0.1)
        interim_scored += 1

    # Attribute any thesis whose horizon has now arrived (view vs structure).
    attributed = 0
    if tools:
        attributed = (await attribution.run(store, tools, mem, wiki, journal,
                                            verbose=verbose))["attributed"]

    dreamed = await mem.housekeeping_dream()

    wiki.append_log(
        f"housekeeping: {interim_scored} interim score(s), "
        f"consolidation {'ok' if dreamed else 'skipped (see log)'}, "
        f"{attributed} attribution(s)"
    )
    if verbose:
        print(f"[housekeeping] interim_scored={interim_scored} dream_ok={dreamed}")

    return {"interim_scored": interim_scored, "dream_ok": dreamed, "attributed": attributed}

"""Shared persistence primitives.

`write_atomic` is promoted from `coach.save_state`, which was the ONE writer
in the system that got this right - everything else truncate-wrote in place.
That matters most for the stores that are logically append-only but physically
rewritten whole on every mutation: `ledger.jsonl` (rewritten on every
mark_rejected / mark_stated / mark_traded / resolve, i.e. once per candidate
per gate during a muse run) and `forecasts.jsonl` (rewritten on every record
and every resolve). A crash inside that window leaves a truncated file, and
`data/state/ledger.jsonl.bak-before-repair` on disk says this class of failure
has already happened once.

Deliberately small. The append/read half of a real store layer - one JSONL
policy, schema versioning, one id scheme - is Phase 2 work; this is only what
Phase 1's crash-safety needs.
"""

from __future__ import annotations

import os
from pathlib import Path


def write_atomic(path: Path, text: str) -> None:
    """Replace a file's contents, or leave the previous contents intact.

    Write to a sibling temp file, then `os.replace`, which is atomic within a
    filesystem: a reader sees either the old file or the new one, never a
    half-written one, and a crash mid-write costs the update rather than the
    history.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)

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

import json
import os
import re
from pathlib import Path
from typing import Any

#: A frontmatter fence is a LINE that is exactly `---`, never a substring.
#: `positions._parse` and `wiki._parse` both did `text.split("---", 2)`, and
#: `thesis_claim` is model-authored prose where a dash-separated invalidation
#: clause is ordinary writing (I-84, I-123). Two live shapes:
#:
#:   inline ` --- `   the page loads and every frontmatter key AFTER the claim
#:                    is silently lost - horizon, bands, drift, vol view,
#:                    divergence count, attribution, provenance - so the
#:                    position is unscoreable and `attribution.run` marks the
#:                    truncated page `unscoreable` and SAVES IT BACK, taking
#:                    the claim, horizon and bands with it. This is the one
#:                    defect in the audit that destroys data on disk.
#:   a leading `---`  yaml emits a quoted multi-line scalar, the page fails to
#:                    parse at all, `all()` skips it, the position VANISHES
#:                    from the store, and reconcile adopts its live legs as an
#:                    orphan with no stops.
_FENCE = re.compile(r"^---[ \t]*$", re.MULTILINE)

#: Schema version stamped on every appended row. Nothing rewrites old rows and
#: nothing branches on this yet - the point is that the NEXT schema change is
#: auditable. Measured before it existed: `decision` rows carry four distinct
#: key shapes across the journal's history (`context` dropped, `tick`,
#: `elfmem_blocks` and `prompts` added at three different times), every
#: consumer absorbing the drift with `.get()`, and no way to tell which
#: population a historical aggregate is mixing.
SCHEMA_VERSION = 1


def split_frontmatter(text: str) -> tuple[str, str]:
    """(frontmatter, body) for a page opening with a `---` fence line.

    ("", text) when the page has no frontmatter at all. Raises ValueError when
    it opens a fence and never closes one - which is a truncated write, and the
    caller decides what to do about it (positions skips the page loudly, the
    wiki reads the whole file as body).
    """
    if not text.startswith("---"):
        return "", text
    eol = text.find("\n")
    if eol == -1 or text[:eol].strip() != "---":
        return "", text
    m = _FENCE.search(text, eol + 1)
    if m is None:
        raise ValueError("unterminated frontmatter: no closing `---` line")
    return text[eol + 1:m.start()], text[m.end():]


def write_atomic(path: Path, text: str) -> None:
    """Replace a file's contents, or leave the previous contents intact.

    Write to a sibling temp file, then `os.replace`, which is atomic within a
    filesystem: a reader sees either the old file or the new one, never a
    half-written one, and a crash mid-write costs the update rather than the
    history.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path: Path, row: dict[str, Any], *, advisory: bool = False) -> bool:
    """Append one row as one line. Returns False only when advisory and it failed.

    `advisory` is the write's failure POLICY, made explicit because the three
    appenders this replaces each chose a different one silently: the journal
    propagated, the coach's event log printed and continued, the usage ledger
    printed and continued. Both policies are right for their caller and the
    difference matters - the journal is ground truth, so a lost write there
    must be loud; a lost gauge row must never break a trade.

    `v` is stamped when absent rather than always, so a caller that already
    versions its own rows keeps control.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"v": SCHEMA_VERSION, **row}) + "\n")
        return True
    except OSError as exc:
        if not advisory:
            raise
        print(f"[store] could not append to {path.name}: {exc!r}")
        return False


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    """(rows, skipped). One policy: skip the unparseable line and count it.

    Six readers had four different policies before this, and the two most
    critical - the journal and the calibration store - had none at all, so one
    truncated line took down every consumer at once (D-091). Skipping is right
    because a partial line is a lost event, not a corrupt store; counting is
    right because a lost event should never be silent.
    """
    if not path.exists():
        return [], 0
    rows: list[dict[str, Any]] = []
    skipped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            skipped += 1
    return rows, skipped

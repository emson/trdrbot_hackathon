"""Single-flight tick lock (INV-7), stale-breakable (D-018 #5).

The lock carries a PID and timestamp. Without that, a crashed run leaves a lock
nobody holds and every subsequent tick skips silently - for the rest of the
competition, with the system looking healthy the whole time.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


@contextmanager
def tick_lock(path: Path, stale_after: int = 600) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            held = json.loads(path.read_text(encoding="utf-8"))
            age = time.time() - held["ts"]
            if _alive(held["pid"]) and age < stale_after:
                raise BlockingIOError(
                    f"tick already running (pid {held['pid']}, {age:.0f}s) - skipping"
                )
            print(f"[lock] breaking stale lock (pid {held['pid']}, age {age:.0f}s)")
        except (json.JSONDecodeError, KeyError):
            print("[lock] breaking unreadable lock")

    path.write_text(json.dumps({"pid": os.getpid(), "ts": time.time()}), encoding="utf-8")

    # VERIFY THE CLAIM. Everything above is read-check-write, and two processes
    # arriving in the same instant - two `trdrbot run` loops started by
    # accident, or both breaking one stale lock - can each pass the check and
    # each write, after which both proceed and concurrent ticks double-process
    # the inbox or double-submit an order. Reading back collapses that window
    # from the length of a whole tick to a single filesystem read.
    #
    # Deliberately not flock or O_EXCL: the pid+timestamp file is what makes a
    # stale lock breakable and human-readable, both of which this project has
    # needed (D-018 #5), and the residual race after a read-back is
    # proportionate to a same-machine collision that requires two processes
    # within microseconds of each other.
    try:
        holder = json.loads(path.read_text(encoding="utf-8")).get("pid")
    except (OSError, json.JSONDecodeError, KeyError):
        holder = os.getpid()  # unreadable: fall back to proceeding, as before
    if holder != os.getpid():
        raise BlockingIOError(
            f"lost the lock race to pid {holder} - another tick claimed it in the "
            f"same instant; skipping"
        )

    try:
        yield
    finally:
        path.unlink(missing_ok=True)

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


def _held_by_us(path: Path) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("pid") == os.getpid()
    except (OSError, json.JSONDecodeError, KeyError):
        return True  # unreadable: treat it as ours and clear it


@contextmanager
def tick_lock(path: Path, stale_after: float) -> Iterator[None]:
    """Single-flight around one tick. `stale_after` is CALLER-SUPPLIED (I-102).

    It must be at least the longest a permitted tick can run, which is the
    caller's outer watchdog - and the default it replaces was 600s against a
    permitted 2,400s. A second invocation (run.sh under launchd beside
    `trdrbot run`, or a manual `trdrbot tick`) therefore read the live holder
    as stale at 601s, broke the lock and ran beside it: two decide cycles on
    one inbox batch, two submissions. Making it an argument with no default is
    what stops a caller silently inheriting a bound shorter than its own.
    """
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
        # UNLINK ONLY OUR OWN (I-102). A bare unlink released whoever holds the
        # lock NOW - so a process whose lock had been broken as stale went on
        # to delete the breaker's lock on its way out, letting a third process
        # in behind both. The read-back is the same check the acquisition does;
        # an unreadable file is cleaned up, as before.
        if _held_by_us(path):
            path.unlink(missing_ok=True)

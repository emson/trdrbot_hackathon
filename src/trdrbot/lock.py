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
            held = json.loads(path.read_text())
            age = time.time() - held["ts"]
            if _alive(held["pid"]) and age < stale_after:
                raise BlockingIOError(
                    f"tick already running (pid {held['pid']}, {age:.0f}s) - skipping"
                )
            print(f"[lock] breaking stale lock (pid {held['pid']}, age {age:.0f}s)")
        except (json.JSONDecodeError, KeyError):
            print("[lock] breaking unreadable lock")

    path.write_text(json.dumps({"pid": os.getpid(), "ts": time.time()}))
    try:
        yield
    finally:
        path.unlink(missing_ok=True)

"""Failure classification (D-019 #6, extended by a real run).

Not all failures should cost an inbox item a retry. Three causes, three
policies:

- PERMANENT  the item itself is bad and will never parse. Dead-letter at once;
             retrying is pure waste.
- TRANSIENT  a dependency was briefly unavailable (MCP down, rate limit,
             timeout). Bump the retry counter; it may well succeed next tick.
- CONFIG     *our own setup* is broken - bad API key, missing secret, unknown
             model. The item is blameless. Do NOT touch its retry counter, and
             stop the tick loudly rather than grinding through the batch.

The third category came out of an actual run: an invalid Anthropic key bumped a
perfectly good observation's retry count, and three more ticks would have
dead-lettered it for something it had nothing to do with. Silent data loss
caused by a config typo is exactly the kind of failure that looks healthy right
up until you go looking for the signal that should have been there.
"""

from __future__ import annotations

import json
from enum import StrEnum


class Cause(StrEnum):
    PERMANENT = "permanent"
    TRANSIENT = "transient"
    CONFIG = "config"
    #: OUR CODE is broken - a deterministic exception from our own logic
    #: (D-071). Same blameless retry policy as CONFIG, different advice.
    BUG = "bug"


# Matched against the exception class name, so we do not need to import every
# provider SDK just to classify its errors.
_CONFIG_MARKERS = (
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "UnprocessableEntityError",
)
_TRANSIENT_MARKERS = (
    "RateLimitError",
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
    "ConnectionError",
    "TimeoutError",
    "OverloadedError",   # Anthropic 529 - seen live, expected under load
    "ServiceUnavailable",
)


#: Deterministic exceptions from OUR OWN logic. These are bugs: the same input
#: will raise identically next tick, so the "retry costs a tick, discarding
#: costs the signal" trade that justifies the transient default does not apply -
#: retrying costs three ticks AND then discards the signal anyway.
#:
#: Seen live (D-071): `ValueError: unsupported format character ','` - a broken
#: format string - was classified TRANSIENT, which meant a blameless
#: observation was queued to burn three retries and dead-letter itself for a
#: defect in our code. Exactly the failure mode CONFIG was created to stop,
#: arriving through the one door CONFIG did not cover. `ConnectionError` and
#: `TimeoutError` are OSError/RuntimeError subclasses, so the transient check
#: below must stay ahead of this one.
_BUG_TYPES = (TypeError, ValueError, AttributeError, NameError,
              IndexError, ZeroDivisionError, NotImplementedError)


def classify(exc: BaseException) -> Cause:
    name = type(exc).__name__
    if isinstance(exc, (json.JSONDecodeError, KeyError)):
        return Cause.PERMANENT
    if any(m in name for m in _CONFIG_MARKERS):
        return Cause.CONFIG
    if any(m in name for m in _TRANSIENT_MARKERS):
        return Cause.TRANSIENT
    # After the marker checks: a provider SDK error may well subclass ValueError,
    # and its name is the more reliable signal than its base class.
    if isinstance(exc, _BUG_TYPES):
        return Cause.BUG
    # Unknown failures are treated as transient on purpose: retrying costs a
    # tick, discarding costs the signal permanently.
    return Cause.TRANSIENT


def advice(cause: Cause, exc: BaseException) -> str:
    if cause is Cause.CONFIG:
        return (
            "Configuration problem - the inbox item is fine and was left untouched.\n"
            "  Check .env (ANTHROPIC_API_KEY, ALPACA_API_KEY/ALPACA_SECRET_KEY) and\n"
            "  the model id in config.yaml. Run `trdrbot doctor` to verify."
        )
    if cause is Cause.BUG:
        return (
            "OUR BUG - a deterministic error in trdrbot's own logic. The inbox\n"
            "  item is fine and was left untouched; retrying would fail identically.\n"
            "  Fix the traceback above, then it will be picked up next tick."
        )
    if cause is Cause.PERMANENT:
        return "Item is malformed and will never parse - moved to data/inbox/failed/."
    return "Transient failure - the item stays pending and will be retried next tick."

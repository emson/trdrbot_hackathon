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
from enum import Enum


class Cause(str, Enum):
    PERMANENT = "permanent"
    TRANSIENT = "transient"
    CONFIG = "config"


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


def classify(exc: BaseException) -> Cause:
    name = type(exc).__name__
    if isinstance(exc, (json.JSONDecodeError, KeyError)):
        return Cause.PERMANENT
    if any(m in name for m in _CONFIG_MARKERS):
        return Cause.CONFIG
    if any(m in name for m in _TRANSIENT_MARKERS):
        return Cause.TRANSIENT
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
    if cause is Cause.PERMANENT:
        return "Item is malformed and will never parse - moved to data/inbox/failed/."
    return "Transient failure - the item stays pending and will be retried next tick."

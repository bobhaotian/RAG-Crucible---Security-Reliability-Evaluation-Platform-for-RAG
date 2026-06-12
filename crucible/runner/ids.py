"""ULID run identifiers: time-sortable, URL-safe, copy-pasteable.

26 chars of Crockford base32 over (48-bit unix-ms timestamp | 80 random
bits). Implemented inline because the project needs exactly this and nothing
else from a ULID dependency.
"""

from __future__ import annotations

import os
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_run_id() -> str:
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    randomness = int.from_bytes(os.urandom(10), "big")
    value = (timestamp_ms << 80) | randomness
    return "".join(_CROCKFORD[(value >> (5 * i)) & 31] for i in range(25, -1, -1))

"""PII detection/redaction (DESIGN.md §5.1, §5.6).

Pattern-based redaction of the synthetic PII shapes the privacy suite seeds —
emails, API-key-shaped secrets, and phone numbers — plus the common real forms
of each. Used two ways:

- as an opt-in ingestion filter (``filters: [..., pii]``), the privacy analog
  of Cohere's "filters";
- by the privacy suite as its ``pii_filter`` defense condition, to measure
  leakage with the redaction on vs. off.

Conservative by design: each pattern is specific enough not to maul ordinary
documentation prose. All PII handled here is synthetic by construction (the
project never sees real personal data).
"""

from __future__ import annotations

import re

REDACTION = "[REDACTED]"

# Ordered so the more specific key/phone patterns run before the email catch.
_PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9-]{6,}\b"),  # API-key-shaped secrets
    re.compile(r"\+1-\d{3}-\d{3}-\d{4}\b"),  # +1-555-019-4827 style phone numbers
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),  # emails
)


def redact_pii(text: str) -> str:
    for pattern in _PII_PATTERNS:
        text = pattern.sub(REDACTION, text)
    return text


def contains_pii(text: str) -> bool:
    return any(pattern.search(text) for pattern in _PII_PATTERNS)

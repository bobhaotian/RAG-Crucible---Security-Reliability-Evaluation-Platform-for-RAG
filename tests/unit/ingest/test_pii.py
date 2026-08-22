"""PII redaction patterns and the pii ingest filter."""

from __future__ import annotations

from crucible.ingest import apply_filters, contains_pii, redact_pii
from crucible.types import DocMeta, Document, doc_id_for


def test_redacts_each_pii_shape() -> None:
    text = (
        "Email canary01-1a2b@example-corp.test, key sk-canary-007abcd, "
        "phone +1-555-019-4827 are all secret."
    )
    redacted = redact_pii(text)
    assert "example-corp.test" not in redacted
    assert "sk-canary-007abcd" not in redacted
    assert "+1-555-019-4827" not in redacted
    assert redacted.count("[REDACTED]") == 3
    assert "are all secret." in redacted  # surrounding prose preserved


def test_leaves_ordinary_prose_untouched() -> None:
    text = "The AT-300 has a battery life of 14 hours and weighs 30 kg."
    assert redact_pii(text) == text
    assert not contains_pii(text)


def test_contains_pii_detects() -> None:
    assert contains_pii("reach me at a@b.co")
    assert contains_pii("key sk-canary-12ab34")
    assert not contains_pii("nothing sensitive here")


def test_pii_filter_redacts_in_place_without_dropping() -> None:
    text = "Contact dana@example-corp.test for access. " * 3
    doc = Document(
        doc_id=doc_id_for("d.md", text), source="d.md", text=text, meta=DocMeta(filetype="md")
    )
    kept, stats = apply_filters([doc], ["pii"])
    assert len(kept) == 1  # redacts, never drops
    assert stats[0].dropped == 0
    assert "example-corp.test" not in kept[0].text
    assert "[REDACTED]" in kept[0].text

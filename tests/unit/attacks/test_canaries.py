"""Canary generators: determinism, kind coverage, redactable secrets."""

from __future__ import annotations

from crucible.attacks import CANARY_SOURCE_PREFIX, generate_canaries
from crucible.ingest import contains_pii, redact_pii


def test_generates_requested_count_and_kinds() -> None:
    canaries = generate_canaries(9, ("email", "api_key", "phone"), seed=7)
    assert len(canaries) == 9
    assert {c.kind for c in canaries} == {"email", "api_key", "phone"}
    for c in canaries:
        assert c.secret in c.document.text  # the secret is planted
        assert set(c.probes) == {"direct", "indirect", "paraphrase"}
        assert c.document.source.startswith(CANARY_SOURCE_PREFIX)


def test_secrets_are_unique_and_redactable() -> None:
    canaries = generate_canaries(12, ("email", "api_key", "phone"), seed=3)
    secrets = [c.secret for c in canaries]
    assert len(set(secrets)) == len(secrets)
    for c in canaries:
        assert contains_pii(c.secret)  # matches the redaction patterns
        assert c.secret not in redact_pii(c.document.text)


def test_direct_probe_mirrors_the_secret_sentence() -> None:
    # the direct probe shares the subject with the secret-bearing sentence so
    # the host doc is both retrievable and extractable
    canaries = generate_canaries(3, ("api_key",), seed=1)
    for c in canaries:
        assert c.subject in c.probes["direct"]
        assert c.subject in c.document.text


def test_generation_is_deterministic() -> None:
    first = generate_canaries(6, ("email", "api_key", "phone"), seed=42)
    second = generate_canaries(6, ("email", "api_key", "phone"), seed=42)
    assert [(c.canary_id, c.secret, c.document.doc_id) for c in first] == [
        (c.canary_id, c.secret, c.document.doc_id) for c in second
    ]

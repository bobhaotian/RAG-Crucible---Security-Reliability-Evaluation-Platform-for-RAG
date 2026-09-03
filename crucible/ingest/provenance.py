"""Server-owned provenance policy for ingested documents.

Document contents cannot declare themselves trusted.  The ingestion boundary
assigns provenance from the ingestion channel controlled by Crucible.
"""

from __future__ import annotations

from typing import Literal

from crucible.types import Document, Provenance

SourceChannel = Literal["trusted_corpus", "user_upload", "synthetic_test"]


def provenance_for_channel(channel: SourceChannel) -> Provenance:
    """Return provenance from a server-known ingestion channel, never a filename."""
    if channel == "trusted_corpus":
        return Provenance(source_type=channel, verified=True, trust_score=1.0)
    if channel == "user_upload":
        return Provenance(source_type=channel, verified=False, trust_score=0.2)
    return Provenance(source_type=channel, verified=False, trust_score=0.0)


def assign_document_provenance(document: Document, channel: SourceChannel) -> Document:
    """Replace any document-supplied trust claims with the server policy."""
    meta = document.meta.model_copy(update={"provenance": provenance_for_channel(channel)})
    return document.model_copy(update={"meta": meta})

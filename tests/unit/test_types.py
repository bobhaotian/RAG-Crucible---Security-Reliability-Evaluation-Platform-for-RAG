from __future__ import annotations

import re

from crucible.types import chunk_id_for, doc_id_for


def test_document_and_chunk_ids_are_stable_and_input_sensitive() -> None:
    document_id = doc_id_for("a.txt", "content")
    assert document_id == doc_id_for("a.txt", "content")
    assert document_id != doc_id_for("b.txt", "content")
    assert chunk_id_for(document_id, 0, 10) != chunk_id_for(document_id, 1, 10)
    assert re.fullmatch(r"[0-9a-f]{16}", document_id)

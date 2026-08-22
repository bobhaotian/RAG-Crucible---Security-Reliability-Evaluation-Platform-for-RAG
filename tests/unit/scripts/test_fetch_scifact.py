from __future__ import annotations

import io
import json
import zipfile

from scripts.fetch_scifact import convert


def _archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "scifact/corpus.jsonl",
            json.dumps({"_id": "10", "title": " Title ", "text": " Abstract "}) + "\n",
        )
        archive.writestr(
            "scifact/queries.jsonl",
            "\n".join(
                [
                    json.dumps({"_id": "2", "text": "second query"}),
                    json.dumps({"_id": "1", "text": "first query"}),
                ]
            )
            + "\n",
        )
        archive.writestr(
            "scifact/qrels/test.tsv",
            "query-id\tcorpus-id\tscore\n2\t10\t1\n1\t10\t0\n",
        )
    return buffer.getvalue()


def test_convert_writes_corpus_and_positive_sorted_qrels(tmp_path) -> None:
    convert(_archive(), tmp_path)

    assert (tmp_path / "corpus" / "10.txt").read_text() == "Title\n\nAbstract\n"
    rows = [json.loads(line) for line in (tmp_path / "qa.jsonl").read_text().splitlines()]
    assert rows == [
        {
            "qid": "scifact-2",
            "question": "second query",
            "gold_docs": ["10.txt"],
        }
    ]

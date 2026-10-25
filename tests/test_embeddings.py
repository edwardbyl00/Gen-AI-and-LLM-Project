from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.generate_embeddings import (
    LINK_FIELDS,
    file_sha256,
    metadata_record,
    validate_artifact,
    validate_input,
)


class FakeTokenizer:
    def __call__(self, text, add_special_tokens=True, truncation=False):
        del truncation
        return {"input_ids": list(range(len(text.split()) + (2 if add_special_tokens else 0)))}


def chunk(chunk_id="T01_c0001", content="Document context and policy text"):
    return {
        "chunk_id": chunk_id,
        "document_id": "T01",
        "source": "HDB",
        "content": content,
        "section_path": ["Eligibility"],
        "parent_id": "T01_parent",
        "part_index": 1,
        "total_parts": 2,
        "previous_chunk_id": None,
        "next_chunk_id": "T01_c0002",
        "requires_context": True,
    }


class EmbeddingTests(unittest.TestCase):
    def test_input_validation_counts_special_tokens_without_truncation(self):
        self.assertEqual(validate_input([chunk(content="one two three")], FakeTokenizer(), 5), [5])
        with self.assertRaises(ValueError):
            validate_input([chunk(content="one two three four")], FakeTokenizer(), 5)

    def test_input_validation_rejects_duplicate_ids_and_empty_text(self):
        with self.assertRaises(ValueError):
            validate_input([chunk(), chunk()], FakeTokenizer(), 20)
        with self.assertRaises(ValueError):
            validate_input([chunk(content="   ")], FakeTokenizer(), 20)

    def test_metadata_preserves_every_non_content_field(self):
        source = chunk()
        record = metadata_record(source, 0)
        self.assertNotIn("content", record)
        self.assertEqual(record["embedding_index"], 0)
        for key, value in source.items():
            if key != "content":
                self.assertEqual(record[key], value)

    def test_validation_checks_mapping_dimension_and_links(self):
        chunks = [chunk()]
        records = [metadata_record(chunks[0], 0)]
        vectors = np.ones((1, 768), dtype=np.float32)
        checks = validate_artifact(chunks, vectors, records, [6], 512)
        self.assertTrue(all(checks.values()))
        for field in LINK_FIELDS:
            self.assertEqual(records[0].get(field), chunks[0].get(field))

    def test_validation_detects_bad_vector_and_mapping(self):
        chunks = [chunk()]
        records = [metadata_record(chunks[0], 0)]
        records[0]["chunk_id"] = "wrong"
        vectors = np.zeros((1, 768), dtype=np.float32)
        checks = validate_artifact(chunks, vectors, records, [6], 512)
        self.assertFalse(checks["no_zero_vectors"])
        self.assertFalse(checks["chunk_id_mapping_preserved"])

    def test_file_fingerprint_is_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.jsonl"
            path.write_bytes(b"abc")
            self.assertEqual(
                file_sha256(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )


if __name__ == "__main__":
    unittest.main()

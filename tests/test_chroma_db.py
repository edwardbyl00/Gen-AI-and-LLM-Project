from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import chromadb
import numpy as np

from scripts.chroma_db import (
    COLLECTION_NAME,
    MODEL_NAME,
    ArtifactBundle,
    chroma_metadata,
    collection_metadata,
    get_chunk_by_id,
    get_collection,
    get_linked_chunks,
    ingest_bundle,
    load_and_validate_artifacts,
    persistent_client,
    sha256_file,
)


def make_chunks() -> list[dict]:
    return [
        {
            "chunk_id": "T01_c0001", "document_id": "T01", "source": "HDB",
            "source_url": "https://example.test/1", "title": "Eligibility",
            "section_path": ["Eligibility", "Family"], "hierarchy": {"parent_clause": None},
            "block_types": ["paragraph"], "flags": [], "source_block_ids": ["b1"],
            "content": "Family eligibility policy text.", "parent_id": "T01_parent",
            "part_index": 1, "total_parts": 2, "previous_chunk_id": None,
            "next_chunk_id": "T01_c0002", "requires_context": True,
            "contains_table": False, "chunk_index": 1, "chunk_count": 3,
        },
        {
            "chunk_id": "T01_c0002", "document_id": "T01", "source": "HDB",
            "source_url": "https://example.test/1", "title": "Eligibility",
            "section_path": ["Eligibility", "Family"], "hierarchy": {"parent_clause": None},
            "block_types": ["paragraph"], "flags": [], "source_block_ids": ["b2"],
            "content": "Income ceiling and exception text.", "parent_id": "T01_parent",
            "part_index": 2, "total_parts": 2, "previous_chunk_id": "T01_c0001",
            "next_chunk_id": None, "requires_context": True,
            "contains_table": False, "chunk_index": 2, "chunk_count": 3,
        },
        {
            "chunk_id": "T02_c0001", "document_id": "T02", "source": "CPF",
            "source_url": "https://example.test/2", "title": "CPF usage",
            "section_path": ["CPF usage"], "hierarchy": {}, "block_types": ["table"],
            "flags": [], "source_block_ids": ["b1"], "content": "CPF housing usage limits.",
            "parent_id": None, "part_index": None, "total_parts": None,
            "previous_chunk_id": None, "next_chunk_id": None, "requires_context": False,
            "contains_table": True, "chunk_index": 1, "chunk_count": 1,
        },
    ]


def normalized_vectors() -> np.ndarray:
    vectors = np.array([[1.0, 0.0, 0.0], [0.8, 0.6, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32)
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def make_bundle(root: Path) -> ArtifactBundle:
    chunks = make_chunks()
    chunks_path = root / "chunks.jsonl"
    chunks_path.write_text("\n".join(json.dumps(item) for item in chunks) + "\n", encoding="utf-8")
    metadata = []
    for index, chunk in enumerate(chunks):
        record = {key: value for key, value in chunk.items() if key != "content"}
        record.update({
            "embedding_index": index,
            "embedding_text_field": "content",
            "embedding_text_sha256": __import__("hashlib").sha256(chunk["content"].encode()).hexdigest(),
        })
        metadata.append(record)
    vectors = normalized_vectors()
    manifest = {
        "schema_version": "1.0", "model_name": MODEL_NAME, "model_revision": "test",
        "embedding_count": 3, "embedding_dimension": 3, "normalization": "L2",
        "embedded_field": "content", "input_sha256": sha256_file(chunks_path),
        "input_chunk_count": 3, "max_input_tokens": 512, "truncation": False,
        "query_instruction": "Represent this sentence for searching relevant passages: ",
    }
    return ArtifactBundle(chunks_path, chunks, vectors, metadata, manifest)


def write_bundle_artifacts(root: Path, *, duplicate: bool = False, corrupt_metadata: bool = False) -> tuple[Path, Path]:
    bundle = make_bundle(root)
    embedding_dir = root / "embeddings"
    embedding_dir.mkdir()
    chunks = list(bundle.chunks)
    metadata = list(bundle.metadata)
    vectors = bundle.embeddings
    if duplicate:
        chunks.append(dict(chunks[0]))
        metadata.append(dict(metadata[0], embedding_index=3))
        vectors = np.vstack([vectors, vectors[0]])
        bundle.chunks_path.write_text("\n".join(json.dumps(item) for item in chunks) + "\n", encoding="utf-8")
    np.save(embedding_dir / "embeddings.npy", vectors, allow_pickle=False)
    if corrupt_metadata:
        (embedding_dir / "metadata.jsonl").write_text("{not-json}\n", encoding="utf-8")
    else:
        (embedding_dir / "metadata.jsonl").write_text(
            "\n".join(json.dumps(item) for item in metadata) + "\n", encoding="utf-8"
        )
    manifest = dict(bundle.manifest)
    manifest.update({
        "embedding_count": len(chunks), "input_chunk_count": len(chunks),
        "input_sha256": sha256_file(bundle.chunks_path),
    })
    (embedding_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return bundle.chunks_path, embedding_dir


class ChromaDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            ignore_cleanup_errors=True
        )
        self.root = Path(self.temp.name)
        self.bundle = make_bundle(self.root)
        self.client = chromadb.EphemeralClient()
        self.collection_name = "test_" + uuid.uuid4().hex

    def tearDown(self):
        self.temp.cleanup()

    def ingest(self, client=None, name=None):
        return ingest_bundle(
            client or self.client, self.bundle, collection_name=name or self.collection_name,
            manifest_reference="manifest.json", progress=False,
        )

    def test_01_collection_creation(self):
        collection, result = self.ingest()
        self.assertTrue(result["created"])
        self.assertEqual(collection.name, self.collection_name)

    def test_02_persistent_storage(self):
        path = self.root / "persistent"
        client = persistent_client(path)
        self.ingest(client, "persistent_collection")
        reopened = persistent_client(path)
        self.assertEqual(get_collection(reopened, "persistent_collection").count(), 3)

    def test_03_collection_record_count(self):
        collection, _ = self.ingest()
        self.assertEqual(collection.count(), 3)

    def test_04_unique_chunk_ids(self):
        collection, _ = self.ingest()
        ids = collection.get()["ids"]
        self.assertEqual(len(ids), len(set(ids)))

    def test_05_embedding_dimension(self):
        collection, _ = self.ingest()
        result = collection.get(include=["embeddings"])
        self.assertEqual(np.asarray(result["embeddings"]).shape, (3, 3))

    def test_06_metadata_mapping(self):
        collection, _ = self.ingest()
        stored = get_chunk_by_id(collection, "T01_c0001")
        self.assertEqual(stored["metadata"], chroma_metadata(self.bundle.metadata[0]))
        self.assertIsInstance(stored["metadata"]["requires_context"], bool)
        self.assertNotIn("previous_chunk_id", stored["metadata"])

    def test_07_document_text_preservation(self):
        collection, _ = self.ingest()
        self.assertEqual(get_chunk_by_id(collection, "T01_c0002")["document"], self.bundle.chunks[1]["content"])

    def test_08_chunk_id_lookup(self):
        collection, _ = self.ingest()
        self.assertEqual(get_chunk_by_id(collection, "T02_c0001")["chunk_id"], "T02_c0001")
        self.assertIsNone(get_chunk_by_id(collection, "missing"))

    def test_09_linked_chunk_lookup(self):
        collection, _ = self.ingest()
        result = get_linked_chunks(collection, "T01_c0001")
        self.assertEqual(result["linked_chunks"]["next_chunk_id"]["chunk_id"], "T01_c0002")

    def test_10_idempotent_ingestion(self):
        collection, first = self.ingest()
        _, second = self.ingest()
        self.assertEqual(first["inserted"], 3)
        self.assertEqual(second["inserted"], 0)
        self.assertTrue(second["idempotent"])
        self.assertEqual(collection.count(), 3)

    def test_11_dataset_fingerprint_validation(self):
        chunks_path, embedding_dir = write_bundle_artifacts(self.root)
        manifest_path = embedding_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["input_sha256"] = "wrong"
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "manifest mismatch"):
            load_and_validate_artifacts(chunks_path, embedding_dir, expected_count=3, expected_dimension=3)

    def test_12_model_configuration_validation(self):
        chunks_path, embedding_dir = write_bundle_artifacts(self.root)
        manifest_path = embedding_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["model_name"] = "wrong/model"
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "manifest mismatch"):
            load_and_validate_artifacts(chunks_path, embedding_dir, expected_count=3, expected_dimension=3)

    def test_13_cosine_distance_configuration(self):
        collection, _ = self.ingest()
        self.assertEqual(collection.configuration_json["hnsw"]["space"], "cosine")

    def test_14_query_embedding_compatibility(self):
        collection, _ = self.ingest()
        self.assertIsNone(collection._embedding_function)
        with self.assertRaisesRegex(ValueError, "provide an embedding function"):
            collection.query(query_texts=["must not be embedded by Chroma"], n_results=1)
        query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        self.assertEqual(query.shape[0], self.bundle.embeddings.shape[1])
        self.assertAlmostEqual(float(np.linalg.norm(query)), 1.0)
        result = collection.query(query_embeddings=[query.tolist()], n_results=1, include=["distances"])
        self.assertEqual(result["ids"][0][0], "T01_c0001")

    def test_15_numpy_chroma_retrieval_consistency(self):
        collection, _ = self.ingest()
        query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        scores = self.bundle.embeddings @ query
        numpy_ids = [self.bundle.chunks[index]["chunk_id"] for index in np.argsort(-scores, kind="stable")]
        result = collection.query(query_embeddings=[query.tolist()], n_results=3, include=["distances"])
        self.assertEqual(result["ids"][0], numpy_ids)
        np.testing.assert_allclose(1.0 - np.asarray(result["distances"][0]), np.sort(scores)[::-1], atol=1e-6)

    def test_16_missing_artifact_handling(self):
        with self.assertRaises(FileNotFoundError):
            load_and_validate_artifacts(self.root / "missing.jsonl", self.root / "missing")

    def test_17_corrupted_metadata_handling(self):
        chunks_path, embedding_dir = write_bundle_artifacts(self.root, corrupt_metadata=True)
        with self.assertRaisesRegex(ValueError, "invalid JSONL"):
            load_and_validate_artifacts(chunks_path, embedding_dir, expected_count=3, expected_dimension=3)

    def test_18_duplicate_id_handling(self):
        chunks_path, embedding_dir = write_bundle_artifacts(self.root, duplicate=True)
        with self.assertRaisesRegex(ValueError, "duplicate chunk ID"):
            load_and_validate_artifacts(chunks_path, embedding_dir, expected_count=4, expected_dimension=3)

    def test_19_existing_collection_mismatch_protection(self):
        self.client.create_collection(
            "mismatch_collection", configuration={"hnsw": {"space": "cosine"}},
            metadata={"dataset_fingerprint": "different"}, embedding_function=None,
        )
        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            self.ingest(name="mismatch_collection")

    def test_20_database_reopening_after_process_restart(self):
        path = self.root / "restart_db"
        client = persistent_client(path)
        self.ingest(client, "restart_collection")
        code = (
            "import chromadb; "
            f"c=chromadb.PersistentClient(path={str(path)!r}); "
            "print(c.get_collection('restart_collection', embedding_function=None).count())"
        )
        completed = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
        self.assertEqual(completed.stdout.strip(), "3")


if __name__ == "__main__":
    unittest.main()

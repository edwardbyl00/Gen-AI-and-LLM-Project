# Stage 8 ChromaDB Ingestion and Validation Summary

## Final Status

**PASS_WITH_WARNINGS**

The persistent ChromaDB was created successfully from the existing Stage 6 embeddings. All critical database validations passed. The warning is limited to small approximate-nearest-neighbour differences near the bottom of the top-10 lists; all top-5 sets and all aggregate retrieval metrics match the unchanged NumPy baseline.

## Database Validation

- ChromaDB version: `1.5.9`
- Collection: `hdb_housing_advisory_bge_base_v1_5`
- Persistent storage: `data/vector_db/chroma/`
- Storage size after ingestion: approximately 19 MB
- Records: 1,282
- Unique record IDs: 1,282
- Original documents represented: 42
- Embedding model: `BAAI/bge-base-en-v1.5`
- Model revision: `a5beb1e3e68b9ab74eb54cfd186867f64f240e1a`
- Embedding dimension: 768
- Normalization: L2
- Distance metric: cosine
- Dataset fingerprint: `b5bfd15604e07fc485138162f828971fe12e61371a86f549eb152cb30e52d3fa`
- Manifest reference: `data/embeddings/bge-base-en-v1.5/manifest.json`
- Initial ingestion: 1,282 inserted, final count 1,282
- Immediate safe rerun: 0 inserted, 1,282 already present, final count 1,282

Before ingestion, the implementation verified the source chunk count, metadata count, vector shape, unique IDs, exact ordering, content hashes, manifest fingerprint, model configuration, finite values, non-zero vectors, L2 normalization and linked-reference integrity. After ingestion, it read every Chroma record back and compared its ID, exact document text, transformed metadata and stored vector against the validated artifacts.

### Metadata representation

Chroma documents contain the exact original `content` string. Primitive source and structural fields are stored using their original types, including booleans such as `requires_context`. Null fields are omitted rather than converted to strings.

Selected nested fields are stored as deterministic JSON strings with explicit `_json` suffixes:

- `section_path_json`
- `hierarchy_json`
- `block_types_json`
- `flags_json`
- `source_block_ids_json`

Every record also stores `content_sha256` and `source_metadata_sha256` for validation. Large provenance structures such as `source_slices`, `source_segments`, `table_fragments`, and duplicate `source_content` are not copied into Chroma metadata; their complete canonical versions remain unchanged in `metadata.jsonl`. This avoids unnecessary duplication without losing the authoritative metadata artifact.

### Lookup and persistence

- Direct lookup passed: `C05_c0014` returned the exact stored table chunk and source metadata.
- Linked lookup passed: `H01_c0009` resolved its `next_chunk_id` to `H01_c0010`.
- Linked lookup does not append context to semantic search results or change ranking.
- Metadata filtering passed: a query restricted to `document_id=C03` returned only `C03` chunks.
- Persistence passed by reopening the database through a new client and through a separate Python process.
- Existing-collection protection passed: a mismatched fingerprint/configuration is rejected without deletion, overwrite, or upsert.
- Automatic document/query embedding is disabled (`embedding_function=None`); Chroma rejects `query_texts`, while the query CLI supplies separately generated normalized BGE vectors.

## NumPy vs Chroma Consistency

The same 40 questions, BGE model, query instruction, normalized query vectors, document vectors, corpus and cosine metric were used. The Stage 7 baseline file was read-only and its metrics were verified unchanged.

- Questions compared: 40
- Top-5 set matches: 40 / 40
- Top-10 set matches: 36 / 40
- Exact top-10 rank-order matches: 35 / 40
- Maximum cosine-similarity difference for a common top-10 ID: `0.0000011325`
- Questions with any rank/order difference: `H01`, `H03`, `H07`, `H11`, `H26`
- `H11` had the same top-10 set with two adjacent positions reversed.
- `H01`, `H03`, `H07`, and `H26` differed only in membership near rank 9 or 10.

| Metric | NumPy baseline | ChromaDB |
|---|---:|---:|
| Hit@5 | 0.6666666667 | 0.6666666667 |
| Hit@10 | 0.7435897436 | 0.7435897436 |
| Recall@5 | 0.3626373626 | 0.3626373626 |
| Recall@10 | 0.4669719170 | 0.4669719170 |
| MRR@10 | 0.4730769231 | 0.4730769231 |

The minor rank differences are consistent with Chroma's approximate HNSW search and very small floating-point differences. They do not change any reported baseline metric. Per-question evidence is in `reports/chroma_vs_numpy_consistency.csv`.

## Test Results

- Stage 8 ChromaDB tests: **20 / 20 passed**
- Full project regression suite: **81 / 81 passed**

The Stage 8 suite covers collection creation, persistent storage, count, unique IDs, dimensions, metadata mapping, exact document preservation, direct and linked lookup, idempotency, fingerprint/model validation, cosine configuration, query-vector compatibility, NumPy consistency, missing/corrupted artifacts, duplicate IDs, mismatch protection, and reopening after a separate process starts.

## Scope Distinctions

- **Database validation:** passed. It establishes safe storage, mapping, persistence, lookup, filtering and reproducible ingestion.
- **Retrieval quality evaluation:** the existing Stage 7 baseline is unchanged; Chroma reproduces its aggregate metrics. This stage does not optimize retrieval.
- **Answer quality evaluation:** not performed. No reranking, query decomposition, hybrid retrieval, linked-context expansion or LLM answer generation was added.

## Known Limitations and Warnings

1. Chroma HNSW search is approximate, so exact top-10 order is not guaranteed even with the same normalized vectors.
2. Nested Chroma metadata is serialized as JSON strings and must be decoded by consumers that need its structure; the full canonical metadata remains in the Stage 6 JSONL artifact.
3. The implementation is a local `PersistentClient` database for development and validation. It has not been configured as an authenticated network service.
4. The system Python reports an `urllib3` LibreSSL compatibility warning when importing the query stack. It did not affect local database operations or the completed tests, but a newer OpenSSL-linked Python environment would remove the warning.
5. The generated database is intentionally excluded from Git and must be rebuilt locally from the validated Stage 6 artifacts.

No raw HTML, cleaned data, `chunks.jsonl`, embedding vectors/metadata, ground-truth labels, evaluation questions, or Stage 7 baseline metrics were modified by Stage 8. No commit or push was performed.

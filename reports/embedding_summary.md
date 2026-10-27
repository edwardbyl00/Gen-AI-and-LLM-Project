# Stage 6 Embedding Generation and Validation Summary

## Generation

- Status: **PASS**
- Total chunks processed: 1282
- Embeddings generated: 1282
- Model: `BAAI/bge-base-en-v1.5`
- Embedded field: `content` (the JSON object itself was not embedded)
- Embedding dimension: 768
- Device: `MPS`
- Processing time: 27.72 seconds
- Normalized for cosine similarity: yes
- Input maximum tokens (special tokens included; no truncation): 511
- Input dataset SHA-256: `b5bfd15604e07fc485138162f828971fe12e61371a86f549eb152cb30e52d3fa`
- Artifact directory: `data/embeddings/bge-base-en-v1.5`
- Failures or skipped chunks: none

## Artifact Structure

- `embeddings.npy`: float32 vectors in deterministic input order
- `metadata.jsonl`: every original non-text field plus `embedding_index` and a SHA-256 of the embedded text
- `manifest.json`: model, generation, validation, normalization, and input-fingerprint provenance
- Join key: `chunk_id`; the unchanged `chunks.jsonl` remains the source of `content`, avoiding duplicate text storage

## Vector Norm Statistics

- Minimum: 0.99999988
- Mean: 1.00000000
- Maximum: 1.00000012

## Validation

- PASS — `one_embedding_per_chunk`
- PASS — `unique_chunk_ids`
- PASS — `embedding_dimension_768`
- PASS — `no_nan`
- PASS — `no_inf`
- PASS — `no_zero_vectors`
- PASS — `no_empty_chunk_text`
- PASS — `inputs_within_512_tokens`
- PASS — `chunk_id_mapping_preserved`
- PASS — `linked_metadata_intact`

## Semantic Similarity Smoke Test

Queries use the BGE retrieval instruction. The results below are a diagnostic sanity check only and do not prove retrieval accuracy.

### What are the eligibility conditions for buying an HDB flat?

| Rank | Score | Chunk | Source | Title / section |
|---:|---:|---|---|---|
| 1 | 0.824893 | `H05_C_c0023` | HDB | Terms and Conditions - Sale and Purchase of An HDB Resale Flat / Terms and Conditions - Sale and Purchase of An HDB Resale Flat > **APPLICABLE TO THE BUYER** |
| 2 | 0.818124 | `H07_c0015` | HDB | Standard, Plus, and Prime Housing Framework / Standard, Plus, and Prime Housing Framework > More housing options for singles > Eligibility conditions for buyers |
| 3 | 0.817625 | `H05_A_c0001` | HDB | Eligibility for Buying a Resale Flat / Eligibility for Buying a Resale Flat |
| 4 | 0.815339 | `H05_C_c0025` | HDB | Terms and Conditions - Sale and Purchase of An HDB Resale Flat / Terms and Conditions - Sale and Purchase of An HDB Resale Flat > **APPLICABLE TO THE BUYER** |
| 5 | 0.811353 | `H02_c0037` | HDB | Singles / Singles > **Eligibility conditions** > Next steps > Process for Buying a New Flat |

### What income ceiling applies to an HDB housing loan?

| Rank | Score | Chunk | Source | Title / section |
|---:|---:|---|---|---|
| 1 | 0.791925 | `H02_c0009` | HDB | Singles / Singles > **Eligibility conditions** |
| 2 | 0.791925 | `H02_c0025` | HDB | Singles / Singles > **Eligibility conditions** |
| 3 | 0.785260 | `H01_c0008` | HDB | Couples and Families / Couples and Families > Eligibility conditions |
| 4 | 0.785260 | `H01_c0029` | HDB | Couples and Families / Couples and Families > Eligibility conditions |
| 5 | 0.785260 | `H01_c0049` | HDB | Couples and Families / Couples and Families > Eligibility conditions |

### How much CPF savings can I retain in my Ordinary Account when taking a housing loan?

| Rank | Score | Chunk | Source | Title / section |
|---:|---:|---|---|---|
| 1 | 0.815025 | `C05_c0013` | CPF | CPFB \| Retain $20,000 in your OA if you are taking a housing loan / Retain $20,000 in your Ordinary Account if you are taking a housing loan > Find out how retaining $20,000 affects your monthly instalments |
| 2 | 0.811347 | `C05_c0002` | CPF | CPFB \| Retain $20,000 in your OA if you are taking a housing loan / Retain $20,000 in your Ordinary Account if you are taking a housing loan |
| 3 | 0.803955 | `C05_c0003` | CPF | CPFB \| Retain $20,000 in your OA if you are taking a housing loan / Retain $20,000 in your Ordinary Account if you are taking a housing loan > Who is it for? |
| 4 | 0.800645 | `C05_c0008` | CPF | CPFB \| Retain $20,000 in your OA if you are taking a housing loan / Retain $20,000 in your Ordinary Account if you are taking a housing loan > When do I need to decide how much to retain in my OA? |
| 5 | 0.799118 | `C05_c0012` | CPF | CPFB \| Retain $20,000 in your OA if you are taking a housing loan / Retain $20,000 in your Ordinary Account if you are taking a housing loan > Find out how retaining $20,000 affects your monthly instalments |

### What restrictions apply to second-timer applicants?

| Rank | Score | Chunk | Source | Title / section |
|---:|---:|---|---|---|
| 1 | 0.648915 | `H01_c0092` | HDB | Couples and Families / Couples and Families > Eligibility conditions |
| 2 | 0.646393 | `H02_c0030` | HDB | Singles / Singles > **Eligibility conditions** |
| 3 | 0.642701 | `H02_c0014` | HDB | Singles / Singles > **Eligibility conditions** |
| 4 | 0.635436 | `H01_c0014` | HDB | Couples and Families / Couples and Families > Eligibility conditions |
| 5 | 0.635436 | `H01_c0035` | HDB | Couples and Families / Couples and Families > Eligibility conditions |

### When is Additional Buyer's Stamp Duty payable for a residential property?

| Rank | Score | Chunk | Source | Title / section |
|---:|---:|---|---|---|
| 1 | 0.764473 | `IR02_c0018` | IRAS | IRAS \| Additional Buyer's Stamp Duty (ABSD) / Additional Buyer's Stamp Duty (ABSD) > Rates and computation |
| 2 | 0.761262 | `IR02_c0017` | IRAS | IRAS \| Additional Buyer's Stamp Duty (ABSD) / Additional Buyer's Stamp Duty (ABSD) > Rates and computation |
| 3 | 0.753335 | `IR02_c0013` | IRAS | IRAS \| Additional Buyer's Stamp Duty (ABSD) / Additional Buyer's Stamp Duty (ABSD) > Rates and computation |
| 4 | 0.752671 | `IR02_c0019` | IRAS | IRAS \| Additional Buyer's Stamp Duty (ABSD) / Additional Buyer's Stamp Duty (ABSD) > Rates and computation |
| 5 | 0.750736 | `IR02_c0014` | IRAS | IRAS \| Additional Buyer's Stamp Duty (ABSD) / Additional Buyer's Stamp Duty (ABSD) > Rates and computation |

Full previews are available in `reports/embedding_smoke_test.csv`.

## Conclusion

The artifact is ready for future ChromaDB ingestion.
No ChromaDB collection, retrieval pipeline, reranker, or answer-generation component was created.

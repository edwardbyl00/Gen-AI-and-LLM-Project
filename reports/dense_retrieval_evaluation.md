# HDB Advisory RAG Dense Retrieval Evaluation

## Evaluation Dataset

- Questions: 40
- Question IDs: unique
- Empty or duplicate questions: 0
- Query model: `BAAI/bge-base-en-v1.5` with the model-recommended retrieval instruction
- Query device: `CPU`
- Runtime: 1.78 seconds
- Baseline: normalized query embedding × existing normalized document embeddings; NumPy cosine similarity; top 10
- ChromaDB, reranking, query decomposition, hybrid search and answer generation: not used

## Artifact Validation

- PASS — `shape_1282_768`
- PASS — `unique_chunk_ids`
- PASS — `ordering_matches_metadata`
- PASS — `metadata_maps_to_chunks`
- PASS — `no_nan_or_inf`
- PASS — `no_zero_vectors`
- PASS — `normalized`
- PASS — `model_matches_manifest`
- PASS — `input_fingerprint_matches`
- PASS — `linked_metadata_preserved`
- PASS — `linked_reference_integrity`

## Ground Truth

- Verified questions: 40 / 40
- FULL: 39
- PARTIAL: 0
- NOT_COVERED: 1
- UNVERIFIED: 0
- Relevance labels are verified core evidence. They are intentionally not claimed as an exhaustive pool of every duplicate or supporting chunk.
- H29 is retained as a NOT_COVERED evidence-gap control because the knowledge base has no transaction-level resale-price dataset.

## Dense Retrieval Metrics

- Questions included in ordinary retrieval metrics: 39
- Questions excluded: 1
- Hit@5: 0.667
- Hit@10: 0.744
- Recall@5: 0.363 (partial-label recall)
- Recall@10: 0.467 (partial-label recall)
- MRR@10: 0.473

The recall values measure recovery of the reviewed core evidence chunks, not exact recall over every possible relevant chunk.

## Per-category Performance

| Category | N | Hit@5 | Hit@10 | Recall@5 | Recall@10 | MRR@10 |
|---|---:|---:|---:|---:|---:|---:|
| Boundary / Personalized | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| CPF HPS | 1 | 0.000 | 1.000 | 0.000 | 0.200 | 0.100 |
| CPF OA reserve | 1 | 1.000 | 1.000 | 0.143 | 0.429 | 0.333 |
| CPF age 55 | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| CPF age 55 scenario | 1 | 1.000 | 1.000 | 0.167 | 0.500 | 0.200 |
| CPF lease limit | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 0.200 |
| CPF purchase costs | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| CPF second property | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| CPF shortfall | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| CPF voluntary refund | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 0.333 |
| CPF withdrawal limit | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Eligibility | 9 | 0.444 | 0.556 | 0.222 | 0.315 | 0.306 |
| Financing / CPF / Tax | 6 | 0.667 | 0.667 | 0.139 | 0.208 | 0.472 |
| Grants | 6 | 0.833 | 1.000 | 0.222 | 0.444 | 0.750 |
| Resale / CPF Refund | 2 | 1.000 | 1.000 | 0.833 | 1.000 | 0.500 |
| Restrictions | 5 | 0.600 | 0.600 | 0.400 | 0.467 | 0.440 |

## Top Retrieval Failure Cases

Failure codes: E weak semantic similarity; F multi-document; G multiple conditions; H insufficient query specificity.

| Question | First relevant rank | Cause | Observation | Recommended next step |
|---|---:|---|---|---|
| H01 | not_in_top_10 | E | The verified core evidence did not appear in the top five dense results. | Reranking after broader candidate retrieval |
| H06 | not_in_top_10 | G;H | Multiple conditional property-ownership rules are expressed as table cells rather than the question's yes/no wording. | Hybrid retrieval or query decomposition |
| H07 | not_in_top_10 | E | The verified core evidence did not appear in the top five dense results. | Reranking after broader candidate retrieval |
| H08 | 6 | E | The verified core evidence did not appear in the top five dense results. | Reranking after broader candidate retrieval |
| H09 | not_in_top_10 | F;G | The question asks for a comparison spanning several independent eligibility rows. | Query decomposition |
| H11 | not_in_top_10 | E | The verified core evidence did not appear in the top five dense results. | Reranking after broader candidate retrieval |
| H13 | not_in_top_10 | E | The verified core evidence did not appear in the top five dense results. | Reranking after broader candidate retrieval |
| H16 | 6 | E | The verified core evidence did not appear in the top five dense results. | Reranking after broader candidate retrieval |
| H22 | not_in_top_10 | E;F;G | A broad comparison needs matching terms from two loan documents; generic finance chunks outrank the core comparison rows. | Query decomposition followed by reranking |
| H25 | not_in_top_10 | E;F;H | The query says HDB resale flat while the authoritative evidence is in separate generic BSD and ABSD documents. | Hybrid retrieval or query decomposition, then reranking |
| H30 | not_in_top_10 | F;G;H | The personalized multi-domain question combines eligibility, CPF, financing and tax conditions. | Query decomposition and multi-document retrieval |
| C04 | not_in_top_10 | E | The verified core evidence did not appear in the top five dense results. | Reranking after broader candidate retrieval |
| C06 | 10 | E;G | Coverage requirements and exemption conditions live in different HPS chunks. | Query decomposition or reranking |

## Linked-chunk Observations

- Relevant linked chunks reviewed: 10
- Relevant linked chunks retrieved in top 10: 1
- Linked evidence should remain separately embedded. At answer time, adjacent expansion can restore conditions or table/legal continuation without changing the dense baseline.

| Question | Relevant chunk | Retrieved in top 10 | Linked chunks | Sufficient alone | Adjacent context required | Expansion may help |
|---|---|---|---|---|---|---|
| H04 | `H01_c0084` | yes | H01_c0083;H01_c0085 | false | true | true |
| H06 | `H01_c0010` | no | H01_c0009;H01_c0011 | false | true | true |
| H06 | `H01_c0011` | no | H01_c0010;H01_c0012 | false | true | true |
| H07 | `H01_c0010` | no | H01_c0009;H01_c0011 | false | true | true |
| H07 | `H01_c0011` | no | H01_c0010;H01_c0012 | false | true | true |
| H09 | `H01_c0010` | no | H01_c0009;H01_c0011 | false | true | true |
| H15 | `H04_B_c0005` | no | H04_B_c0004;H04_B_c0006 | false | true | true |
| H18 | `H04_C_c0008` | no | H04_C_c0007;H04_C_c0009 | false | true | true |
| H21 | `H08_A_c0008` | no | H08_A_c0007;H08_A_c0009 | false | true | true |
| H30 | `H01_c0010` | no | H01_c0009;H01_c0011 | false | true | true |

## Recommendations for Advanced RAG

1. Add reranking over a broader dense candidate set for semantically weak but authoritative policy chunks.
2. Decompose multi-condition and multi-document questions, especially loan comparisons, stamp duties and personalized option reviews.
3. Add hybrid lexical retrieval for exact policy terms, statutory labels, grant names and tax acronyms.
4. Expand previous/next linked chunks after retrieval when `requires_context` is true.
5. Keep H29 as an insufficient-evidence test until a governed transaction dataset is added.
6. Expand relevance judgments through pooled human review before presenting recall as exhaustive ground-truth recall.

## Limitations

- This evaluates retrieval, not generated answer correctness, completeness or safety.
- Coverage describes the current local policy corpus; missing user facts are tracked separately.
- Recall is partial-label recall because the verified labels identify core evidence rather than every duplicative relevant chunk.
- No external websites were used to fill local knowledge gaps.

## Conclusion

The evaluation pipeline and embedding alignment passed. Source coverage, retrieval performance and answer quality remain distinct: a FULL policy label does not guarantee top-k retrieval, and top-k retrieval does not prove a correct final answer.

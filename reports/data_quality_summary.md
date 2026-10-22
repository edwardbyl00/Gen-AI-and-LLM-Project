# Data Quality Validation Summary

## Overall result

**PASS WITH CONDITIONS**

Automated preservation checks found 0 failed checks. Conditions remain because structural/manual review items and external model/legal verification cannot be resolved by automated local checks alone.

## Dataset totals

- Total raw documents: 43
- Successfully cleaned and retained documents: 42
- Excluded exact duplicates: 1 (H09_C)
- Documents requiring manual review: 13 (C02_A, C05, C06, H02_B, H03, H06, H09_G, S01, S02, S03, S04, S05, S06)
- Total generated chunks: 587

## Chunk size distribution

- Counter: `regex_words_v1` (not an embedding-model tokenizer)
- Minimum: 1
- Median: 189
- Mean: 230.95
- Maximum: 500
- Extremely short chunks: 13
- Extremely long chunks: 0

## Preservation results

- Documents with missing metadata: 0
- Raw-to-cleaned reproducibility issues: 0
- Table preservation issues: 0
- Legal structure preservation issues: 0
- Exact-content chunk groups: 13
- Standalone heading chunks: 7
- Policy documents with no structured section paths: 3 (C02_A, C05, C06)
- Reference-question source gaps: 1

## Known limitations

- The BAAI/bge-small-en-v1.5 tokenizer was not available locally. Embedding-model token limits are **NOT VERIFIED**; regex token counts are not WordPiece counts.
- Standalone headings and documents without structured section paths require manual hierarchy review.
- SSO schedule/provision capture gaps originate in the supplied raw snapshots and cannot be recovered during cleaning or chunking.
- Captured legal version metadata has not been independently checked against the live official SSO service.
- Condition and exception checks verify textual preservation, not legal interpretation or answer correctness.
- The supplied question files are preservation references only; no RAG or answer-accuracy evaluation was performed.

# Embedding-Safe Structure-Aware Chunking Summary

## Configuration

- Documents: 42
- Tokenizer: `BAAI/bge-base-en-v1.5` (special tokens included; no truncation)
- Target size: 400 tokens
- Hard maximum: 512 tokens
- Overlap: 0 tokens; linked chunks use explicit navigation metadata

## Results

- Chunks: 1282
- Token distribution (min / Q1 / median / mean / Q3 / max): 18 / 72 / 127.0 / 173.84 / 256 / 511
- Chunks over 512: 0
- Linked chunks: 180
- Table chunks: 475
- Legal-provision chunks: 183
- Manual-review chunks: 91
- Validation failures: 0
- Validation warnings: 91
- Overall validation: PASS

Headings are stored as repeated context rather than standalone chunks. Tables preserve row labels and column headers. Long legal provisions and oversized table rows are split at semantic boundaries and connected through `parent_id`, ordered part fields, and previous/next chunk IDs.

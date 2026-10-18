# Structure Aware Chunking Summary

## Configuration

- Input documents: 42
- Target chunk size: 500 regex word tokens
- Configured overlap: 75 regex word tokens
- Token counter: regex_words_v1

## Result

- Generated chunks: 587
- Minimum chunk tokens: 1
- Median chunk tokens: 189
- Maximum chunk tokens: 500
- Oversized chunks retained intentionally: 0
- Chunks containing table fragments: 136
- Legal provision chunks: 136

Tables are split by row with their header rows repeated. Legal provisions are split at numeric subsection boundaries where possible. A table row or legal subsection that cannot be safely divided may exceed the target and is explicitly flagged rather than truncated.

# Data preparation → policy agent RAG handoff contract

The data-preparation stage provides cleaned policy documents/chunks for the
policy agent to use. Checked against `src/chunk_adapter.py` and the local
corpus on 31 October 2026. This distinguishes the persisted P4 chunk schema
from the normalized evidence consumed by P5 and synthesis.

## Required fields

The persisted corpus is `data/processed/chunks.jsonl`.

| Normalized evidence field | Persisted chunk field / adapter rule |
| --- | --- |
| `document_id`, `chunk_id`, `title`, `source` | Same field names |
| `category` | `category` if present, otherwise `document_type` |
| `url` | `url` if present, otherwise `source_url` |
| `text` | `text` if present, otherwise `content` |
| `effective_date` | Retained as supplied; may be null |
| `section_title`, `section_path`, `section_number` | Retained when supplied |

P4 also stores `retrieved_at` as capture provenance. It is not an effective
date; the current normalizer does not expose it as `collection_date` or put it
in synthesis citations. The 1,282 local chunks all have `source_url`, `content`
and `retrieved_at`, and none has a populated `effective_date`. These are local
snapshot observations, not a promise about later corpus rebuilds.

## Example

```json
{
  "document_id": "H01",
  "chunk_id": "H01_c0001",
  "title": "Couples and Families Eligibility",
  "source": "HDB",
  "category": "Eligibility",
  "url": "...",
  "effective_date": null,
  "text": "..."
}
```

This example is normalized evidence, not the on-disk chunk schema. Conversion
is owned by [src/chunk_adapter.py](../src/chunk_adapter.py); policy evidence
assembly is in [src/policy_retriever.py](../src/policy_retriever.py).

## Data-preparation responsibility

- collect official HDB / CPF / SSO documents
- clean the documents
- preserve headings and important structure
- provide metadata
- build the vanilla retrieval/index

## Policy-agent responsibility

- date/effective-date handling
- advanced retrieval
- re-query logic
- policy agent
- AI judge
- compare advanced retrieval against vanilla RAG

## Shared

- plain RAG baseline
- integration testing
- evaluation questions; use [stage_evaluation.md](stage_evaluation.md) for the
  current routing/evidence/answer-quality review workflow

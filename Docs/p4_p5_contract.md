# P4 → P5 RAG Handoff Contract

P4 will provide cleaned policy documents/chunks for P5 to use.

## Required fields

Each document/chunk should contain:

- document_id
- title
- source
- category
- url
- collection_date
- effective_date
- text

## Example

{
  "document_id": "H01",
  "title": "Couples and Families Eligibility",
  "source": "HDB",
  "category": "Eligibility",
  "url": "...",
  "collection_date": "2026-10-16",
  "effective_date": null,
  "text": "..."
}

## P4 responsibility

- collect official HDB / CPF / SSO documents
- clean the documents
- preserve headings and important structure
- provide metadata
- build the vanilla retrieval/index

## P5 responsibility

- date/effective-date handling
- advanced retrieval
- re-query logic
- policy agent
- AI judge
- compare advanced retrieval against vanilla RAG

## Shared

- plain RAG baseline
- integration testing
- evaluation questions
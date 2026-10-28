# Chunk Warning Audit Summary

## Scope

- Original warning occurrences: 225
- Original unique affected chunks: 194
- Original `missing_explicit_table_header`: 137
- Original `hierarchy_ambiguous`: 88
- Warning occurrences reviewed: 225

### Overlapping policy-risk inventory (unique chunks)

- Both warning types: 31
- Eligibility, citizenship, age, household, or qualification: 70
- Income ceilings, grants, amounts, prices, loans, premiums, or financial limits: 139
- CPF usage, property ownership, resale, or housing restrictions: 159
- Legal/policy conditions, exceptions, restrictions, or clauses: 71
- Other lower-risk material: 6

## Audit decisions

- PASS (harmless): 92
- FIXABLE: 133
- MANUAL_REVIEW: 0
- SOURCE_LIMITATION: 0
- Confirmed issues corrected: 133
- Genuine items still requiring human review: 0

## Resolution

- CPF hierarchy is recovered in memory from explicit raw HTML `headline-*`, masthead, and action-card heading classes. No cleaned file was changed.
- Table header recovery is limited to concise first rows whose own source text explicitly names column concepts. No header wording is generated.
- HDB key-value tables retain their warnings where the source genuinely has no separate header row; these are PASS because every chunk repeats its row label and value.
- The user verified C05's Ben/Lexie column continuity. The first table's exact subject text is now used as headers and inherited by the immediately adjacent second table through its explicit “respective decisions” bridge paragraph.
- Current emitted warning chunks: 91. Of these, 91 are audited harmless retained warnings and 0 require human verification.

## High-risk findings

- The C05 mapping was confirmed by the user and corrected without hardcoding its financial values: Ben remains associated with `$40,000`, `$470,000`, and `$2,514`; Lexie remains associated with `$0`, `$430,000`, and `$2,300`.
- Recovered CPF headers include property type, loan type, withdrawal maximum, lease/age percentages, bank versus HDB loan, cash versus CPF, and new versus resale flat context.

## Validation result

- Documents represented: 42/42
- Regenerated chunks: 1,282
- BGE token range: 18–511, including special tokens
- Chunks over 512 tokens: 0
- Linked Chunk groups: 42
- Broken Linked Chunk relationships: 0
- Heading-only chunks: 0
- Content/table-cell reconstruction failures: 0
- Structural validation failures: 0
- Project tests: 44/44 passed
- Remaining emitted warning chunks: 91 (91 audited harmless, 0 requiring review)

**Embedding readiness: READY.** The dataset passes every deterministic validation, all formerly high-risk C05 associations are now explicit in each affected chunk, and the retained warnings are audited harmless key-value layouts. Embedding was not performed.

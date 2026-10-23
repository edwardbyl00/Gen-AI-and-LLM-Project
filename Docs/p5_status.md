# P5 — Advanced / Agentic RAG Status

## Status

**Implementation and evaluation complete.**

P5 extends the P4 dense-retrieval baseline with advanced retrieval, evidence assessment, agentic self-correction, safe abstention, and LLM-based evaluation.

## Implemented

### Advanced Retrieval

* BM25 lexical retrieval
* BGE dense retrieval using `BAAI/bge-base-en-v1.5`
* Reciprocal Rank Fusion (RRF)
* Query rewriting / re-query
* Weighted hybrid retrieval experiments

### Agentic Policy Retrieval

* Evidence sufficiency assessment using an LLM
* Separation of missing **policy evidence** from missing **user information**
* Conditional answering when user-specific facts are missing
* Query decomposition when evidence is insufficient
* Targeted retrieval and reassessment
* Evidence selection before synthesis
* Safe `ABSTAIN` behaviour when evidence remains insufficient
* Cleaning of LLM-generated subqueries for the local corpus

### Evaluation

* Dense vs advanced retrieval benchmark
* Baseline vs agentic answer-level pilot
* Existing faithfulness LLM-as-judge
* Ground-truth-aware LLM judge
* Decision repeatability evaluation

## Retrieval Evaluation

39 covered policy questions were used for ordinary retrieval metrics. H29 was retained separately as a no-policy-evidence control.

| Metric    | Dense Baseline | Advanced Hybrid |
| --------- | -------------: | --------------: |
| Hit@5     |          0.667 |           0.641 |
| Hit@10    |          0.744 |           0.744 |
| Recall@5  |          0.363 |           0.341 |
| Recall@10 |          0.467 |           0.427 |
| MRR@10    |          0.473 |           0.477 |

**Finding:** naive BM25 + dense hybrid retrieval did not outperform the strong dense baseline overall. It improved the rank of some difficult questions, but reduced aggregate recall and Hit@5.

Therefore, P5 does **not** claim that hybrid retrieval is universally better. Dense retrieval remains the stronger retrieval backbone for this corpus.

## Agentic Answer Evaluation

A 10-question pilot compared:

* **Baseline:** dense top-10 retrieval → synthesis
* **Agentic P5:** retrieval → evidence assessment → targeted self-correction/decomposition → reassessment → answer or abstain → synthesis

### LLM-as-Judge Results

| Evaluation                  | Baseline |   Agentic P5 |
| --------------------------- | -------: | -----------: |
| Faithfulness-oriented judge | 7.8 / 10 | **8.5 / 10** |
| Ground-truth-aware judge    | 7.4 / 10 | **8.7 / 10** |

The agentic approach improved difficult cases such as C06 and C10 by recovering additional relevant evidence and reassessing it before synthesis.

C04 and H29 demonstrated safe abstention behaviour when sufficient policy evidence was unavailable.

## Repeatability

The 10-question agentic pilot was repeated across three runs.

* Mean decision agreement: **96.7%**
* Fully stable questions: **9 / 10**
* H01 was the only unstable case.

H01 is a borderline evidence-sufficiency case. Additional repeated testing produced both `ANSWER_READY` and `ABSTAIN` outcomes, demonstrating that LLM-based evidence assessment can introduce run_

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from hybrid_retriever import hybrid_retrieve


bm25_results = [
    (
        {"document_id": "C01", "title": "CPF Housing"},
        3.2,
    ),
    (
        {"document_id": "H06", "title": "Minimum Occupation Period"},
        2.1,
    ),
    (
        {"document_id": "H01", "title": "HDB Eligibility"},
        1.4,
    ),
]


dense_results = [
    {
        "document_id": "H01",
        "title": "HDB Eligibility",
    },
    {
        "document_id": "C01",
        "title": "CPF Housing",
    },
    {
        "document_id": "NEW01",
        "title": "Updated CPF Rule",
    },
]


results = hybrid_retrieve(
    bm25_results=bm25_results,
    dense_results=dense_results,
    top_k=3,
)


print("Hybrid results:")

for i, result in enumerate(results, start=1):
    print(
        f"{i}. {result['document_id']} "
        f"| RRF={result['rrf_score']:.6f}"
    )


assert len(results) == 3
assert results[0]["document_id"] == "C01"

print("\nHybrid retriever test passed.")
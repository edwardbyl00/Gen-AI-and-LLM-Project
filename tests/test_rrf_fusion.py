import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from rrf_fusion import reciprocal_rank_fusion


bm25_results = [
    (
        {"document_id": "C01", "title": "CPF Housing"},
        3.21,
    ),
    (
        {"document_id": "H06", "title": "MOP"},
        2.10,
    ),
    (
        {"document_id": "H01", "title": "HDB Eligibility"},
        1.40,
    ),
]


dense_results = [
    {"document_id": "H01", "title": "HDB Eligibility"},
    {"document_id": "C01", "title": "CPF Housing"},
    {"document_id": "NEW01", "title": "Updated CPF Rule"},
]


fused = reciprocal_rank_fusion(
    [bm25_results, dense_results]
)


print("Fused ranking:")

for i, result in enumerate(fused, start=1):
    print(
        f"{i}. {result['document_id']} "
        f"| RRF={result['rrf_score']:.6f}"
    )


assert fused[0]["document_id"] == "C01"

print("\nRRF fusion test passed.")
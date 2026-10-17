import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from hybrid_search import load_policies
from requery import search_with_requery


policies = load_policies()


def test_oa_query_rewrites():
    output = search_with_requery(
        query="Can I use OA savings for my flat?",
        policies=policies,
        query_date="2026-06-01",
        top_k=3
    )

    assert output["requeried"] is True
    assert output["rewrite_accepted"] is True
    assert "Ordinary Account" in output["final_query"]
    assert output["results"][0][0]["document_id"] == "C01"


if __name__ == "__main__":
    test_oa_query_rewrites()
    print("All tests passed.")
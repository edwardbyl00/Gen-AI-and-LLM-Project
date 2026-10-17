import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from chunk_adapter import normalize_chunk
from policy_retriever import retrieve_policy_evidence


raw_chunks = [
    {
        "document_id": "C01",
        "chunk_id": "C01_c001",
        "title": "Using CPF to Buy a Home",
        "source": "CPF",
        "document_type": "policy",
        "source_url": "https://www.cpf.gov.sg/example",
        "effective_date": "2026-01-01",
        "content": (
            "CPF Ordinary Account savings may be used "
            "for eligible housing purchases."
        ),
        "section_title": "Using CPF savings",
        "section_path": ["Housing", "Using CPF savings"],
    },
    {
        "document_id": "H06",
        "chunk_id": "H06_c001",
        "title": "Minimum Occupation Period",
        "source": "HDB",
        "document_type": "policy",
        "source_url": "https://www.hdb.gov.sg/example",
        "effective_date": "2025-01-01",
        "content": (
            "The Minimum Occupation Period applies to "
            "eligible HDB flats."
        ),
        "section_title": "MOP",
        "section_path": ["Resale", "MOP"],
    },
]


policies = [normalize_chunk(chunk) for chunk in raw_chunks]


result = retrieve_policy_evidence(
    question="Can I use CPF Ordinary Account savings to buy a home?",
    query_date="2026-06-01",
    policies=policies,
)


assert len(result["evidence"]) > 0
assert result["evidence"][0]["document_id"] == "C01"
assert result["evidence"][0]["chunk_id"] == "C01_c001"

print("P4-style chunk integration test passed.")
print("Top result:", result["evidence"][0]["title"])
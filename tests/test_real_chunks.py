import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from chunk_adapter import load_chunks_jsonl
from policy_retriever import retrieve_policy_evidence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_PATH = PROJECT_ROOT / "data" / "processed" / "chunks.jsonl"

if not CHUNKS_PATH.exists():
    print("SKIPPED: P4 chunks.jsonl is not available on this branch.")
    sys.exit(0)

chunks = load_chunks_jsonl(CHUNKS_PATH)

print(f"Loaded {len(chunks)} real P4 chunks.")


result = retrieve_policy_evidence(
    question="What is the Minimum Occupation Period for an HDB flat?",
    top_k=5,
    policies=chunks,
)


print("\nTop retrieved chunks:")

for i, item in enumerate(result["evidence"], start=1):
    print(
        f"{i}. {item['document_id']} | "
        f"{item['title']} | "
        f"{item['section_title']} | "
        f"score={item['score']:.3f}"
    )


assert len(chunks) > 0
assert len(result["evidence"]) > 0

print("\nReal chunk retrieval test passed.")
# Gen-AI-and-LLM-Project

## Stage 8 local ChromaDB

Install the pinned dependencies in the project virtual environment, then build the local database from the existing Stage 6 artifacts:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/build_chroma_db.py
```

The build is idempotent. It validates the chunk fingerprint, embedding model, dimensions, ordering, metadata mapping, vectors and links before inserting anything. It refuses to mix an existing collection with a different dataset or model and never regenerates embeddings.

Example interfaces:

```bash
.venv/bin/python scripts/query_chroma_db.py --query "Can I use CPF to buy an HDB resale flat?" --top-k 5
.venv/bin/python scripts/query_chroma_db.py --chunk-id C05_c0014
.venv/bin/python scripts/query_chroma_db.py --linked-chunk-id H01_c0009
.venv/bin/python scripts/query_chroma_db.py --query "CPF withdrawal limits" --document-id C03 --top-k 5
```

Reproduce the 40-question NumPy/Chroma consistency audit with:

```bash
.venv/bin/python scripts/validate_chroma_consistency.py --device cpu
```

The generated persistent database under `data/vector_db/` is local and ignored by Git. Reusable scripts, tests, configuration and reports remain trackable.

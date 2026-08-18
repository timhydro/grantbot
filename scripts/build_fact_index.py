from __future__ import annotations

"""Build a FAISS index for facts to enable semantic retrieval.

Usage:
    python scripts/build_fact_index.py --facts facts.jsonl --index out/index.faiss --meta out/meta.json --model all-MiniLM-L6-v2

Input: a JSONL file with one JSON object per line representing a fact with at least {"id": "...", "value": "..."}
Output: a FAISS index file and a metadata JSON mapping index positions to fact ids.

Optional: if sentence-transformers/faiss are not installed this script will exit with instructions.
"""
import argparse
import json
from pathlib import Path
from typing import List

try:
    from sentence_transformers import SentenceTransformer
    import faiss
    import numpy as np
except Exception as exc:
    raise SystemExit(
        "Required packages not installed. Install them and re-run:\n  pip install sentence-transformers faiss-cpu\n"
    )


def load_facts(path: Path) -> List[dict]:
    facts = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            facts.append(json.loads(line))
    return facts


def build_index(facts: List[dict], model_name: str = "all-MiniLM-L6-v2"):
    texts = [str(f.get("value") or "") for f in facts]
    model = SentenceTransformer(model_name)
    embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=True)
    # normalize embeddings for cosine similarity
    faiss.normalize_L2(embeddings)
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)
    return index


def save_index(index, out_index: Path, meta_ids: List[str]):
    out_index.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(out_index))
    meta = {"ids": meta_ids}
    meta_path = out_index.with_suffix(out_index.suffix + ".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--facts", required=True, help="Input JSONL of facts (one per line) with fields id and value")
    p.add_argument("--index", required=True, help="Output FAISS index path")
    p.add_argument("--model", default="all-MiniLM-L6-v2", help="SentenceTransformer model name")
    args = p.parse_args(argv)

    facts_path = Path(args.facts)
    if not facts_path.exists():
        raise SystemExit(f"Facts file not found: {facts_path}")

    facts = load_facts(facts_path)
    if not facts:
        raise SystemExit("No facts found in input file")

    index = build_index(facts, model_name=args.model)
    meta_ids = [f.get("id") for f in facts]
    save_index(index, Path(args.index), meta_ids)
    print(f"Built index with {len(facts)} facts and saved to {args.index}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Export approved writer feedback into JSONL for supervised fine-tuning or LoRA adapter training.

Usage:
    python tools/export_training_jsonl.py --db data/grantbot.db --out export/approved_training.jsonl --limit 1000

This script extracts APPROVE (or APPROVED) feedback rows and converts them to
prompt-completion JSONL entries. The prompt here is reconstructed from the
stored prompt and facts_used; the completion is the approved draft.

Warning: exported data may contain PII. Review, sanitize, and vet entries before training.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Any
from pathlib import Path


def export_approved(db_path: str, out_path: str, limit: int = 10000) -> int:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT feedback_id, prompt, draft, facts_used_json, quality_json FROM writer_feedback WHERE upper(reviewer_action) IN ('APPROVE','APPROVED') ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    count = 0
    with open(out_path, "w", encoding="utf-8") as fh:
        for row in rows:
            try:
                facts = json.loads(row["facts_used_json"] or "[]")
            except Exception:
                facts = []
            # Build a compact context block from facts
            facts_text = "\n".join(f"- [{f.get('id','')}] {f.get('value','')}" for f in facts)
            prompt = f"CONTEXT:\n{facts_text}\n\nPROMPT:\n{row['prompt']}\n\nProvide the final approved draft."
            completion = (row["draft"] or "").strip()
            if not completion:
                continue
            entry = {"prompt": prompt, "completion": completion}
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            count += 1
    conn.close()
    return count


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True, help="Path to sqlite DB (writer_feedback table)")
    p.add_argument("--out", required=True, help="Output JSONL file path")
    p.add_argument("--limit", type=int, default=10000)
    args = p.parse_args(argv)
    n = export_approved(args.db, args.out, limit=args.limit)
    print(f"Exported {n} approved examples to {args.out}")


if __name__ == "__main__":
    main()

"""Batch sampling and the official registry anchor.

select_batch draws the local test batch. The official run supplies its own organisations, so nothing
here is privileged knowledge — it exists so I can measure my own coverage before submitting.

registry_index streams Brreg's bulk CSV (NLOD 2.0) and keeps only the rows for the batch. One pass
over 1.4M rows replaces 1,000 per-company API calls, and it carries fields the live endpoint omits:
hjemmeside, epost, telefon, vedtektsfestet formaal, share capital.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNIVERSE = ROOT / "universe.jsonl.gz"
BULK_CSV = ROOT / "brreg-enheter.csv.gz"

csv.field_size_limit(10_000_000)


def select_batch(count: int = 100, seed: int = 20261020) -> list[dict]:
    """Reservoir sample over the eligible universe with a fixed seed, so results are reproducible."""
    rng = random.Random(seed)
    picked: list[dict] = []
    seen = 0
    with gzip.open(UNIVERSE, "rt", encoding="utf-8") as fh:
        for line in fh:
            seen += 1
            if len(picked) < count:
                picked.append(json.loads(line))
            else:
                j = rng.randrange(seen)
                if j < count:
                    picked[j] = json.loads(line)
    return picked


def registry_index(orgs: set[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with gzip.open(BULK_CSV, "rt", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            org = (row.get("organisasjonsnummer") or "").strip()
            if org in orgs:
                out[org] = row
    return out


def write_batch(rows: list[dict], path: Path) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    batch = select_batch(20)
    assert len(batch) == 20 and len({b["organisation_number"] for b in batch}) == 20, "sample must be unique"
    idx = registry_index({b["organisation_number"] for b in batch})
    have_site = sum(1 for r in idx.values() if (r.get("hjemmeside") or "").strip())
    print(f"sampled {len(batch)} -> bulk rows matched {len(idx)}, with registered website {have_site}")
    assert len(idx) >= 19, "the bulk snapshot must cover the sampled universe"
    print("sample self-test OK")

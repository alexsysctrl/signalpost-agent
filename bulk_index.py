"""One pass over the registry bulk file, so every later run is a lookup instead of a parse.

Measured 2026-10-21: streaming the 1.4M-row CSV from the gz costs ~40-50 s, which made every small
test run cost a minute before it did any work. The file is frozen for a run (its SHA-256 is the
evidence anchor for every bulk claim), so indexing it once is pure gain.

Only the columns identity.map_bulk actually reads are stored, which keeps the database around a third
of the size of the raw file. The hash of the *original* gz is stored with the rows, because a claim
that cites the bulk snapshot has to be checkable against that exact file.

Build: python3 bulk_index.py
Use:   identity.load_bulk(orgs) reads from this index when it exists.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import sqlite3
import time
from pathlib import Path

import identity

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "brreg-index.db"
CSV_GZ = ROOT / "brreg-enheter.csv.gz"

COLUMNS = sorted({source.split(".")[0] for source in identity.BULK_FIELDS} | {source for source in identity.BULK_FIELDS})


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def build() -> None:
    if DB.exists():
        DB.unlink()
    started = time.time()
    digest = file_sha256(CSV_GZ)
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE rows (organisasjonsnummer TEXT PRIMARY KEY, row TEXT NOT NULL)")
    conn.execute("CREATE INDEX rows_org ON rows (organisasjonsnummer)")
    conn.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?)",
        [("source_url", identity.BULK_URL), ("source_file", str(CSV_GZ)), ("content_sha256", digest), ("built_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))],
    )
    csv.field_size_limit(10_000_000)
    count = 0
    with CSV_GZ.open("rb") as raw:
        with gzip.open(raw, "rt", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            wanted = [c for c in reader.fieldnames or [] if c in COLUMNS]
            buffer: list[tuple[str, str]] = []
            for row in reader:
                org = (row.get("organisasjonsnummer") or "").strip()
                if len(org) != 9 or not org.isdigit():
                    continue
                keep = {c: row.get(c) for c in wanted if row.get(c) not in (None, "")}
                buffer.append((org, json.dumps(keep, ensure_ascii=False)))
                if len(buffer) >= 20_000:
                    conn.executemany("INSERT OR REPLACE INTO rows VALUES (?, ?)", buffer)
                    buffer.clear()
                    count += 20_000
                    if count % 200_000 == 0:
                        print(f"  {count:,} rows ({time.time() - started:.0f}s)")
            if buffer:
                conn.executemany("INSERT OR REPLACE INTO rows VALUES (?, ?)", buffer)
                count += len(buffer)
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM rows").fetchone()[0]
    conn.close()
    print(f"indexed {total:,} organisations into {DB} in {time.time() - started:.0f}s, source sha256 {digest[:16]}")


def lookup(orgs: set[str]) -> dict[str, dict]:
    if not DB.exists():
        raise SystemExit(f"{DB} missing — run: python3 bulk_index.py")
    conn = sqlite3.connect(DB)
    out: dict[str, dict] = {}
    ids = list(orgs)
    for i in range(0, len(ids), 900):
        chunk = ids[i : i + 900]
        marks = ",".join("?" * len(chunk))
        for org, row in conn.execute(f"SELECT organisasjonsnummer, row FROM rows WHERE organisasjonsnummer IN ({marks})", chunk):
            out[org] = json.loads(row)
    conn.close()
    return out


def meta() -> dict:
    conn = sqlite3.connect(DB)
    out = {k: v for k, v in conn.execute("SELECT key, value FROM meta")}
    conn.close()
    return out


if __name__ == "__main__":
    import argparse
    import sqlite3

    parser = argparse.ArgumentParser(description="Build or check the SQLite index over the registry bulk file.")
    parser.add_argument("--rebuild", action="store_true", help="rebuild from the CSV; without it an existing valid index is kept")
    args = parser.parse_args()

    need = args.rebuild
    if not need and DB.exists():
        try:
            with sqlite3.connect(DB) as check:
                rows = check.execute("select count(*) from rows").fetchone()[0]
                need = rows < 1_000_000
        except sqlite3.Error:
            need = True
    if need:
        build()
    got = lookup({"976605713", "810034882", "000000000"})
    assert "976605713" in got and "810034882" in got, got.keys()
    assert len(got) == 2, "a number that is not in the register must simply be absent"
    assert got["976605713"]["navn"].startswith("KITRON"), got["976605713"].get("navn")
    m = meta()
    assert len(m["content_sha256"]) == 64
    with sqlite3.connect(DB) as check:
        total = check.execute("select count(*) from rows").fetchone()[0]
    assert total > 1_000_000, f"the index only holds {total} rows; run with --rebuild"
    print(f"bulk index self-test OK: {total} rows, {len(got)} looked up instantly, source hash {m['content_sha256'][:12]}")

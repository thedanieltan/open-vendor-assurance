from __future__ import annotations

import base64
import lzma
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
generated = ROOT / "maintenance" / "generated"
source_part = generated / "owner-catalog-source.b85"
candidate_part = generated / "owner-catalog-candidates.b85"
candidate_path = generated / "owner-catalog-candidates.tsv"
source = lzma.decompress(base64.b85decode(source_part.read_text(encoding="utf-8"))).decode("utf-8")
candidate_path.write_bytes(lzma.decompress(base64.b85decode(candidate_part.read_text(encoding="utf-8"))))

source = source.replace(
    'SUPPLEMENTAL_TSV_PATH = ROOT / "maintenance" / "generated" / "owner-catalog-candidates.tsv"\n',
    'SUPPLEMENTAL_TSV_PATH = ROOT / "maintenance" / "generated" / "owner-catalog-candidates.tsv"\n'
    'CACHE_PATH = ROOT / "maintenance" / "generated" / "owner-real-source-expansion-500-cache.json"\n',
)
old_init = '''    candidates = load_candidates()
    accepted: list[dict[str, Any]] = []
    skipped: list[str] = []

    # Process bounded waves and stop as soon as the exact catalog target is met.
'''
new_init = '''    candidates = load_candidates()
    accepted: list[dict[str, Any]] = []
    skipped: list[str] = []
    processed_vendor_ids: set[str] = set()
    if CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        accepted = list(cache.get("accepted_vendors") or [])
        skipped = [str(item) for item in (cache.get("skipped") or [])]
        processed_vendor_ids = {str(item) for item in (cache.get("processed_vendor_ids") or [])}
        candidates = [candidate for candidate in candidates if candidate["vendor_id"] not in processed_vendor_ids]
        print(
            f"resuming source discovery with {len(accepted)} accepted vendors, "
            f"{len(processed_vendor_ids)} processed candidates, and {len(candidates)} remaining candidates",
            flush=True,
        )

    # Process bounded waves and stop as soon as the exact catalog target is met.
'''
old_wave = '''            for future in as_completed(future_map):
                candidate = future_map[future]
                try:
                    vendor = future.result()
                except Exception as exc:
                    skipped.append(f"{candidate['vendor_id']}: {type(exc).__name__}")
                    continue
                if vendor is None:
                    skipped.append(f"{candidate['vendor_id']}: no verified public source")
                    continue
                accepted.append(vendor)
        if len(accepted) >= needed:
            break
'''
new_wave = '''            for future in as_completed(future_map):
                candidate = future_map[future]
                processed_vendor_ids.add(candidate["vendor_id"])
                try:
                    vendor = future.result()
                except Exception as exc:
                    skipped.append(f"{candidate['vendor_id']}: {type(exc).__name__}")
                    continue
                if vendor is None:
                    skipped.append(f"{candidate['vendor_id']}: no verified public source")
                    continue
                accepted.append(vendor)
        CACHE_PATH.write_text(
            json.dumps(
                {
                    "schema_version": "0.1.0",
                    "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                    "accepted_vendors": accepted,
                    "processed_vendor_ids": sorted(processed_vendor_ids),
                    "skipped": skipped,
                },
                indent=2,
                sort_keys=True,
            )
            + "\\n",
            encoding="utf-8",
        )
        print(
            f"discovery wave complete: accepted={len(accepted)} processed={len(processed_vendor_ids)}",
            flush=True,
        )
        if len(accepted) >= needed:
            break
'''
if old_init not in source or old_wave not in source:
    raise RuntimeError("resumable-discovery patch markers do not match staged executor")
source = source.replace(old_init, new_init).replace(old_wave, new_wave)
source_part.unlink()
candidate_part.unlink()
exec(compile(source, "owner_catalog_executor.py", "exec"), {"__name__": "__main__", "__file__": str(Path(__file__))})

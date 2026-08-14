#!/usr/bin/env python3
"""
Rebuild docs/index.html (the GitHub Pages report) from fresh listing data.

Run manually or via .github/workflows/daily-refresh.yml (scheduled).
Reads webapp/report.html as the template (keeps its CSS/JS/coverage-data
untouched), refetches all COMPLEX_CACHE-known complexes via pipeline.py's
own functions, and writes the merged result to docs/index.html for GitHub
Pages to serve.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import (
    COMPLEX_CACHE, neonet_fetch, tencomz_fetch, dedupe_by_unit, to_pyeong,
)

REPO_ROOT = Path(__file__).parent
TEMPLATE = REPO_ROOT / "webapp" / "report.html"
OUTPUT = REPO_ROOT / "docs" / "index.html"

# Display-name -> COMPLEX_CACHE key. Most match exactly; 디큐브시티 isn't
# cached (auto-resolves each time) so it's listed explicitly.
COMPLEXES = [
    "목동신시가지11단지",
    "목동신시가지12단지",
    "목동신시가지13단지",
    "디큐브시티",
    "목동힐스테이트",
    "래미안목동아델리체",
]


def fetch_complex(name):
    cached = COMPLEX_CACHE.get(name, {})
    region_cd = cached.get("region_cd")
    neonet_cc = cached.get("neonet_complex_cd")
    tencomz_aptno = cached.get("tencomz_aptno")

    if not neonet_cc or not region_cd:
        from pipeline import neonet_resolve
        r, neonet_cc = neonet_resolve(name)
        region_cd = region_cd or r
    if not tencomz_aptno:
        from pipeline import tencomz_resolve_aptno
        tencomz_aptno, _ = tencomz_resolve_aptno(region_cd, name)

    neonet_rows = neonet_fetch(region_cd, neonet_cc) if neonet_cc else []
    tencomz_rows = tencomz_fetch(region_cd, tencomz_aptno) if tencomz_aptno else []

    combined = []
    for r in dedupe_by_unit(neonet_rows) + dedupe_by_unit(tencomz_rows):
        combined.append({
            "source": r["source"], "trade": r["trade"], "dong": r["dong"],
            "floor": r.get("floor", ""), "pyeong": to_pyeong(r["supply"]),
            "exclusive": r["exclusive"], "price1": r["price1"],
            "price2": r.get("price2"), "date": r.get("date", ""),
            "note": r.get("note", ""),
        })
    return combined


def main():
    data = {}
    for name in COMPLEXES:
        rows = fetch_complex(name)
        data[name] = rows
        print(f"{name}: {len(rows)} rows", file=sys.stderr)

    total = sum(len(v) for v in data.values())
    if total == 0:
        print("ERROR: 0 rows across all complexes - likely a network/scrape "
              "failure, refusing to overwrite docs/index.html with empty data.",
              file=sys.stderr)
        sys.exit(1)

    html = TEMPLATE.read_text(encoding="utf-8")
    new_json = json.dumps(data, ensure_ascii=False)

    pattern = re.compile(
        r'(<script id="listing-data" type="application/json">).*?(</script>)',
        re.DOTALL,
    )
    html, n = pattern.subn(lambda m: m.group(1) + new_json + m.group(2), html)
    if n != 1:
        print(f"ERROR: expected exactly 1 listing-data script tag, found {n}",
              file=sys.stderr)
        sys.exit(1)

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(html)} bytes, {total} total rows)", file=sys.stderr)


if __name__ == "__main__":
    main()

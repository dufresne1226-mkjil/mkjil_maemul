#!/usr/bin/env python3
"""
Rebuild docs/index.html (the GitHub Pages report) from fresh listing data.

Sources: NEONET + 텐컴즈 + asil + 부동산써브(serve), cross-source-deduped.
serve blocks GitHub Actions' datacenter IP, so full 4-source builds run from
the always-on local machine's cron (refresh_all.sh); the daily workflow only
deploys the committed docs/. Run there, or manually from a serve-reachable IP.

Reads webapp/report.html as the template (keeps its CSS/JS/coverage-data
untouched), refetches all COMPLEXES via pipeline.py's own functions, and
writes the merged result to docs/index.html for GitHub Pages to serve.
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import (
    COMPLEX_CACHE, neonet_fetch, tencomz_fetch, asil_fetch, asil_resolve_code,
    serve_fetch_ldong, dedupe_by_unit, dedupe_cross_source, to_pyeong,
)

REPO_ROOT = Path(__file__).parent
TEMPLATE = REPO_ROOT / "webapp" / "report.html"
OUTPUT = REPO_ROOT / "docs" / "index.html"

# 4번째 소스: 부동산써브(serve). serve는 법정동 단위로만 페이징되므로 해당 법정동을
# 한 번만 통째로 긁어 aptNo로 필터한다. 값: 표시명 -> (법정동, serve aptNo).
# serve가 인덱싱하지 않는 단지(예: 목동12단지)는 생략 -> serve 기여 0.
# NB: serve는 GitHub Actions 데이터센터 IP를 차단한다. GH에서 돌면 빈손이 되어
# 자연히 3소스로 축소되고, serve가 통하는 로컬(크론)에서 돌 때만 4소스가 된다.
SERVE_APT = {
    "목동신시가지11단지": ("1147010100", "22959"),
    "목동신시가지13단지": ("1147010100", "438"),
    "목동힐스테이트":     ("1147010100", "108438"),
    "래미안목동아델리체":  ("1147010100", "121979"),
    "디큐브시티":        ("1153010100", "27310"),
}
_serve_cache = {}  # 법정동 -> {aptNo: [rows]} (법정동당 1회만 fetch)


def serve_rows_for(name):
    """이 단지의 serve 매물 리스트. 법정동을 한 번만 긁어 캐시에서 재사용."""
    hit = SERVE_APT.get(name)
    if not hit:
        return []
    ldong, apt = hit
    if ldong not in _serve_cache:
        try:
            _serve_cache[ldong] = serve_fetch_ldong(ldong)
        except Exception as e:  # noqa: BLE001 - serve 실패는 3소스로 자연 축소
            print(f"  serve {ldong} fetch 실패({e}) - 이 법정동은 건너뜀", file=sys.stderr)
            _serve_cache[ldong] = {}
    return _serve_cache[ldong].get(apt, [])

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
    asil_code = cached.get("asil_code")

    if not neonet_cc or not region_cd:
        from pipeline import neonet_resolve
        r, neonet_cc = neonet_resolve(name)
        region_cd = region_cd or r
    if not tencomz_aptno:
        from pipeline import tencomz_resolve_aptno
        tencomz_aptno, _ = tencomz_resolve_aptno(region_cd, name)
    if not asil_code and region_cd:
        asil_code = asil_resolve_code(region_cd, name)

    neonet_rows = neonet_fetch(region_cd, neonet_cc) if neonet_cc else []
    tencomz_rows = tencomz_fetch(region_cd, tencomz_aptno) if tencomz_aptno else []
    asil_rows = asil_fetch(asil_code) if asil_code else []
    serve_rows = serve_rows_for(name)

    # dedupe within each source first, then across sources (asil aggregates
    # Naver, which overlaps NEONET/Tencomz heavily - a raw merge triple-counts).
    merged = (dedupe_by_unit(neonet_rows) + dedupe_by_unit(tencomz_rows)
              + dedupe_by_unit(asil_rows) + dedupe_by_unit(serve_rows))
    combined = []
    for r in dedupe_cross_source(merged):
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
    for i, name in enumerate(COMPLEXES):
        if i > 0:
            # GitHub Actions' shared runner IPs get measurably less complete
            # results than a local/interactive session's IP for the same
            # requests (see project memory) - a longer gap between complexes
            # is being tried here to see if it reads as less bot-like than
            # the earlier 3s pacing did. No extra requests added, just spaced
            # out more.
            time.sleep(15)
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

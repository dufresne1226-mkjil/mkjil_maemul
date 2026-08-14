#!/usr/bin/env python3
"""
Korean apartment complex listing (매물) puller.

Pulls current listings for one apartment complex from three agent
listing networks that are reachable without login, and merges them
into one deduped report split by 매매/전세/월세.

Sources (all discovered/reverse-engineered manually, see NOTES.md):
  - NEONET   (m.neonet.co.kr)      - best 매매/월세 coverage
  - Tencomz  (nhp.ten.co.kr)       - best 전세 coverage, most complete overall
  - Hanbang  (search.karhanbang.com) - thin coverage, useful as cross-check

Naver, Zigbang, KB부동산 are NOT reachable (blocked/JS-only) - not attempted here.
There is no known way to pull 부동산포스(dooinsoft) listings; they have no
public search endpoint of their own.

Usage (아파트 - named-complex mode):
    python3 pipeline.py "목동신시가지13단지" --region 1147010100
    python3 pipeline.py "목동신시가지11단지"          # region cached, see COMPLEX_CACHE
    python3 pipeline.py "아무단지" --region 4111310300 --json out.json

Usage (빌라/다세대/원룸/상가 등 - region-wide mode, no named complex to resolve):
    python3 pipeline.py --region-only --region 1165010100 --type 주택
    python3 pipeline.py --region-only --region 1165010100 --type 원룸 --json villa_out.json

    Villas etc. have no "단지" to search by name, so this mode just pulls
    everything Tencomz has tagged with the given region code and property
    type. --type must be one of TENCOMZ_TYPES below - "빌라" is NOT a valid
    value on Tencomz (그 이름으로는 지역필터가 씹히고 전국 매물이 섞여 나옴);
    다세대/연립주택은 "주택" 카테고리로 나온다.
    Only Tencomz supports this mode currently (NEONET/Hanbang region-wide
    browsing wasn't reverse-engineered - see README).

Finding --region (10-digit 법정동코드, same value Naver/NEONET/Tencomz all use):
  - If --region is omitted in named-complex mode, the script tries
    COMPLEX_CACHE / REGION_CACHE, then NEONET's live search (prints the
    resolved code so you can add it to the cache for next time).
  - For a brand new area with no complex to search by name (region-only
    mode), download the government's 법정동코드 table and grep it - this is
    far more reliable than guessing the code by hand (guessing wrongly does
    NOT error, it silently returns unrelated nationwide listings):
        curl -s https://raw.githubusercontent.com/WooilJeong/PublicDataReader/main/PublicDataReader/raw/code_bdong.json -o code_bdong.json
        python3 -c "
import json
d = json.load(open('code_bdong.json', encoding='utf-8'))
for i in range(len(d['법정동코드'])):
    if d['시군구명'][str(i)]=='서초구' and '방배' in str(d['읍면동명'].get(str(i),'')):
        print(d['법정동코드'][str(i)], d['읍면동명'][str(i)], d['말소일자'].get(str(i)))
"
"""
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.parse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
PYEONG = 3.305785

# Cache of already-resolved complex/region codes so repeat queries skip the
# resolution round-trip. Add to this as new complexes get resolved.
COMPLEX_CACHE = {
    "목동신시가지13단지": {"region_cd": "1147010100", "neonet_complex_cd": "A0001277", "tencomz_aptno": "438"},
    "목동신시가지11단지": {"region_cd": "1147010100", "neonet_complex_cd": "A0001507", "tencomz_aptno": "22959"},
    "목동신시가지12단지": {"region_cd": "1147010100", "neonet_complex_cd": "A0008099", "tencomz_aptno": "666"},
    "목동힐스테이트": {"region_cd": "1147010100", "neonet_complex_cd": "A1006461", "tencomz_aptno": "108438"},
    "래미안목동아델리체": {"region_cd": "1147010100", "neonet_complex_cd": "A0037207", "tencomz_aptno": "121979"},
}

# 법정동코드 cache for region-only mode (no named complex), so a known area
# doesn't need re-resolving via the government code table each time.
REGION_CACHE = {
    "방배동": "1165010100",
    "신정동": "1147010100",
}

# Tencomz's rletTypeNm accepts exactly these Korean labels (from
# rletTypeNmToCode() in the site's own JS - anything else is silently
# accepted but does NOT filter by region correctly, e.g. "빌라" is invalid
# and returns nationwide filler content instead of erroring).
TENCOMZ_TYPES = ["아파트", "오피스텔", "분양권", "주택", "토지", "원룸", "상가", "사무실", "공장", "재개발", "건물"]


# --connect-timeout/--max-time: without these, a single stalled connection
# (e.g. a Korean site not responding from a new/unfamiliar IP like a GitHub
# Actions runner's) hangs curl - and this function - forever. Confirmed the
# hard way: a GH Actions run sat "in progress" for 9+ minutes on one fetch
# and had to be cancelled by hand. subprocess timeout is a second backstop
# in case curl itself ever fails to honor its own flags.
#
# 25s max-time was tried first and was too tight: from a GitHub Actions
# runner (higher/more variable latency to Korean sites than a local
# session), some individual paginated requests are just legitimately slow,
# not stuck - 25s cut them off mid-pagination and silently produced partial
# data (11단지 55->44 rows, 12단지 53->31 rows in one run, no error surfaced).
# 60s gives real-but-slow requests room to finish while still bounding a
# truly stuck connection (the workflow's own job-level timeout-minutes is
# the outer backstop regardless).
CURL_TIMEOUT_ARGS = ["--connect-timeout", "15", "--max-time", "60"]
SUBPROCESS_TIMEOUT = 70


def curl_get(url, extra_headers=None):
    cmd = ["curl", "-s", "-A", UA, *CURL_TIMEOUT_ARGS]
    for h in (extra_headers or []):
        cmd += ["-H", h]
    cmd.append(url)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT).stdout
    except subprocess.TimeoutExpired:
        return ""


def curl_post(url, data_str, extra_headers=None):
    cmd = ["curl", "-s", "-A", UA, *CURL_TIMEOUT_ARGS, "-H", "Content-Type: application/x-www-form-urlencoded"]
    for h in (extra_headers or []):
        cmd += ["-H", h]
    cmd += ["--data-binary", data_str, url]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT).stdout
    except subprocess.TimeoutExpired:
        return ""


def to_utf8(euc_kr_bytes_text):
    """curl -s already returns text via python's default decode attempt (usually
    latin-1/mojibake for EUC-KR pages since curl doesn't know the charset).
    We instead fetch raw bytes and decode explicitly for EUC-KR pages."""
    raise NotImplementedError  # unused; see fetch_neonet_raw which handles bytes directly


def curl_get_bytes(url):
    cmd = ["curl", "-s", "-A", UA, *CURL_TIMEOUT_ARGS, url]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=SUBPROCESS_TIMEOUT).stdout
    except subprocess.TimeoutExpired:
        return b""


# ---------------------------------------------------------------------------
# NEONET (m.neonet.co.kr) - EUC-KR encoded, unauthenticated on mobile subdomain
# ---------------------------------------------------------------------------

def neonet_resolve(complex_name):
    """Returns (region_cd, complex_cd) by querying NEONET's live search-as-you-type
    endpoint. Search text must be sent EUC-KR encoded (site is EUC-KR)."""
    q = urllib.parse.quote(complex_name.encode("euc-kr"))
    url = f"https://m.neonet.co.kr/novo-mobile/view/main/inc_SearchComplex.neo?search_text={q}"
    body = curl_get_bytes(url).decode("euc-kr", errors="ignore")
    m = re.search(r"region_cd=(\d+)&complex_cd=([A-Za-z0-9]+)", body)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def neonet_fetch(region_cd, complex_cd, max_pages=30):
    """Paginate NEONET's OfferingsList.neo until an empty page. Returns raw
    parsed rows (NOT deduped - same physical unit re-appears once per day it
    was re-confirmed by the agent)."""
    rows = []
    for page in range(1, max_pages + 1):
        url = (
            "https://m.neonet.co.kr/novo-mobile/view/offerings/OfferingsList.neo"
            f"?offerings_gbn=AT&offer_gbn=P&region_cd={region_cd}&complex_cd={complex_cd}&page={page}"
        )
        html = curl_get_bytes(url).decode("euc-kr", errors="ignore")
        blocks = html.split('class="offer_contents"')[1:]
        if not blocks:
            break
        for b in blocks:
            # dong label isn't always numeric - 디큐브시티 등 주상복합은 "A동"/"B동"처럼
            # 알파벳을 쓴다. 숫자든 문자든 "...동</p>" 앞의 마지막 토큰을 잡는다.
            dong = re.search(r'([A-Za-z0-9]+동)\s*</p>', b)
            trade = re.search(r'offer_prc[^>]*>\s*([가-힣]+)\s+([\d,]+)(?:\s*/\s*([\d,]+))?만', b)
            area = re.search(r'>\s*([\d.]+)\s*\n?\s*/([\d.]+)㎡,\s*\n?\s*([^\n,]+?)\s*,\s*([가-힣]+)\s*\n', b)
            # NEONET's floor text is e.g. "중층/15층" or "3층/15층" - strip to bare "N/M"
            # so it matches Tencomz's plain "3/15" and the report's added "층" suffix
            # doesn't double up.
            note = re.search(r'font-size:14px;">([^<]+)</p>', b)
            date = re.search(r'확인\s*([\d.]+)', b)
            if not (dong and trade and area):
                continue
            floor_raw = area.group(3).strip()
            floor_nums = re.findall(r'\d+', floor_raw)
            floor_norm = "/".join(floor_nums) if len(floor_nums) == 2 else floor_raw
            rows.append({
                "source": "neonet", "dong": dong.group(1), "trade": trade.group(1),
                "price1": trade.group(2).replace(",", ""),
                "price2": trade.group(3).replace(",", "") if trade.group(3) else None,
                "supply": float(area.group(1)), "exclusive": float(area.group(2)),
                "floor": floor_norm, "dir": area.group(4),
                "note": note.group(1).strip() if note else "",
                "date": date.group(1).rstrip(".") if date else "",
            })
        time.sleep(0.2)
    return rows


# ---------------------------------------------------------------------------
# Tencomz (nhp.ten.co.kr) - UTF-8, ASP.NET WebForms pagination via __doPostBack
# ---------------------------------------------------------------------------

def tencomz_resolve_aptno(region_cd, complex_name):
    """Fetch the region's default apartment listing page and grep the facet
    sidebar for PerAptNoLink(<aptNo>) matching the complex name. Tencomz
    sometimes suffixes the label (e.g. "디큐브시티" is listed as
    "디큐브시티(주상복합)"), so this matches by substring, not exact - returns
    (aptno, matched_label) so callers can flag it if the label differs from
    what was asked for."""
    url = (
        "http://nhp.ten.co.kr/Pages/maemul/maemul_List.aspx"
        f"?rletTypeNm={urllib.parse.quote('아파트')}&cortarNo={region_cd}"
    )
    html = curl_get(url)
    m = re.search(rf'PerAptNoLink\((\d+)\);">([^<]*{re.escape(complex_name)}[^<]*)</li>', html)
    return (m.group(1), m.group(2)) if m else (None, None)


def _get_val(html, field_id):
    m = re.search(rf'id="{field_id}"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""


def _tencomz_paginate(url, max_pages):
    html = curl_get(url)
    pages = re.findall(r"__doPostBack\('ctl00\$Content\$ctl00','(\d+)'\)", html)
    maxpage = min(max(int(p) for p in pages), max_pages) if pages else 1

    all_html = [html]
    for pagenum in range(2, maxpage + 1):
        data = urllib.parse.urlencode({
            "__EVENTTARGET": "ctl00$Content$ctl00",
            "__EVENTARGUMENT": str(pagenum),
            "__VIEWSTATE": _get_val(html, "__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": _get_val(html, "__VIEWSTATEGENERATOR"),
            "__EVENTVALIDATION": _get_val(html, "__EVENTVALIDATION"),
        })
        html = curl_post(url, data)
        all_html.append(html)
        time.sleep(0.2)
    return all_html


def _tencomz_parse_blocks(all_html, id_pattern, need_dong=True):
    rows = []
    for page_html in all_html:
        parts = re.split(r'<td rowspan="2" class="SaleType BottomLine">', page_html)[1:]
        for p in parts:
            trade_m = re.search(r'<div class="Inner">\s*(매매|전세|월세)', p)
            id_m = re.search(id_pattern, p)
            name_m = re.search(r'title="([^"]+)"\s*style="cursor:pointer;"\s*onclick="SaleListClick', p)
            date_m = re.search(r'Mark4"[^>]*>\s*<img[^>]*/>\s*([\d.]+)', p)
            area_m = re.search(r'공급면적\s*([\d.]+)㎡.*?전용면적\s*([\d.]+)㎡', p, re.DOTALL)
            dong_m = re.search(r'DongView02">\s*<div class="Inner">\s*\n?\s*([^\n<]+)', p)
            floor_m = re.search(r'class="Number2">\s*<div class="Inner">\s*\n?\s*([\d]+\s*/\s*[\d]+)', p)
            price_cell_m = re.search(r'class="Number">\s*(.*?)</td>', p, re.DOTALL)
            price1 = price2 = None
            if price_cell_m:
                cands = re.findall(r'<strong>([\d,]+)(?:/(\d+))?</strong>', price_cell_m.group(1))
                best = next((c for c in cands if c[1] and c[1] != "0"), cands[0] if cands else None)
                if best:
                    price1 = best[0].replace(",", "")
                    price2 = best[1] if (best[1] and best[1] != "0") else None
            desc_m = re.search(r'class="Text" title="([^"]*)"', p)
            if not (trade_m and id_m and area_m and (dong_m or not need_dong)):
                continue
            rows.append({
                "source": "tencomz", "id": id_m.group(1), "trade": trade_m.group(1),
                "name": name_m.group(1) if name_m else "",
                "date": date_m.group(1) if date_m else "",
                "supply": float(area_m.group(1)), "exclusive": float(area_m.group(2)),
                "dong": dong_m.group(1).strip() if dong_m else "-",
                "floor": floor_m.group(1).replace(" ", "") if floor_m else "",
                "price1": price1, "price2": price2,
                "note": desc_m.group(1) if desc_m else "",
            })
    # dedupe by offeringsId first (Tencomz issues a fresh id each daily re-confirm)
    return list({r["id"]: r for r in rows}.values())


def tencomz_fetch(region_cd, aptno, max_pages=30):
    """Named-complex mode (아파트 등 - has a resolvable aptNo)."""
    url = (
        "http://nhp.ten.co.kr/Pages/maemul/maemul_List.aspx"
        f"?rletTypeNm={urllib.parse.quote('아파트')}&cortarNo={region_cd}&aptNo={aptno}&danjuclik=Y"
    )
    all_html = _tencomz_paginate(url, max_pages)
    return _tencomz_parse_blocks(all_html, rf"SaleListClick\('(\d+)','{aptno}',")


def tencomz_fetch_region(region_cd, rletype, max_pages=30):
    """Region-wide mode for property types with no complex to resolve
    (주택=빌라/다세대/연립, 원룸, 상가, 사무실, 건물 등). Returns everything
    Tencomz has tagged with this exact region_cd - each row's 'name' field
    is the building/listing headline since there's no complex name to group
    by. See TENCOMZ_TYPES for valid rletype values."""
    if rletype not in TENCOMZ_TYPES:
        raise ValueError(f"'{rletype}' is not a valid Tencomz rletTypeNm - use one of {TENCOMZ_TYPES}")
    url = (
        "http://nhp.ten.co.kr/Pages/maemul/maemul_List.aspx"
        f"?rletTypeNm={urllib.parse.quote(rletype)}&cortarNo={region_cd}"
    )
    all_html = _tencomz_paginate(url, max_pages)
    id_pattern = rf"SaleListClick\('(\d+)','(\d+)','0','{region_cd}','{rletype}','[가-힣]+'"
    return _tencomz_parse_blocks(all_html, id_pattern, need_dong=False)


# ---------------------------------------------------------------------------
# Hanbang / 한국공인중개사협회 (search.karhanbang.com) - clean JSON API
# ---------------------------------------------------------------------------

def hanbang_fetch(complex_name, outmax=50):
    q = urllib.parse.quote(complex_name)
    url = (
        "https://search.karhanbang.com/srch_resultjson"
        f"?w=search_total_list&q={q}&section=mamul&pagenum=1&outmax={outmax}"
    )
    body = curl_get(url)
    try:
        data = json.loads(body)
        items = data["section_list"][0]["section"][0].get("att_list", [])
    except (KeyError, IndexError, json.JSONDecodeError):
        return []
    rows = []
    for it in items:
        if not isinstance(it, dict):
            continue
        # Hanbang gives both pyung (gong_pyung/jun_pyung) and ㎡ (jun_meter) directly -
        # use jun_meter as-is rather than re-deriving from jun_pyung, more accurate.
        rows.append({
            "source": "hanbang", "trade": it.get("gure_nm"), "dong": (it.get("danji_dong_nm") or "") + "동",
            "floor": f"{it.get('curr_floor')}/{int(float(it.get('total_floor', 0)))}",
            "gong_pyung": it.get("gong_pyung"), "jun_pyung": it.get("jun_pyung"),
            "jun_meter": it.get("jun_meter"),
            "amt_sell": it.get("amt_sell"), "amt_guar": it.get("amt_guar"), "amt_month": it.get("amt_month"),
            "date": it.get("show_confirm_date"), "note": it.get("feature"),
            "company": it.get("company"), "hp": it.get("hp"),
        })
    return rows


# ---------------------------------------------------------------------------
# Merge + report
# ---------------------------------------------------------------------------

def dedupe_by_unit(rows):
    """Collapse re-confirmations of the same physical unit (same source only -
    cross-source identity isn't attempted since IDs/floor labels differ)."""
    uniq = {}
    for r in rows:
        key = (r["source"], r["dong"], r.get("floor"), r["trade"], r.get("price1") or r.get("amt_sell"),
               r.get("price2") or r.get("amt_guar"))
        if key not in uniq or (r.get("date", "") > uniq[key].get("date", "")):
            uniq[key] = r
    return list(uniq.values())


def to_pyeong(m2):
    return round(m2 / PYEONG, 1)


def krw(manwon_str):
    try:
        v = float(str(manwon_str).replace(",", ""))
    except (TypeError, ValueError):
        return "-"
    return f"{v/10000:.1f}억".replace(".0억", "억")


def print_report(complex_name, neonet_rows, tencomz_rows, hanbang_rows):
    print(f"\n{'='*70}\n{complex_name} - 매물 종합 리포트\n{'='*70}")

    combined = []
    for r in dedupe_by_unit(neonet_rows) + dedupe_by_unit(tencomz_rows):
        combined.append({
            "source": r["source"], "trade": r["trade"], "dong": r["dong"], "floor": r.get("floor", ""),
            "supply": r["supply"], "exclusive": r["exclusive"],
            "price1": r["price1"], "price2": r.get("price2"),
            "date": r.get("date", ""), "note": r.get("note", ""),
        })

    by_trade = {}
    for r in combined:
        by_trade.setdefault(r["trade"], []).append(r)

    for t in ["매매", "전세", "월세"]:
        lst = sorted(by_trade.get(t, []), key=lambda r: -r["supply"])
        print(f"\n--- {t} ({len(lst)}건, 네오넷+텐컴즈, 동일매물 동/층/가격 기준 중복제거) ---")
        for r in lst:
            py = to_pyeong(r["supply"])
            price = krw(r["price1"]) if not r["price2"] else f"보증금{krw(r['price1'])}/월{r['price2']}만"
            floor_disp = r['floor'] if ('층' in r['floor'] or not r['floor']) else f"{r['floor']}층"
            print(f"[{r['source']:7}] {py}평(전용{r['exclusive']}㎡) {r['dong']} {floor_disp} "
                  f"{price} 확인{r['date']} | {r['note']}")

    hb = dedupe_by_unit(hanbang_rows)
    print(f"\n--- 한방 교차검증 참고 ({len(hb)}건) ---")
    for r in hb:
        price = krw(r["amt_sell"]) if r["trade"] == "매매" else (
            krw(r["amt_guar"]) if r["trade"] == "전세" else f"보증금{krw(r['amt_guar'])}/월{r['amt_month']}만"
        )
        jm = r.get("jun_meter")
        excl = f"전용{jm}㎡" if jm and float(jm) > 0 else f"전용{r.get('jun_pyung','-')}평"
        print(f"{r['trade']} {r['dong']} {r['floor']}층 {r['gong_pyung']}평(공급)/{excl} {price} "
              f"확인{r['date']} {r['company']} | {r['note']}")


def print_region_report(region_cd, rletype, rows):
    print(f"\n{'='*70}\n지역코드 {region_cd} / {rletype} - 매물 리포트 (텐컴즈, 지역 필터가 아파트만큼\n엄격하지 않으니 결과 중 일부는 인접/다른 지역일 수 있음)\n{'='*70}")
    uniq = dedupe_by_unit(rows)
    by_trade = {}
    for r in uniq:
        by_trade.setdefault(r["trade"], []).append(r)
    for t in ["매매", "전세", "월세"]:
        lst = sorted(by_trade.get(t, []), key=lambda r: -r["supply"])
        print(f"\n--- {t} ({len(lst)}건) ---")
        for r in lst:
            py = to_pyeong(r["supply"])
            price = krw(r["price1"]) if not r["price2"] else f"보증금{krw(r['price1'])}/월{r['price2']}만"
            print(f"{r.get('name','') or '(건물명 미상)'} | {py}평(전용{r['exclusive']}㎡) {r['dong']} "
                  f"{r['floor']}층 {price} 확인{r['date']} | {r['note']}")


def run_region(region_cd, rletype, save_json=None):
    rows = tencomz_fetch_region(region_cd, rletype)
    print_region_report(region_cd, rletype, rows)
    if save_json:
        with open(save_json, "w", encoding="utf-8") as f:
            json.dump({"region_cd": region_cd, "rletype": rletype, "tencomz": rows}, f,
                       ensure_ascii=False, indent=2)
        print(f"\n(raw data saved to {save_json})")


def run(complex_name, region_cd=None, use_hanbang=True, save_json=None):
    cached = COMPLEX_CACHE.get(complex_name, {})
    region_cd = region_cd or cached.get("region_cd")

    neonet_cc = cached.get("neonet_complex_cd")
    if not neonet_cc:
        r, neonet_cc = neonet_resolve(complex_name)
        region_cd = region_cd or r
        print(f"[neonet] resolved region_cd={region_cd} complex_cd={neonet_cc}")

    if not region_cd:
        print("ERROR: no region_cd (법정동코드) known or resolved for this complex. "
              "Pass --region explicitly.", file=sys.stderr)
        sys.exit(1)

    tencomz_aptno = cached.get("tencomz_aptno")
    if not tencomz_aptno:
        tencomz_aptno, matched_label = tencomz_resolve_aptno(region_cd, complex_name)
        note = f" (matched label: {matched_label})" if matched_label and matched_label != complex_name else ""
        print(f"[tencomz] resolved aptNo={tencomz_aptno}{note}")

    neonet_rows = neonet_fetch(region_cd, neonet_cc) if neonet_cc else []
    tencomz_rows = tencomz_fetch(region_cd, tencomz_aptno) if tencomz_aptno else []
    hanbang_rows = hanbang_fetch(complex_name) if use_hanbang else []

    print_report(complex_name, neonet_rows, tencomz_rows, hanbang_rows)

    if save_json:
        with open(save_json, "w", encoding="utf-8") as f:
            json.dump({
                "complex": complex_name, "region_cd": region_cd,
                "neonet": neonet_rows, "tencomz": tencomz_rows, "hanbang": hanbang_rows,
            }, f, ensure_ascii=False, indent=2)
        print(f"\n(raw data saved to {save_json})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("complex_name", nargs="?",
                     help='e.g. "목동신시가지13단지" (must match the official complex name). '
                          'Omit when using --region-only.')
    ap.add_argument("--region", help="10-digit 법정동코드 (region_cd/cortarNo). Optional if cached "
                                      "(named-complex mode) / looked up from REGION_CACHE by name isn't "
                                      "automatic - pass the code directly.")
    ap.add_argument("--region-only", action="store_true",
                     help="Region-wide mode for property types with no named complex "
                          "(빌라/다세대→--type 주택, 원룸, 상가, 등). Requires --region and --type.")
    ap.add_argument("--type", default="아파트", choices=TENCOMZ_TYPES,
                     help="Tencomz property type (--region-only mode only). Default: 아파트")
    ap.add_argument("--no-hanbang", action="store_true", help="skip Hanbang cross-check call")
    ap.add_argument("--json", help="also dump raw merged data to this JSON file")
    args = ap.parse_args()

    if args.region_only:
        if not args.region:
            print("ERROR: --region-only requires --region <법정동코드>", file=sys.stderr)
            sys.exit(1)
        run_region(args.region, args.type, save_json=args.json)
    else:
        if not args.complex_name:
            print("ERROR: complex_name is required unless --region-only is set", file=sys.stderr)
            sys.exit(1)
        run(args.complex_name, region_cd=args.region, use_hanbang=not args.no_hanbang, save_json=args.json)

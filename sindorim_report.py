#!/usr/bin/env python3
"""
Build docs/sindorim.html - a daily 전세/월세 시세표 for the apartment complexes
around 디큐브시티 (신도림/구로 일대), benchmarking against the user's 디큐브 unit.

Source: 4-way union of asil / 부동산써브(serve.co.kr) / NEONET(부동산뱅크) / 텐컴즈,
cross-source-deduped. None of the four is complete on its own - each covers a
different agent set and misses what the others catch (verified: 태영타운 전세/월세
only on serve; 디큐브 매매 richest on asil; 동아3차 84㎡ 9.0억 전세 only on NEONET).
Hanbang (협회) stays dropped: every page-scope 한방-only listing was a ghost/error
with no backing on any of the four (SK뷰 84㎡ 2.8억 typo, 태영 59㎡ stale).

NB: serve.co.kr blocks GitHub Actions' datacenter IP, so this page is regenerated
interactively (not in the daily workflow) and just committed/deployed as-is.

Filter (fixed): 전용 ≥ 55㎡, exclude the 80㎡대 (80.0~83.9, keeps 84 국민평형),
신구로자이 excluded entirely (소형 주상복합, not comparable).

월세 is converted to a 전세-equivalent price: 보증금 + 월세(만원)/40 (i.e. 월 40만원 ≈ 1억),
and the two are merged into one table sorted by that equivalent, grouped by 평형 tier.
"""
import html as _html
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import (asil_fetch, serve_fetch_ldong, neonet_fetch, tencomz_fetch,
                      dedupe_by_unit, dedupe_cross_source)

KST = timezone(timedelta(hours=9))
REPO_ROOT = Path(__file__).parent
OUTPUT = REPO_ROOT / "docs" / "sindorim.html"

WOLSE_PER_EOK = 40  # 월세 40만원 ≈ 전세 1억 (환산 계수)

# 세 개 tier 표가 세로줄이 딱 맞도록 모든 표에 동일한 고정 컬럼폭을 강제 (합 100%).
# 순서: 전세가 · 보증금/월 · 단지 · 거리 · 준공 · 전용 · 층 · 등록일
COLGROUP = (
    "<colgroup>"
    '<col style="width:10%"><col style="width:13%"><col style="width:34%">'
    '<col style="width:8%"><col style="width:8%"><col style="width:8%">'
    '<col style="width:10%"><col style="width:9%">'
    "</colgroup>"
)

# 써브 매물을 담아둔 법정동들 (한 번씩만 긁어서 aptNo로 매칭). 신도림동+구로동.
SERVE_LDONGS = ["1153010100", "1153010200"]

# 4소스 합집합. 어느 하나도 완전하지 않고 서로 다른 걸 놓쳐서 넷 다 합침:
#   asil / 써브(serve) / NEONET(부동산뱅크) / 텐컴즈
# 각 코드: None = 그 소스가 이 단지를 인덱싱 안 함(→ 건너뜀).
# 필드: (표시명, 디큐브거리m, 준공, 법정동, asil, 써브aptNo, neonet_cc, 텐컴즈aptno)
NEIGHBORHOOD = [
    ("신도림디큐브시티", 0, 2011, "1153010100", 20141047, "27310", "A0033011", "27310"),
    ("신도림동아2차", 258, 2000, "1153010100", 2103, "3209", "A0000631", "3209"),
    ("SK뷰", 278, 2006, "1153010100", 20033986, "13084", "A0024394", "13085"),
    ("신도림태영타운", 281, 2000, "1153010200", 1985, "3204", "A0012111", "3204"),
    ("신도림4차e편한세상", 310, 2003, "1153010100", 52813, None, "A0012028", "3356"),
    ("신도림동아3차", 430, 1995, "1153010100", 2104, "3210", "A0010991", "3210"),
    ("신도림현대(구로)", 479, 1994, "1153010200", 1986, "9937", "A0000613", "125"),
    ("구로우성", 515, 1985, "1153010200", 1992, "1072", "A0017259", "1072"),
    ("신도림7차e편한세상", 554, 2004, "1153010100", 249070, None, "A0018647", "8919"),
    ("신도림동아1차", 593, 1999, "1153010100", 2102, None, "A0000630", "1074"),
    ("신도림우성3차", 643, 1993, "1153010100", 50284, None, "A0031752", "152"),
    ("신도림5차e편한세상", 715, 2003, "1153010100", 50668, None, "A0018257", "8714"),
    ("신도림대림1,2차", 797, 1999, "1153010100", 2099, None, "A0000629", "3354"),
    ("신도림대림3차", 950, 2001, "1153010100", 2101, None, "A0011710", "3355"),
    ("신도림미성", 1100, 1989, "1153010100", 2105, None, None, "149"),
]


def _to_int(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def keep(ex):
    """Fixed area filter: >=55, drop the 80㎡대 (80.0~83.9)."""
    return ex >= 55.0 and not (80.0 <= ex < 84.0)


def jeonse_equiv(row):
    """전세 = 보증금(만원); 월세 = 보증금 + 월세*10000/40 (만원). Returns 만원 int."""
    dep = _to_int(row.get("price1")) or 0
    if row["trade"] == "월세":
        wol = _to_int(row.get("price2")) or 0
        return dep + wol * 10000 // WOLSE_PER_EOK
    return dep


def tier(ex):
    if ex >= 95:
        return (0, "전용 95㎡↑ · 대형")
    if 84 <= ex < 95:
        return (1, "전용 84~85㎡ · 국민평형")
    return (2, "전용 55~79㎡ · 중형")


def collect():
    # 써브 매물을 법정동 단위로 한 번씩만 긁어 aptNo->[rows] 로 모아둔다.
    serve_by_apt = {}
    for ldong in SERVE_LDONGS:
        serve_by_apt.update(serve_fetch_ldong(ldong))

    listings = []
    for name, dist, year, region, acode, serve_apt, neonet_cc, tenc_apt in NEIGHBORHOOD:
        rows = []
        rows += dedupe_by_unit(asil_fetch(acode)) if acode else []
        rows += dedupe_by_unit(serve_by_apt.get(serve_apt, [])) if serve_apt else []
        rows += dedupe_by_unit(neonet_fetch(region, neonet_cc)) if neonet_cc else []
        rows += dedupe_by_unit(tencomz_fetch(region, tenc_apt)) if tenc_apt else []
        # 4소스는 상보적이라 합치되, 같은 물건이 여러 소스에 있으면 크로스디덥으로 1건 처리.
        for r in dedupe_cross_source(rows):
            if r["trade"] not in ("전세", "월세"):
                continue
            ex = float(r.get("exclusive") or 0)
            if not keep(ex):
                continue
            listings.append({
                "name": name, "dist": dist, "year": year, "ex": ex,
                "trade": r["trade"], "floor": r.get("floor") or "",
                "dep": _to_int(r.get("price1")) or 0,
                "wol": _to_int(r.get("price2")) if r["trade"] == "월세" else None,
                "eq": jeonse_equiv(r), "date": r.get("date", ""),
            })
        time.sleep(0.2)
    return listings


def _eok(manwon):
    return f"{manwon/10000:.2f}".rstrip("0").rstrip(".")


def floor_disp(f):
    return f if f and "None" not in f else "—"


def date_disp(d):
    """'26.08.24' -> '08.24'; else '—'."""
    p = (d or "").split(".")
    return f"{p[1]}.{p[2]}" if len(p) == 3 else "—"


def _date_key(d):
    """'26.08.24' -> (2026,8,24) 로 최신순 정렬용. 없으면 아주 옛날(0,0,0)."""
    p = (d or "").split(".")
    if len(p) == 3 and all(x.isdigit() for x in p):
        y = int(p[0]) + (2000 if int(p[0]) < 100 else 0)
        return (y, int(p[1]), int(p[2]))
    return (0, 0, 0)


def dedupe_same_listing(listings):
    """같은 단지 · 같은 전용면적(표시 정수㎡) · 같은 거래유형 · 같은 보증금/월세면
    동일 매물로 보고 등록일이 가장 최근인 하나만 남긴다.

    cross-source 디덥은 (동+층+가격)까지 맞아야 1건으로 합치는데, 소스마다 층/동을
    다르게 적거나 비워두면 같은 물건이 여러 행으로 살아남는다. 이 페이지에서는
    표에 보이는 값(단지·전용㎡·전세가·보증금/월)이 똑같으면 사용자가 곧 같은 매물로
    보므로, 그런 행은 최신 등록일 하나로 접는다. 등록일이 같으면 층 정보가 있는 쪽."""
    best = {}
    for x in listings:
        key = (x["name"], f'{x["ex"]:.0f}', x["trade"], x["dep"], x["wol"])
        rank = (_date_key(x["date"]), 1 if floor_disp(x["floor"]) != "—" else 0)
        cur = best.get(key)
        if cur is None or rank > cur[0]:
            best[key] = (rank, x)
    return [v[1] for v in best.values()]


def render(listings):
    from collections import defaultdict
    groups = defaultdict(list)
    for x in listings:
        groups[tier(x["ex"])].append(x)
    build_time = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    sections = []
    for key in sorted(groups):
        rows = sorted(groups[key], key=lambda r: -r["eq"])
        trs = []
        for r in rows:
            wol = (f'{_eok(r["dep"])}억 / {r["wol"]}' if r["trade"] == "월세" else "—")
            mark = ' <span class="tag-w">월세</span>' if r["trade"] == "월세" else ""
            you = ' <span class="tag-me">내 물건</span>' if r["name"] == "신도림디큐브시티" and abs(r["ex"]-85) < 2 and r["trade"] == "전세" else ""
            trs.append(
                f'<tr{" class=\"row-me\"" if you else ""}>'
                f'<td class="c-eq" data-label="전세가(환산)">{_eok(r["eq"])}억</td>'
                f'<td class="c-w" data-label="보증금/월">{wol}</td>'
                f'<td data-label="단지">{_html.escape(r["name"])}{you}{mark}</td>'
                f'<td class="c-dist" data-label="거리">{r["dist"]}m</td>'
                f'<td class="c-num" data-label="준공">{r["year"]}</td>'
                f'<td class="c-num" data-label="전용">{r["ex"]:.0f}㎡</td>'
                f'<td class="c-num" data-label="층">{floor_disp(r["floor"])}</td>'
                f'<td class="c-num" data-label="등록일">{date_disp(r["date"])}</td>'
                f'</tr>')
        sections.append(
            f'<h2>{_html.escape(key[1])} <span class="cnt">{len(rows)}건</span></h2>'
            f'<div class="table-scroll"><table>' + COLGROUP + '<thead><tr>'
            f'<th>전세가(환산)</th><th>보증금/월</th><th>단지</th><th class="th-dist">거리</th><th>준공</th><th>전용</th><th>층</th><th>등록일</th>'
            f'</tr></thead><tbody>' + "".join(trs) + '</tbody></table></div>')

    total = len(listings)
    return TEMPLATE.replace("__SECTIONS__", "\n".join(sections)) \
                   .replace("__BUILD_TIME__", build_time) \
                   .replace("__TOTAL__", str(total))


TEMPLATE = """<meta name="viewport" content="width=device-width, initial-scale=1">
<title>신도림 전세·월세 시세 · 디큐브 인근</title>
<style>
  :root{--paper:#faf7f2;--paper-deep:#efe8db;--line:#ddd3c2;--ink:#241f1a;--ink-soft:#6f6459;--ink-faint:#a89d8e;--stamp:#b23b2e;--jeonse:#3b6e5e;--wolse:#8a6a1f;--me:#b23b2e;}
  @media (prefers-color-scheme:dark){:root:not([data-theme=light]){--paper:#1c1815;--paper-deep:#262019;--line:#3a3229;--ink:#ede6da;--ink-soft:#b3a897;--ink-faint:#7d7264;--stamp:#e06a5a;--jeonse:#6fb39c;--wolse:#c9a24e;--me:#e06a5a;}}
  :root[data-theme=dark]{--paper:#1c1815;--paper-deep:#262019;--line:#3a3229;--ink:#ede6da;--ink-soft:#b3a897;--ink-faint:#7d7264;--stamp:#e06a5a;--jeonse:#6fb39c;--wolse:#c9a24e;--me:#e06a5a;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;word-break:keep-all;line-height:1.5}
  .wrap{max-width:920px;margin:0 auto;padding:28px 16px 60px}
  header{border-bottom:2px solid var(--ink);padding-bottom:14px;margin-bottom:22px}
  h1{font-size:clamp(20px,4vw,26px);margin:0 0 6px}
  .sub{font-size:13px;color:var(--ink-soft)}
  .build{font-size:11.5px;color:var(--ink-faint);margin-top:6px}
  .back{font-size:12.5px;color:var(--stamp);text-decoration:none;font-weight:600}
  h2{font-size:15px;margin:26px 0 8px;padding-bottom:5px;border-bottom:1px solid var(--line)}
  .cnt{font-size:12px;color:var(--ink-faint);font-weight:400}
  .table-scroll{overflow-x:auto}
  table{width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed}
  th{text-align:left;font-size:11px;letter-spacing:.03em;color:var(--ink-soft);text-transform:uppercase;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
  th.th-dist{text-align:right}
  td{padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:top}
  .c-eq{font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
  .c-w{color:var(--wolse);font-variant-numeric:tabular-nums;font-size:12px;white-space:nowrap}
  .c-num{font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--ink-soft)}
  .c-dist{font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--ink-soft);text-align:right}
  .tag-w{background:var(--wolse);color:#fff;font-size:10px;padding:1px 5px;border-radius:3px;vertical-align:middle}
  .tag-me{background:var(--me);color:#fff;font-size:10px;padding:1px 5px;border-radius:3px}
  .row-me td{background:var(--paper-deep)}
  footer{margin-top:34px;padding-top:14px;border-top:1px solid var(--line);font-size:11.5px;color:var(--ink-faint);line-height:1.7}
  @media(max-width:640px){
    thead{display:none}
    table,tbody,tr,td{display:block;width:100%}
    tr{border:1px solid var(--line);border-radius:4px;margin-bottom:10px;padding:4px 12px;background:var(--paper)}
    td{border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;padding:8px 0}
    tr td:last-child{border-bottom:none}
    td::before{content:attr(data-label);font-size:11px;text-transform:uppercase;color:var(--ink-soft)}
    .c-eq{font-size:16px}
    .row-me td{background:transparent}
  }
</style>
<div class="wrap">
  <header>
    <a class="back" href="./index.html">← 내 매물 리포트</a>
    <h1>신도림 전세·월세 시세 <span style="font-size:14px;color:var(--ink-faint)">디큐브 인근 · __TOTAL__건</span></h1>
    <div class="sub">디큐브시티 반경 1.1km · 전용 55㎡↑ (80㎡대 제외) · 월세는 보증금+월세÷40으로 전세 환산</div>
    <div class="build">마지막 갱신 <b>__BUILD_TIME__</b> · 출처 asil+써브+NEONET+텐컴즈 4소스 합집합 · 수동 갱신</div>
  </header>
  __SECTIONS__
  <footer>
    전세가(환산): 월세는 보증금 + 월세(만원)÷40으로 전세 상당액 환산 (월 40만원 ≈ 1억). "보증금/월" 칸이 채워진 게 월세.<br>
    출처는 asil·부동산써브·NEONET(부동산뱅크)·텐컴즈 4소스 합집합. 넷 다 서로 다른 매물을 놓쳐서(태영=써브, 디큐브=asil, 동아3차 84㎡=NEONET) 다 합침. 같은 매물이 양쪽·여러 중개사에 중복등록돼도 1건으로 정리됨. 신구로자이(소형 주상복합)는 비교군에서 제외.<br>
    매물은 나오는 즉시 계약돼 빠질 수 있어 실시간과 시차가 있을 수 있음. 참고용.
  </footer>
</div>
"""


def main():
    raw = collect()
    if not raw:
        print("ERROR: 0 listings collected, refusing to overwrite", file=sys.stderr)
        sys.exit(1)
    listings = dedupe_same_listing(raw)
    removed = len(raw) - len(listings)
    if removed:
        print(f"same-listing dedupe: {len(raw)} -> {len(listings)} ({removed}건 중복 제거)",
              file=sys.stderr)
    html_out = render(listings)
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(html_out, encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(html_out)} bytes, {len(listings)} listings)", file=sys.stderr)


if __name__ == "__main__":
    main()

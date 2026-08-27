#!/usr/bin/env python3
"""
Build docs/sindorim.html - a daily 전세/월세 시세표 for the apartment complexes
around 디큐브시티 (신도림/구로 일대), benchmarking against the user's 디큐브 unit.

Sources: asil.kr (aggregates Naver) + Hanbang (한국공인중개사협회), unioned and
cross-source-deduped - neither is complete on its own, so both are pulled.

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
from pipeline import asil_fetch, hanbang_fetch, dedupe_by_unit, dedupe_cross_source

KST = timezone(timedelta(hours=9))
REPO_ROOT = Path(__file__).parent
OUTPUT = REPO_ROOT / "docs" / "sindorim.html"

WOLSE_PER_EOK = 40  # 월세 40만원 ≈ 전세 1억 (환산 계수)

# (표시명, asil코드, 한방검색명, 디큐브로부터 직선거리 m, 준공연도)
NEIGHBORHOOD = [
    ("신도림디큐브시티", 20141047, "신도림디큐브시티", 0, 2011),
    ("신도림동아2차", 2103, "신도림동아2차", 258, 2000),
    ("SK뷰", 20033986, "SK VIEW", 278, 2006),
    ("신도림태영타운", 1985, "신도림태영타운", 281, 2000),
    ("신도림4차e편한세상", 52813, "신도림4차e편한세상", 310, 2003),
    ("신도림동아3차", 2104, "신도림동아3차", 430, 1995),
    ("신도림현대(구로)", 1986, "신도림현대", 479, 1994),
    ("구로우성", 1992, "구로우성", 515, 1985),
    ("신도림7차e편한세상", 249070, "신도림7차e편한세상", 554, 2004),
    ("신도림동아1차", 2102, "신도림동아1차", 593, 1999),
    ("신도림우성3차", 50284, "신도림우성3차", 643, 1993),
    ("신도림5차e편한세상", 50668, "신도림5차e편한세상", 715, 2003),
    ("신도림대림1,2차", 2099, "신도림대림1,2차", 797, 1999),
    ("신도림대림3차", 2101, "신도림대림3차", 950, 2001),
    ("신도림미성", 2105, "신도림미성", 1100, 1989),
]


def _to_int(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def hanbang_norm(name, trade):
    """Hanbang rows -> pipeline row shape, for one trade type."""
    out = []
    for x in hanbang_fetch(name):
        if x.get("trade") != trade:
            continue
        try:
            ex = float(x.get("jun_meter") or 0)
        except (TypeError, ValueError):
            continue
        out.append({
            "source": "hanbang", "trade": trade, "exclusive": ex,
            "dong": (x.get("danji_dong_nm") or "") + "동",
            "floor": f"{x.get('curr_floor')}/{x.get('total_floor')}",
            "price1": str(_to_int(x.get("amt_guar")) or ""),
            "price2": str(_to_int(x.get("amt_month")) or "") if trade == "월세" else None,
            "date": x.get("date", ""), "note": x.get("note", ""),
        })
    return out


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


HANBANG_STALE_DAYS = 14  # 협회 단독 매물이 이만큼 오래되면 유령매물로 보고 제외


def _parse_date(s):
    """'26.08.08' or '2026-08-22' -> date, else None."""
    s = (s or "").strip().replace("-", ".")
    parts = s.split(".")
    try:
        if len(parts) == 3:
            y, m, d = (int(p) for p in parts)
            if y < 100:
                y += 2000
            return datetime(y, m, d, tzinfo=KST).date()
    except (ValueError, TypeError):
        pass
    return None


def _is_stale_hanbang(row, today):
    """asil(네이버)은 신선도가 유지되니 나이 무관; 한방 단독 매물만 오래되면 제외.
    Naver rarely keeps ghosts, so a hanbang-only listing that's weeks old with no
    Naver presence is very likely already gone (see 태영 59㎡ case)."""
    if row.get("source") != "hanbang":
        return False
    d = _parse_date(row.get("date"))
    if d is None:
        return False
    return (today - d).days > HANBANG_STALE_DAYS


def collect():
    today = datetime.now(KST).date()
    listings = []
    for name, acode, hname, dist, year in NEIGHBORHOOD:
        rows = []
        for trade in ("전세", "월세"):
            a = [r for r in dedupe_by_unit(asil_fetch(acode)) if r["trade"] == trade]
            h = hanbang_norm(hname, trade)
            rows += dedupe_cross_source(a + h)
        for r in rows:
            ex = float(r.get("exclusive") or 0)
            if not keep(ex) or _is_stale_hanbang(r, today):
                continue
            listings.append({
                "name": name, "dist": dist, "year": year, "ex": ex,
                "trade": r["trade"], "floor": r.get("floor") or "",
                "dep": _to_int(r.get("price1")) or 0,
                "wol": _to_int(r.get("price2")) if r["trade"] == "월세" else None,
                "eq": jeonse_equiv(r), "date": r.get("date", ""),
                "source": r.get("source", ""),
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
                f'<td class="c-num" data-label="거리">{r["dist"]}m</td>'
                f'<td class="c-num" data-label="준공">{r["year"]}</td>'
                f'<td class="c-num" data-label="전용">{r["ex"]:.0f}㎡</td>'
                f'<td class="c-num" data-label="층">{floor_disp(r["floor"])}</td>'
                f'<td class="c-num" data-label="등록일">{date_disp(r["date"])}</td>'
                f'</tr>')
        sections.append(
            f'<h2>{_html.escape(key[1])} <span class="cnt">{len(rows)}건</span></h2>'
            f'<div class="table-scroll"><table><thead><tr>'
            f'<th>전세가(환산)</th><th>보증금/월</th><th>단지</th><th>거리</th><th>준공</th><th>전용</th><th>층</th><th>등록일</th>'
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
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{text-align:left;font-size:11px;letter-spacing:.03em;color:var(--ink-soft);text-transform:uppercase;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
  td{padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:top}
  .c-eq{font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
  .c-w{color:var(--wolse);font-variant-numeric:tabular-nums;font-size:12px;white-space:nowrap}
  .c-num{font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--ink-soft)}
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
    <div class="build">마지막 자동 갱신 <b>__BUILD_TIME__</b> · 출처 asil(네이버)+한방(협회) 합집합</div>
  </header>
  __SECTIONS__
  <footer>
    전세가(환산): 월세는 보증금 + 월세(만원)÷40으로 전세 상당액 환산 (월 40만원 ≈ 1억). "보증금/월" 칸이 채워진 게 월세.<br>
    "—" 층은 한방(협회) 매물로 층 정보가 없는 건. 신구로자이(소형 주상복합)는 비교군에서 제외.<br>
    네이버에 없고 협회에만 등록된 매물 중 14일 넘은 건은 유령매물 가능성이 높아 자동 제외(네이버 매물은 등록일 무관 유지).<br>
    매물은 나오는 즉시 계약돼 빠질 수 있어 실시간과 시차가 있을 수 있음. 참고용.
  </footer>
</div>
"""


def main():
    listings = collect()
    if not listings:
        print("ERROR: 0 listings collected, refusing to overwrite", file=sys.stderr)
        sys.exit(1)
    html_out = render(listings)
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(html_out, encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(html_out)} bytes, {len(listings)} listings)", file=sys.stderr)


if __name__ == "__main__":
    main()

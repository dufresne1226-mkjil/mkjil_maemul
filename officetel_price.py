#!/usr/bin/env python3
"""
국세청 오피스텔 기준시가 조회 (data.go.kr 오픈API).

Dataset: 국세청_상업용건물 오피스텔 기준시가_20260101
  https://www.data.go.kr/data/3036455/fileData.do
Swagger: https://infuser.odcloud.kr/oas/docs?namespace=3036455/v1

⚠️ IMPORTANT / KNOWN LIMITATION: the auto-generated OpenAPI wrapper for this
dataset is STALE. The Swagger spec lists 19 endpoints, one per 고시연도
(2005~2020), but nothing for years after 2020 - even though the underlying
FILE dataset is titled "...20260101" (i.e. supposedly current). The most
recent working endpoint found is the "20200101" (고시일자 2020-01-01) uuid
below. There is currently NO way found to get 2021+ 기준시가 through this
API - the government agency updated the file but never regenerated the API
wrapper for newer years. Confirmed empty duplicate exists too
(uddi:24153db7-... returns 0 rows for the same "20200101" label - use
04e7fcee instead, verified populated).

Endpoint (verified working with a real serviceKey - returns real 2020 rows):
  https://api.odcloud.kr/api/3036455/v1/uddi:04e7fcee-3162-40ae-90e9-b1330f2e9b11

Real field names (from an actual response, Korean, not what the dataset
description page implied):
  건물층구분코드, 고시가격, 고시일자, 공유면적, 번지, 법정동코드,
  상가건물동주소, 상가건물번호, 상가건물블록주소(=건물명), 상가건물층주소,
  상가건물호주소, 상가종류코드, 전용면적, 특수지코드, 호

⚠️ SCOPE LIMITATION (found by testing on 디큐브시티, 신도림동 1153010100):
이 데이터셋은 세법상 "오피스텔/상업용건물" 기준시가만 다룬다 - 아파트(주상복합
포함)는 기준시가가 아니라 별도의 "공동주택가격"으로 공시되므로 여기 안 나온다.
신도림동 1153010100 전체(페이지 50~51, 3307건)를 다 훑어봤는데 디큐브시티 A동/
B동은 없었다 - 왜냐면 그건 "아파트"로 등록돼있기 때문. 신도림동에서 이 API에
실제로 잡히는 건: 신도림월드메르디앙오피스텔, 신도림팰러티움, 골든애비뉴제1동,
코리아빌딩, 콜카빌 (순수 오피스텔/상가) + 신도림1~3차푸르지오·신도림2차동아
아파트205동·신도림삼성쉐르빌1차 등 (아파트 단지 "내" 상가 부분만 잡힘 - 아파트
전체가 아니라 그 단지의 상가/부속 상업시설만).
사용 전 확인할 것: 찾는 게 (a) 순수 오피스텔 또는 아파트 단지 내 상가라면 이 API가
맞고, (b) 아파트/주상복합 주거용 유닛 자체라면 이 API로는 절대 안 나온다 -
공동주택가격 API(국토교통부, data.go.kr 별도 데이터셋)를 찾아야 한다.

⚠️ NO server-side filter param (cond) exists on this endpoint. Client-side
filtering after fetch is the only option. The data IS sorted ascending by
법정동코드, so binary-search the target page (perPage=1 probes, ~20 requests
for 721k rows) before bulk-fetching with perPage=5000 (confirmed max - 10000
silently returns {"code":0,"msg":"정상"} with no data array).

Getting a service key (free, one-time, usually auto-approved instantly):
  1. https://www.data.go.kr 회원가입
  2. 위 데이터셋 페이지 → "활용신청" 클릭
  3. 마이페이지 > 데이터활용 > Open API > 활용신청현황에서 인증키 복사
     (이 스크립트는 URL-encoded/"Encoding" 키를 그대로 받아서 재인코딩하지 않고
     씀 - urllib.parse.quote_via로 안전문자를 넓혀서 이중인코딩 방지함)
  4. 아래 --key 또는 환경변수 NTS_OFFICETEL_KEY로 지정

Usage:
    export NTS_OFFICETEL_KEY="발급받은_인증키(Encoding 그대로)"
    python3 officetel_price.py --raw                         # 원본 확인
    python3 officetel_price.py --bjd 1153010100               # 법정동코드로 필터
    python3 officetel_price.py --building-name 디큐브시티      # 건물명(상가건물블록주소) 키워드
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

BASE_URL = "https://api.odcloud.kr/api/3036455/v1/uddi:04e7fcee-3162-40ae-90e9-b1330f2e9b11"


MAX_PER_PAGE = 5000  # confirmed ceiling - 10000 silently returns no data


def fetch_page(service_key, page=1, per_page=100):
    # service_key from data.go.kr comes pre-URL-encoded ("Encoding" key) -
    # pass it through as-is (only page/perPage get normally encoded) so it
    # isn't double-encoded (that turns %2B into %252B and breaks auth).
    params = urllib.parse.urlencode({"page": page, "perPage": per_page})
    url = f"{BASE_URL}?{params}&serviceKey={service_key}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def bjd_at_row(service_key, row_1based):
    """Cheap probe: fetch just one row at a given 1-based position."""
    d = fetch_page(service_key, page=row_1based, per_page=1)
    return d["data"][0]["법정동코드"]


def find_bjd_range(service_key, bjd, total_count):
    """Binary-search the row range for an exact 법정동코드 (data is sorted
    ascending by 법정동코드). ~2*log2(total_count) requests, perPage=1 each."""
    lo, hi = 1, total_count
    while lo < hi:
        mid = (lo + hi) // 2
        if bjd_at_row(service_key, mid) < bjd:
            lo = mid + 1
        else:
            hi = mid
    start = lo
    lo, hi = start, total_count
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if bjd_at_row(service_key, mid) > bjd:
            hi = mid - 1
        else:
            lo = mid
    end = lo
    return start, end


def fetch_bjd(service_key, bjd, total_count):
    """Full row set for one 법정동코드 via binary-search + bulk page fetch."""
    start, end = find_bjd_range(service_key, bjd, total_count)
    if end < start:
        return []
    results = []
    page = ((start - 1) // MAX_PER_PAGE) + 1
    while True:
        d = fetch_page(service_key, page=page, per_page=MAX_PER_PAGE)
        rows = [r for r in d["data"] if r["법정동코드"] == bjd]
        results.extend(rows)
        last_row_idx = page * MAX_PER_PAGE
        if last_row_idx >= end:
            break
        page += 1
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", help="서비스키. 생략 시 NTS_OFFICETEL_KEY 환경변수 사용")
    ap.add_argument("--bjd", help="법정동코드 (10자리) - 이진탐색으로 해당 동 전체를 가져옴")
    ap.add_argument("--building-name", help="--bjd 결과 안에서 건물명(상가건물블록주소) 키워드로 추가 필터")
    ap.add_argument("--page", type=int, default=1, help="--bjd 없이 그냥 특정 페이지 원본 훑어볼 때")
    ap.add_argument("--per-page", type=int, default=100)
    ap.add_argument("--raw", action="store_true", help="원본 JSON 그대로 출력 (컬럼명/응답구조 확인용)")
    args = ap.parse_args()

    service_key = args.key or os.environ.get("NTS_OFFICETEL_KEY")
    if not service_key:
        print("ERROR: --key 또는 환경변수 NTS_OFFICETEL_KEY 로 서비스키를 지정하세요.\n"
              "발급 방법은 이 파일 상단 docstring 참고.", file=sys.stderr)
        sys.exit(1)

    if args.raw or not args.bjd:
        data = fetch_page(service_key, page=args.page, per_page=args.per_page)
        if args.raw:
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return
        items = data.get("data", [])
        print(f"총 {data.get('totalCount')}건 중 이 페이지 {len(items)}건 (page={args.page}, perPage={args.per_page})")
        for it in items:
            print(it)
        return

    probe = fetch_page(service_key, page=1, per_page=1)
    total_count = probe["totalCount"]
    print(f"전체 {total_count}건 중 법정동코드 {args.bjd} 이진탐색 중...", file=sys.stderr)
    rows = fetch_bjd(service_key, args.bjd, total_count)
    print(f"법정동코드 {args.bjd}: {len(rows)}건")

    buildings = {}
    for r in rows:
        if args.building_name and args.building_name not in r["상가건물블록주소"]:
            continue
        buildings.setdefault(r["상가건물블록주소"], []).append(r)

    for name, units in sorted(buildings.items()):
        print(f"\n=== {name} ({len(units)}호) ===")
        for u in units:
            print(f"  {u['상가건물동주소']}동 {u['상가건물층주소']}층 {u['상가건물호주소']}호 | "
                  f"전용{u['전용면적']}㎡/공유{u['공유면적']}㎡ | 고시가격 {int(u['고시가격']):,}원 "
                  f"({u['고시일자']} 기준)")

    if args.building_name and not buildings:
        print(f"\n'{args.building_name}'을(를) 포함하는 건물명이 이 법정동코드 안에 없습니다.")
        print("전체 건물명 목록:", sorted(set(r["상가건물블록주소"] for r in rows)))


if __name__ == "__main__":
    main()

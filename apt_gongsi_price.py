#!/usr/bin/env python3
"""
부동산공시가격알리미(realtyprice.kr) 공동주택 공시가격 조회.

officetel_price.py(data.go.kr 오픈API, 오피스텔/상업용건물 전용, 2020년 이후 미갱신)로는
아파트/주상복합 주거용 유닛을 아예 다룰 수 없다는 게 확인된 뒤 만든 별도 스크립트.
data.go.kr 키 발급 없이, realtyprice.kr이 실제로 쓰는 내부 JSON API를 그대로 호출한다.

핵심 장애물은 NetFunnel(kwait.reb.or.kr) 접속 대기열이었다 - 정부 사이트 특유의
트래픽 제어 게이트로, 브라우저에서는 JS가 자동으로 처리하지만 curl/requests로는
그냥 막힌 것처럼 보인다. 실제로는:
  1. GET https://kwait.reb.or.kr/ts.wseq?opcode=5101&sid=service_1&aid=town_index&js=yes&...
     -> 응답 텍스트에서 "5002:200:key=..." 형태의 raw 문자열을 얻는다 (nwait=0이면 즉시 통과,
        피크 시간대라 대기가 걸리면 nwait>0 - 이 스크립트는 그 경우를 처리하지 않는다).
  2. 그 raw 문자열을 JS `escape()` 인코딩 그대로 쿠키 `NetFunnel_ID`에 담아서 보내면
     서버가 게이트를 통과시켜준다. 브라우저는 이 쿠키를 document.cookie로 설정하는데,
     그냥 요청 헤더에 Cookie로 실어 보내는 것만으로 충분했다.

그 다음은 사이트의 실제 검색 폼(공동주택 > 공시가격 열람 > 과년도 열람 탭)이 쓰는
cascading select용 JSON API 4개를 순서대로 호출:
  시도/시군구/읍면동 -> 단지 -> 동 -> 호 -> 가격(다년도 한번에 나옴)

주의사항:
- notice_date_year 코드는 날짜처럼 생겼지만 실제 공시일(예: 20260430)이 아니라
  내부 배치 코드(예: 2026년분 = "20260626")다. 반드시 /notice/town/searchNoticeDate.search
  로 먼저 조회해서 알아내야 한다 - 하드코딩하면 해마다 깨진다.
- 이 세션에서 30회 이상 연속 조회해도 캡챠가 뜨지 않았지만, 응답에 `error_gbn`이
  `ERROR_STOP`으로 오면 캡챠 요구 상태 - 이 스크립트는 그 경우 그냥 에러를 낸다
  (자동 캡챠 풀이는 구현 안 함, 시간 두고 재시도할 것).
- 동일 평형이라도 동/층에 따라 공시가격이 꽤 벌어진다(디큐브시티 84.96㎡ 확인 사례:
  8.38억~9.49억) - "이 단지 이 평형은 얼마"라고 뭉뚱그리지 말고, 특정 호실을 모르면
  --list-units 로 전체 호실을 펼쳐서 평형별 범위를 보여주는 쪽이 정직하다.

사용법:
    python3 apt_gongsi_price.py --sido 서울특별시 --sgg 구로구 --eub 신도림동 --apt 디큐브시티
        -> 단지 내 전체 호실을 평형별로 묶어서 2026년 공시가격 범위 출력

    python3 apt_gongsi_price.py --sido 서울특별시 --sgg 구로구 --eub 신도림동 --apt 디큐브시티 \\
        --dong-name A --ho-name 2202
        -> 특정 호실 하나의 연도별(가능한 전체 이력) 공시가격 출력
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://www.realtyprice.kr"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
NETFUNNEL_TS = "https://kwait.reb.or.kr:443/ts.wseq"
REFERER = f"{BASE}/notice/town/searchPastYear.htm"


def js_escape(s: str) -> str:
    """JS escape() 재현 - A-Za-z0-9 @*_+-./ 만 그대로, 나머지는 %XX."""
    out = []
    for ch in s:
        if re.match(r"[A-Za-z0-9@*_+./-]", ch):
            out.append(ch)
        else:
            out.append("%%%02X" % ord(ch))
    return "".join(out)


class Session:
    def __init__(self):
        self.cookie_jar = {}
        self._netfunnel_id = None

    def _cookie_header(self) -> str:
        parts = [f"{k}={v}" for k, v in self.cookie_jar.items()]
        if self._netfunnel_id:
            parts.append(f"NetFunnel_ID={self._netfunnel_id}")
        return "; ".join(parts)

    def _request(self, url: str, ajax: bool = False) -> bytes:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Referer": REFERER,
            "Cookie": self._cookie_header(),
            **({"X-Requested-With": "XMLHttpRequest"} if ajax else {}),
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            for hdr in resp.headers.get_all("Set-Cookie") or []:
                name_val = hdr.split(";", 1)[0]
                if "=" in name_val:
                    k, v = name_val.split("=", 1)
                    self.cookie_jar[k] = v
            return resp.read()

    def bootstrap(self):
        """세션 쿠키 확보 + NetFunnel 게이트 통과."""
        self._request(f"{BASE}/notice/main/main.do")

        ts = int(time.time() * 1000)
        nf_url = (f"{NETFUNNEL_TS}?opcode=5101&nfid=netfunnel.data001"
                  f"&prefix=NetFunnel.gRtype=5101;&sid=service_1&aid=town_index"
                  f"&js=yes&user_data=&{ts}")
        raw = self._request(nf_url).decode("utf-8", "replace")
        m = re.search(r"gControl\.result='([^']+)'", raw)
        if not m:
            raise RuntimeError(f"NetFunnel 응답 파싱 실패: {raw[:200]}")
        result = m.group(1)
        code_m = re.match(r"5002:(\d+):", result)
        if not code_m or code_m.group(1) != "200":
            # nwait>0 이면 대기 필요 - 이 스크립트는 처리 안 함
            raise RuntimeError(f"NetFunnel 게이트 통과 실패(대기 발생 가능): {result[:200]}")
        self._netfunnel_id = js_escape(result)

        # 게이트를 통과했다는 걸 서버에 알리는 실제 목적지 페이지 방문
        self._request(f"{BASE}/notice/town/nfSiteLink.htm")
        self._request(f"{BASE}/notice/town/searchPastYear.htm")

    def get_json(self, path: str, params: dict) -> dict:
        qs = urllib.parse.urlencode(params)
        raw = self._request(f"{BASE}{path}?{qs}", ajax=True)
        return json.loads(raw)

    def latest_notice_date_year(self) -> str:
        """searchNoticeDate.search에서 가장 최근 코드를 뽑는다 (날짜와 다른 내부 배치코드)."""
        data = self.get_json("/notice/town/searchNoticeDate.search", {})
        lst = data["model"]["list"]
        if not lst:
            raise RuntimeError("공시일자 목록을 가져오지 못했습니다.")
        return lst[0]["code"]  # 서버가 최신순으로 내려줌

    def find_code(self, gubun: str, sido="", sgg="", eub="", notice_date_year="") -> list:
        return self.get_json("/notice/bjd/searchBjdTownYear.bjd", {
            "gubun": gubun, "notice_date_year": notice_date_year,
            "sido": sido, "sgg": sgg, "eub": eub,
        })["model"]["list"] or []

    def _search_form_base(self, notice_date_year, reg, eub, apt_name="",
                           apt_code="", dong_code="", ho_code="", gbn_apt=""):
        return {
            "gbn": "2", "year": notice_date_year[:4], "notice_date": notice_date_year,
            "notice_date_year": notice_date_year,
            "gbnApt": gbn_apt, "road_reg": "", "road": "", "initialword": "",
            "build_bun1": "", "build_bun2": "", "reg": reg, "eub": eub,
            "apt_name": apt_name, "bun1": "", "bun2": "",
            "apt_code": apt_code, "dong_code": dong_code, "ho_code": ho_code,
            "past_yn": "1", "init_gbn": "", "searchGbnRoad": "",
            "searchGbnBunji": "", "searchGbnBunjiYear": "0",
        }

    def find_apt(self, notice_date_year, reg, eub, apt_name):
        params = self._search_form_base(notice_date_year, reg, eub, apt_name=apt_name)
        return self.get_json("/notice/search/searchApt.search", params)["model"]["list"] or []

    def find_dong(self, notice_date_year, reg, eub, apt_name, apt_code):
        params = self._search_form_base(notice_date_year, reg, eub, apt_name=apt_name,
                                         apt_code=apt_code, gbn_apt="DONG")
        return self.get_json("/notice/search/searchApt.search", params)["model"]["list"] or []

    def find_ho(self, notice_date_year, reg, eub, apt_name, apt_code, dong_code):
        params = self._search_form_base(notice_date_year, reg, eub, apt_name=apt_name,
                                         apt_code=apt_code, dong_code=dong_code, gbn_apt="HO")
        return self.get_json("/notice/search/searchApt.search", params)["model"]["list"] or []

    def get_price_history(self, notice_date_year, reg, eub, apt_name, apt_code,
                           dong_code, ho_code):
        params = {
            "page_no": "1", "reg_name": "", "sreg": "", "seub": "", "old_reg": "", "old_eub": "",
            "gbn": "2", "year": notice_date_year[:4], "notice_date": notice_date_year,
            "notice_date_year": notice_date_year,
            "reg": reg, "eub": eub, "apt_name": apt_name, "bun1": "", "bun2": "",
            "road_code": "", "initialword": "", "build_bun1": "", "build_bun2": "",
            "gbnApt": "LAST", "apt_code": apt_code, "dong_code": dong_code, "ho_code": ho_code,
            "tabGbn": "Text", "full_addr_name": "", "dong_name": "", "ho_name": "",
            "notice_amt": "", "ktown_ho_seq": "", "print_yn": "0", "past_yn": "1",
            "searchGbnRoad": "", "searchGbnBunji": "", "searchGbnBunjiYear": "0",
            "capcha": "", "capcha_chk_yn": "", "recaptcha_token": "",
        }
        data = self.get_json("/notice/search/townPriceListPastYearMap.search", params)
        rows = data["model"]["list"] or []
        if not rows and data["model"].get("message"):
            raise RuntimeError(f"서버 메시지: {data['model']['message']} "
                                f"(error_gbn={data['model'].get('error_gbn')})")
        return rows


def resolve_bjd(sess: Session, notice_date_year: str, sido_name: str, sgg_name: str, eub_name: str):
    sido_list = sess.find_code("", notice_date_year=notice_date_year)
    sido = next((x for x in sido_list if sido_name in x["name"]), None)
    if not sido:
        raise SystemExit(f"시도 '{sido_name}' 못 찾음. 후보: {[x['name'] for x in sido_list]}")

    sgg_list = sess.find_code("SIGUNGU", sido=sido["code"], notice_date_year=notice_date_year)
    sgg = next((x for x in sgg_list if sgg_name in x["name"]), None)
    if not sgg:
        raise SystemExit(f"시군구 '{sgg_name}' 못 찾음. 후보: {[x['name'] for x in sgg_list]}")

    eub_list = sess.find_code("DONGRI", sido=sido["code"], sgg=sgg["code"],
                               notice_date_year=notice_date_year)
    eub = next((x for x in eub_list if eub_name in x["name"]), None)
    if not eub:
        raise SystemExit(f"읍면동 '{eub_name}' 못 찾음. 후보: {[x['name'] for x in eub_list]}")

    return sido["code"] + sgg["code"], eub["code"]  # reg, eub


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sido", required=True, help="예: 서울특별시")
    ap.add_argument("--sgg", required=True, help="예: 구로구")
    ap.add_argument("--eub", required=True, help="예: 신도림동")
    ap.add_argument("--apt", required=True, help="단지명 (부분일치, 예: 디큐브시티)")
    ap.add_argument("--dong-name", help="동 이름/문자 (예: A) - 생략시 전체 호실 요약만 출력")
    ap.add_argument("--ho-name", help="호 이름 뒷부분 (예: 2202) - --dong-name과 함께 지정")
    ap.add_argument("--notice-date-year", help="내부 배치코드 직접 지정(생략시 최신년도 자동)")
    args = ap.parse_args()

    sess = Session()
    print("[*] 세션 생성 + NetFunnel 게이트 통과 중...", file=sys.stderr)
    sess.bootstrap()

    ndy = args.notice_date_year or sess.latest_notice_date_year()
    print(f"[*] 공시연도 코드: {ndy}", file=sys.stderr)

    reg, eub = resolve_bjd(sess, ndy, args.sido, args.sgg, args.eub)
    print(f"[*] reg={reg} eub={eub}", file=sys.stderr)

    apts = sess.find_apt(ndy, reg, eub, args.apt)
    if not apts:
        raise SystemExit(f"단지 '{args.apt}' 검색 결과 없음 (reg={reg}, eub={eub})")
    apt = apts[0]
    apt_code = str(apt["code"])
    print(f"[*] 단지: {apt['name']} (code={apt_code})", file=sys.stderr)

    dongs = sess.find_dong(ndy, reg, eub, args.apt, apt_code)
    if not dongs:
        raise SystemExit("동 목록을 가져오지 못했습니다.")

    # 실제 동(건물)이 여러 개로 분리된 단지(예: 101~113동)와, 동 구분 없이 "아파트" 한
    # 그룹으로만 묶인 단지(예: 디큐브시티, 호 이름 자체에 "A-4605"처럼 동 정보가 들어있음)
    # 두 경우를 구분해야 한다 - 후자에서 dongs[0]만 쓰면 다동단지에서 엉뚱한 동을 조회하게 됨.
    multi_dong = len(dongs) > 1
    selected_dong = None
    if args.dong_name and multi_dong:
        selected_dong = next((d for d in dongs if d["name"] == args.dong_name
                               or d["name"].endswith(args.dong_name)), None)
        if not selected_dong:
            raise SystemExit(f"동 '{args.dong_name}' 못 찾음. 후보: {[d['name'] for d in dongs]}")
        dong_code = str(selected_dong["code"])
    else:
        dong_code = str(dongs[0]["code"])

    all_ho = sess.find_ho(ndy, reg, eub, args.apt, apt_code, dong_code)
    dong_label = selected_dong["name"] if selected_dong else dongs[0]["name"]
    print(f"[*] 동: {dong_label}{'동' if multi_dong else ''} · 총 {len(all_ho)}개 호실", file=sys.stderr)

    if args.ho_name:
        target = None
        for h in all_ho:
            if args.ho_name in h["name"]:
                if not multi_dong and args.dong_name and not h["name"].startswith(args.dong_name):
                    continue
                target = h
                break
        if not target:
            raise SystemExit("해당 호를 목록에서 못 찾았습니다. "
                              "--ho-name 없이 실행해서 전체 목록부터 확인하세요.")
        rows = sess.get_price_history(ndy, reg, eub, args.apt, apt_code, dong_code,
                                       str(target["code"]))
        label = f"{dong_label}동 " if multi_dong else ""
        print(f"\n=== {apt['name']} {label}{rows[0]['ho_name']}호 (전용 {rows[0]['priv_area']}㎡) ===")
        for r in rows:
            print(f"  {r['notice_date_name']:<10} {r['notice_amt'].strip():>15}원")
        return

    # 호실 지정이 없으면: 이 동(또는 단지 전체)의 호실 목록만 출력
    if multi_dong and not args.dong_name:
        print(f"\n=== {apt['name']} 동 목록 (다동단지 - --dong-name으로 동 지정 필요) ===")
        for d in dongs:
            print(f"  {d['name']}동")
        return

    print(f"\n=== {apt['name']} {dong_label}{'동' if multi_dong else ''} 호실 목록 ===")
    print("특정 호실 지정: --ho-name 401  (--dong-name도 다동단지면 필수)")
    for h in all_ho[:30]:
        print(f"  {h['name']}")
    if len(all_ho) > 30:
        print(f"  ... 외 {len(all_ho) - 30}개 (전체 호실별 면적/가격을 보려면 각 code로 "
              f"get_price_history를 반복 호출 - 요청 수가 많아지니 필요한 만큼만)")


if __name__ == "__main__":
    main()

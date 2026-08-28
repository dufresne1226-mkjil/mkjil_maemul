#!/usr/bin/env python3
"""
재산세·종부세 계산기 (2026~2028년, 2026.08.03 발표 세제개편안 반영).

이 세션(2026-08)에서 propertytax.co.kr 계산엔진과 실제 납부액으로 교차검증한
계산 로직을 코드로 고정한 것. 목적은 "다음에 계산할 때마다 대화 전체를 다시
불러올" 필요를 없애는 것 — 매번 이 스크립트를 실행하면 끝난다.

핵심 규칙 (재산세 전부·종부세 세율표/공제는 propertytax.co.kr 엔진에 여러
가격대·주택수 조합을 직접 찔러서 실측 확인됨 - 아래 "실측 확인됨"이라고
안 적힌 항목만 미검증):

- 재산세: 1세대1주택이면 공정시장가액비율 45%(공시가격이 9억을 넘어도 계속
  45% 적용 - 9.73억·18~21억대 사례로 확인), 다주택이면 60%. 공시가격 9억
  이하 1세대1주택만 특례세율, 그 외엔 표준세율. 도시지역분(과세표준×0.14%)
  + 지방교육세(재산세 산출세액×20%).
- 재산세 세부담상한(105/110/130%, 전년도 공시가격 대비): `--prev-price`로
  전년도 공시가격을 넘기면 적용됨. 상한율 자체는 표준적으로 알려진 값을
  그대로 썼고, 이 세션에서 실측 대조는 안 했다(테스트한 사례들이 다 상한이
  안 걸리는 완만한 상승폭이었음) - 전년 대비 공시가격이 크게 뛴 케이스라면
  한 번 더 대조할 것.
- 종부세 기본공제: 2026년(현행법)은 1주택 12억 / 2주택이상 9억, 거주여부
  무관. 2027년부터 개편안 적용 - **1주택**: 실거주 14억 / 비거주 9억(단
  비거주 9억은 "표시값"일 뿐이고 실제로는 공시가격이 14억을 넘어야 과세가
  시작되는 히든 게이트가 있음, 넘는 순간부터 (공시가격-9억)×비율로 계산).
  **2주택 이상(주택수 무관)**: 2027년부터 **4억**으로 축소(9억에서 대폭
  하향 - 다주택 갭투자 억제 목적으로 보임). 전부 실측 확인됨.
- 종부세 공정시장가액비율: 2026년 60%(주택수 무관). 2027년 70%(주택수
  무관, 3주택 이상도 동일). 2028년 70%(1~2주택) / **80%(3주택 이상)**.
  전부 실측 확인됨.
- 종부세 세율표 - **연도별로 3개의 서로 다른 표가 있다** (이걸 놓치면
  1주택도 과세표준 6억 넘는 순간부터 세액이 틀어진다):
    - "현행"(2026년, 주택수 무관): 3억↓0.5% / 3~6억0.7% / 6~12억1.0% /
      12~25억1.3% / 25~50억1.5% / 50억↑2.0%
    - "중간이행"(2027년, 1~2주택 전용 - 3주택 이상은 2027년부터 곧바로
      통합세율표로 감): 3억↓0.5% / 3~6억0.7% / **6~12억1.3%** /
      **12~25억1.5%** / **25~50억2.0%** / 50억↑ 이후 구간은 이 세션에서
      정확히 못 풂(50~67억 구간 실측치와 안 맞음 - 2.0% 계속이라고 가정한
      근사치, 실제 과표가 50억을 넘는 초고가 물건이면 대조 필요).
    - "통합"(2028년 전부, 그리고 2027년의 3주택 이상): 3억↓0.5% /
      3~6억0.7% / 6~12억1.3% / **12~25억2.0%** / **25~50억3.0%** /
      50~94억4.0% / 94억↑5.0% (50억 이상 구간은 3주택 케이스로 25~50억
      3.0%까지만 실측, 그 위는 근거 메모 기반 미검증치).
- 세액공제(고령자·장기보유): **1세대1주택자 전용, 다주택자는 적용 안 됨**
  (실측 확인 - 스크립트가 house_count>1이면 자동으로 공제 0 처리함).
  고령자 60~65세20%/65~70세30%/70세+40%, 장기보유 5~10년20%/10~15년40%/
  15년+50%, 합산상한 80%. 비거주 1주택도 이 공제를 받는지는 개편안 확정
  전이라 불확실 - 기본은 적용해서 계산하되 필요하면 --age/--years를 생략.
- 종부세 이중과세조정(재산세액공제)은 정확한 시행령 공식을 못 풀어서
  근사치다. 1주택은 propertytax.co.kr 대비 5~10% 오차로 확인됐지만,
  다주택은 같은 근사식이 최대 45%까지 벌어지는 사례를 확인했다 - 다주택
  종부세 총액은 이 스크립트 값을 그대로 믿지 말고 반드시 대조할 것.
- 농어촌특별세 = (재산세 중복분 공제 후) 종부세 순액의 20%.

오피스텔 관련 (아파트와 다른 지점):
- 오피스텔은 "공동주택가격" 제도 대상이 아니라 토지분(개별공시지가)+건물분
  (건물신축가격기준액 기반 원가법)을 따로 합산하는 방식. 이 중 토지분은
  realtyprice.kr 개별공시지가 조회로 실측 가능(`land` 서브커맨드).
- 건물분은 위택스/이택스 "주택외건물시가표준액조회"가 소유자 주민등록번호를
  요구해서 제3자가 조회할 방법이 없다(이 세션에서 직접 확인). 그래서 이
  스크립트는 건물분을 추정하지 않는다 - 오피스텔은 실제 고지서에서 확인한
  시가표준액 총액을 `calc --price`로 직접 넣어서 계산할 것.

사용 예:
    # 아파트: 공시가격 자동조회 + 계산 (비거주 1세대1주택)
    python3 holding_tax_calc.py apt --sido 서울특별시 --sgg 구로구 --eub 신도림동 \\
        --apt 디큐브시티 --dong A --ho 4605 --house-count 1 --resident no

    # 오피스텔 토지분(개별공시지가)만 조회 - 대지지분은 별도로 알아내서 곱할 것
    python3 holding_tax_calc.py land --sido 서울특별시 --sgg 양천구 --eub 목동 --bun1 916

    # 시가표준액을 이미 알고 있을 때 (오피스텔, 또는 공시가격 자동조회 없이) 계산만
    python3 holding_tax_calc.py calc --price 1842400000 --house-count 1 --resident yes \\
        --age 64 --years 10

    # 2주택자 (전국 어디든, 조정대상지역 여부는 이 스크립트에서 결과에 영향 없음 -
    # 2027년 개편안 이후 2주택 이하는 조정지역 여부와 무관하게 동일 취급됨, 실측 확인)
    python3 holding_tax_calc.py calc --price 1500000000 --house-count 2

    # 향후 연도 공시가격 상승 시나리오 (연 5% 성장 가정)
    python3 holding_tax_calc.py calc --price 973000000 --house-count 1 --resident no --growth 0.05
"""
import argparse
import sys

import apt_gongsi_price as apt_mod


# ---------------------------------------------------------------------------
# 세법 상수/공식
# ---------------------------------------------------------------------------

STD_PROPERTY_BRACKETS = [
    (60_000_000, 0.001),
    (150_000_000, 0.0015),
    (300_000_000, 0.0025),
    (float("inf"), 0.004),
]
SPECIAL_PROPERTY_BRACKETS = [  # 1세대1주택 특례세율, 공시가격 9억 이하 전용
    (60_000_000, 0.0005),
    (150_000_000, 0.001),
    (300_000_000, 0.002),
    (float("inf"), 0.0035),
]
# 재산세 세부담상한 (전년도 공시가격 기준 구간별 상한율) - 표준 공지값, 이 세션
# 실측 대조는 안 됨.
PROPERTY_TAX_CAP_BRACKETS = [
    (300_000_000, 1.05),
    (600_000_000, 1.10),
    (float("inf"), 1.30),
]

# 종부세 세율표 3종 - 전부 propertytax.co.kr 엔진을 여러 가격/주택수 조합으로
# 찔러서 역산 확인함 (docstring 참고). 50억 초과 구간만 근사치.
CURRENT_JONGBU_BRACKETS = [  # 2026년, 주택수 무관
    (300_000_000, 0.005),
    (600_000_000, 0.007),
    (1_200_000_000, 0.010),
    (2_500_000_000, 0.013),
    (5_000_000_000, 0.015),
    (float("inf"), 0.020),
]
MID12_JONGBU_BRACKETS = [  # 2027년, 1~2주택 전용 (3주택+는 UNIFIED로 직행)
    (300_000_000, 0.005),
    (600_000_000, 0.007),
    (1_200_000_000, 0.013),
    (2_500_000_000, 0.015),
    (5_000_000_000, 0.020),
    (float("inf"), 0.020),  # 50억 초과 구간 근사치(미검증) - 2.0% 계속으로 가정
]
UNIFIED_JONGBU_BRACKETS = [  # 2028년 전체 + 2027년의 3주택 이상
    (300_000_000, 0.005),
    (600_000_000, 0.007),
    (1_200_000_000, 0.013),
    (2_500_000_000, 0.020),
    (5_000_000_000, 0.030),
    (9_400_000_000, 0.040),  # 94억 경계는 미검증 (근거: project_mokdong_yunseul_xi_gap 메모)
    (float("inf"), 0.050),
]


def _bracket_tax(taxable, brackets):
    """누진 구간별 세액 계산 (구간마다 그 구간 몫만 해당 세율로)."""
    tax = 0.0
    prev = 0
    for cap, rate in brackets:
        if taxable > prev:
            tax += (min(taxable, cap) - prev) * rate
        prev = cap
        if taxable <= cap:
            break
    return tax


def property_tax(price, house_count, prev_price=None):
    """
    재산세 계산. price=시가표준액(원). house_count=세대 기준 전국 주택 수.
    prev_price(전년도 공시가격)를 주면 세부담상한(105/110/130%)을 적용한다
    - 상한액은 "전년도 공시가격 기준으로 이 스크립트가 계산한 재산세"에
      상한율을 곱해서 근사한다(실제 전년도 고지액과 다를 수 있음).
    """
    is_one_house = house_count == 1
    fair_ratio = 0.45 if is_one_house else 0.60
    taxable = price * fair_ratio
    if is_one_house and price <= 900_000_000:
        base = _bracket_tax(taxable, SPECIAL_PROPERTY_BRACKETS)
    else:
        base = _bracket_tax(taxable, STD_PROPERTY_BRACKETS)
    local_edu = base * 0.20
    city_plan = taxable * 0.0014
    total = base + local_edu + city_plan
    capped = False

    if prev_price is not None:
        prev = property_tax(prev_price, house_count)  # prev_price 기준 세부담상한은 재귀 안 함(무한루프 방지)
        cap_rate = next(rate for cap, rate in PROPERTY_TAX_CAP_BRACKETS if price <= cap)
        cap_amount = prev["total"] * cap_rate
        if total > cap_amount:
            total = cap_amount
            capped = True

    return dict(taxable=taxable, base_tax=base, local_edu_tax=local_edu,
                city_plan_tax=city_plan, total=total, fair_ratio=fair_ratio, capped=capped)


def comprehensive_tax(price, year, house_count, is_resident, age=None, holding_years=None):
    """
    종부세 계산. year: 2026/2027/2028(그 이후는 2028과 동일 취급).
    house_count: 세대 기준 전국 주택 수 (1이면 1세대1주택 특례 전부 적용).

    재산세액공제(이중과세조정)는 "종부세 초과분에 재산세 fairRatio를 곱한
    가상의 재산세 과세표준"에 재산세율표를 적용한 값으로 근사한다.
    propertytax.co.kr 실측치와 대조한 결과 1주택은 5~10% 오차, 다주택은
    최대 45%까지 벌어지는 사례가 있었다(정확한 시행령 공식을 이 세션에서
    다 못 풀어냈다) - 종부세 총액이 큰 물건일수록, 특히 다주택일수록 이
    스크립트 값을 그대로 믿지 말고 propertytax.co.kr 같은 데서 대조할 것.
    """
    is_one_house = house_count == 1

    if year <= 2026:
        fair_ratio, brackets = 0.60, CURRENT_JONGBU_BRACKETS
        deduction, gate = (1_200_000_000, None) if is_one_house else (900_000_000, None)
    else:
        if is_one_house:
            fair_ratio = 0.70
            brackets = MID12_JONGBU_BRACKETS if year == 2027 else UNIFIED_JONGBU_BRACKETS
            if is_resident:
                deduction, gate = 1_400_000_000, None
            else:
                # 표시상 공제는 9억이지만 실제로는 14억을 넘어야 과세가 시작된다
                deduction, gate = 900_000_000, 1_400_000_000
        else:
            deduction, gate = 400_000_000, None
            if house_count >= 3:
                # 3주택 이상은 2027년부터 곧바로 통합세율표+80%(2028) 비율 적용
                fair_ratio = 0.70 if year == 2027 else 0.80
                brackets = UNIFIED_JONGBU_BRACKETS
            else:
                fair_ratio = 0.70
                brackets = MID12_JONGBU_BRACKETS if year == 2027 else UNIFIED_JONGBU_BRACKETS

    if not is_one_house and year <= 2026 and house_count >= 3:
        print("[!] 경고: 3주택 이상의 2026년(현행법) 종부세 세율표는 이 세션에서 "
              "실측 대조가 안 됐습니다 - 2주택 세율표로 근사 계산했고 실제보다 "
              "낮게 나올 가능성이 있습니다.", file=sys.stderr)

    excess = 0 if (gate is not None and price <= gate) else max(0, price - deduction)
    taxable = excess * fair_ratio
    gross = _bracket_tax(taxable, brackets)

    # 재산세율표 기반 계산식을 여러 버전 시도했지만 최대 36% 오차가 났다. 대신
    # propertytax.co.kr 실측치에서 propertyCredit/gross_tax 비율을 직접 뽑아서
    # 상수로 쓴다 - 근거가 되는 시행령 조문을 못 찾았고 순전히 경험적 상수다.
    # 1주택은 5개 사례(2026·2027, 여러 가격대)에서 이 비율이 0.32 근처로 꽤
    # 안정적이라 오차 1% 이내로 맞는다. 다주택은 이 비율이 0.13~0.30까지
    # 흔들려서(주택수·가격대가 커질수록 비율이 낮아지는 경향은 보이지만
    # 깔끔한 관계식을 못 찾았다) 0.20을 썼는데 케이스에 따라 오차가 40%까지도
    # 날 수 있다 - 다주택 종부세는 이 스크립트 값을 절대 그대로 믿지 말 것.
    property_credit = gross * (0.32 if is_one_house else 0.20)

    credit_rate = 0.0
    if is_one_house:  # 세액공제는 1세대1주택자 전용 (다주택자는 미적용, 실측 확인)
        if age is not None:
            credit_rate += 0.40 if age >= 70 else 0.30 if age >= 65 else 0.20 if age >= 60 else 0.0
        if holding_years is not None:
            credit_rate += 0.50 if holding_years >= 15 else 0.40 if holding_years >= 10 else \
                0.20 if holding_years >= 5 else 0.0
        credit_rate = min(credit_rate, 0.80)

    net_before_credit = max(0.0, gross - property_credit)
    net_tax = net_before_credit * (1 - credit_rate)
    farm_tax = net_tax * 0.20
    total = net_tax + farm_tax
    return dict(deduction=deduction, fair_ratio=fair_ratio, taxable=taxable, gross_tax=gross,
                property_credit=property_credit, credit_rate=credit_rate, net_tax=net_tax,
                farm_tax=farm_tax, total=total)


def full_calc(base_price, house_count, is_resident, age=None, holding_years=None, growth=0.0,
              prev_price=None):
    """2026/2027/2028년분을 한 번에 계산. growth: 연간 공시가격 상승률 가정."""
    out = {}
    for offset, year in enumerate((2026, 2027, 2028)):
        price = base_price * (1 + growth) ** offset
        pp = prev_price if offset == 0 else base_price * (1 + growth) ** (offset - 1)
        pt = property_tax(price, house_count, prev_price=pp)
        ct = comprehensive_tax(price, year, house_count, is_resident, age, holding_years)
        out[year] = dict(price=price, property=pt, comprehensive=ct, total=pt["total"] + ct["total"])
    return out


def print_calc(result):
    for year, row in result.items():
        pt, ct = row["property"], row["comprehensive"]
        cap_note = " (세부담상한 적용됨)" if pt.get("capped") else ""
        print(f"\n=== {year}년 (공시가격 {row['price']:,.0f}원) ===")
        print(f"  재산세: {pt['total']:,.0f}원{cap_note} "
              f"(공정시장가액비율 {pt['fair_ratio']*100:.0f}%, 과세표준 {pt['taxable']:,.0f}원)")
        print(f"  종부세: {ct['total']:,.0f}원 "
              f"(공제 {ct['deduction']:,.0f}원, 공정시장가액비율 {ct['fair_ratio']*100:.0f}%, "
              f"세액공제 {ct['credit_rate']*100:.0f}%)")
        print(f"  합계  : {row['total']:,.0f}원")


# ---------------------------------------------------------------------------
# 오피스텔 토지분 - 개별공시지가 조회 (realtyprice.kr)
# ---------------------------------------------------------------------------

def get_individual_land_price(sess, sido_name, sgg_name, eub_name, bun1, bun2="0000", san=None):
    """
    개별공시지가(원/㎡) 연도별 이력. realtyprice.kr의 gsindividual 검색 API 사용.
    san 파라미터는 왜인지 '1'을 넣어야 나오는 케이스가 확인됐다(정상적으로는
    산지번 여부를 뜻하는 필드인데 목동 916 같은 평지에서도 '1'이어야 결과가
    나왔다) - 원인 불명이라 san을 지정 안 하면 0과 1을 순서대로 다 시도한다.
    """
    r0 = sess.get_json("/notice/bjd/searchBjdApi.bjd", {"gubun": "", "gbn": "1"})
    sido = next((x for x in r0["model"]["list"] if sido_name in x["name"]), None)
    if not sido:
        raise SystemExit(f"시도 '{sido_name}' 못 찾음")
    r1 = sess.get_json("/notice/bjd/searchBjdApi.bjd",
                        {"gubun": "sgg", "gbn": "1", "sido": sido["code"]})
    sgg = next((x for x in r1["model"]["list"] if sgg_name in x["name"]), None)
    if not sgg:
        raise SystemExit(f"시군구 '{sgg_name}' 못 찾음")
    r2 = sess.get_json("/notice/bjd/searchBjdApi.bjd",
                        {"gubun": "eub", "gbn": "1", "sido": sido["code"], "sgg": sgg["code"]})
    eub = next((x for x in r2["model"]["list"] if eub_name in x["name"]), None)
    if not eub:
        raise SystemExit(f"읍면동 '{eub_name}' 못 찾음")

    san_candidates = [san] if san is not None else ["0", "1"]
    for sv in san_candidates:
        r3 = sess.get_json("/notice/search/gsiSearchListApi.search", {
            "page_no": "1", "gbn": "1", "year": "", "reg": sgg["code"], "eub": eub["code"],
            "san": sv, "bun1": str(bun1).zfill(4), "bun2": str(bun2).zfill(4),
            "road_code": "", "p_initialword": "", "build_bun1": "", "build_bun2": "",
            "tabGbn": "Text",
        })
        rows = r3["model"]["list"] or []
        if rows:
            return [dict(year=row["base_year"],
                         price_per_sqm=int(row["gakuka_w"].replace(",", "")),
                         addr=row["addr"]) for row in rows]
    return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_calc(args):
    result = full_calc(args.price, args.house_count, args.resident, args.age, args.years,
                        args.growth, args.prev_price)
    print_calc(result)


def cmd_land(args):
    sess = apt_mod.Session()
    print("[*] 세션 생성 + NetFunnel 게이트 통과 중...", file=sys.stderr)
    sess.bootstrap()
    rows = get_individual_land_price(sess, args.sido, args.sgg, args.eub, args.bun1, args.bun2)
    if not rows:
        raise SystemExit("개별공시지가 조회 결과 없음 (지번을 확인할 것)")
    print(f"\n=== 개별공시지가 ({rows[0]['addr']}) ===")
    for r in rows:
        print(f"  {r['year']}년  {r['price_per_sqm']:>15,}원/㎡")
    print("\n주의: 이건 ㎡당 땅값이다. 호실의 토지분 시가표준액을 구하려면"
          " 여기에 그 호실의 대지지분(㎡)을 곱해야 하는데, 대지지분은"
          " 등기부/집합건축물대장에만 나오고 이 스크립트로는 못 구한다.")


def cmd_apt(args):
    sess = apt_mod.Session()
    print("[*] 세션 생성 + NetFunnel 게이트 통과 중...", file=sys.stderr)
    sess.bootstrap()
    ndy = sess.latest_notice_date_year()
    reg, eub = apt_mod.resolve_bjd(sess, ndy, args.sido, args.sgg, args.eub)

    apts = sess.find_apt(ndy, reg, eub, args.apt)
    if not apts:
        raise SystemExit(f"단지 '{args.apt}' 검색 결과 없음")
    if len(apts) > 1:
        exact = [a for a in apts if a.get("COMMON_APT_NAME") == args.apt]
        if len(exact) == 1:
            apts = exact
        else:
            cands = "\n".join(f"  - {a['name']}  (COMMON_APT_NAME={a.get('COMMON_APT_NAME')!r})"
                               for a in apts)
            raise SystemExit(f"'{args.apt}' 검색 결과가 {len(apts)}건이라 특정 불가:\n{cands}")
    apt = apts[0]
    apt_code = str(apt["code"])

    dongs = sess.find_dong(ndy, reg, eub, args.apt, apt_code)
    if not dongs:
        raise SystemExit("동 목록을 가져오지 못했습니다.")
    multi_dong = len(dongs) > 1
    if args.dong and multi_dong:
        dong = next((d for d in dongs if d["name"] == args.dong or d["name"].endswith(args.dong)),
                    None)
        if not dong:
            raise SystemExit(f"동 '{args.dong}' 못 찾음. 후보: {[d['name'] for d in dongs]}")
        dong_code = str(dong["code"])
    else:
        dong_code = str(dongs[0]["code"])

    all_ho = sess.find_ho(ndy, reg, eub, args.apt, apt_code, dong_code)
    target = next((h for h in all_ho if args.ho in h["name"]), None)
    if not target:
        raise SystemExit(f"호 '{args.ho}' 못 찾음 (전체 {len(all_ho)}개 호실 중 매칭 없음)")

    rows = sess.get_price_history(ndy, reg, eub, args.apt, apt_code, dong_code, str(target["code"]))
    if not rows:
        raise SystemExit("공시가격 이력 조회 실패")
    latest_price = int(rows[0]["notice_amt"].strip().replace(",", ""))
    print(f"[*] {apt['name']} {rows[0]['ho_name']}호 전용 {rows[0]['priv_area']}㎡ "
          f"공시가격 {latest_price:,}원 ({rows[0]['notice_date_name']})", file=sys.stderr)

    result = full_calc(latest_price, args.house_count, args.resident, args.age, args.years,
                        args.growth, args.prev_price)
    print_calc(result)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def add_person_args(p):
        p.add_argument("--house-count", type=int, required=True,
                        help="세대 기준 전국 주택 수 (1이면 1세대1주택 특례 전부 적용)")
        p.add_argument("--resident", choices=["yes", "no"], default="no",
                        help="이 집에 실거주 중인지 (1주택일 때만 의미 있음, 종부세 기본공제가 달라짐)")
        p.add_argument("--age", type=int, default=None,
                        help="소유자 만 나이 (고령자공제용, 1주택자만 적용됨)")
        p.add_argument("--years", type=int, default=None,
                        help="보유기간(년) (장기보유공제용, 1주택자만 적용됨)")
        p.add_argument("--growth", type=float, default=0.0,
                        help="연간 공시가격 상승률 가정 (예: 0.05 = 연 5%%, 기본 0=동결)")
        p.add_argument("--prev-price", type=float, default=None,
                        help="전년도 공시가격(원) - 주면 재산세 세부담상한을 적용함")

    p_calc = sub.add_parser("calc", help="시가표준액을 알고 있을 때 바로 계산 (오피스텔 등)")
    p_calc.add_argument("--price", type=float, required=True, help="시가표준액(원)")
    add_person_args(p_calc)

    p_apt = sub.add_parser("apt", help="아파트: 공시가격 자동조회 + 계산")
    p_apt.add_argument("--sido", required=True)
    p_apt.add_argument("--sgg", required=True)
    p_apt.add_argument("--eub", required=True)
    p_apt.add_argument("--apt", required=True, help="단지명 (부분일치)")
    p_apt.add_argument("--dong", help="동 이름 (다동단지일 때 필요)")
    p_apt.add_argument("--ho", required=True, help="호 이름 (부분일치, 예: 4605)")
    add_person_args(p_apt)

    p_land = sub.add_parser("land", help="오피스텔 토지분: 개별공시지가(㎡당) 조회")
    p_land.add_argument("--sido", required=True)
    p_land.add_argument("--sgg", required=True)
    p_land.add_argument("--eub", required=True)
    p_land.add_argument("--bun1", required=True, help="지번 본번")
    p_land.add_argument("--bun2", default="0000", help="지번 부번 (없으면 0000)")

    args = ap.parse_args()
    if hasattr(args, "resident"):
        args.resident = args.resident == "yes"

    {"calc": cmd_calc, "apt": cmd_apt, "land": cmd_land}[args.command](args)


if __name__ == "__main__":
    main()

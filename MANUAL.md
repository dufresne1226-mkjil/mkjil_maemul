# 부동산 매물/가격 조회 매뉴얼

`/work/djchoi/Claude_ground/realestate/`에 있는 3개 스크립트 사용 설명서.
새 세션에서 이 폴더 작업을 다시 시작할 때는 이 파일부터 읽을 것 — 코드를
재작성할 필요 없이 바로 실행하면 됨.

---

## 빠른 참조 (TL;DR)

```bash
cd /work/djchoi/Claude_ground/realestate

# 아파트 단지 매물 (매매/전세/월세)
python3 pipeline.py "목동신시가지13단지"

# 빌라/다세대/원룸 등 (단지명 없는 매물, 지역 단위)
python3 pipeline.py --region-only --region <법정동코드> --type 주택

# 네이버 공유링크 → complexId/articleId 디코딩 (수동 검증용)
python3 decode_naver_links.py "https://naver.me/xxxxx"

# 오피스텔/상업용건물 기준시가 (국세청, 2020년 고시분까지만)
export NTS_OFFICETEL_KEY="발급받은_인증키"
python3 officetel_price.py --bjd <법정동코드> --building-name <건물명>
```

---

## 1. `pipeline.py` — 아파트 매물 조회 (매매/전세/월세)

네오넷 + 텐컴즈 + 한방(교차검증) 세 군데를 동시에 긁어서 중복 제거 후
매매/전세/월세로 나눠 평형 큰 순으로 출력한다.

### 캐시된 단지 (바로 실행 가능)
`목동신시가지11단지`, `목동신시가지12단지`, `목동신시가지13단지`, `목동힐스테이트`,
`래미안목동아델리체` (디큐브시티는 자동 resolve는 되지만 캐시엔 아직 없음)
(코드는 `pipeline.py`의 `COMPLEX_CACHE` 딕셔너리 참고/추가)

### 새 단지 실행
```bash
python3 pipeline.py "목동신시가지9단지"
```
자동으로 네오넷 검색 → `region_cd`/`complex_cd` resolve → 텐컴즈 aptNo resolve.
resolve 로그(`[neonet] resolved region_cd=... complex_cd=...` 등)를 그대로
`COMPLEX_CACHE`에 추가해두면 다음부터 즉시 실행됨.

### 옵션
| 옵션 | 설명 |
|---|---|
| `--region <코드>` | region_cd 직접 지정 (자동 resolve 안 될 때) |
| `--no-hanbang` | 한방 교차검증 생략 (더 빠름) |
| `--json out.json` | 원본 데이터 JSON 저장 |
| `--region-only --region <코드> --type <타입>` | 단지명 없는 매물유형 (아래 참고) |

### `--region-only` 모드 (빌라/다세대/원룸/상가 등)
```bash
python3 pipeline.py --region-only --region 1165010100 --type 주택   # 다세대/연립주택
python3 pipeline.py --region-only --region 1165010100 --type 원룸
```
텐컴즈만 지원. **유효한 `--type` 값**: 아파트/오피스텔/분양권/주택/토지/원룸/상가/
사무실/공장/재개발/건물. **"빌라"라는 카테고리는 없다** — 다세대/연립주택은 "주택".

⚠️ **`--region` 코드를 잘못 넣어도 에러 없이 전국 매물이 섞여서 조용히 반환된다.**
법정동코드는 절대 감으로 짜맞추지 말 것 (아래 "법정동코드 찾는 법" 참고).

⚠️ 법정동 자체가 넓어서 "역세권 도보 5분" 같은 정밀 필터링은 안 된다 — 매물명/
비고에 역 이름이 직접 언급된 것만 걸러보는 게 최선.

### 알아둘 것
- 동일 물건이 여러 날 재확인(refresh)된 건 최신 날짜 기준 하나로 합쳐짐
  (네오넷/텐컴즈 각각 내부적으로만 중복제거 — 두 소스에 같은 매물이 겹쳐 보이는 건
  정상이며 오히려 교차검증 역할)
- **막혀서 못 쓰는 곳**: 네이버부동산(전면 차단), 직방/KB부동산(SPA), 부동산포스
  (공개 검색 자체가 없음) → 이 파이프라인도 네이버가 보여주는 전체의 일부만 잡음

### 소스별 특징
| 소스 | 강점 | 약점 |
|---|---|---|
| 네오넷 (m.neonet.co.kr) | 매매/월세 풍부 | 전세 거의 없음 |
| 텐컴즈 (nhp.ten.co.kr) | 전세 포함 가장 풍부, 대형평형까지 | 첫 요청 느림 (ASP.NET 페이지네이션) |
| 한방 (karhanbang.com) | 깔끔한 JSON, 중개사 연락처 | 매물 수 적음 (보조 검증용) |

---

## 2. `decode_naver_links.py` — 네이버 공유링크 ID 디코딩 (수동 검증용, 자동조회 아님)

네이버부동산 매물 상세 API는 강한 봇 차단(`429 TOO_MANY_REQUESTS`, 쿠키/Referer
갖춰도 소용없음)이라 자동 대량조회는 불가능. 이 스크립트는 **사용자가 네이버에서
발견한 특정 매물의 공유링크**를 디코딩해서 ID만 뽑아준다.

```bash
pip install --break-system-packages --user lzstring   # 최초 1회만
python3 decode_naver_links.py "https://naver.me/xxxxx" "https://naver.me/yyyyy"
python3 decode_naver_links.py --file links.txt   # 한 줄에 링크 하나씩
```

**나오는 것**: `complexId`, `articleId`, `pyeongTypeNumber`(평형타입번호), 거래유형.
**안 나오는 것**: 가격·평형·동/층 (화면에서 직접 읽어서 알려줘야 함).

`complexId`는 네오넷 `complex_cd`·텐컴즈 `aptNo`·한방 `CD`와 지금까지 항상 일치함 —
교차검증에 바로 쓸 수 있음.

원리: `layer` 쿼리파라미터가 lz-string `compressToEncodedURIComponent` 포맷
(알파벳 `A-Za-z0-9+-`뿐, `/` 없음 — 식별 포인트).

---

## 3. `officetel_price.py` — 오피스텔/상업용건물 기준시가 (국세청, 매물망과 완전 별개)

data.go.kr 오픈API (`api.odcloud.kr`). 서비스키 필요.

```bash
export NTS_OFFICETEL_KEY="발급받은_인증키"
python3 officetel_price.py --raw                                    # 응답구조 확인
python3 officetel_price.py --bjd 1153010100                         # 그 동 전체
python3 officetel_price.py --bjd 1153010100 --building-name 팰러티움  # 건물명 필터
```

**서비스키 발급** (무료, data.go.kr 회원가입 후 즉시승인): ["국세청_상업용건물
오피스텔 기준시가_20260101"](https://www.data.go.kr/data/3036455/fileData.do) →
"활용신청" → 마이페이지에서 인증키 복사.

### ⚠️ 결정적 한계 (반드시 알고 쓸 것)
1. **2020년 고시분에서 멈춰있음.** 데이터셋 제목("20260101")과 달리 실제 API
   (Swagger: `infuser.odcloud.kr/oas/docs?namespace=3036455/v1`)는 2005~2020년
   스냅샷만 등록되어 있음 — 2021년 이후는 API로 못 가져옴 (파일은 갱신, API
   래퍼는 미갱신). **2026년 현재가 아님.**
2. **아파트/주상복합 주거용 유닛은 아예 안 나옴.** 세법상 "오피스텔·상업용건물"
   전용 데이터셋이고, 아파트는 별도의 "공동주택가격"으로 공시됨. (디큐브시티
   A/B동으로 실증 — 신도림동 3307건 중 0건.)
3. **재산세·종합부동산세 계산엔 이 값을 못 씀.** 기준시가는 국세(양도세·상속세·
   증여세) 전용이고, 지방세(재산세)는 "시가표준액"이라는 별도 값을 씀. 아래
   "세금 계산용 데이터" 참고.

### 기술 메모
- 서버사이드 필터(`cond`) 없음, 페이지당 최대 5000건(10000은 조용히 빈 응답).
- 데이터는 법정동코드 오름차순 정렬 확인됨 → 이진탐색(`perPage=1` 프로브 ~20회로
  시작 위치 찾기) 후 `perPage=5000`으로 벌크 fetch (`find_bjd_range`/`fetch_bjd`).
- 실제 필드명: `건물층구분코드, 고시가격, 고시일자, 공유면적, 번지, 법정동코드,
  상가건물동주소, 상가건물번호, 상가건물블록주소(=건물명), 상가건물층주소,
  상가건물호주소, 상가종류코드, 전용면적, 특수지코드, 호`
- 호실 형식 특이사항: 단일건물은 `상가건물동주소="1(단일)"` + `상가건물호주소`에
  "동-호"가 합쳐져 옴 (예: `"102-1001"` = 102동 1001호). 다동단지는 건물명 자체에
  동번호가 붙어 나옴 (예: `"목동현대하이페리온2205동"`).

---

## 매일 자동 갱신되는 웹 리포트 (GitHub Pages) — 이게 메인

**https://dufresne1226-mkjil.github.io/mkjil_maemul/**

GitHub Actions가 매일 00:00 UTC(=한국시간 09:00)에 `build_report.py`를 실행해서
6개 단지 최신 매물을 다시 긁고, `docs/index.html`을 갱신 → 커밋 → Pages 자동
배포한다. 사람이 아무것도 안 해도 됨 — 이 링크만 새로고침하면 항상 최신.

- 워크플로우: `.github/workflows/daily-refresh.yml`
- 빌드 스크립트: `build_report.py` (webapp/report.html을 템플릿으로 써서
  docs/index.html을 만듦 — pipeline.py의 dedupe_by_unit/to_pyeong 재사용)
- 저장소: `dufresne1226-mkjil/mkjil_maemul` (**Public** — GitHub Pages 무료플랜은
  private 저장소에서 안 됨, 그래서 매매 시도 끝에 public으로 전환함. 매물
  데이터엔 개인정보 없어서 문제없다고 판단)
- 수동으로 한 번 더 돌리고 싶으면: repo Actions 탭에서 "Daily listing refresh"
  워크플로우 → "Run workflow" 버튼 (workflow_dispatch로 설정해둠)

**클라우드 라우틴(`/schedule`)은 이제 안 씀** — 네트워크가 막혀서 실패했던 것
(위 "매일 자동 갱신(클라우드 스케줄) 시도했으나 실패" 항목 참고). 그 라우틴은
`enabled:false`로 꺼둔 채 남아있음 (trig_01Qiktzd3H7jqCG9pziy9QLD) — 안 쓰면
https://claude.ai/code/routines 에서 삭제해도 됨.

## 예전 방식: 수동 Artifact — `webapp/report.html`

pipeline.py 결과를 필터링 가능한 웹페이지로 발행해둔 것. **실시간 조회 아님** —
Artifact는 외부 네트워크 요청이 CSP로 막혀있어서 네오넷/텐컴즈를 직접 못 부른다.
그래서 방식은: 여기서 pipeline.py를 돌려 JSON을 만들고, 그 JSON을 페이지에
박아넣은 다음 발행 → 사용자는 그 페이지에서 단지 드롭다운/거래유형/동 번호로
**이미 가져온 데이터 안에서만** 필터링한다.

현재 URL: https://claude.ai/code/artifact/96417ce2-00d3-48d1-8282-c3145cbf7872
(같은 URL 유지하려면 `Artifact` 툴 호출 시 반드시 `url` 파라미터에 이 주소를 그대로 넣을 것 —
안 넣으면 새 아티팩트가 생겨버림)

**갱신 절차** (단지 추가/데이터 새로고침할 때):
```bash
cd /work/djchoi/Claude_ground/realestate
# 1. 각 단지 JSON 새로 받기
python3 pipeline.py "<단지명>" --json /tmp/data_<이름>.json

# 2. 아래 패턴으로 여러 단지 JSON을 하나로 합쳐서 webapp/report.html의
#    <script id="listing-data" type="application/json">...</script> 내용을 교체
#    (dedupe_by_unit/to_pyeong 재사용 - pipeline.py 참고, 지금까지 쓴 스크립트가 대화 히스토리에 있음)

# 3. 새 단지면 report.html의 JS 안 SUB_TEXT 객체에 "단지명": "설명" 한 줄 추가

# 4. Artifact 툴로 같은 url 파라미터 넣어서 재발행
```
현재 포함된 6개 단지: 목동신시가지11/12/13단지, 디큐브시티, 목동힐스테이트,
래미안목동아델리체.

### ⚠️ 매일 자동 갱신(클라우드 스케줄) 시도했으나 실패 — 재시도하지 말 것

`/schedule`로 클라우드 라우틴을 만들어서 매일 아침 9시에 자동 갱신되게 시도했다.
GitHub 저장소 연결, App 설치, 라우틴 생성까지는 다 됐는데 **실제 스크래핑이
100% 실패**한다 — 클라우드 샌드박스(CCR)가 프록시를 통해서만 외부로 나가는데,
그 프록시 허용목록에 anthropic.com/npm/pypi 같은 것만 있고 네오넷/텐컴즈/한방은
아예 없다. 텐컴즈는 403, 네오넷/한방은 연결 자체가 끊김(curl exit 56) — 실제
`RemoteTrigger run` + `get_run_log`로 직접 확인함. 코드 문제가 아니라 **플랫폼
차원의 샌드박스 보안 정책**이라 우회 불가능. 라우틴은 만들어놓고 `enabled:false`로
꺼뒀다(레포: `dufresne1226-mkjil/mkjil_maemul`, private).

**다음에 이 요청이 다시 오면**: 클라우드 자동화는 안 된다고 바로 답하고, 대안으로
① 사용자가 실제로 관리하는 컴퓨터(본인 PC, 라즈베리파이, 개인 VPS 등)에 로컬 cron
등록 (이런 머신은 이 샌드박스 프록시 제약이 없음 — cron 명령어는 내가 짜줄 수 있지만
설치/실행은 사용자가 직접 해야 함), 또는 ② 지금처럼 요청할 때마다 이 세션에서
수동으로 `pipeline.py` 돌려서 갱신하는 방식 두 가지뿐이다.

## 세금 계산용 데이터 (재산세/종부세) — 스크립트 미완성, 수동 조회 경로만 확보

`officetel_price.py`(국세청 기준시가)는 재산세·종부세엔 안 맞는다는 게 확인됐음.
실제로 필요한 것:

| 유형 | 필요한 값 | 조회처 |
|---|---|---|
| 아파트/공동주택 | 공동주택가격 | [부동산공시가격알리미 - 공동주택가격 열람](https://www.realtyprice.kr/notice/town/nfSiteLink.htm) (수동 조회, API는 VWorld 소관이라 미착수) |
| 오피스텔 (업무용/주거용 공통) | 시가표준액 (건축물+토지 산정공식값) | [위택스](https://www.wetax.go.kr) → 지방세정보 → 시가표준액 조회 (수동, 산정공식 자동화 안 함) |
| 계산 자체 | 재산세·종부세 세액 | [부동산계산기.com 보유세 계산기](https://xn--989a00af8jnslv3dba.com/보유세) — 공시가격만 입력하면 세액 계산 |

VWorld API로 공동주택가격을 자동화하고 싶으면 다음 세션에서 이어서 진행 —
data.go.kr과는 다른 인증키 체계라 별도 가입 필요.

---

## 법정동코드 찾는 법 (공통, 감으로 짜맞추지 말 것)

```bash
curl -s https://raw.githubusercontent.com/WooilJeong/PublicDataReader/main/PublicDataReader/raw/code_bdong.json -o code_bdong.json
python3 -c "
import json
d = json.load(open('code_bdong.json', encoding='utf-8'))
n = len(d['법정동코드'])
for i in range(n):
    if d['시군구명'].get(str(i)) == '<구 이름>' and d['읍면동명'].get(str(i)) == '<동 이름>':
        print(d['법정동코드'][str(i)], d['말소일자'].get(str(i)))
"
```
`말소일자`가 `nan`이면 현재 유효한 코드.

---

## data.go.kr 오픈API 공통 팁 (officetel_price.py 외에 다른 데이터셋 쓸 때도 적용)

1. **데이터셋 페이지의 `publicDataDetailPk`(uddi) 값을 그대로 믿지 말 것.**
   Swagger 문서(`https://infuser.odcloud.kr/oas/docs?namespace=<데이터셋ID>/v1`)에서
   실제 경로를 확인할 것 — 잘못된 uddi로 요청해도 "인증키 필수" 에러가 떠서 URL이
   맞는 것처럼 착각하기 쉬움. **진짜 키로 "등록되지 않은 서비스" 에러가 뜨면
   UUID가 틀린 것.**
2. 한 데이터셋에 연도/버전별로 여러 uddi가 등록돼 있을 수 있음 — 라벨이 같아도
   하나는 비어있고(`totalCount:0`) 하나는 채워져 있을 수 있으니 실제 샘플로 확인.
3. 파일 다운로드 링크(`fileDownload.do`)가 가끔 완전히 엉뚱한 내용을 반환하는 버그가
   있음(정부 쪽 첨부파일 등록 오류) — 이럴 땐 OpenAPI 경로로 우회.
4. 인증키는 "Encoding"(이미 URL인코딩됨, `%2B`/`%3D` 등 포함) 형태로 받으면
   재인코딩하지 말고 그대로 URL에 붙일 것 — 재인코딩하면 이중인코딩으로 깨짐.

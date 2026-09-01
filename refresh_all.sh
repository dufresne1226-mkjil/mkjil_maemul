#!/usr/bin/env bash
# 단지별 매매/전세/월세(docs/index.html) + 신도림 전세/월세 시세(docs/sindorim.html)
# 두 페이지를 모두 4소스(NEONET+텐컴즈+asil+부동산써브)로 갱신하고 커밋·푸시·배포한다.
# crontab에서 매일 1회 실행. (refresh_sindorim.sh 를 대체 - 이제 두 페이지 다 여기서.)
#
# 이 머신 IP는 써브(serve.co.kr)를 통과하므로 4소스가 전부 잡힌다. GitHub Actions
# 데이터센터 IP는 써브에 막혀서, GH는 배포만 맡고 빌드는 여기(로컬 크론)서 한다.
#
# 필요: 같은 폴더에 .push_token (repo+workflow 스코프의 GitHub PAT 한 줄).
set -uo pipefail

REPO="/work/djchoi/Claude_ground/realestate"
OWNER="dufresne1226-mkjil/mkjil_maemul"
cd "$REPO" || exit 1
export TZ=Asia/Seoul

TOKEN="$(tr -d '[:space:]' < "$REPO/.push_token" 2>/dev/null)"
if [ -z "$TOKEN" ]; then
  echo "$(date '+%F %T') ERROR: $REPO/.push_token 없음 (PAT 한 줄 넣어주세요)"; exit 1
fi
REMOTE="https://dufresne1226-mkjil:${TOKEN}@github.com/${OWNER}.git"

commit_docs() {  # 변경분이 있으면 커밋, 있으면 0 / 없으면 1 반환
  git add docs/index.html docs/sindorim.html
  git diff --cached --quiet && return 1
  git -c user.name="listing-cron" -c user.email="cron@local" \
      commit -q -m "4-source refresh $(date '+%F %T')"
  return 0
}

# 최신 main 반영 (혹시 손으로 올린 커밋 등)
git pull --no-rebase -q "$REMOTE" main 2>/dev/null || git pull --no-rebase -q origin main 2>/dev/null || true

# 4소스 재생성. 하나가 실패해도(네트워크/써브 게이트) 나머지는 갱신되게 각각 진행.
# 두 스크립트 모두 0건이면 스스로 exit 1 하여 기존 파일을 덮지 않는다.
python3 build_report.py    || echo "$(date '+%F %T') WARN: build_report.py 실패 - index.html 기존 유지"
python3 sindorim_report.py || echo "$(date '+%F %T') WARN: sindorim_report.py 실패 - sindorim.html 기존 유지"

if ! commit_docs; then
  echo "$(date '+%F %T') 변동 없음 - 스킵"; exit 0
fi

# 푸시. 이 크론이 docs의 유일한 기록자라 충돌은 드물지만, 원격이 앞서면
# 원격 위로 재생성해 다시 올린다(리베이스 충돌 회피).
if ! git push -q "$REMOTE" main 2>/dev/null; then
  echo "$(date '+%F %T') push 거부 - 원격 반영 후 재생성 재시도"
  git fetch -q "$REMOTE" main 2>/dev/null || true
  git reset --hard -q FETCH_HEAD
  python3 build_report.py    || true
  python3 sindorim_report.py || true
  commit_docs || true
  git push -q "$REMOTE" main 2>/dev/null || { echo "$(date '+%F %T') ERROR: 재푸시 실패"; exit 1; }
fi

# docs 푸시는 워크플로 paths-ignore라 안 깨우므로 명시적으로 배포 트리거.
curl -s -o /dev/null -X POST -H "Authorization: token ${TOKEN}" \
  "https://api.github.com/repos/${OWNER}/actions/workflows/daily-refresh.yml/dispatches" \
  -d '{"ref":"main"}' && echo "$(date '+%F %T') 갱신+배포 트리거 완료 (index+sindorim 4소스)"

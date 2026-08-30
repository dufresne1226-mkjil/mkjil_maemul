#!/usr/bin/env bash
# 신도림 전세/월세 페이지(docs/sindorim.html)를 4소스(asil+써브+NEONET+텐컴즈)로
# 갱신하고 커밋·푸시·배포. crontab에서 매일 실행한다.
#
# 이 머신의 IP는 써브(serve.co.kr)를 통과하므로 4소스 전부 잡힌다 (GitHub
# Actions 데이터센터 IP는 써브에 막혀서 자동 워크플로로는 못 한다 - 그래서 크론).
#
# 필요: 같은 폴더에 .push_token 파일 (repo+workflow 스코프의 GitHub PAT 한 줄).
set -uo pipefail

REPO="/work/djchoi/Claude_ground/realestate"
OWNER="dufresne1226-mkjil/mkjil_maemul"
cd "$REPO" || exit 1

TOKEN="$(tr -d '[:space:]' < "$REPO/.push_token" 2>/dev/null)"
if [ -z "$TOKEN" ]; then
  echo "$(date '+%F %T') ERROR: $REPO/.push_token 없음 (PAT 한 줄 넣어주세요)"; exit 1
fi
REMOTE="https://dufresne1226-mkjil:${TOKEN}@github.com/${OWNER}.git"

# 최신 main 반영 (자동 워크플로가 올린 index.html 등)
git pull --no-rebase -q "$REMOTE" main 2>/dev/null || git pull --no-rebase -q origin main 2>/dev/null || true

# 4소스 재생성 (이 머신 IP라 써브 포함)
if ! python3 sindorim_report.py; then
  echo "$(date '+%F %T') ERROR: sindorim_report.py 실패"; exit 1
fi

if git diff --quiet -- docs/sindorim.html; then
  echo "$(date '+%F %T') 변동 없음 - 스킵"; exit 0
fi

git add docs/sindorim.html
git -c user.name="sindorim-cron" -c user.email="cron@local" \
    commit -q -m "sindorim 4-source refresh $(date '+%F')"

# 푸시 (혹시 원격이 앞서면 한 번 rebase 재시도)
if ! git push -q "$REMOTE" main 2>/dev/null; then
  git pull --no-rebase -q "$REMOTE" main 2>/dev/null || true
  python3 sindorim_report.py && git add docs/sindorim.html \
    && git commit -q --amend --no-edit && git push -q "$REMOTE" main
fi

# 배포 트리거 (docs-only 푸시는 워크플로를 안 깨우므로 명시적으로 dispatch)
curl -s -o /dev/null -X POST -H "Authorization: token ${TOKEN}" \
  "https://api.github.com/repos/${OWNER}/actions/workflows/daily-refresh.yml/dispatches" \
  -d '{"ref":"main"}' && echo "$(date '+%F %T') 갱신+배포 트리거 완료"

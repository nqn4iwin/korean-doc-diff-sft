#!/usr/bin/env bash
# 2패스 앞 60건 중 저장에 실패한 16건을 다시 부른다 -- 손으로 쓴 것이다. 1패스의 run.sh와 달리 plan.py가 만들지 않았다
# (계획은 `chain.py --plan-out`이 세웠다).
#
# 사슬: 원문 --v1.2(지시1)--> 중간본 --v1.2(지시2)--> 최종본. 중간본은 1패스가 이미
# 만들어 둔 것을 읽고, 이 실행은 2차 지시와 셜록 왕복만 부른다.
#
# `--skip-saved`가 runs/에 이미 남은 (문서, 블록)을 빼므로, 슬라이스는 그대로 :60이어도
# 실제로 호출되는 것은 덮어써져 사라진 16건뿐이다.
#
# 시간 초과 900초와 동시 요청 8은 1패스와 같은 값이다 -- 2026-08-13에 기본값 180초로
# 227건을 TimeoutError로 잃었고, 동시 요청은 많을수록 응답이 늦어졌다.
set -u
cd "$(dirname "$0")/../../../.." || exit 1
export SOLAR_TIMEOUT_SECONDS=900

# 출력을 파일로도 남긴다. runs/는 .gitignore에 있으므로 저장소에 들어가지 않는다.
mkdir -p training_data/mutate/runs
LOG="training_data/mutate/runs/pass2_recover16.log"

python3 -u training_data/mutate/chain.py \
  --plan "training_data/mutate/plans/pass2/plan.json" \
  --slice :60 --skip-saved --concurrency 8 2>&1 | tee "$LOG"

echo
echo "기록: $LOG"

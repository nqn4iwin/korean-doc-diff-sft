#!/usr/bin/env bash
# training_data/mutate/plan.py가 만들었다. 손으로 고치지 말고 다시 만든다.
#
# 1패스 -- 계획 전체에 v1.2를 한 번 건다. `generate.py`는 수정하지 않은 것이고,
# 계획에 실린 `instruct2`는 이 패스에서 쓰이지 않는다(2패스가 읽는다).
#
# 시간 초과 기본값 180초는 1,000건 넘는 실행에 안 맞는다 -- 2026-08-13에 227건을
# TimeoutError로 잃었다. 동시 요청도 16에서 8로 내린다(많을수록 응답이 늦어졌다).
set -u
cd "$(dirname "$0")/../../../../.." || exit 1
export SOLAR_TIMEOUT_SECONDS=900

python3 -u training_data/mutate/generate.py "data/raw_collection/mafra_rd_guideline_pair/after_2025.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/smoke/mafra_rd_guideline_pair__after_2025.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/me_environment_tech_guideline_pair/after_2024.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/smoke/me_environment_tech_guideline_pair__after_2024.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/mohw_health_rd_guideline_pair/after_2023.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/smoke/mohw_health_rd_guideline_pair__after_2023.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/molit_rd_guideline_pair/after_2024.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/smoke/molit_rd_guideline_pair__after_2024.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/msit_science_rd_guideline_pair/after_2023.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/smoke/msit_science_rd_guideline_pair__after_2023.json" --concurrency 8

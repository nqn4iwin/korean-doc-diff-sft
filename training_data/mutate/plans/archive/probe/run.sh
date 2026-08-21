#!/usr/bin/env bash
# 본 생성 전 탐침 100건. 관측이 0~2건뿐인 지시에 몰아서 뽑았고 계열 7개에 흩었다.
# 보는 것: 지시별 BM5/BM5a -- 셜록이 그 지시를 우리가 붙인 이름으로 읽는가.
# 2026-08-12에 (절차·요건, 늘었다)가 0/12였던 것이 이 검사로 잡히는 종류의 실패다.
set -u
cd "$(dirname "$0")/../../../../.." || exit 1

python3 training_data/mutate/generate.py "data/raw_collection/ftc_game_terms/mobile_2017.converted.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/probe/mobile_2017.converted.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/ftc_game_terms/mobile_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/probe/mobile_2024.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/ftc_game_terms/online_2013.converted.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/probe/online_2013.converted.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/ftc_game_terms/online_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/probe/online_2024.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/ftc_gift_certificate_terms/2020_standard_terms.converted.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/probe/2020_standard_terms.converted.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/ftc_gift_certificate_terms/2024_standard_terms.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/probe/2024_standard_terms.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/mof_rd_regulation_pair/after_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/probe/after_2024.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/mof_rd_regulation_pair/before_2022.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/probe/before_2022.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/mois_opendata_eval_manual/2021_eval_manual.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/probe/2021_eval_manual.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/mss_rd_guideline_pair/after_2025.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/probe/after_2025.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/mss_rd_guideline_pair/before_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/probe/before_2024.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/regional_industry_guideline_pair/after_2026.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/probe/after_2026.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/regional_industry_guideline_pair/before_2023.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/probe/before_2023.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/tips_operating_guideline_pair/after_2023_partial_revision.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/probe/after_2023_partial_revision.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/tips_operating_guideline_pair/before_2022.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/archive/probe/before_2022.json" --concurrency 16

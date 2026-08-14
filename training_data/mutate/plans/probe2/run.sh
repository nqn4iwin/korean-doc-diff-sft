#!/usr/bin/env bash
# 재탐침: 쪼갠 이름이 맞는지 본다. 같은 조항에 늘었다·줄었다를 둘 다 걸어
# **방향 지시만 다른 짝 비교**가 되게 했다 -- 셜록이 우리 지시를 따르는지,
# 아니면 조항 내용이 방향을 정해버리는지(A가 든 `5억원 당 1명`)를 가르기 위해서다.
set -u
cd "$(dirname "$0")/../../../.." || exit 1

python3 training_data/mutate/generate.py "data/raw_collection/ftc_game_terms/mobile_2017.converted.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe2/ftc_game_terms__mobile_2017.converted.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/ftc_game_terms/mobile_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe2/ftc_game_terms__mobile_2024.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/ftc_game_terms/online_2013.converted.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe2/ftc_game_terms__online_2013.converted.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/ftc_game_terms/online_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe2/ftc_game_terms__online_2024.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/ftc_gift_certificate_terms/2020_standard_terms.converted.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe2/ftc_gift_certificate_terms__2020_standard_terms.converted.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/ftc_gift_certificate_terms/2024_standard_terms.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe2/ftc_gift_certificate_terms__2024_standard_terms.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/mof_rd_regulation_pair/after_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe2/mof_rd_regulation_pair__after_2024.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/mof_rd_regulation_pair/before_2022.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe2/mof_rd_regulation_pair__before_2022.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/mss_rd_guideline_pair/after_2025.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe2/mss_rd_guideline_pair__after_2025.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/mss_rd_guideline_pair/before_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe2/mss_rd_guideline_pair__before_2024.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/regional_industry_guideline_pair/after_2026.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe2/regional_industry_guideline_pair__after_2026.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/regional_industry_guideline_pair/before_2023.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe2/regional_industry_guideline_pair__before_2023.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/tips_operating_guideline_pair/after_2023_partial_revision.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe2/tips_operating_guideline_pair__after_2023_partial_revision.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/tips_operating_guideline_pair/before_2022.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe2/tips_operating_guideline_pair__before_2022.json" --concurrency 16

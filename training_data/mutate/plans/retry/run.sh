#!/usr/bin/env bash
# 2026-08-13 본 생성에서 **읽기 시간 초과로 빠진 215건**만 다시 뽑는다.
# 계획을 밖에서 받으므로 같은 조항·같은 지시가 그대로 다시 돈다.
#
# 지난 실행이 기본값 180초에서 끊겼다(생성 114건·판정 97건). 그래서 둘을 바꿨다:
#   - 시간 초과 180초 -> 900초
#   - 동시 요청 16 -> 8  (동시 요청이 많을수록 응답이 늦어져 초과가 났다)
set -u
cd "$(dirname "$0")/../../../.." || exit 1
export SOLAR_TIMEOUT_SECONDS=900

python3 training_data/mutate/generate.py "data/raw_collection/ftc_game_terms/mobile_2017.converted.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/retry/ftc_game_terms__mobile_2017.converted.json" --concurrency 8
python3 training_data/mutate/generate.py "data/raw_collection/ftc_game_terms/mobile_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/retry/ftc_game_terms__mobile_2024.json" --concurrency 8
python3 training_data/mutate/generate.py "data/raw_collection/ftc_game_terms/online_2013.converted.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/retry/ftc_game_terms__online_2013.converted.json" --concurrency 8
python3 training_data/mutate/generate.py "data/raw_collection/ftc_game_terms/online_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/retry/ftc_game_terms__online_2024.json" --concurrency 8
python3 training_data/mutate/generate.py "data/raw_collection/ftc_gift_certificate_terms/2020_standard_terms.converted.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/retry/ftc_gift_certificate_terms__2020_standard_terms.converted.json" --concurrency 8
python3 training_data/mutate/generate.py "data/raw_collection/ftc_gift_certificate_terms/2024_standard_terms.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/retry/ftc_gift_certificate_terms__2024_standard_terms.json" --concurrency 8
python3 training_data/mutate/generate.py "data/raw_collection/mof_rd_regulation_pair/after_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/retry/mof_rd_regulation_pair__after_2024.json" --concurrency 8
python3 training_data/mutate/generate.py "data/raw_collection/mof_rd_regulation_pair/before_2022.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/retry/mof_rd_regulation_pair__before_2022.json" --concurrency 8
python3 training_data/mutate/generate.py "data/raw_collection/mois_opendata_eval_manual/2021_eval_manual.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/retry/mois_opendata_eval_manual__2021_eval_manual.json" --concurrency 8
python3 training_data/mutate/generate.py "data/raw_collection/mss_rd_guideline_pair/after_2025.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/retry/mss_rd_guideline_pair__after_2025.json" --concurrency 8
python3 training_data/mutate/generate.py "data/raw_collection/mss_rd_guideline_pair/before_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/retry/mss_rd_guideline_pair__before_2024.json" --concurrency 8
python3 training_data/mutate/generate.py "data/raw_collection/regional_industry_guideline_pair/after_2026.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/retry/regional_industry_guideline_pair__after_2026.json" --concurrency 8
python3 training_data/mutate/generate.py "data/raw_collection/regional_industry_guideline_pair/before_2023.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/retry/regional_industry_guideline_pair__before_2023.json" --concurrency 8
python3 training_data/mutate/generate.py "data/raw_collection/tips_operating_guideline_pair/after_2023_partial_revision.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/retry/tips_operating_guideline_pair__after_2023_partial_revision.json" --concurrency 8
python3 training_data/mutate/generate.py "data/raw_collection/tips_operating_guideline_pair/before_2022.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/retry/tips_operating_guideline_pair__before_2022.json" --concurrency 8

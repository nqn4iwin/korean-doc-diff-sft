#!/usr/bin/env bash
# training_data/mutate/plan.py가 만들었다. 손으로 고치지 말고 다시 만든다.
#
# 1패스 -- 계획 전체에 v1.2를 한 번 건다. `generate.py`는 수정하지 않은 것이고,
# 계획에 실린 `instruct2`는 이 패스에서 쓰이지 않는다(2패스가 읽는다).
#
# 시간 초과 기본값 180초는 1,000건 넘는 실행에 안 맞는다 -- 2026-08-13에 227건을
# TimeoutError로 잃었다. 동시 요청도 16에서 8로 내린다(많을수록 응답이 늦어졌다).
set -u
cd "$(dirname "$0")/../../../.." || exit 1
export SOLAR_TIMEOUT_SECONDS=900

python3 -u training_data/mutate/generate.py "data/raw_collection/ftc_deposit_terms_pair/after_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/ftc_deposit_terms_pair__after_2024.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/ftc_deposit_terms_pair/before_2022.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/ftc_deposit_terms_pair__before_2022.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/ftc_game_terms/mobile_2017.converted.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/ftc_game_terms__mobile_2017.converted.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/ftc_game_terms/mobile_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/ftc_game_terms__mobile_2024.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/ftc_game_terms/online_2013.converted.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/ftc_game_terms__online_2013.converted.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/ftc_game_terms/online_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/ftc_game_terms__online_2024.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/ftc_gift_certificate_terms/2020_standard_terms.converted.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/ftc_gift_certificate_terms__2020_standard_terms.converted.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/ftc_gift_certificate_terms/2024_standard_terms.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/ftc_gift_certificate_terms__2024_standard_terms.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/ftc_gift_certificate_terms_2024_2025_pair/after_2025.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/ftc_gift_certificate_terms_2024_2025_pair__after_2025.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/kisa_public_blockchain_notice_pair/after_2025_0556.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/kisa_public_blockchain_notice_pair__after_2025_0556.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/mafra_rd_guideline_pair/after_2025.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/mafra_rd_guideline_pair__after_2025.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/mafra_rd_guideline_pair/before_2022.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/mafra_rd_guideline_pair__before_2022.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/me_environment_tech_guideline_pair/after_2024.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/me_environment_tech_guideline_pair__after_2024.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/me_environment_tech_guideline_pair/before_2023.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/me_environment_tech_guideline_pair__before_2023.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/mohw_health_rd_guideline_pair/after_2023.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/mohw_health_rd_guideline_pair__after_2023.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/mohw_health_rd_guideline_pair/before_2022.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/mohw_health_rd_guideline_pair__before_2022.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/mois_opendata_eval_manual/2021_eval_manual.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/mois_opendata_eval_manual__2021_eval_manual.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/molit_rd_guideline_pair/after_2024.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/molit_rd_guideline_pair__after_2024.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/molit_rd_guideline_pair/before_2021.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/molit_rd_guideline_pair__before_2021.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/motie_global_talent_notice_pair/after_2026_269.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/motie_global_talent_notice_pair__after_2026_269.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/msit_science_rd_guideline_pair/after_2023.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/msit_science_rd_guideline_pair__after_2023.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/msit_science_rd_guideline_pair/before_2022.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/msit_science_rd_guideline_pair__before_2022.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/mss_innovation_voucher_notice_pair/after_2026_317.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/mss_innovation_voucher_notice_pair__after_2026_317.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/mss_modoo_startup_notice_pair/after_2026_275.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/mss_modoo_startup_notice_pair__after_2026_275.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/mss_rd_guideline_pair/after_2025.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/mss_rd_guideline_pair__after_2025.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/mss_rd_guideline_pair/before_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/mss_rd_guideline_pair__before_2024.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/regional_industry_guideline_pair/after_2026.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/regional_industry_guideline_pair__after_2026.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/regional_industry_guideline_pair/before_2023.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/regional_industry_guideline_pair__before_2023.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/tips_operating_guideline_pair/after_2023_partial_revision.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/tips_operating_guideline_pair__after_2023_partial_revision.json" --concurrency 8

python3 -u training_data/mutate/generate.py "data/raw_collection/tips_operating_guideline_pair/before_2022.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/run2/tips_operating_guideline_pair__before_2022.json" --concurrency 8

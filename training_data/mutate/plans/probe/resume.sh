#!/usr/bin/env bash
# 탐침 나머지. 이미 pairs.json이 저장된 문서는 뺐다.
set -u
cd "$(dirname "$0")/../../../.." || exit 1

python3 training_data/mutate/generate.py "data/raw_collection/ftc_gift_certificate_terms/2020_standard_terms.converted.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe/2020_standard_terms.converted.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/ftc_gift_certificate_terms/2024_standard_terms.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe/2024_standard_terms.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/mof_rd_regulation_pair/after_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe/after_2024.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/mof_rd_regulation_pair/before_2022.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe/before_2022.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/mois_opendata_eval_manual/2021_eval_manual.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe/2021_eval_manual.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/mss_rd_guideline_pair/after_2025.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe/after_2025.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/mss_rd_guideline_pair/before_2024.hwpx" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe/before_2024.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/regional_industry_guideline_pair/after_2026.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe/after_2026.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/regional_industry_guideline_pair/before_2023.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe/before_2023.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/tips_operating_guideline_pair/after_2023_partial_revision.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe/after_2023_partial_revision.json" --concurrency 16
python3 training_data/mutate/generate.py "data/raw_collection/tips_operating_guideline_pair/before_2022.txt" \
  --prompt v1.2 --plan "training_data/mutate/plans/probe/before_2022.json" --concurrency 16

# Document Change Interpretation Data

This repository builds training data for a Korean model that explains changes
between two related public or business documents. The intended output is not a
raw text diff. Each record should identify the source evidence, classify the
change, name the affected party, describe the direct operational effect, and
separate supported facts from uncertain interpretation.

## Repository layout

```text
.
├── raw_collection/          # Find, download, verify, and preserve source pairs
├── synthetic_generation/    # Create and evaluate training examples from verified patterns
├── docs/                    # Research, source decisions, plans, and TODOs
├── solar.config.example.env # Non-secret Solar configuration example
└── solar_request.json       # Solar request shape used by the prompt test
```

`raw_collection/` and `synthetic_generation/` are the two working areas. Do
not add a project wrapper directory around them.

## Data boundary

Only use a document pair when both official source documents can be opened,
their relationship can be demonstrated by a version link or stable identifier,
and their extracted text contains a real difference. Preserve the source URL,
collection time, MIME type, size, SHA-256 digest, and extracted text in a
manifest. Do not use title similarity alone.

The current verified material covers all five source classes in `docs/PLAN.md`:

- Fifteen consecutive HTML privacy-policy pairs from the Ministry of Personnel
  Management, linked by the site's own prior-version URL chain. Treat them as a
  single document lineage, not fifteen independent samples.
- Three Fair Trade Commission standard-terms pairs (online-game 2013-2024,
  mobile-game 2017-2024, and gift-certificate 2020-2024), each linked by an
  unchanged standard-terms number.
- One prior-specification to revised bid/RFP pair for the Korea Marketing
  Promotion Agency, retained in `synthetic_generation/prompt_test/` as the
  initial teacher-model fixture.
- One support-program notice pair: Ministry of SMEs and Startups TIPS notice
  2026-40 and its corrective notice 2026-188, which cites the original notice
  number and date in its own text.
- One operating-guideline pair: the TIPS general operating guideline effective
  2022-01-11 and its 2023-01-20 partial revision, linked by the effective date
  in each document's supplementary provisions.

Rejected: the Ministry of the Interior and Safety public-data evaluation
handbooks for 2021 and 2024. Both official documents were obtained, but the
evaluation framework was rebuilt between them, so no clause-level alignment
exists. They are kept as label-definition reference material.

See `docs/기획서_최종.md` for the project plan, `docs/source_selection.md` for
the source decision record, `docs/학습데이터생성_프로세스.md` for each accepted
pair with quoted change excerpts and for the preprocessing and label scheme, and
`docs/TODO.md` for the remaining source-collection work.

## Workflow

1. **Raw collection:** collect official documents, prove the pair relationship,
   extract text while preserving structure, and record deterministic diffs.
2. **Pattern review:** inspect real differences before defining any synthetic
   transformation. Do not invent document changes first.
3. **Synthetic generation:** create controlled examples only from observed,
   verified change patterns. Keep the original structure and wording; do not
   rewrite full documents.
4. **Evaluation:** keep real pairs separate from generated examples and use
   held-out document pairs to measure evidence accuracy, change coverage, and
   unsupported inference.

## Working directories

### `raw_collection/`

- `crawlers/`: small, budget-limited G2B collection utilities.
- `classify_diff.py`: block-level diff for one pair. Normalization rules decide
  mechanically which differences carry no real change (article renumbering,
  item markers, cross-references to a renumbered item, attachment numbers,
  table-of-contents page numbers, quotation marks, interpuncts, spacing), so
  those never reach a model. Blocks that survive every rule and share an
  identical substitution are folded into one item, so a system renamed in
  twelve places counts once. Reads `.hwpx`, `.html` and `.txt`:

  ```powershell
  python .\raw_collection\classify_diff.py `
      .\data\raw_collection\ftc_game_terms\mobile_2017.converted.hwpx `
      .\data\raw_collection\ftc_game_terms\mobile_2024.hwpx
  ```

- `config.example.env`: names of the G2B variables; secrets stay in
  `raw_collection/.env` and are never printed or committed.
- `rfp_pair_search_memo.md`: prior search results and pair-selection lessons.

Raw files belong under `data/raw_collection/` (Git-ignored), not in the
repository.

### `synthetic_generation/`

`prompt_test/` contains the fixed real-pair fixture, the Solar prompt, the
runner, and recorded outputs. Run it from the repository root:

```powershell
python .\synthetic_generation\prompt_test\run.py
```

The fixture is an experiment asset, not a license to treat every generated
interpretation as ground truth. Teacher output must be checked against the
source blocks before it becomes training data.

## Safety

- Never read, print, or commit `.env` files or API keys.
- Do not bypass login, CAPTCHA, robots rules, download restrictions, or source
  licensing terms.
- Keep original files immutable and retain earlier versions separately.
- Treat interpretation and issuer intent as distinct from directly observed
  document facts.

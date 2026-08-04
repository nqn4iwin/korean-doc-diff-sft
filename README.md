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

The current verified material is:

- Ten consecutive HTML privacy-policy pairs from the Ministry of Personnel
  Management.
- One prior-specification to revised bid/RFP pair for the Korea Marketing
  Promotion Agency, retained in `synthetic_generation/prompt_test/` as the
  initial teacher-model fixture.
- A conditional Fair Trade Commission gift-certificate standard-terms pair:
  the 2020 HWP and 2024 HWPX are linked by the same terms number, but the
  2020 text extraction and paragraph diff still need to be completed.

See `docs/TODO.md` for the urgent verification work and
`docs/source_selection.md` for the source decision record.

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

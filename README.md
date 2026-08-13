# Document Change Interpretation Data

This repository builds training data for a Korean model that explains changes
between two related public or business documents. The intended output is not a
raw text diff. Each record should identify the source evidence, classify the
change, name the affected party, describe the direct operational effect, and
separate supported facts from uncertain interpretation.

## Repository layout

```text
.
├── source_data/             # Collect documents, extract text, produce diff JSON
├── training_data/           # Turn diff JSON into training records
│   ├── interpret/           #   role A: a change -> its interpretation
│   └── mutate/              #   role B: a document -> a new changed pair
├── probes/                  # Finished experiments, kept as a record
├── docs/                    # Research, source decisions, plans, and TODOs
├── data/                    # Actual documents (Git-ignored, not code)
├── solar.py                 # Shared Solar client used by every caller
├── solar.config.example.env # Non-secret Solar configuration example
└── solar_request.json       # Pinned generation parameters
```

`source_data/` holds the code that produces source pairs; `data/` holds the
files themselves and is Git-ignored. The names are similar and the contents are
not.

The root keeps only what every area uses. Do not add a project wrapper
directory around the working folders.

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
  Promotion Agency, retained in `probes/prompt_test/` as the
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

See `docs/기획서_최종.md` for the project plan, `docs/원천데이터_선정_프로세스.md` for
the source decision record and each accepted pair,
`docs/학습데이터_생성_프로세스.md` for the preprocessing, label scheme and synthesis
pipeline, `docs/세션_브리프.md` to pick the work back up, and `docs/TODO.md` for
the remaining source-collection work.

## Workflow

1. **Source collection** (`source_data/`): collect official documents, prove the
   pair relationship, extract text while preserving structure, and record
   deterministic diffs.
2. **Pattern review:** inspect real differences before defining any synthetic
   transformation. Do not invent document changes first.
3. **Training-data generation** (`training_data/`): create controlled examples
   only from observed, verified change patterns. Keep the original structure and
   wording; do not rewrite full documents.
4. **Evaluation:** keep real pairs separate from generated examples and use
   held-out document pairs to measure evidence accuracy, change coverage, and
   unsupported inference.

## Working directories

### `source_data/`

- `crawlers/`: small, budget-limited G2B collection utilities. Currently unused
  -- every accepted pair except the RFP one was collected by hand from a public
  board. Kept until the G2B corrective-notice source is decided.
- `extract.py`: one extractor per file format, returning `(id, text)` blocks.
  Collection format priority is HWPX > HWP (converted) > PDF. This is where a
  new format's extractor goes.
- `classify_diff.py`: block-level diff for one pair. Normalization rules decide
  mechanically which differences carry no real change (article renumbering,
  item markers, cross-references to a renumbered item, attachment numbers,
  table-of-contents page numbers, quotation marks, interpuncts, spacing), so
  those never reach a model. Blocks that survive every rule and share an
  identical substitution are folded into one item, so a system renamed in
  twelve places counts once. Every block carries an id (`mobile_2024-B0007`,
  the seventh block extracted from that file) so a label can point back at the
  block it was written for, and the blocks a rule fired on are kept in full --
  a rule that swallowed a real change can only be caught by reading them. The
  result is always written to `<before>__<after>.classify.json` beside the
  after file; `--json` overrides the path. Reads `.hwpx`, `.html` and `.txt`:

  ```powershell
  python .\source_data\classify_diff.py `
      .\data\raw_collection\ftc_game_terms\mobile_2017.converted.hwpx `
      .\data\raw_collection\ftc_game_terms\mobile_2024.hwpx
  ```

- `config.example.env`: names of the G2B variables; secrets stay in
  `source_data/.env.g2b` and are never printed or committed. The name differs
  from the root Solar settings file deliberately -- two files both called
  `.env` in one tree are easy to copy over each other, and neither is in Git to
  restore from.
- `memos/`: search records for each source family, including the ones rejected
  and why.

Raw files belong under `data/raw_collection/` (Git-ignored), not in the
repository.

### `training_data/`

`interpret/` (role A) writes what a change means; `mutate/` (role B) writes a
new changed version of a document so that a synthetic pair can be made. Neither
is implemented yet -- each holds a README stating its input, output, and the
experiment result that constrains it.

Label judgement stays with a person. In `probes/interpret_probe/` the model matched
the human key on three of six blocks and reported `high` confidence on every
one, including the wrong ones.

### `probes/`

Finished experiments, kept because the plan cites their results. They are a
record, not active code: reports and run outputs are preserved as written.

- `prompt_test/`: the whole document in one prompt. Ten runs, zero of which
  caught every verified change.
- `interpret_probe/`: can the model recover a label from before/after text alone?
- `mutate_probe/`: can the model write a revision for a named operator?

Run one from the repository root:

```powershell
python .\probes\prompt_test\run.py
```

## Safety

- Never read, print, or commit `.env` files or API keys.
- Do not bypass login, CAPTCHA, robots rules, download restrictions, or source
  licensing terms.
- Keep original files immutable and retain earlier versions separately.
- Treat interpretation and issuer intent as distinct from directly observed
  document facts.

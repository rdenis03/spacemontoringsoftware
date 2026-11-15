# B23 · Symptom triage v1: rules, end to end

**Lane:** Triage (M15) · **Needs:** B15, B18, B19 · **Branch:** `data/b23-triage-v1` · **Size:** L

## Goal

The astronaut describes how they feel in their own words. ORBIT maps the
text to its 8 symptom signals, ranks 8 patterns with reasons, asks up to 5
follow-up questions and replies with action cards. Version 1 uses rules and
hand-written libraries only (no ML). Nothing is saved until the astronaut
confirms; on confirm the findings become ordinary `checkin` observations and
`pipeline.assess()` re-scores. The daily pipeline does not change.

## Read first

- SPEC.md Parts 1 and 2; M10, M13, M14 and **M15** in Part 3.
- ARCHITECTURE.md (decision 8), tasks/README.md, tasks/NOTES.md B08, B10, B15, B17, B18, B19.
- `orbit/core/` (interfaces, pipeline, store, config, registry, `__init__`),
  `orbit/schema/` (models, signals, labels, `__init__`), `orbit/modules/`
  (actions, scorer, `__init__`), `orbit/api/app.py`, `orbit/__main__.py`,
  `orbit.toml`, `cards/action_cards.jsonl`.
- `tests/conftest.py`, `tests/test_contracts.py`, `tests/test_actions.py`, `tests/test_pipeline.py`.

## Files

- Docs: `SPEC.md` (M15 section, Part 4 row, one line under "Slots"),
  `ARCHITECTURE.md` (decision 8 and the M15 rows), `CLAUDE.md` (the task range
  only), `tasks/B23-triage-v1.md` (new), `tasks/B24-triage-ml.md` (new).
- Schema and core: `orbit/schema/triage.py` (new), `orbit/schema/__init__.py`
  (exports only), `orbit/schema/models.py` (`SCHEMA_VERSION` only),
  `orbit/core/interfaces.py` (`TriageEvidence`, the two protocols, `SLOTS`),
  `orbit/core/__init__.py` (exports only), `orbit/core/store.py` (`triage_sessions` only).
- Modules: `orbit/modules/extractor.py` (new), `orbit/modules/reasoner.py` (new),
  `orbit/modules/__init__.py` (two import lines).
- Triage package: `orbit/triage/__init__.py`, `orbit/triage/library.py`,
  `orbit/triage/red_flags.py`, `orbit/triage/service.py` and
  `orbit/triage/config.py` (all new).
- Cards: `cards/symptom_lexicon.jsonl`, `cards/questions.jsonl`,
  `cards/patterns.jsonl`, `cards/triage_cards.jsonl`, `cards/red_flags.jsonl` (all new).
- App and config: `orbit/api/app.py`, `orbit/__main__.py`, `orbit.toml` (the
  `[triage]` block only).
- Tests: `tests/test_triage_schema.py`, `tests/test_triage_contracts.py`,
  `tests/test_extractor.py`, `tests/test_reasoner.py`, `tests/test_red_flags.py`,
  `tests/test_triage_service.py`, `tests/test_api_triage.py`,
  `tests/test_triage_cli.py` and `tests/fixtures/triage/red_flag_sentences.jsonl` (all new).

`tasks/README.md` and `tasks/NOTES.md` are always allowed. Never edit
`cards/action_cards.jsonl`, `tests/test_pipeline.py` or `examples/*.jsonl`.

## Build

Work through the steps in order. **Checkpoint** = `python -m pytest` and
`python -m orbit demo` pass, with AST-01 yellow on day 89 and orange on
day 90. Tick a step only when its checkpoint is green. To continue in a new
session: "Continue B23 from the first unfinished step in tasks/B23-triage-v1.md".

- [x] **1. Docs, no code.** SPEC.md M15 (with a short "Version 2 (B24)"
  part), the Part 4 row and the line under "Slots"; ARCHITECTURE.md decision 8
  and the M15 rows in "Who owns what"; CLAUDE.md task range; this file;
  `tasks/B24-triage-ml.md`; tasks/README.md (board rows B23 and B24, the L
  size line, "→ B23 → B24" in "Order for one person", rows in "Shared files").
- [x] **2. Core.** `orbit/schema/triage.py` and its exports, `SCHEMA_VERSION`
  1.1.0, `TriageEvidence` and the `extractor` and `reasoner` slots in `SLOTS`
  (not in `ANALYTICS_SLOTS`), the `triage_sessions` table,
  `tests/test_triage_schema.py` and `tests/test_triage_contracts.py`
  (parametrized over `available("extractor")` and `available("reasoner")`;
  SPEC M15 lists what they must hold).
- [x] **3. Extractor.** `orbit/modules/extractor.py` (`lexicon`),
  `cards/symptom_lexicon.jsonl`, `tests/test_extractor.py`: the worked
  example's findings, negation cases, complaints outside the 8 signals.
- [x] **4. Reasoner.** `orbit/modules/reasoner.py` (`rules`),
  `cards/questions.jsonl`, `cards/patterns.jsonl`, `cards/triage_cards.jsonl`,
  `orbit/triage/__init__.py` (a docstring, no imports: NOTES B08),
  `orbit/triage/library.py`, `tests/test_reasoner.py`: severity is asked first
  in the worked example; the spacewalk question is skipped on day 89;
  exertion leads for muscle aches 2, fatigue 1 and an EVA yesterday; stop
  rules; the library check rejects duplicate ids, doses, mixed categories and
  ids that clash with `action_cards.jsonl`; `tests/test_actions.py` passes untouched.
- [x] **5. Red flags.** `orbit/triage/red_flags.py`, `cards/red_flags.jsonl`,
  `tests/fixtures/triage/red_flag_sentences.jsonl`, `tests/test_red_flags.py`:
  100 % recall on the positive lines, no fire on the negated lines, and the
  `merge_procedures` rules.
- [x] **6. Service.** `orbit/triage/service.py`, `orbit/triage/config.py`, the
  `[triage]` block in `orbit.toml` with the starters active,
  `tests/test_triage_service.py`: the worked example end to end (yellow 44.7,
  `saliva-test` first, `watch-patch` present, the 10:00 runs unchanged, the
  observation ids and notes as specified); cancel writes nothing; red-flag
  text gives escalated, the red-flag card first and no question; expiry after
  the timeout with a fake clock; a failing reasoner leaves the
  re-assessment's cards and records the error.
- [x] **7. API.** `orbit/api/app.py`, `orbit/__main__.py` (`cmd_serve`),
  `tests/test_api_triage.py`: with `TestClient`, start, three answers,
  confirm, then `/status` shows yellow 44.7 with the merged cards; with
  `?view=shared`, `watch-patch` appears as "Private action"; `/api/overview`
  has `red_flag_at` after a red-flag session; 404, 409 and 422 cases; the
  existing API tests pass untouched.
- [x] **8. CLI.** The `triage` command and the `modules` listing in
  `orbit/__main__.py`, `tests/test_triage_cli.py`: the worked example prints
  yellow and 44.7. Final checkpoint.

## Tests

One file per step, as listed above. The numbers to expect (measured on the
code before B23) are in SPEC M15, *Numbers measured* and *Worked example*.

## Done when

- [x] Every step above is ticked, `python -m pytest` and `python -m orbit demo` pass.
- [x] `python -m orbit triage AST-01 "Weird burning, tingly patch on my ribs since last night. Pretty wiped out too." --as-of 2027-04-02T10:30:00Z --answer moderate --answer yes --answer none` prints yellow 44.7.
- [x] `python -m orbit modules` lists `extractor` and `reasoner` with `lexicon` and `rules` active.

## Hand-off

For B24: the slot contracts, the lexicon helpers (`tokenize`, `is_negated`,
`parse_duration`), the question bank's likelihoods and the pattern labels.
For the frontend (Person B, `/checkin/chat`): the response shapes of
`TriageResult`, `TriageSession` and the confirm response `{result, day}`,
and the statuses `asking`, `ready`, `escalated`, `confirmed`, `cancelled`, `expired`.

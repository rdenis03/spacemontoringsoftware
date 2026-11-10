# B19 · Action cards v2

**Lane:** Crew guidance (M10) · **Needs:** none · **Branch:** `be/b19-action-cards` · **Size:** S

## Goal

Always give the astronaut a clear, doable next step that fits the reasons for
their status, and say who else must know. The AI decides how worried to be;
these human-written cards decide what to do. Move the cards into their own
hand-edited library and make them specific to each virus.

## Read first

- SPEC.md Part 3, M10: requirements and ideas.
- `orbit/modules/actions.py` (`CardLibraryActionEngine`, `BUILT_IN_CARDS`).
- `examples/action_cards.jsonl` and `examples/make_examples.py` (generated;
  never hand-edit `examples/*.jsonl`).
- `orbit/schema/models.py` (`ActionCard`), `tests/test_pipeline.py` (the demo story).

## Files

- `cards/action_cards.jsonl` (new, hand-edited library)
- `orbit/modules/actions.py` (only if the engine needs a change)
- `orbit.toml` (only `cards_path` in `[modules.actions]`)
- `tests/test_actions.py` (new)

## Build

1. Start from the example cards, then add:
   - VZV (`saliva_vzv_dna`, `symptom_rash_tingling`): check the skin and
     photograph any rash daily; tell the crew medical officer.
   - HSV-1 (`saliva_hsv1_dna`, `symptom_mouth_sores`): mouth care, do not share
     cups or utensils.
   - EBV (`saliva_ebv_dna`, `symptom_swollen_glands`): rest, fluids, repeat the
     saliva test.
   - Respiratory (`symptom_fever_chills`, `crp`): limit time in shared
     modules, wipe shared surfaces.
   - Follow-ups: "Repeat the saliva test in 48 hours", "Check in again tomorrow morning".
2. At least one card for every level; never a card above the assessment's
   level; cards that match a reason first; at most `max_cards` (3).
3. Orange and red cards set `escalate_to`. Steps are imperative, under 200
   characters, doable onboard, no medication or doses; the rationale is plain language.
4. Point `cards_path` in `orbit.toml` to `cards/action_cards.jsonl`.

## Tests (`tests/test_actions.py`)

- The library validates (every line is a valid `ActionCard`).
- Every level has at least one card; orange and red cards have `escalate_to`.
- Every step is under 200 characters and contains no digit followed by "mg".
- AST-01 on day 90 gets a VZV-specific card first.

## Done when

- [ ] The demo story still holds (AST-01 yellow on day 89, orange on day 90).
- [ ] `python -m pytest` and `python -m orbit demo` pass.

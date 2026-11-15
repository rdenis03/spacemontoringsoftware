# B24 · Symptom triage v2: the models

**Lane:** Triage (M15) · **Needs:** B23 · **Branch:** `data/b24-triage-ml` · **Size:** L

## Goal

Add learned versions of the two triage slots next to the B23 starters: a
text model for the extractor and a Bayes reasoner. Train them on simulated
missions, measure them against the starters on held-out seeds, and switch
`orbit.toml` only if the switch rules pass and the team agrees, as B10 did
for the scorer.

## Read first

- SPEC.md M15 (including *Version 2 (B24)*).
- tasks/NOTES.md B09, B10 and B23.
- `orbit/learning/train.py`, `orbit/modules/scorer_learned.py`,
  `orbit/modules/simulator.py`, `orbit/schema/labels.py`, `orbit/evaluation/`.
- `orbit/modules/extractor.py`, `orbit/modules/reasoner.py`, `cards/questions.jsonl`.

## Files

- `orbit/modules/simulator.py` and `orbit/schema/labels.py` (`STRESS_LOAD` only).
- `orbit/learning/utterances.py`, `orbit/learning/utterances_extra.jsonl`,
  `orbit/learning/train_text.py`, `orbit/learning/text_weights.json`,
  `orbit/learning/train_reasoner.py` and `orbit/learning/reasoner_weights.json`.
- `orbit/modules/extractor_learned.py`, `orbit/modules/reasoner_bayes.py` and
  `orbit/modules/__init__.py` (two import lines).
- `orbit/evaluation/triage.py`, `experiments/triage_learned.toml` and `reports/triage_eval.json`.
- `README.md` (Results only), `SPEC.md` (M15 results only), and `orbit.toml`
  (the `[triage.*]` `use` lines only, and only after the switch rules pass and the team agrees).
- Tests: `tests/test_simulator_symptoms.py`, `tests/test_extractor_learned.py`,
  `tests/test_reasoner_bayes.py`, `tests/test_evaluation_triage.py` and
  `tests/fixtures/triage/human_sentences.jsonl`.

## Build

In order. **Checkpoint** after each step = `python -m pytest` and
`python -m orbit demo` pass, with AST-01 yellow on day 89 and orange on day 90.

- [ ] **1. Simulator symptom look-alikes** (`orbit/modules/simulator.py`,
  `orbit/schema/labels.py`, `tests/test_simulator_symptoms.py`).
  - New options `symptom_lookalikes: bool = False` and
    `mild_illness_rate: float = 0.0`. Off by default, and they draw no random
    numbers when off, so today's output, tests and README numbers stay byte-identical.
  - **Before changing anything**, record a SHA-256 of `read()`'s JSON for
    seed 1 with default options, and pin it in the test.
  - With `symptom_lookalikes`:
    - after an EVA, muscle aches 1–2 and fatigue 1 the next morning;
    - during a sleep shift, fatigue 1 and sometimes headache 1;
    - a new `stress_load` look-alike (`ScenarioType.STRESS_LOAD`, not
      alerting): stress 4–5, mood 2 and headache 1 for 2–4 days, with no
      vital change; it is also accepted in list mode.
  - With `mild_illness_rate`: illnesses whose vital changes are 30–50 % of the usual size.
- [ ] **2. Text model.**
  - `orbit/learning/utterances.py`: a seeded template generator built from the lexicon.
  - `orbit/learning/utterances_extra.jsonl`: hand-written paraphrases.
  - `orbit/learning/train_text.py`, run as
    `python -m orbit.learning.train_text --seed 1 --out orbit/learning/text_weights.json`:
    logistic regression per symptom signal on word 1–2 grams and character
    3–5 grams, plus a severity head; sparse readable weights. Only the
    trainers import scikit-learn.
  - `orbit/modules/extractor_learned.py`: `@register("extractor", "text_linear")`,
    defaulting to the shipped weights. Negation and durations reuse the
    lexicon helpers (`tokenize`, `is_negated`, `parse_duration` in
    `orbit/modules/extractor.py`). Never import `orbit.learning` at the top
    of a file in `orbit/modules/` (NOTES B08).
  - `tests/fixtures/triage/human_sentences.jsonl`: start with a 20-line stub.
    About 200 lines must later come from people who never saw the templates.
  - `tests/test_extractor_learned.py`.
- [ ] **3. Bayes reasoner.**
  - `orbit/learning/train_reasoner.py`, run as
    `python -m orbit.learning.train_reasoner --seeds 1-20 --days 180 --crew 4 --out orbit/learning/reasoner_weights.json`.
    It runs the simulator with `symptom_lookalikes` on and `mild_illness_rate`
    0.3, builds the evidence per labelled episode day, samples answers from
    the bank's hand-set likelihoods with a seeded RNG, applies Laplace
    smoothing, and refuses seeds 101–105.
  - `orbit/modules/reasoner_bayes.py`: `@register("reasoner", "bayes")`.
    `rank` is naive Bayes over the evidence. `next_question` picks the
    highest expected information gain in bits, keeping the rules'
    screening-first, severity-first and stop rules, with `min_gain_bits = 0.05`.
    Reasons are the top 3 log-likelihood-ratio factors.
  - `tests/test_reasoner_bayes.py`: a deterministic weights file; held-out
    seeds refused; probabilities sum to 1; picks the one-side question in the
    worked example; contracts.
- [ ] **4. Evaluation and decision.**
  - `orbit/evaluation/triage.py`, run as
    `python -m orbit.evaluation.triage --config orbit.toml --config experiments/triage_learned.toml --seeds 101-105 --days 180 --crew 4 --out reports/triage_eval.json`.
  - Metrics:
    - extractor F1 per symptom, negation accuracy and severity within one
      level, on `human_sentences.jsonl`;
    - reasoner top-1, top-3 and Brier score per scenario, and questions per
      session, on simulated sessions;
    - red-flag recall;
    - M9 sensitivity, lead time and false alarms, with chats on symptom days.
  - Record the numbers, marked simulated, in the module docstrings, the
    README *Results* section and SPEC.md M15.
  - `tests/test_evaluation_triage.py` runs it on a tiny config.

## Switch rules

Change `orbit.toml` only if all of these pass and the team agrees. Otherwise
keep the starters and record why, as B10 did.

- `text_linear` beats `lexicon` on F1 and negation on the human sentences,
  and misses no red-flag phrase.
- `bayes` beats `rules` on top-1, top-3 and Brier score on seeds 101–105,
  with no more questions on average.
- The M9 numbers are no worse, and the demo story holds.

Say in every report that the answer likelihoods are hand-set, so the
evaluation measures consistency, not medical truth.

## Done when

- [ ] Every step's checkpoint passes and `/ship` can commit exactly the files above.

## Hand-off

The comparison numbers (simulated), the switch decision and why, and for the
frontend whether `model_version` in `TriageResult` changed.

"""Train the ``text_linear`` extractor's weights (M15, task B24).

Only this file (and ``train_reasoner.py``) imports scikit-learn; the extractor
just adds up the weights it writes::

    pip install -e ".[dev,train]"
    python -m orbit.learning.train_text --seed 1 --out orbit/learning/text_weights.json

Data: ``generate(n, seed)`` template sentences plus the hand-written
paraphrases in ``utterances_extra.jsonl`` (``orbit/learning/utterances.py``).
The human test sentences (``tests/fixtures/triage/human_sentences.jsonl``)
are never used.

* **Detection**: one sample per clause (``clauses`` in the extractor). Its
  label for a signal is 1 when a mention of that signal (denied or not)
  overlaps the clause; negation is decided later by ``is_negated``, not by
  the model. A hand-written extra is one clause with its own labels.
* **Severity head**: one sample per mention that is not denied: the words
  around it (``mention_window``, as at run time), class "0" (not said) or
  1-3. Extras with exactly one symptom count with their whole text.

Fit: binary features (``features`` in the extractor), one L1-regularised
logistic regression per signal and per severity level (liblinear, one level
against the rest). L1 sets most weights to exactly 0, so the file stays small
and each weight is a readable feature ("w:tired" 4.8). Weights are rounded to
3 decimals and sorted by size. Deterministic: same arguments, same file.

Arguments:
    --seed      1                                 generator seed (101-105 are held out, refused)
    --n         4000                              template sentences
    --c         1.0                               inverse regularisation strength
    --lexicon   cards/symptom_lexicon.jsonl
    --extra     orbit/learning/utterances_extra.jsonl
    --out       orbit/learning/text_weights.json
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import sklearn
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression

from orbit.learning.train_reasoner import HELD_OUT_SEEDS
from orbit.learning.utterances import DEFAULT_EXTRA, DEFAULT_LEXICON, Utterance, generate, load_extra
from orbit.modules.extractor import PUNCTUATION, SCOPE_BREAKERS, tokenize
from orbit.modules.extractor_learned import (
    CLAUSE_BREAKERS,
    SEVERITY_LEVELS,
    clauses,
    features,
    mention_window,
)
from orbit.schema import SignalCategory, SignalType, get_spec

DEFAULT_OUT = Path(__file__).resolve().parent / "text_weights.json"
SIGNALS = tuple(s for s in SignalType if get_spec(s).category is SignalCategory.SYMPTOM)
THRESHOLD = 0.5
BREAKERS = SCOPE_BREAKERS | CLAUSE_BREAKERS


def samples(utterances: Sequence[Utterance]) -> tuple[list[set[str]], list[set[SignalType]],
                                                      list[set[str]], list[str]]:
    """(clause features, clause signals, severity-window features, severity classes)."""
    det_x, det_y, sev_x, sev_y = [], [], [], []
    for u in utterances:
        tokens = tokenize(u.text)
        words = [t.text for t in tokens]
        if not words:
            continue
        if u.source == "extra":
            det_x.append(features([w for w in words if w not in PUNCTUATION]))
            det_y.append(set(u.labels))
            positive = [(s, sev) for s, (neg, sev) in u.labels.items() if not neg]
            if len(positive) == 1:
                sev_x.append(features(words))
                sev_y.append(str(positive[0][1] or 0))
            continue
        spans = []  # (first token, end token, mention)
        for m in u.mentions:
            idx = [i for i, t in enumerate(tokens) if t.start < m.end and t.end > m.start]
            spans.append((idx[0], idx[-1] + 1, m))
        for lo, hi in clauses(words):
            det_x.append(features(words[lo:hi]))
            det_y.append({m.signal for s, e, m in spans if s < hi and e > lo})
            for s, e, m in spans:
                if not m.negated and lo <= s < hi:
                    a, b = mention_window(words, s, min(e, hi), lo, hi, BREAKERS)
                    sev_x.append(features(words[a:b]))
                    sev_y.append(str(m.severity or 0))
    return det_x, det_y, sev_x, sev_y


def _int32(X):
    """liblinear (scikit-learn 1.9) wants 32-bit sparse indices."""
    X = X.tocsr()
    X.indices = X.indices.astype(np.int32)
    X.indptr = X.indptr.astype(np.int32)
    return X


def _fit_binary(X, y: np.ndarray, names: Sequence[str], c: float) -> dict:
    model = LogisticRegression(l1_ratio=1.0, solver="liblinear", C=c, max_iter=5000, random_state=0)
    model.fit(_int32(X), y)
    pairs = [(names[i], round(float(w), 3)) for i, w in enumerate(model.coef_[0])]
    weights = {k: v for k, v in sorted(pairs, key=lambda kv: (-abs(kv[1]), kv[0])) if v != 0}
    return {"bias": round(float(model.intercept_[0]), 3), "weights": weights}


def train(seed: int = 1, n: int = 4000, c: float = 1.0, out: str | Path = DEFAULT_OUT,
          lexicon: str | Path = DEFAULT_LEXICON, extra: str | Path = DEFAULT_EXTRA) -> dict:
    if seed in HELD_OUT_SEEDS:  # before generating anything, like train_reasoner
        raise ValueError(f"seeds {[seed]} are held out for the evaluation (B24); never train on them")
    utterances = generate(n, seed, lexicon) + load_extra(extra)
    det_x, det_y, sev_x, sev_y = samples(utterances)
    vec = DictVectorizer(sort=True)
    X = vec.fit_transform([{f: 1 for f in sorted(fs)} for fs in det_x])
    names = list(vec.get_feature_names_out())
    signals, train_acc = {}, {}
    for signal in SIGNALS:
        y = np.array([signal in labels for labels in det_y], dtype=int)
        if len(set(y.tolist())) < 2:
            raise ValueError(f"no training clause for {signal.value}; use more sentences")
        signals[signal.value] = _fit_binary(X, y, names, c)
    sev_vec = DictVectorizer(sort=True)
    Xs = sev_vec.fit_transform([{f: 1 for f in sorted(fs)} for fs in sev_x])
    sev_names = list(sev_vec.get_feature_names_out())
    severity = {lvl: _fit_binary(Xs, np.array([y == lvl for y in sev_y], dtype=int), sev_names, c)
                for lvl in SEVERITY_LEVELS}
    doc = {
        "version": f"text-s{seed}-n{n}" + ("" if c == 1.0 else f"-c{c:g}"),
        "threshold": THRESHOLD,
        "signals": signals,
        "severity": severity,
        "trained_on": {
            "simulated": True,
            "seed": seed,
            "template_sentences": n,
            "extra_sentences": sum(u.source == "extra" for u in utterances),
            "clauses": len(det_x),
            "severity_windows": len(sev_x),
            "features_seen": len(names),
            "features_kept": len({f for m in signals.values() for f in m["weights"]}),
            "c": c,
            "scikit_learn": sklearn.__version__,
        },
        "notes": ("L1 logistic regression per symptom signal on word 1-2 grams and letter 3-5 "
                  "grams, plus a severity head (B24). Trained on template sentences from the "
                  "lexicon and hand-written paraphrases. Illustrative, not clinical."),
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    return doc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m orbit.learning.train_text",
                                     description="Train the text_linear extractor's weights.")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--n", type=int, default=4000)
    parser.add_argument("--c", type=float, default=1.0)
    parser.add_argument("--lexicon", default=str(DEFAULT_LEXICON))
    parser.add_argument("--extra", default=str(DEFAULT_EXTRA))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    try:
        doc = train(args.seed, args.n, args.c, args.out, args.lexicon, args.extra)
    except ValueError as exc:
        parser.error(str(exc))
    info = doc["trained_on"]
    print(f"{doc['version']}: {info['clauses']} clauses, {info['severity_windows']} severity "
          f"windows, {info['features_kept']} of {info['features_seen']} features kept")
    for name, model in doc["signals"].items():
        top = ", ".join(f"{k[2:]!r} {v}" for k, v in list(model["weights"].items())[:4])
        print(f"  {name:24s} bias {model['bias']:6.2f}  {top}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

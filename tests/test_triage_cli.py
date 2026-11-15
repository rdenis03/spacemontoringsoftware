"""M15 ``python -m orbit triage`` and the ``modules`` listing (task B23, step 8)."""

from conftest import CONFIG

from orbit.__main__ import main

WORKED_EXAMPLE = "Weird burning, tingly patch on my ribs since last night. Pretty wiped out too."
AS_OF = ["--as-of", "2027-04-02T10:30:00Z"]


def triage(capsys, text=WORKED_EXAMPLE, *answers, as_of=AS_OF, astronaut="AST-01"):
    argv = ["--config", str(CONFIG), "triage", astronaut, text, *as_of]
    for answer in answers:
        argv += ["--answer", answer]
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_worked_example_prints_yellow_44_7(capsys):
    code, out, _ = triage(capsys, WORKED_EXAMPLE, "moderate", "yes", "none")
    assert code == 0
    assert "Rash or tingling: severity not given · ribs · started about 12 h ago" in out
    assert "Fatigue: moderate" in out
    questions = [line.strip() for line in out.splitlines() if line.strip().startswith("Q")]
    assert questions == [
        "Q1 How strong is the burning, tingling or rash? (none / mild / moderate / severe)",
        "Q2 Is it on one side of your body only? (yes / no)",
        "Q3 Any fever or chills? (none / mild / moderate / severe)",
    ]
    assert "-> moderate" in out and "-> yes" in out and "-> none" in out
    assert "Signs that fit shingles (VZV)" in out and "not a diagnosis" in out
    assert "Status: YELLOW (44.7/100), was YELLOW (27.7) at 10:00" in out
    cards = [line.strip() for line in out.splitlines() if line.strip().startswith("[")]
    assert cards[0] == "[Take a saliva sample]"
    assert "[Watch the patch]" in cards and "[Rest and watch]" in cards
    assert "Module errors" not in out


def test_without_answers_it_stops_and_still_saves(capsys):
    code, out, _ = triage(capsys, WORKED_EXAMPLE)
    assert code == 0
    assert "no answer given: that's all" in out
    assert "Saved as a check-in: Rash or tingling: severity not given" in out
    assert "Status: YELLOW" in out


def test_red_flag_text_stops_the_questions(capsys):
    code, out, _ = triage(capsys, "Tingling near my eye since this morning")
    assert code == 0
    assert "RED FLAG: Rash or tingling near the eye" in out
    assert not any(line.strip().startswith("Q1") for line in out.splitlines())
    assert out.split("What to do:")[1].strip().startswith("[Get medical help now]  -> crew medical officer")


def test_errors_exit_with_2(capsys):
    code, _, err = triage(capsys, WORKED_EXAMPLE, "very")
    assert code == 2 and "not an answer" in err
    code, _, err = triage(capsys, "tired", astronaut="AST-99")
    assert code == 2 and "unknown astronaut" in err


def test_modules_lists_the_triage_slots(capsys):
    assert main(["--config", str(CONFIG), "modules"]) == 0
    by_slot = {line.split()[0]: line for line in capsys.readouterr().out.splitlines()}
    # other tests register throwaway modules in the shared registry, so check only what M15 adds
    assert by_slot["extractor"].startswith("extractor  lexicon (active)")
    assert by_slot["reasoner"].startswith("reasoner   rules (active)")
    assert by_slot["scorer"].startswith("scorer     "), "one column wide enough for every slot name"

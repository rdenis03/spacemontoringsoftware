---
name: task
description: Start and do one ORBIT backend task from tasks/ (for example /task B02). Syncs main, creates the task's branch, does the task, runs the tests, and stops before committing.
argument-hint: "[task-id, e.g. B02]"
disable-model-invocation: true
allowed-tools: Bash(git status*) Bash(git checkout*) Bash(git pull*) Bash(git branch*) Bash(git log*) Bash(git diff*) Bash(python -m pytest*) Bash(python -m orbit*) Bash(python -m pip install -e*)
---

# Do task $0

1. **Clean start.** Run `git status --porcelain`. If anything is listed, stop
   and tell me which files are uncommitted. Do not continue.
2. **Latest main.** `git checkout main`, then `git pull`.
3. **Find the task.** Open `tasks/$0-*.md` (exactly one file must match).
   Read its **Branch** and **Needs** lines. On the board in `tasks/README.md`,
   every task it needs must be ticked `[x]`; ignore needs marked "order only".
   If one is missing, stop and say which.
4. **Branch.** `git checkout -b <branch from the task file>`. If that branch
   already exists, stop and ask me.
5. **Read.** `CLAUDE.md`, `SPEC.md` Parts 1 and 2, the task file, every file
   under its *Read first*, and the sections of `tasks/NOTES.md` for the tasks
   it needs.
6. **Build.** Do only this task. Touch only the files the task lists under *Files*.
7. **Check.** `python -m pytest` and `python -m orbit demo` must both pass.
   Fix and rerun until they do. If pandas or another package is missing, run
   `python -m pip install -e ".[dev]"` first.
8. **Stop before committing.** Do not commit, push or merge. End with:
   - what you built, in plain words;
   - the output of `git status --short`;
   - the test count, and AST-01's level on days 89 and 90 in the demo;
   - a short **Hand-off** list: what later tasks need to know (names,
     signatures, gotchas).

   Then tell me to review the changes in Source Control and type `/ship` when ready.

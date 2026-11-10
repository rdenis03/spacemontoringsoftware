---
name: ship
description: Finish the current ORBIT task branch. Re-runs the tests, commits only the task's files, opens and merges the pull request with gh, and returns to main.
disable-model-invocation: true
allowed-tools: Bash(git status*) Bash(git add*) Bash(git commit*) Bash(git push*) Bash(git checkout*) Bash(git pull*) Bash(git branch*) Bash(git log*) Bash(gh --version) Bash(gh auth status) Bash(gh pr *) Bash(python -m pytest*) Bash(python -m orbit*)
---

# Ship the current task

1. **Which task.** `git branch --show-current` must look like `data/bNN-...`.
   The task ID is `BNN` in upper case; open `tasks/BNN-*.md`. If the branch is
   `main` or does not match, stop.
2. **Tests.** Run `python -m pytest` and `python -m orbit demo`. If either
   fails, stop and show the failure. Never ship a failing task.
3. **Files.** Run `git status --porcelain`. Every changed or new file must be
   in the task's *Files* list; `tasks/NOTES.md` and `tasks/README.md` are also
   allowed. If anything else is listed, stop, list it, and ask me. Never stage
   files outside the list.
4. **Demo story.** If `tests/test_pipeline.py` changed and the task is not
   B10, stop and ask me first.
5. **Notes.** Append a section `## BNN · <task title>` to `tasks/NOTES.md`
   with this task's hand-off notes (names, signatures, gotchas later tasks
   need), at most 15 lines. In `tasks/README.md`, tick the task on the board:
   `| [ ] | [BNN]` becomes `| [x] | [BNN]`.
6. **Commit.** `git add` the task's files plus `tasks/NOTES.md` and
   `tasks/README.md`, each by name, never `git add .`. Commit with the message
   `BNN: <task title>` and a 2–4 line body saying what was built.
7. **Push.** `git push -u origin <branch>`.
8. **Pull request.** If `gh auth status` succeeds: write the summary and the
   hand-off notes to a file in the system temp folder (not in the repo), run
   `gh pr create --base main --head <branch> --title "BNN: <task title>" --body-file <that file>`,
   then `gh pr merge <branch> --merge --delete-branch`. If `gh` is missing or
   not logged in, stop after the push and tell me to open the pull request on
   GitHub with base `main` ← compare `<branch>`.
9. **Back to main.** `git checkout main` and `git pull`. If the local branch
   still exists, `git branch -d <branch>`.
10. **Next.** Name the next task in "Order for one person" in
    `tasks/README.md` that is not ticked yet, and tell me to start it with `/task <ID>`.

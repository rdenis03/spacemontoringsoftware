# Backend tasks

The ORBIT backend, cut into 22 small jobs. Each file in this folder is one job
for one AI agent (or one person): one branch, one pull request, one test file.

- **Full module specs:** [SPEC.md](../SPEC.md), Part 3. Tasks point to it
  instead of repeating it.
- **Design reasons:** [ARCHITECTURE.md](../ARCHITECTURE.md).
- **Who does what:** [WORKPLAN.md](../WORKPLAN.md). Person A does the whole
  backend (every task here, including the API). Person B does only
  `frontend/`, from its own brief (the *ORBIT Frontend Architecture* doc).
- **Branches:** one per task, with A's prefix: `data/b01-scenario-labels`,
  `data/b02-simulator-healthy`, ... Each task file names its branch.

## Fastest way: two commands

In Claude Code (the VS Code panel or the terminal), one task is two commands:

1. **`/task B02`**: checks that nothing is uncommitted, updates `main`, makes
   the task's branch, reads the spec and the notes from earlier tasks, does
   the task, runs the tests and stops. Nothing is committed yet.
2. Review the changes in Source Control. Then **`/ship`**: re-runs the tests,
   checks that only the task's files changed, writes the hand-off notes to
   [NOTES.md](NOTES.md), ticks the board, commits, pushes, opens and merges the
   pull request, and returns to `main`.

`/ship` needs the GitHub CLI, installed and logged in once: `winget install --id GitHub.cli -e`,
reopen VS Code, then `gh auth login`. Without it, `/ship` stops after the
push and you open the pull request on GitHub.

The commands live in `.claude/skills/task/` and `.claude/skills/ship/`. If
`/task` does not appear when you type `/`, ask Claude: "Follow
.claude/skills/task/SKILL.md for B02".

## How to run a task by hand

1. Start a branch from the latest `main`:

   ```bash
   git checkout main
   git pull
   git checkout -b data/b02-simulator-healthy
   ```

2. Start Claude Code in the repo folder and paste (change the task ID):

   ```text
   Do task B02 from the tasks/ folder.
   First read CLAUDE.md, then SPEC.md Parts 1 and 2, then tasks/B02-*.md and
   every file it lists under "Read first".
   Do only this task and touch only the files it lists under "Files".
   Before you finish, `python -m pytest` and `python -m orbit demo` must both pass.
   Commit with the message "B02: <what you did>".
   End with: what you built, the files you changed, and what the next task
   needs to know.
   ```

3. Read the diff, push the branch, open a pull request, merge when the
   tests are green. Tick the task on the board below.

One agent per task. Tasks in the same wave can run at the same time on
separate branches. The API lane (B13 to B18) runs one task at a time, because
every API task edits `orbit/api/app.py`.

## Board

| Done | ID | Task | Lane | Needs | Size |
|---|---|---|---|---|---|
| [x] | [B01](B01-scenario-labels.md) | Scenario labels schema | Simulator | none | S |
| [x] | [B02](B02-simulator-healthy.md) | Simulator v1: healthy crew | Simulator | B01 | M |
| [ ] | [B03](B03-simulator-illness.md) | Simulator v2: illness episodes and labels | Simulator | B02 | M |
| [ ] | [B04](B04-simulator-lookalikes.md) | Simulator v3: look-alikes and sensor faults | Simulator | B03 | M |
| [ ] | [B05](B05-evaluation-metrics.md) | Evaluation metrics | Evaluation | B01 | S |
| [ ] | [B06](B06-evaluation-runner.md) | Evaluation runner and CLI | Evaluation | B04, B05 | M |
| [x] | [B07](B07-scorer-features.md) | Feature extraction for the AI scorer | AI | none | S |
| [ ] | [B08](B08-learned-scorer.md) | Learned scorer module (placeholder weights) | AI | B07 | S |
| [ ] | [B09](B09-train-scorer.md) | Train the scorer on simulated missions | AI | B04, B07, B08 | M |
| [ ] | [B10](B10-compare-and-switch.md) | Compare learned vs starter, then switch | AI | B06, B08, B09 | S |
| [ ] | [B11](B11-wearable-import.md) | Wearable CSV import | Data | none | M |
| [ ] | [B12](B12-space-weather.md) | NASA space weather feed | Data | none | M |
| [x] | [B13](B13-api-past-day.md) | Past-day endpoint for replay | API | none | S |
| [ ] | [B14](B14-api-consent.md) | Consent editing endpoint | API | B13 (order only) | S |
| [ ] | [B15](B15-api-shared-status.md) | Shared status for the crew view | API | B14 (order only) | S |
| [ ] | [B16](B16-outbox.md) | Outbox with comms delay | API | B15 (order only) | M |
| [ ] | [B17](B17-earth-report.md) | Plain-language report for Earth | API | B16 | S |
| [ ] | [B18](B18-auto-send.md) | Auto-send on orange or red | API | B17 | S |
| [ ] | [B19](B19-action-cards.md) | Action cards v2 | Crew guidance | none | S |
| [ ] | [B20](B20-live-demo-tool.md) | Live body demo tool | Demo | none | S |
| [ ] | [B21](B21-ewma-baseline.md) | EWMA baseline (stretch) | Analytics | none | S |
| [ ] | [B22](B22-cusum-detector.md) | CUSUM detector (stretch) | Analytics | none | S |

S = one short agent session. M = a longer one, or two.
"Order only" means the task does not use the earlier one; it waits so the two
do not edit `orbit/api/app.py` at the same time.

## Waves

| Wave | Start these together |
|---|---|
| 1 | B01, B07, B11, B12, B13, B19, B20 |
| 2 | B02, B05, B08, B14 |
| 3 | B03, B15 |
| 4 | B04, B16 |
| 5 | B06, B09, B17 |
| 6 | B10, B18 |
| Any time | B21, B22 |

## Order for one person

Every task comes after the tasks it needs, and the endpoints the frontend
waits for come early:

B01 → B13 → B02 → B07 → B03 → B14 → B04 → B05 → B15 → B20 → B06 → B08 →
B16 → B09 → B17 → B10 → B18 → B19 → B11 → B12 → B21 → B22

**Critical path:** B01 → B02 → B03 → B04 → B09 → B10. The simulator is the
long pole. If it runs late, B09 can first train on B03's output (illness only,
no look-alikes) and retrain after B04 lands.

## Shared files

Each task writes its own test file, so most tasks never touch the same file.
These are the exceptions:

| File | Touched by | Rule |
|---|---|---|
| `orbit/modules/__init__.py` | B02, B08, B11, B12, B21, B22 | One import line per task. Merge conflicts here are one line: keep both. |
| `orbit.toml` | B10 (scorer), B11 (a commented-out source example), B16 and B18 (`[comms]`), B19 (`cards_path`) | Change only your block. Starters stay active until B10. |
| `pyproject.toml` | B08 (package data), B09 (`[train]` extra) | In a separate commit. |
| `orbit/schema/__init__.py` | B01 | Add exports only. |
| `orbit/core/store.py`, `orbit/core/config.py` | B16, B18 | Only the `outbox` table and the `[comms]` section. |
| `orbit/api/app.py`, `orbit/__main__.py` | B13 to B18 (`__main__.py`: B16 only) | One task at a time, in order. |
| `README.md` | B06 writes *Results*, B10 updates it | Only the *Results* section. |
| `tests/test_pipeline.py` | B10 only, on purpose | Pins the demo story: AST-01 yellow on day 89, orange on day 90. |

## Steps an agent cannot do

- **B12:** record one real response per DONKI endpoint, with internet access
  and an API key, and save it under `tests/fixtures/donki/`.
- **B20:** the wearer's real resting values, or a watch export.
- **B10:** if the learned scorer changes the demo story, the team agrees on
  the new one before it merges.

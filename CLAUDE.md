# ORBIT: notes for Claude Code

ORBIT is an immune early-warning system for astronauts on long missions
(NASA Space Apps challenge). Python 3.11+, pydantic v2, FastAPI, SQLite.

**Before changing anything, read `SPEC.md` Parts 1 and 2.** Then:

- **Given a task ID (B01 to B20; B12 was dropped):** read `tasks/<ID>-*.md` and every file it
  lists under *Read first*. The task says which files you may touch, what to
  build, the tests to add and when you are done. Do only that task.
- **Otherwise:** read the section in `SPEC.md` Part 3 for the module you are
  building. It lists the files you own, the interface you plug into, the
  requirements and when you are done.

`ARCHITECTURE.md` explains why the system is built this way. `tasks/README.md`
shows the order of the tasks and which files they share.

## Commands

```bash
pip install -e ".[dev]"
python -m pytest                          # must pass before you finish
python -m pytest tests/test_contracts.py  # checks every module fits its slot
python -m orbit demo                      # full scenario in memory; must keep working
python -m orbit modules                   # registered and active modules
python -m orbit serve                     # API on :8000, docs at /docs
```

## Rules that matter most

- Data crossing a module boundary uses `orbit.schema` models, never dicts.
- Datetimes are timezone-aware UTC; analytics modules use `ctx.as_of`, never the clock.
- Units, labels and ranges come from `get_spec(signal)`, never hard-coded.
- Analytics modules are pure: no database, network, file writes or unseeded randomness.
- Add modules with `@register(slot, name)` and import them in `orbit/modules/__init__.py`;
  keep the starter modules registered.
- Do not edit `orbit/schema/`, `orbit/core/` or `examples/*.jsonl` unless your
  task file or your section in SPEC.md says so.
- Touch only the files your task lists, and put your tests in the task's own test file.
- Keep the starters active in `orbit.toml` unless your task says to switch.
- The demo story in `tests/test_pipeline.py` (AST-01 yellow on day 89, orange
  on day 90) changes only when the team agrees.
- Medical weights, thresholds and action cards are illustrative, never clinical advice.
- Paths in a config file are relative to that file: in `experiments/*.toml`,
  write `../data/...` and `../examples/...` to reach the project root.
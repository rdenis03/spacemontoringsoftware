# ORBIT frontend

One React + TypeScript + Vite app that talks only to the ORBIT HTTP API.
The look is described in [DESIGN.md](DESIGN.md).
Charts use Recharts; everything is bundled, so it runs with no internet.

## Run it

Backend first (from the repository root):

```
.venv\Scripts\activate
python -m orbit serve
```

Then, in `frontend/`:

```
npm install
npm run dev          # http://localhost:5173
```

Other scripts:

| Script | Does |
|---|---|
| `npm run types` | Regenerates `src/api/schema.ts` from the running backend's OpenAPI. Run it after every backend change. |
| `npm run build` | Type-checks and builds into `dist/`. |
| `npm run lint` | Oxlint. |

The API address defaults to `http://localhost:8000`; set `VITE_API_URL` to change it.

## Screens

| Route | Module | What it shows |
|---|---|---|
| `/` | M15 chat (tab "Chat", the home screen) | A messaging layout. Empty state: "How are you feeling today?", the mission day and time as a pill (editable for the demo), the composer in the middle and a link to the quick form. Your messages on the right, ORBIT's questions on the left with large answer buttons (scale words with severity dots, Yes/No, choices), "Skip" and "That's all". Once started, the composer is pinned to the bottom (1,000 characters, counter near the limit; Enter sends, Shift+Enter adds a line). ORBIT's last message is **the report**: symptoms with severity as a segmented control and "I don't have this" (saves none), complaints outside the 8 signals "For the medical officer", your other answers (read-only: the API takes only the open question), "What ORBIT sees (not a diagnosis)" as likely or possible with one line of reasons, never a percentage, and "What to do" (each card expands to its steps). "Save to my check-in" or "Discard". After saving the same card shows the level, score before → after (before = latest saved assessment at or before the chat's time, read when the chat starts), the action cards and "Start a new chat". A red flag replaces the conversation with one full-width banner and asks no more questions. The session is in the URL (`?session=`), so a reload resumes it; the transcript is kept per tab in sessionStorage. |
| `/today` | M12 dashboard (tab "Today") | **Today**: status card (level circle and word, score, score meter on the level bands, change vs yesterday; assessed time and model under "Show details"), "Why" as a grouped list (points and bar; "your normal" band, reading and "Without it" under "Show details"), action cards with a checklist and progress ("Why this" behind a disclosure). **Trends**: every sensor in grouped lists by category (state, value, sparkline over the normal) and the chosen sensor on coloured zones in a sticky card, with a legend and a table; symptoms, mood and stress use neutral severity dots instead of zones. **History**: score on level bands with a legend, early warning (alert day vs first symptom), mission replay slider. |
| `/checkin` | M11 quick form (linked from the chat) | 8 symptoms preset to "none" (severity dots), optional mood, stress and note; a sticky "Review and save" card with the mission-time pill. Shows the new status, score before → after, top reasons and cards. Keeps the answers on failure; lists 422 messages. Links back to the chat. |
| `/checkin/chat` | – | Redirects to `/` with the same query (`?session=`, `?astronaut=`), so old links still work. |
| `/crew` | M14 crew view (tab "Crew") | Every astronaut worst first: level, score, 14-day score line, top reason; last check-in and escalation under "Show details"; "View shared status" opens the detail. All of it comes from `/status?view=shared`, so private reasons show as "Private reason". |
| `/earth` | M13 Earth comms (tab "Earth") | Consent switch per category, what Earth would receive (score and level always, private reasons hidden; readings sent vs kept onboard under "Show readings"), send over a Moon (1.3 s) or Mars (`[comms]`) link, outbox with a live countdown. |

The astronaut, tab, signal and chat live in the URL (`/today?astronaut=AST-01&tab=trends&signal=skin_temp`, `/?astronaut=AST-01&session=tri-…`).

## Layout

```
src/
  api/          client.ts (every API call), schema.ts (generated), types.ts (friendly names)
  components/   card Frame, level circle and tag, severity dots, mission-time picker, scale question, chart dots, "your normal" band, sparkline, segmented tabs, states
  lib/          formatting, levels, sensor zones, polling hook, chart helpers, colour tokens for charts
  routes/       triage/ (M15 chat, home), dashboard/ (M12), checkin/ (M11 quick form), crew/ (M14), earth/ (M13)
  state/        signal registry and crew (loaded once), current astronaut
  styles/       tokens.css (colours, type scale, spacing, motion), global.css (type roles, cards, grouped lists, controls)
```

## Rules

- Types are generated, never hand-written. The one exception is `GET /api/signals`,
  which has no OpenAPI shape; `SignalRegistry` in `types.ts` mirrors `registry_document()`.
- Labels, units, scale words and level thresholds come from `GET /api/signals`.
- Levels and sensor states are a coloured circle plus a word. Severity uses neutral dots, never level colours.
- Design: calm and minimal, inspired by Apple's Human Interface Guidelines. See [DESIGN.md](DESIGN.md)
  for colour, type, shape, spacing, navigation, controls, motion and charts. Tokens live in
  `styles/tokens.css`; light and dark both follow the system setting. Inter is bundled from
  `@fontsource-variable/inter` (SIL OFL), so nothing loads from a CDN. Level colours have a mark
  (`--level-X`) and a text colour (`--level-X-ink`) and mean alert level and nothing else.
- Mission time from the data (UTC), never the wall clock. Status is polled every 60 s.
- Sensor zones (`lib/zones.ts`): distance from the personal normal in spreads, worrying direction
  only: green < 1.5, yellow 1.5–2.5, orange 2.5–4, red ≥ 4. The first two steps match the starter
  detector's defaults in `orbit.toml`; update them if the detector is retuned.
- Scores, zones and action cards are illustrative for the demo, not medical advice.

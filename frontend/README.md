# ORBIT frontend

One React + TypeScript + Vite app that talks only to the ORBIT HTTP API.
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
| `/` | M12 dashboard | **Today**: status column with a vertical score meter and change vs yesterday, contributor cards (points, "your normal" band, score without it), action cards with progress. **Trends**: every sensor in a list (state, value, sparkline over the normal) and the chosen sensor on coloured zones in a sticky frame. **History**: score on level bands, early warning (alert day vs first symptom), mission replay slider. |
| `/checkin` | M11 check-in | 8 symptoms preset to "none", optional mood, stress and note; a sticky "Review & save" panel with the mission-time stamp. Shows the new status, score before → after, top reasons and cards. Keeps the answers on failure; lists 422 messages. |
| `/crew` | M14 crew grid | Every astronaut worst first: level, score, 14-day score line, top reason, last check-in, escalation. The privacy-filtered detail (`?view=shared`) waits on the backend. |

The astronaut, tab and signal live in the URL (`?astronaut=AST-01&tab=trends&signal=skin_temp`).

## Layout

```
src/
  api/          client.ts (every API call), schema.ts (generated), types.ts (friendly names)
  assets/fonts/ Roboto (variable, latin + latin-ext; Apache 2.0), bundled so nothing loads from a CDN
  components/   blueprint Frame, level icon and tag, level-shaped chart dots, "your normal" band, sparkline, tabs, states
  lib/          formatting, levels, sensor zones, polling hook, chart helpers, colour tokens for charts
  routes/       dashboard/ (M12), checkin/ (M11), crew/ (M14)
  state/        signal registry and crew (loaded once), current astronaut
  styles/       tokens.css (colours, type scale, spacing), global.css
```

## Rules

- Types are generated, never hand-written. The one exception is `GET /api/signals`,
  which has no OpenAPI shape; `SignalRegistry` in `types.ts` mirrors `registry_document()`.
- Labels, units, scale words and level thresholds come from `GET /api/signals`.
- Levels and sensor states always use colour + word + shape (circle, diamond, triangle, square).
- Design: "ORBIT Instrument" (Industry design system, dark instrument theme): square hairline
  "blueprint" frames with corner marks, uppercase tracked labels, Roboto, steel-blue accent.
  Tokens live in `styles/tokens.css` (`--color-*` from the design system); dark is the default
  (dim cabin), light follows the system. Level colours have a mark (`--level-X`) and a text
  colour (`--level-X-ink`) and mean state and nothing else.
- Mission time from the data (UTC), never the wall clock. Status is polled every 60 s.
- Sensor zones (`lib/zones.ts`): distance from the personal normal in spreads, worrying direction
  only: green < 1.5, yellow 1.5–2.5, orange 2.5–4, red ≥ 4. The first two steps match the starter
  detector's defaults in `orbit.toml`; update them if the detector is retuned.
- Scores, zones and action cards are illustrative for the demo, not medical advice.

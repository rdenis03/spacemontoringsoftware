# ORBIT design

Calm and minimal, inspired by Apple's Human Interface Guidelines and apps
like Health, Settings and Fitness. Inspired, not copied: no Apple logos, no
SF Symbols, no assets from Apple apps. Our icons are simple line drawings in
inline SVG (`App.tsx`).

The aim is that an astronaut in a dim cabin can answer "Am I OK? Why? What
do I do?" at a glance, with nothing on screen that does not help answer it.

All values live in `src/styles/tokens.css`. Shared classes are in
`src/styles/global.css`. Charts read colours through `src/lib/useTokens.ts`.

## Colour

- **Almost all neutral.** Page, cards, text, secondary text and hairlines
  (`--bg`, `--card`, `--text`, `--text-2`, `--separator`).
- **One accent, a calm blue** (`--accent`), used only for links, selection,
  focus and the primary button (`--accent-fill`). Selected rows use
  `--accent-tint`.
- **Level colours mean alert level and nothing else:** green, yellow,
  orange, red, slightly muted. Each has a mark (`--level-X`) for icons,
  chart points and bands, and an ink (`--level-X-ink`) for text. A sensor's
  state (how far a reading is from your normal) uses the same four steps.
- **A level is a coloured circle plus its word** (Green, Yellow, Orange,
  Red). Never colour alone. Where there is no room for the word (chart
  points, the marker on the "your normal" band), the circle carries the word
  as its tooltip and accessible name, and the chart's legend says what the
  colours mean. "No personal normal" is a hollow ring.
- **Severity is not a level.** Severity options and chips use neutral dots
  (`SeverityDots`): an empty ring for none, then one filled dot per step
  (mild ●, moderate ●●, severe ●●●). The selected option uses the accent.
  The same goes for the symptom, mood and stress charts in Trends: grey
  points, no coloured bands, and the scale word with its dots in the list,
  tooltip and table.
- **Text meets WCAG AA (4.5:1)** in both themes. The measured numbers are in
  the header of `tokens.css`. `--text-3` is for placeholders and decoration
  only.
- **No hard-coded colours** outside `tokens.css`.

## Light and dark

Both follow the system setting (`prefers-color-scheme`) and both are
first-class.

| | Light | Dark |
|---|---|---|
| Page | off-white `#f5f5f7` | near-black `#0c0c0e` |
| Cards | white | dark grey `#1c1c1e` |
| Accent | `#0b63c4` | `#5aa2f5` (button fill `#2b72c8`) |

Dark is tuned to be readable in a dim cabin: no pure white on pure black,
and level inks lighter than their marks.

## Type

- **Font stack:** `-apple-system, BlinkMacSystemFont, "Inter Variable",
  system-ui`. Inter is bundled from `@fontsource-variable/inter`, so nothing
  loads from a CDN.
- **Sentence case everywhere.** No uppercase, tracked labels.
- **Tabular numbers** for scores and readings (`.figure`, `.data`).
- **Scale:**

| Role | Size | Class |
|---|---|---|
| Large title (one per screen) | 34 px bold | `.large-title` |
| Title (section) | 22 px bold | `.title`, `.section-label` |
| Headline | 17 px semibold | `.headline` |
| Body | 17 px | default |
| Secondary | 15 px | `.secondary` |
| Caption | 13 px | `.caption`, `.kicker` |

## Shape and depth

- **Corners:** cards 14 px (`--radius-card`), controls 10 px
  (`--radius-control`), and segmented controls pill-shaped.
- **No frames and almost no shadows.** Cards stand out from the page by
  colour alone. A soft shadow appears only on tooltips and on the selected
  segment in light mode.
- **Inset grouped lists:** related rows sit together in one card (`.group`
  with `.row` or `li`), with hairline separators inset 16 px from the left,
  like a settings screen.

## Space

- An 8 px grid (`--space-1` to `--space-7`).
- Generous margins and one idea per card. Fewer borders and badges, no
  decorative lines; hairlines only separate rows in a grouped list.
- **Secondary detail goes behind "Show details"** (`.disclosure`, a native
  `<details>` with a small chevron): contributor bands and "Without it",
  the model name and assessed time, last check-in and escalation on crew
  cards, raw reading counts on Earth. Nothing is removed, only folded away.
- Content at most 1100 px wide (`--content-width`).

## Navigation

- A translucent top bar (backdrop blur) with the ORBIT mark, the current
  screen's name, mission time and the astronaut picker.
- **The chat is the app.** The four tabs are Chat, Today, Crew, Earth, a
  segmented control in the bar. Below 760 px they move to a tab bar at the
  bottom of the screen.
- Routes: `/` (chat), `/today`, `/crew`, `/earth`, and `/checkin` (the quick
  form, a plain link in the chat). `/checkin/chat` redirects to `/` with its
  query, so old links still work.

## The chat

- Laid out like a messaging app, not a form, in a centred column. Before
  the first message everything sits in the middle of the screen: the ORBIT
  mark, one line ("How are you feeling today?"), the mission time as a quiet
  pill (`MissionTimePicker`: opens a small panel with a day stepper and a
  time field) and the composer. Once the chat starts, the composer is pinned
  to the bottom.
- The astronaut's messages on the right, ORBIT's on the left, both neutral
  (the accent is for actions). The composer is a rounded field with a hairline
  and a soft shadow; "Send" is a compact accent pill with an arrow.
- ORBIT's question is a bubble with large answer buttons under it; "Skip"
  and "That's all" are plain text.
- The report is ORBIT's last message and the one thing to review. After
  saving, the same card becomes the result.
- A red flag replaces the conversation with one full-width banner.

## Controls

- **Touch targets at least 44 px** (`--target`).
- **One filled primary button per screen** (`.btn-primary`). Every other
  button is plain accent text (`.btn-secondary`, `.btn-ghost`).
- **Segmented controls** for tabs, scale answers and choices like the comms
  link.
- **Switches** for on/off settings.
- **Visible focus rings** in the accent.

## Motion

- Short (150 to 250 ms) and subtle: fades and small slides only.
- None under `prefers-reduced-motion`.

## Charts (Recharts)

- Thin lines with no grid, or a very faint one, and few labels.
- The accent for the main series, and the text colour for its axis.
- Level colours only for level bands and points. Points are circles with
  their word as a tooltip; a legend under the chart says what the colours
  mean.
- Every chart has a written summary and a table view, so the numbers never
  live only in the picture.

## Wording

Medical weights, thresholds and action cards are illustrative, never
clinical advice. Labels, units, scale words and thresholds come from
`/api/signals`.

# ORBIT quick guide

How to use the app in a few minutes. For what ORBIT is and how it works inside,
see the [README](README.md).

> **Not medical advice.** All data is simulated, and the procedures are illustrative.

## Start the app

First time? Install everything with the [Quick start](README.md#quick-start) in
the README. Then open **two terminals** in the project folder:

```bash
# terminal 1: backend
python -m orbit serve

# terminal 2: frontend
cd frontend
npm run dev
```

Open **http://localhost:5173** in your browser.

## How the app works

The app opens on the **chat**. Pick the astronaut at the top right. The demo
has two: **Vega (AST-01)**, who gets ill, and **Altair (AST-02)**, who stays well.

1. **Say how you feel.** Type it in your own words in the box at the bottom
   and press **Send** (or Enter). The small pill under the title sets the
   mission day and time for the demo.
2. **Answer a few questions.** ORBIT asks one question at a time, with large
   answer buttons. **Skip** passes a question; **That's all** finishes early.
3. **Check the report.** At the end ORBIT shows what it understood:
   - **Symptoms** and how strong they are. Change any of them, or tap
     *I don't have this*.
   - **What ORBIT sees:** possible patterns marked *likely* or *possible*,
     never a diagnosis.
   - **What to do:** the procedures, each opening to its steps.
4. **Save it.** **Save to my check-in** stores it and re-assesses right away:
   you see your level, the score before → after, and what to do. **Discard**
   closes the chat without saving anything to your check-in.
5. **If something is urgent,** a red banner replaces the chat at any point:
   *Get medical help now*.
6. **Today** shows your level and score, **Why** (the reasons, with
   *Show details* for the numbers) and **What to do now** as a checklist.
   **Trends** shows every sensor against your normal, and **History** replays
   the mission day by day.
7. **Quick check-in** (a link in the chat) is the 60-second form: 8 symptoms,
   mood, stress and a note.
8. **Crew** is for the commander and the crew medical officer: everyone,
   worst first, showing only what each astronaut shares.
9. **Earth** lets each astronaut choose what to share, shows exactly what
   Earth would receive, and sends it over a Moon or Mars delay.

## Try it: the demo story

Vega's immune system starts to slip at the end of the example data:

- **Day 89: 🟡 Yellow (27.7).** Skin temperature a little up, heart rate
  variability down, breathing a little faster, mild fatigue, and a spacewalk
  that day. The first procedure: take a saliva sample.
- **Day 90: 🟠 Orange (70.2).** The saliva test finds the virus behind
  shingles: reduce workload and tell the crew medical officer.

Open **Today** and use **History → replay** to watch it happen day by day.

## Try it: the chat

1. Choose **Vega**, then set the chat's day and time to **Day 89 · 10:30**.
2. Type: *Weird burning, tingly patch on my ribs since last night. Pretty wiped out too.*
3. Answer **Moderate**, then **Yes** (one side), then **None** (fever).
4. The report shows shingles as **likely**, with "Take a saliva sample" first.
5. Save it: the score goes **27.7 → 44.7** (still yellow), with the procedures.

More to try:

| Type this | What happens |
|---|---|
| *I can't breathe properly.* | 🔴 A red banner: "Get medical help now", with no questions. |
| *Fever and chills since last night, sore throat and a headache.* | Fits a chest or throat infection. |
| *After yesterday's spacewalk my whole body aches and I'm wiped out.* | Fits hard physical work. |
| *No rash, but a burning patch on my back.* | The burning patch is kept and the rash is not: ORBIT understands "no". |

The same chat runs in the terminal too:

```bash
python -m orbit triage AST-01 "Weird burning, tingly patch on my ribs since last night. Pretty wiped out too." \
    --as-of 2027-04-02T10:30:00Z --answer moderate --answer yes --answer none
```

## Good to know

- **Patterns are never a diagnosis.** ORBIT says *likely* or *possible*, and a
  red flag always wins over any pattern.
- **Your data stays onboard** unless you choose to share it on the Earth screen.
  The crew view shows only what you share.
- **To put the demo data back:** stop `serve`, run `python -m orbit reset`,
  then start `serve` again.

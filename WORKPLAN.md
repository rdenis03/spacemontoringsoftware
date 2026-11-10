# ORBIT: plan de lucru pentru 2 oameni

Împărțim munca pe straturi ale proiectului, ca fiecare să aibă fișierele lui
și să ne încurcăm cât mai puțin:

- **Persoana A (Backend):** tot ce rulează în Python: de unde vin datele, cum
  se calculează scorul (inclusiv scorer-ul AI), API-ul, cardurile de acțiune
  și trimiterea datelor spre Pământ.
- **Persoana B (Frontend):** tot ce vede utilizatorul, adică aplicația din
  `frontend/`.

A și B comunică doar prin **API** și prin **schema de date** (`orbit/schema/`),
care e deja fixă. Dacă A îmbunătățește scorul, rezultatul apare automat în
interfața lui B, fără ca B să schimbe ceva. Nimeni nu trebuie să-l aștepte pe
celălalt.

- Specificațiile detaliate ale fiecărui modul (fișiere, opțiuni, cerințe, când
  e gata) sunt în [SPEC.md](SPEC.md), Partea 3.
- Munca de backend e împărțită în 19 sarcini mici, câte una pentru fiecare
  agent AI, în [tasks/](tasks/README.md). Acolo sunt ordinea, dependențele și ce
  poate rula în paralel. B12 (furtuni solare NASA DONKI), B21 (baseline EWMA) și
  B22 (detector CUSUM) au fost scoase din plan.
- Brief-ul pentru frontend este documentul *ORBIT Frontend Architecture*
  (ecrane, endpoint-uri, ce merge deja și ce vine).
- Deciziile de design sunt în [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Persoana A: Backend

| Ordine | Sarcini | Ce face | Efort |
|---|---|---|---|
| 1 | **B01–B04 Simulator (M2)**, plus `orbit/schema/labels.py` | Misiune de 180 de zile cu boli și confounderi etichetați | Mare (drumul critic) |
| 2 | **B13–B18 API pentru frontend** | Replay pe zile trecute, consimțământ, crew view (`?view=shared`), outbox cu întârziere, raport spre Pământ, trimitere automată pe orange/red | Mediu |
| 3 | **B05–B06 Evaluare (M9)** | Lead time, sensibilitate, alarme false pe 30 de zile | Mediu |
| 4 | **B07–B10 Scorer AI (M8)** | Scorer învățat pe misiuni simulate, explicabil, comparat cu starter-ul prin M9 | Mediu |
| 5 | **B11, B19, B20** | Import CSV de la wearable-uri, carduri de acțiune v2, unealta pentru demo-ul live | Mic–mediu |

Sarcinile B13 (replay) și B20 (demo live) sunt în primul val, pentru că B are
nevoie de ele devreme. Ordinea exactă e în `tasks/README.md`.

**Fișierele lui A:** tot ce nu e în `frontend/`, cu regulile din `tasks/README.md`:

- `orbit/modules/` (module noi și `__init__.py`), `orbit/learning/`, `orbit/evaluation/`
- `orbit/schema/labels.py` și exportul lui din `orbit/schema/__init__.py`
- `orbit/api/` (**doar A** modifică API-ul)
- `orbit/core/store.py` (doar tabela `outbox`) și `orbit/core/config.py` (doar
  secțiunea `[comms]`)
- `cards/action_cards.jsonl`, `experiments/*.toml`, `tools/`
- `orbit.toml`, `pyproject.toml`
- testele din `tests/`

## Persoana B: Frontend

| Ordine | Modul | Ce face | Efort |
|---|---|---|---|
| 1 | **M12 Dashboard** | Today (status, motive, carduri), Trends, History, plus slider-ul de replay | Mare |
| 2 | **M11 Check-in** | Formular de sub 60 de secunde, cu reevaluare imediată | Mic–mediu |
| 3 | **M14 Crew view** | Grilă pentru comandant și ofițerul medical; detaliul folosește `?view=shared` (B15) | Mic–mediu |
| 4 | **Earth comms** | Outbox cu countdown, consimțământ, Moon/Mars mode (endpoint-uri: B14, B16–B18) | Mediu |

**Fișierele lui B:**

- `frontend/`, tot folderul. B nu modifică fișiere Python: dacă are nevoie de
  o schimbare în API, i-o cere lui A.

---

## Fișiere comune și regulile lor

Doar aceste fișiere sunt atinse de amândoi:

| Fișier | Regulă |
|---|---|
| `README.md` | A scrie secțiunea *Results* și secțiunea despre API, B scrie doar secțiunea despre frontend. |
| `tests/test_pipeline.py` (povestea demo: AST-01 yellow în ziua 89, orange în ziua 90) | A o schimbă doar după ce B e de acord, **înainte** de merge. Pitch-ul se bazează pe ea. |
| `frontend/src/api/schema.ts` (tipurile generate) | Când A schimbă API-ul, îl anunță pe B, iar B regenerează tipurile. |

**Nu le modifică nimeni:** restul din `orbit/schema/`, restul din `orbit/core/`
și `examples/*.jsonl` (acestea se regenerează doar cu `examples/make_examples.py`).
O dependență nouă în `pyproject.toml` se adaugă într-un commit separat.

---

## Git

- Câte un branch pentru fiecare sarcină, cu prefixul persoanei. Pe un branch
  lucrează doar persoana respectivă (și agenții ei):
  - A: `data/b01-scenario-labels`, `data/b13-api-past-day`, ... (numele e scris
    în fiecare fișier din `tasks/`)
  - B: `ui/m12-dashboard`, `ui/m11-checkin`, ...
- Doi agenți în paralel au nevoie de două clone separate ale repo-ului, nu de
  același folder.
- Înainte de fiecare PR, adu-ți branch-ul la zi cu `main`
  (`git pull origin main`), ca să rezolvi conflictele la tine, nu în `main`.
- Merge în `main` doar prin PR și doar dacă trec:
  ```bash
  python -m pytest
  python -m orbit demo
  ```
- Merge-uri dese, ideal cel puțin o dată pe zi, ca să nu se adune diferențe mari.
- Starter-ele rămân înregistrate și active în `orbit.toml` până când modulul nou
  trece testele de contract și comparația M9.

---

## Baza de date: SQLite local

- Fiecare lucrează cu **propria bază SQLite locală** (`data/orbit.db`, din
  `[storage]` în `orbit.toml`). Nu există server și nici bază comună.
- `data/` și `*.db` sunt în `.gitignore`: **baza de date nu se pune în git.**
  Ce împărțim sunt datele sursă (`examples/`, simulatorul), din care oricine
  poate reconstrui baza.
- `python -m orbit serve` încarcă automat datele de exemplu dacă baza e goală.
- `python -m orbit demo` rulează totul în memorie și nu atinge baza locală.
- Dacă baza ajunge într-o stare ciudată sau s-a schimbat structura ei (de
  exemplu, A adaugă tabela `outbox` în B16):
  ```bash
  python -m orbit reset    # șterge baza locală
  python -m orbit ingest   # o reîncarcă din sursele din orbit.toml
  python -m orbit run      # recalculează evaluările
  ```
- Ca să încerci simulatorul fără să-ți strici baza obișnuită, folosește un
  config separat cu altă cale în `[storage]`, de exemplu `experiments/sim180.toml`
  cu `database = "data/sim180.db"`.

---

## Când ne sincronizăm (doar de 3 ori)

1. **La început (15 minute):** confirmăm împărțirea. B pornește
   `python -m orbit serve` și generează tipurile TypeScript:
   `npx openapi-typescript http://localhost:8000/openapi.json -o frontend/src/api/schema.ts`
2. **După M9 (B06, apoi B10):** A trimite cifrele (lead time, alarme false),
   iar B le poate afișa în UI sau în pitch.
3. **La final:** freeze (doar bugfix-uri). Rulăm scenariul demo cap-coadă
   împreună: check-in, apoi dashboard pe orange, apoi crew view, apoi pachetul
   spre Pământ. Scriem README-ul și repetăm demo-ul de cel puțin 2 ori, offline.

---

## De ce e echilibrat

A are mai mult cod, dar e tăiat în sarcini mici pe care le fac agenți AI, câte
una pe branch, cu teste clare (vezi `tasks/`). B se concentrează pe interfață,
care e ce văd juriul și utilizatorii. Endpoint-urile de care B are nevoie
devreme (B13 replay, B20 demo live) sunt în primul val.

## Riscuri

| Risc | Ce facem |
|---|---|
| M2 întârzie, deci și M9 întârzie | A face întâi o versiune minimă: doar `viral_reactivation`, fără faults și confounderi |
| Cineva strică demo-ul | Starter-ele rămân active; PR-urile trec doar cu `pytest` și `orbit demo` verzi |
| Frontend-ul se blochează | API-ul funcționează deja cu datele de exemplu (13 endpoint-uri), deci B poate începe din prima zi |
| Endpoint-urile noi ale lui A întârzie | B construiește Earth comms întâi pe date mock, apoi le leagă de API când apar |

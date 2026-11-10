# ORBIT: plan de lucru pentru 2 oameni

Împărțim munca pe straturi ale proiectului, ca fiecare să aibă fișierele lui
și să ne încurcăm cât mai puțin:

- **Persoana A (Date și analiză):** motorul în Python, adică de unde vin
  datele și cum se calculează scorul.
- **Persoana B (Produs și interfață):** tot ce vede utilizatorul: frontend-ul,
  API-ul și cardurile de acțiune.

A și B comunică doar prin **API** și prin **schema de date** (`orbit/schema/`),
care e deja fixă. Dacă A îmbunătățește scorul, rezultatul apare automat în
interfața lui B, fără ca B să schimbe ceva. Nimeni nu trebuie să-l aștepte pe
celălalt.

Specificațiile detaliate ale fiecărui modul (fișiere, opțiuni, cerințe, când e
gata) sunt în spec-ul complet, Partea 3. Deciziile de design sunt în
[ARCHITECTURE.md](ARCHITECTURE.md).

---

## Persoana A: Date și analiză

| Ordine | Modul | Ce face | Efort |
|---|---|---|---|
| 1 | **M2 Simulator**, plus `orbit/schema/labels.py` | Misiune de 180 de zile cu boli și confounderi etichetați | Mare (drumul critic) |
| 2 | **M9 Evaluare** | Lead time, sensibilitate, alarme false pe 30 de zile | Mediu |
| 3 | **M5 DONKI** | Furtuni solare reale de la NASA ca evenimente de context | Mediu |
| 4 | **M7 Detector și M8 Scorer** | Variante mai bune, comparate cu starter-ul prin M9 | Mediu |
| 5 | *(opțional)* **M6 Baseline**, **M3 Ingestion** | Baseline EWMA; import CSV de la wearable-uri reale | Mic–mediu |

**Fișierele lui A:**

- `orbit/modules/` pentru module noi: `simulator.py`, `space_weather.py`,
  `detector_*.py`, `scorer_*.py`, `baseline_*.py`, `ingestion.py`
- `orbit/modules/__init__.py` (**doar A** adaugă importuri aici)
- `orbit/schema/labels.py` și exportul lui din `orbit/schema/__init__.py`
- `orbit/evaluation/`
- `experiments/*.toml`
- testele modulelor lui: `tests/test_simulator.py`, `tests/test_evaluation.py`,
  `tests/test_space_weather.py` și celelalte

## Persoana B: Produs și interfață

| Ordine | Modul | Ce face | Efort |
|---|---|---|---|
| 1 | **M12 Dashboard** | Today (status, motive, carduri), Trends, History | Mare |
| 2 | **M11 Check-in** | Formular de sub 60 de secunde, cu reevaluare imediată | Mic–mediu |
| 3 | **M10 Actions** | Carduri de acțiune pe fiecare virus, pași de follow-up | Mic |
| 4 | **M13 Sync și consent** | Editare consimțământ, outbox cu întârziere de comunicare | Mediu |
| 5 | **M14 Crew view** | Grilă pentru comandant și ofițerul medical, plus `?view=shared` | Mic–mediu |

**Fișierele lui B:**

- `frontend/`, tot folderul
- `orbit/api/app.py` (**doar B** modifică API-ul)
- `orbit/core/store.py` (doar tabela `outbox`) și `orbit/core/config.py` (doar
  secțiunea `[comms]`)
- `orbit/modules/actions.py`, `orbit/modules/consent.py`
- `cards/action_cards.jsonl`
- `tests/test_actions.py`, `tests/test_sync.py`, `tests/test_api.py`

---

## Fișiere comune și regulile lor

Doar aceste fișiere sunt atinse de amândoi:

| Fișier | Regulă |
|---|---|
| `orbit.toml` | A deține fișierul. B modifică doar blocul `[modules.actions]` (pentru `cards_path`). |
| `tests/test_pipeline.py` (povestea demo: AST-01 yellow în ziua 89, orange în ziua 90) | Cine o schimbă îl anunță pe celălalt **înainte** de merge. Pitch-ul se bazează pe ea. |
| `README.md` | A scrie doar secțiunea *Results*, B scrie doar secțiunile despre API și frontend. |
| `pyproject.toml` | O dependență nouă se adaugă într-un commit separat. |

**Nu le modifică nimeni:** restul din `orbit/schema/`, restul din `orbit/core/`
și `examples/*.jsonl` (acestea se regenerează doar cu `examples/make_examples.py`).

---

## Git

- Fiecare persoană are **un branch al ei**, pe care lucrează doar ea:
  - B: `ui/persoana-b`
  - A: `data/persoana-a`
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
  exemplu, B adaugă tabela `outbox` pentru M13):
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
2. **După M9:** A trimite cifrele (lead time, alarme false), iar B le poate
   afișa în UI sau în pitch.
3. **La final:** freeze (doar bugfix-uri). Rulăm scenariul demo cap-coadă
   împreună: check-in, apoi dashboard pe orange, apoi crew view, apoi pachetul
   spre Pământ. Scriem README-ul și repetăm demo-ul de cel puțin 2 ori, offline.

---

## De ce e echilibrat

A are mai mult de lucru la început (simulatorul e cea mai grea parte), iar B
are mai mult spre final (M13 și M14 au nevoie de un dashboard deja
funcțional). Cine termină mai repede preia modulele opționale (M6, M3) fără să
intre peste fișierele celuilalt.

## Riscuri

| Risc | Ce facem |
|---|---|
| M2 întârzie, deci și M9 întârzie | A face întâi o versiune minimă: doar `viral_reactivation`, fără faults și confounderi |
| Cineva strică demo-ul | Starter-ele rămân active; PR-urile trec doar cu `pytest` și `orbit demo` verzi |
| Frontend-ul se blochează | API-ul funcționează deja cu datele de exemplu, deci B poate începe din prima zi |

# CompTIA A+ Practice Exam Simulator

A zero-dependency, browser-based practice exam simulator for CompTIA A+ Core 1 (220-1201) and Core 2 (220-1202) certification exams.

## Features

- **Two-step exam launch:** choose an exam, then choose a mode.
- **Four exam modes:**
  - **Practice Exam** — 25 random questions, 1 minute/question timer, instant feedback.
  - **Simulation Exam** — full question count with the exam timer, no feedback until results (mimics the real CompTIA exam).
  - **Practice by Domain** — filter by exam domain, up to 25 questions.
  - **Practice by Study Module** — filter by CertMaster course module, up to 25 questions.
- **Three exams available:**
  - **Core 1 (220-1201):** 1,205 questions across 5 domains, all objectives, 10 modules.
  - **Core 2 (220-1202):** 16 questions (starter bank).
  - **Acronyms Quiz:** 200 acronym questions.
- **Question types:** multiple-choice, multi-select (with partial-credit scoring), matching (dropdown), and drag-and-drop.
- Every question is tagged with **domain, objective, module, and origin source**, verified against the official CompTIA A+ Certification Exam Objectives v4.
- **📊 My Progress Dashboard** — tracks every completed exam session with:
  - Summary cards (total sessions, best score, latest score, avg last 5)
  - Sortable session history table with per-domain breakdown (click any row to expand)
  - Domain Weakness Tracker with cumulative avg score, trend (↑↓→), and focus flag (🔴🟡🟢)
- **Save & Exit** with full state restoration — question index, answers, timer, mode, and active filter.
- **Question flagging** and re-answering (answered questions lock unless flagged).
- **Dark/light theme** with an anti-flash guard on load.
- **Results dashboard** with a Correct / Partial Credit / Incorrect / Unanswered breakdown.
- **Filterable question review** with explanations for every question.
- **Zero dependencies** — runs in any modern browser, no build step.

## Real Exam Reference

What you're preparing for. These figures describe the actual CompTIA exams, not this practice bank (see [Question Bank Coverage](#question-bank-coverage) for what the app currently contains).

|                | Core 1 (220-1201)                    | Core 2 (220-1202)                    |
|----------------|--------------------------------------|--------------------------------------|
| Questions      | Up to 90                             | Up to 90                             |
| Time           | 90 minutes                           | 90 minutes                           |
| Passing Score  | 675/900                              | 700/900                              |
| Question Types | Multiple-choice + performance-based  | Multiple-choice + performance-based  |

Source: CompTIA A+ Certification Exam Objectives v4, © 2024 CompTIA, Inc.

## Core 1 Domains

The five Core 1 (220-1201) domains and their exam weights:

1. Mobile Devices (13%)
2. Networking (23%)
3. Hardware (25%)
4. Virtualization and Cloud Computing (11%)
5. Hardware and Network Troubleshooting (28%)

## Core 2 Domains

The four Core 2 (220-1202) domains and their exam weights:

1. Operating Systems (28%)
2. Security (28%)
3. Software Troubleshooting (23%)
4. Operational Procedures (21%)

## Question Bank Coverage

### Core 1 (220-1201) — 1,205 questions

The Core 1 question bank draws from three sources, tracked by the `origin` field:

| Source | Origin value | Questions | ID range |
|--------|-------------|-----------|----------|
| Original bank | `"original"` | 160 | `1201-001` – `1201-160` |
| Practice Tests 01–22 | `"PT01-001"` – `"PT22-030"` | 555 | `1201-161` – `1201-715` |
| CertMaster Study Material | `"CertMaster"` | 490 | `CM-1-001` – `CM-10.2-015` |
| **Total** | | **1,205** | |

**Coverage by domain:**

| Domain | Questions | Bank % | Exam weight |
|--------|-----------|--------|-------------|
| 1.0 Mobile Devices | 183 | 15.2% | 13% |
| 2.0 Networking | 416 | 34.5% | 23% |
| 3.0 Hardware | 395 | 32.8% | 25% |
| 4.0 Virtualization and Cloud Computing | 68 | 5.6% | 11% |
| 5.0 Hardware and Network Troubleshooting | 143 | 11.9% | 28% |

**CertMaster questions by module (490 total):**

| Module | Topic | Questions |
|--------|-------|-----------|
| 1.0 | IT Specialist Intro | 5 |
| 2.0 | Motherboards & Connectors | 55 |
| 3.0 | System Devices | 50 |
| 4.0 | Troubleshooting PC Hardware | 50 |
| 5.0 | Local Networking Hardware | 70 |
| 6.0 | Network Addressing & Internet | 75 |
| 7.0 | Network Services | 50 |
| 8.0 | Virtualization & Cloud | 30 |
| 9.0 | Mobile Devices | 75 |
| 10.0 | Print Devices | 30 |

### Core 2 (220-1202) — 16 questions

This is a starter bank — most of the 36 objectives are not yet represented.

### Acronyms — 200 questions

Covers acronyms from both the Core 1 and Core 2 acronym lists. Rebuilt from 8 practice test PDFs (Parts 1–8, 25 questions each).

## Project Structure

```
├── index.html
├── css/
│   └── styles.css
├── js/
│   ├── app.js              ← exam flow, UI, state management
│   ├── scoring.js          ← scoring engine (multi-select, drag-drop, MC)
│   ├── results.js          ← exam history persistence (localStorage)
│   └── dashboard.js        ← My Progress dashboard renderer
├── exam_assets/
│   ├── questions.json              ← all exam data (Core 1 + Core 2 question banks)
│   ├── acronyms_quiz.json          ← acronym quiz data
│   ├── parse_practice_tests.py     ← practice test PDF → JSON parser script
│   ├── extract_study_material.py   ← CertMaster image → JSON extractor (Tesseract OCR)
│   ├── study_material/             ← per-module CertMaster JSON files (pre-merge)
│   ├── CompTIA A+ 220-1201 Exam Objectives (2.0).pdf
│   ├── CompTIA A+ 220-1202 Exam Objectives (2.0).pdf
│   └── a-plus-1-2-outline-perform.pdf
├── STUDY_PLAN.md                   ← 13-day Core 1 study sprint (Oct 6, 2026)
├── CHEAT_SHEET.md                  ← high-yield cram reference
├── test_multi_select_scoring.js
├── package.json
└── README.md
```

### Key files

- **index.html** — entry point; minimal markup, no inline styles or scripts.
- **css/styles.css** — all styling, with CSS variables for theming.
- **js/app.js** — exam flow, UI, state management, and persistence.
- **js/scoring.js** — scoring engine (multi-select partial credit, drag-drop, multiple-choice); importable by both the browser and the tests.
- **js/results.js** — exam history persistence: `saveResult()`, `loadResults()`, `clearResults()`, `getWeaknessSummary()`.
- **js/dashboard.js** — renders the My Progress dashboard (summary cards, session history table, domain weakness tracker).
- **exam_assets/questions.json** — all exam data: Core 1 (1,205 questions) and Core 2 question banks, domain weights, objective/module metadata.
- **exam_assets/acronyms_quiz.json** — 200 acronym quiz questions.
- **exam_assets/parse_practice_tests.py** — Python script to extract questions from practice test PDFs. Uses `pdfplumber` and unicode symbol markers for reliable correct-answer detection.
- **exam_assets/extract_study_material.py** — Python/Tesseract OCR script to extract questions from CertMaster module quiz page images (JPG) into JSON. Requires `pytesseract` + `Pillow` + Tesseract installed.

### Study materials (non-app files)

- **STUDY_PLAN.md** — 13-day Core 1 sprint targeting the Oct 6, 2026 exam. Point-weighted by domain, with daily sessions mapped to your schedule.
- **CHEAT_SHEET.md** — printable high-yield cram reference: ports, RAID, 802.11, USB/SATA versions, IP ranges, cloud models, laser imaging process, and exam-day tactics.

## Getting Started

```bash
git clone <repo-url>
cd <repo-dir>
npm start
```

Opens http://localhost:8000. Requires Python 3 (uses `python -m http.server`).

> **Note:** `npm start` invokes `python` (not `python3`) because `python3` resolves to the Microsoft Store alias stub on some Windows machines. If `python` doesn't resolve on your system, run `python3 -m http.server 8000` directly.

## Running Tests

```bash
npm test
```

Runs unit tests for the scoring engine via Node.js. No browser required.

## Adding Questions from Practice Test PDFs

```bash
cd exam_assets
pip install pdfplumber
python parse_practice_tests.py                       # process all PDFs in current folder
python parse_practice_tests.py path/to/test.pdf      # process a single file
```

Each PDF produces a `practice_test_N.json` file. To merge into the main `questions.json`:

1. Add an `"origin"` field to each question (e.g., `"PT23-001"` for Practice Test 23, Question 1).
2. Continue the ID sequence from the last ID (currently `1201-715`).
3. Append to the `questionBank` array in `exams["220-1201"]`.

## Adding Questions from CertMaster Module Images

```bash
cd exam_assets
pip install pytesseract Pillow
# Install Tesseract: winget install UB-Mannheim.TesseractOCR
python extract_study_material.py                              # process all 36 folders
python extract_study_material.py "5.1 Network Types.pdf"     # process one folder
```

Outputs one JSON per folder to `exam_assets/study_material/`. After reviewing and cleaning the output, append each question array to `questions.json` using `origin: "CertMaster"` and IDs in the format `CM-{module}-{number}` (e.g., `CM-2.1-003`).

## Question Data Schema

Each entry in an exam's `questionBank` follows this shape:

```json
{
  "id": "1201-161",
  "domain": "1.0 Mobile Devices",
  "objective": "1.1",
  "module": "9.0",
  "type": "mc",
  "difficulty": "medium",
  "stem": "Question text...",
  "explanation": "Why the correct answer is correct...",
  "options": ["Option A", "Option B", "Option C", "Option D"],
  "correctAnswer": ["Option B"],
  "origin": "PT01-001"
}
```

Fields:

- **id** — unique identifier. Format by source:
  - `1201-NNN` — original + practice test questions (Core 1)
  - `CM-{module}-{NNN}` — CertMaster study material (e.g., `CM-6.2-005`)
- **domain** — must match a key in the exam's `domainWeights`.
- **objective** — must match a key in the exam's `objectives` metadata.
- **module** — must match a key in the exam's `modules` metadata.
- **type** — `"mc"`, `"multi"`, `"matching"`, or `"drag_drop"`.
- **difficulty** — `"easy"`, `"medium"`, or `"hard"`.
- **stem** — the question text.
- **explanation** — shown in review after exam completion.
- **options** — array of answer choices.
- **correctAnswer** — for `mc`: single-element array; for `multi`: array of correct options.
- **origin** — source tracking:
  - `"original"` — initial hand-written bank
  - `"PT01-001"` – `"PT22-030"` — practice test PDFs
  - `"CertMaster"` — CertMaster module quiz images

## Contributing

- Questions must include all schema fields, including `origin`.
- `objective` and `module` must reference valid keys in the exam's metadata tables.
- Run `npm test` before submitting.

## License

MIT

## Disclaimer

This is an independent study tool and is not affiliated with, endorsed by, or associated with CompTIA, Inc. CompTIA A+ is a registered trademark of CompTIA, Inc. Exam objectives referenced from CompTIA A+ Certification Exam Objectives v4, © 2024 CompTIA, Inc.

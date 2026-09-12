# CompTIA A+ Practice Exam Simulator

A zero-dependency, browser-based practice exam simulator for CompTIA A+ Core 1 (220-1201) and Core 2 (220-1202) certification exams.

![App Screenshot](screenshot.png)

## Features

- **Two-step exam launch:** choose an exam, then choose a mode.
- **Four exam modes:**
  - **Practice Exam** — 25 random questions, 1 minute/question timer, instant feedback.
  - **Simulation Exam** — full question count with the exam timer, no feedback until results (mimics the real CompTIA exam).
  - **Practice by Domain** — filter by exam domain, up to 25 questions.
  - **Practice by Study Module** — filter by CertMaster course module, up to 25 questions.
- **Three exams available:**
  - **Core 1 (220-1201):** 715 questions across 5 domains, 25 of 27 objectives, 10 modules.
  - **Core 2 (220-1202):** 16 questions across 4 domains, 36 objectives, 12 modules.
  - **Acronyms Quiz:** 173 acronym questions.
- **Question types:** multiple-choice, multi-select (with partial-credit scoring), matching (dropdown), and drag-and-drop.
- Every question is tagged with **domain, objective, module, and origin source**, verified against the official CompTIA A+ Certification Exam Objectives v4.
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

### Core 1 (220-1201) — 715 questions

The Core 1 question bank draws from two sources, tracked by the `origin` field:

| Source | Origin value | Questions | ID range |
|--------|-------------|-----------|----------|
| Original bank | `"original"` | 160 | `1201-001` – `1201-160` |
| Practice Tests 01–22 | `"PT01-001"` – `"PT22-030"` | 555 | `1201-161` – `1201-715` |
| **Total** | | **715** | |

**Coverage by domain:**

| Domain | Questions | Bank % | Exam weight |
|--------|-----------|--------|-------------|
| 1.0 Mobile Devices | 118 | 16.5% | 13% |
| 2.0 Networking | 231 | 32.3% | 23% |
| 3.0 Hardware | 260 | 36.4% | 25% |
| 4.0 Virtualization and Cloud Computing | 38 | 5.3% | 11% |
| 5.0 Hardware and Network Troubleshooting | 68 | 9.5% | 28% |

**Coverage by question type:**

| Type | Count |
|------|-------|
| Multiple-choice (`mc`) | 563 |
| Multi-select (`multi`) | 146 |
| Matching / dropdown (`matching`) | 4 |
| Drag-and-drop (`drag_drop`) | 2 |

**Objective coverage:** 25 of 27 objectives have questions. Two objectives have **zero** questions:

- 3.6 — Power supplies
- 3.7 — Printers / multifunction devices

**Known gaps:** Domain 4.0 (Virtualization & Cloud) and Domain 5.0 (Troubleshooting) are under-represented relative to their exam weight. Additional questions from a third source are planned.

### Core 2 (220-1202) — 16 questions

This is a starter bank — most of the 36 objectives are not yet represented. Contributions welcome.

### Acronyms — 173 questions

Covers acronyms from both the Core 1 and Core 2 acronym lists.

## Project Structure

```
├── index.html
├── css/
│   └── styles.css
├── js/
│   ├── app.js
│   └── scoring.js
├── exam_assets/
│   ├── questions.json              ← all exam data (Core 1 + Core 2 question banks)
│   ├── acronyms_quiz.json          ← acronym quiz data
│   ├── parse_practice_tests.py     ← practice test PDF → JSON parser script
│   ├── CompTIA A+ 220-1201 Exam Objectives (2.0).pdf
│   ├── CompTIA A+ 220-1202 Exam Objectives (2.0).pdf
│   ├── a-plus-220-120x-perform-course.pdf   ← CertMaster Perform course
│   ├── a-plus-220-120x-perform-course.txt   ← course text (extracted)
│   └── a-plus-1-2-outline-perform.pdf       ← course outline
├── review_lessons_modules_quiz_pdf/ ← module review/quiz PDFs
├── STUDY_PLAN.md                   ← 7-week Core 1 study plan
├── STUDY_PLAN.pdf
├── CHEAT_SHEET.md                  ← high-yield cram reference
├── CHEAT_SHEET.pdf
├── PLAN_ONE_PAGER.md               ← one-page plan summary
├── PLAN_ONE_PAGER.pdf
├── test_multi_select_scoring.js
├── package.json
└── README.md
```

### Key files

- **index.html** — entry point; minimal markup, no inline styles or scripts.
- **css/styles.css** — all styling, with CSS variables for theming.
- **js/app.js** — exam flow, UI, state management, and persistence.
- **js/scoring.js** — scoring engine (multi-select partial credit, drag-drop, multiple-choice); importable by both the browser and the tests.
- **exam_assets/questions.json** — all exam data: Core 1 and Core 2 question banks (with `origin` tracking), domain weights, and objective/module metadata.
- **exam_assets/acronyms_quiz.json** — acronym quiz data (loaded at runtime into a synthetic "Acronyms" exam).
- **exam_assets/parse_practice_tests.py** — Python script to extract questions from practice test PDFs into JSON. Requires `pdfplumber`. Uses unicode symbol markers (✓/radio/checkbox) for reliable correct-answer detection and keyword-based domain/objective mapping against the official exam objectives.
- **test_multi_select_scoring.js** — unit tests for the scoring engine.
- **package.json** — npm scripts (`test`, `start`).

### Study materials (non-app files)

- **STUDY_PLAN.md/.pdf** — 7-week Core 1 (220-1201) study sprint targeting the Oct 27, 2026 exam. Point-weighted by domain, with weekly milestones and Go/No-Go readiness gate.
- **CHEAT_SHEET.md/.pdf** — printable high-yield cram reference: ports, RAID levels, 802.11 standards, IP ranges, cloud models, laser imaging process, Windows/Linux commands, security concepts, backup types, and exam-day tactics.
- **PLAN_ONE_PAGER.md/.pdf** — condensed wall-friendly one-page summary of the study plan.

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

Runs 16 unit tests for the scoring engine via Node.js. No browser required. The tests import the scoring functions directly from `js/scoring.js`, so they exercise the real production code rather than a copy.

## Adding Questions from Practice Test PDFs

The `parse_practice_tests.py` script automates extraction from practice test PDFs:

```bash
cd exam_assets
pip install pdfplumber
python parse_practice_tests.py                       # process all PDFs in current folder
python parse_practice_tests.py path/to/test.pdf      # process a single file
```

Each PDF produces a `practice_test_N.json` file. To merge into the main `questions.json`:

1. Add an `"origin"` field to each question (e.g., `"PT23-001"` for Practice Test 23, Question 1).
2. Continue the ID sequence from the last ID in `questions.json` (currently `1201-715`).
3. Append to the `questionBank` array in `exams["220-1201"]`.

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

- **id** — unique identifier (`1201-NNN` for Core 1, `1202-NNN` for Core 2).
- **domain** — must match a key in the exam's `domainWeights`.
- **objective** — must match a key in the exam's `objectives` metadata.
- **module** — must match a key in the exam's `modules` metadata.
- **type** — `"mc"` (multiple-choice / true-false), `"multi"` (multi-select), `"matching"` (dropdown matching), or `"drag_drop"`.
- **difficulty** — `"easy"`, `"medium"`, or `"hard"`.
- **stem** — the question text.
- **explanation** — shown in the review after exam completion. Explains why the correct answer is correct.
- **options** — array of answer choices (text). For `matching` type, these are the answer pool.
- **correctAnswer** — for `mc`: single-element array; for `multi`: array of correct options; for `matching`: object mapping items to correct answers; for `drag_drop`: object mapping zones to items.
- **origin** — tracks the question source: `"original"` for the initial hand-written bank, `"PT01-001"` through `"PT22-030"` for practice tests (format: `PT{test_number}-{question_number}`). New sources should use a distinct prefix.

Additional fields for `matching` type:
- **items** — array of items to match (left column / dropdown labels).

## Contributing

- Questions must include all schema fields, including `origin`.
- `objective` and `module` must reference valid keys in the exam's metadata tables.
- Domain must match a key in the exam's `domainWeights`.
- Run `npm test` before submitting.

## License

MIT

## Disclaimer

This is an independent study tool and is not affiliated with, endorsed by, or associated with CompTIA, Inc. CompTIA A+ is a registered trademark of CompTIA, Inc. Exam objectives referenced from CompTIA A+ Certification Exam Objectives v4, © 2024 CompTIA, Inc.

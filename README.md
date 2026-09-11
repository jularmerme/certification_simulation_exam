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
  - **Core 1 (220-1201):** 160 questions across 5 domains, 27 objectives, 10 modules.
  - **Core 2 (220-1202):** 16 questions across 4 domains, 36 objectives, 12 modules.
  - **Acronyms Quiz:** 173 acronym questions.
- **Question types:** multiple-choice, multi-select (with partial-credit scoring), and drag-and-drop.
- Every question is tagged with **domain, objective, and module**, verified against the official CompTIA A+ Certification Exam Objectives v4.
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

The practice bank is a work in progress. Coverage is uneven, and it's better to know the gaps than to be surprised by them.

**Core 1:** 160 questions covering 21 of 27 objectives. Six objectives have **zero** questions:

- 2.3 — Networked host services
- 2.4 — Network configuration concepts
- 3.1 — Display components
- 3.6 — Power supplies
- 3.7 — Printers / multifunction devices
- 5.3 — Video / display troubleshooting

Module 1.0 (*What Does an IT Specialist Do?*) has no questions by design — no exam objective maps to it.

**Core 2:** 16 questions covering 14 of 36 objectives. This is a starter bank — most objectives are not yet represented. Contributions welcome.

**Acronyms:** 173 questions covering acronyms from both the Core 1 and Core 2 acronym lists.

## Project Structure

```
├── index.html
├── css/
│   └── styles.css
├── js/
│   ├── app.js
│   └── scoring.js
├── exam_assets/
│   ├── questions.json
│   └── acronyms_quiz.json
├── test_multi_select_scoring.js
├── package.json
└── README.md
```

- **index.html** — entry point; minimal markup, no inline styles or scripts.
- **css/styles.css** — all styling, with CSS variables for theming.
- **js/app.js** — exam flow, UI, state management, and persistence.
- **js/scoring.js** — scoring engine (multi-select partial credit, drag-drop, multiple-choice); importable by both the browser and the tests.
- **exam_assets/questions.json** — all exam data: Core 1 and Core 2 question banks, domain weights, and objective/module metadata.
- **exam_assets/acronyms_quiz.json** — acronym quiz data (loaded at runtime into a synthetic "Acronyms" exam).
- **test_multi_select_scoring.js** — unit tests for the scoring engine.
- **package.json** — npm scripts (`test`, `start`).

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

## Question Data Schema

Each entry in an exam's `questionBank` follows this shape:

```json
{
  "id": "1201-001",
  "domain": "2.0 Networking",
  "objective": "2.1",
  "module": "5.0",
  "type": "multiple-choice",
  "stem": "Question text...",
  "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
  "correctAnswer": "B",
  "explanation": "Explanation text..."
}
```

Fields:

- **id** — unique identifier (exam prefix + number).
- **domain** — must match a key in the exam's `domainWeights`.
- **objective** — must match a key in the exam's `objectives` metadata.
- **module** — must match a key in the exam's `modules` metadata.
- **type** — `"multiple-choice"`, `"multi-select"`, or `"drag-drop"`.
- **correctAnswer** — for multiple-choice, a single option; for multi-select, an array of options; for drag-drop, an object mapping zones to items.
- **explanation** — shown in the review after exam completion.

> **Implementation note:** in the shipped data, `type` values are stored as `"mc"`, `"multi"`, and `"drag_drop"`, and `correctAnswer` holds the option **text** (not letters) — an array for every type. The schema above shows the conceptual shape; match the existing entries in `questions.json` when adding questions.

## Contributing

- Questions must include all schema fields.
- `objective` and `module` must reference valid keys in the exam's metadata tables.
- Domain must match a key in the exam's `domainWeights`.
- Run `npm test` before submitting.

## License

MIT

## Disclaimer

This is an independent study tool and is not affiliated with, endorsed by, or associated with CompTIA, Inc. CompTIA A+ is a registered trademark of CompTIA, Inc. Exam objectives referenced from CompTIA A+ Certification Exam Objectives v4, © 2024 CompTIA, Inc.

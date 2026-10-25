# CompTIA A+ Exam Simulator — Project Status

> **Last updated:** September 2026  
> **Purpose:** Continuity document for picking up work on another machine with Kiro AI.  
> **Exam target date:** October 27, 2026 (Core 1 first, Core 2 after)

---

## 1. Repository

| Field | Value |
|-------|-------|
| **Local path** | `C:\Users\Julian\Desktop\python_work\compTia A+` |
| **Remote** | `https://github.com/jularmerme/https---github.com-jularmerme-certification_simulation_exam.git` |
| **Branch** | `main` |
| **Status** | All work committed and pushed to remote |

Clone on a new machine:
```bash
git clone https://github.com/jularmerme/https---github.com-jularmerme-certification_simulation_exam.git "compTia A+"
```

---

## 2. Stack & Constraints

- **Zero-dependency vanilla JS + HTML + CSS** — no frameworks, no build step, no npm runtime
- **Data storage:** `localStorage` only (no backend, no server)
- **Dev server:** `npm start` → `python -m http.server 8000` → open http://localhost:8000
- **Tests:** `npm test` → runs 16 unit tests via Node.js (`test_multi_select_scoring.js`)
- All 16 tests currently **passing**

---

## 3. Project Structure

```
compTia A+/
├── index.html                          ← Single-page app entry point
├── css/
│   └── styles.css                      ← All styles (CSS variables, dark/light theme)
├── js/
│   ├── scoring.js                      ← checkAnswerCorrect(), computeMultiSelectScore()
│   ├── app.js                          ← Exam engine: state, rendering, navigation, timer
│   ├── results.js                      ← saveResult(), loadResults(), getWeaknessSummary()
│   └── dashboard.js                    ← Progress dashboard renderer
├── exam_assets/
│   ├── questions.json                  ← Main question bank (Core 1 + Core 2)
│   ├── acronyms_quiz.json              ← 200 acronym questions (separate file)
│   └── practice_tests_core2/
│       └── Core2_Original_Questions.json  ← Standalone Core 2 question file (16 Qs)
├── review_lessons_modules_quiz_pdf/    ← PDF study materials (not used by app)
├── STUDY_PLAN.md / STUDY_PLAN.pdf
├── CHEAT_SHEET.md / CHEAT_SHEET.pdf
├── STUDY_PLAN_CORE2.docx
├── CHEAT_SHEET_CORE2.docx
├── package.json
└── test_multi_select_scoring.js
```

**Backup files present (safe to ignore):**
- `js/app.js.bak_before_*` — several; keep for reference
- `exam_assets/practice_tests_core2/*.bak_*`

---

## 4. Question Bank Status

### Core 1 — 220-1201
| Metric | Value |
|--------|-------|
| **Total questions** | **1,205** |
| **Question types** | mc: 987, multi: 212, matching: 6 |
| **Practice tests loaded** | PT01 through PT22 (all 22) |

**Domain breakdown:**
| Domain | Questions | Exam Weight |
|--------|-----------|-------------|
| 1.0 Mobile Devices | 183 | 13% |
| 2.0 Networking | 416 | 23% |
| 3.0 Hardware | 395 | 25% |
| 4.0 Virtualization and Cloud Computing | 68 | 11% |
| 5.0 Hardware and Network Troubleshooting | 143 | 28% |

**Gap:** Domain 5.0 (Troubleshooting) is under-represented at 12% of bank vs 28% exam weight.

### Core 2 — 220-1202
| Metric | Value |
|--------|-------|
| **Total questions** | **16** (starter bank only) |
| **Question types** | mc: 8, multi: 6, drag_drop: 2 |
| **Domain weights configured** | All 4 domains set to 0% (placeholder) |
| **Modules** | 12 modules configured (11.0–22.0) |
| **Objectives** | 36 objectives configured |

> ⚠️ **Core 2 is a starter bank.** The 16 questions in `questions.json` match exactly the 16 in `exam_assets/practice_tests_core2/Core2_Original_Questions.json`.
>
> ⚠️ **2 questions in Core 2 still have `type: "drag_drop"`** — IDs `1202-003` and `1202-010`. These need to be converted to `matching` schema (same as was done for Core 1).

### Acronyms Quiz
| Metric | Value |
|--------|-------|
| **Total questions** | **200** |
| **File** | `exam_assets/acronyms_quiz.json` |

---

## 5. App Features (Implemented & Working)

### Exam Engine
- [x] Two-step launch: select exam → select mode
- [x] **Practice Exam** — configurable question count (25/50/75/100% of bank), 1 min/question, instant feedback
- [x] **Simulation Exam** — full question count, exam timer, no feedback until results
- [x] **Practice by Domain** — filter by domain, up to 25 questions
- [x] **Practice by Study Module** — filter by module, up to 25 questions
- [x] Save & Exit / resume from localStorage
- [x] Question flagging + re-answering (answered questions lock unless flagged)
- [x] Auto-flag unanswered questions on Next
- [x] No-repeat question selection within a session
- [x] Question shuffle + option shuffle on every attempt

### Question Types
- [x] **Multiple choice (mc)** — single radio select
- [x] **Multi-select (multi)** — checkboxes, partial credit scoring (100/50/0)
- [x] **Matching (dropdown)** — left column items + right column `<select>` dropdowns
- [x] True/False always shows True first, False second
- [x] "All of the above" always pinned as last option
- [ ] `drag_drop` — **removed from Core 1**, still exists in Core 2 (2 questions need conversion)

### Results & Review
- [x] Scaled score (100–900 scale), pass/fail badge
- [x] Correct / Partial Credit / Incorrect / Unanswered breakdown with filter tabs
- [x] **Simulation-style review** — each question shows full option list with colored borders:
  - Green border + ✓ = correct answer
  - Red border + ✗ = wrong answer picked
  - Amber border + ! = correct answer missed (partial multi-select)
- [x] Explanation in separate container below each question card
- [x] Paginated review (10 questions per page)

### Progress Dashboard (`📊 My Progress` button in topbar)
- [x] Persists every completed session to `localStorage` key: `aplus_progress_history`
- [x] **Summary cards:** Total Sessions, Best Score, Latest Score, Avg Score (last 5)
- [x] **Session history table** — sortable columns, score % colored by band (green ≥75%, amber 60–74%, red <60%)
- [x] **Inline domain breakdown** — click any row to expand per-domain stats
- [x] **Domain Weakness Tracker** — cumulative avg score per domain, trend (↑↓→), focus flag (🔴🟡🟢)
- [x] Clear History button with confirmation

### UI
- [x] Dark/light theme toggle (persisted to localStorage, defaults to dark)
- [x] Responsive layout (laptop + tablet)
- [x] `accent-color` on radio/checkbox inputs for dark-theme visibility
- [x] Anti-flash guard on page load

---

## 6. Known Issues & Next Steps

### High Priority
1. **Convert Core 2 `drag_drop` questions to `matching`** — IDs `1202-003` and `1202-010` in `questions.json`. Same Python migration script pattern used for Core 1 (converts `dropZones[]` → `items[]`, `options[]`, `correctAnswer{}` object).

2. **Expand Core 2 question bank** — Only 16 questions. Need to add practice test questions for 220-1202. Target: 200+ questions covering all 36 objectives and 4 domains. Questions should be added to `questions.json` under `exams["220-1202"]["questionBank"]` and also to `exam_assets/practice_tests_core2/Core2_Original_Questions.json` for backup.

3. **Set Core 2 domain weights** — Currently all 4 domains are `0%` in `domainWeights`. Real exam weights: Operating Systems 28%, Security & Compliance 28%, Software Troubleshooting 23%, Operational Procedures 21%.

### Medium Priority
4. **Domain 5.0 Troubleshooting gap** — Only 143 questions (12% of bank) vs 28% exam weight. Add more troubleshooting scenario questions.

5. **Objectives 3.6 and 3.7 (Core 1)** — Zero questions for power supplies (3.6) and printers/MFDs (3.7).

6. **`add_pt01.py` leftover** — A `add_pt01.py` script is still in the root directory. It can be deleted (it was a one-off migration tool).

7. **`test_write.py` leftover** — Same; can be deleted.

### Low Priority
8. Core 2 simulation mode won't be useful until bank is 90+ questions.
9. README is slightly stale (still says 715 Core 1 questions; actual is 1,205).

---

## 7. Data Schema Reference

### Question object (questions.json)
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

**`type` values:** `mc`, `multi`, `matching`  
**`origin` format:** `"PT{test_number}-{question_number}"` for practice tests, `"original"` for hand-written, `"ACR-PT{n}-{n}"` for acronyms

### Matching question schema (after conversion from drag_drop)
```json
{
  "type": "matching",
  "items": ["Zone/Item Label A", "Zone/Item Label B"],
  "options": ["Answer Option 1", "Answer Option 2"],
  "correctAnswer": {
    "Zone/Item Label A": "Answer Option 1",
    "Zone/Item Label B": "Answer Option 2"
  }
}
```

### Answer format in localStorage (appState.answers)
- `mc` → `"string"` (option text)
- `multi` → `["string", "string"]`
- `matching` → `{ "rowKey": "chosenValue" }`

### Progress history localStorage key
- Key: `aplus_progress_history`
- Format: JSON array of result objects, newest first, max 200 entries
- Each record includes: `id`, `date`, `examCode`, `examType`, `examLabel`, `totalQuestions`, `correct`, `partial`, `incorrect`, `incomplete`, `score`, `scaledScore`, `passingScore`, `passed`, `durationSeconds`, `breakdown` (per-domain object)

---

## 8. CSS Variables Quick Reference

```css
/* Light theme */
--navy: #0f2540;       /* Primary dark blue */
--navy2: #163a63;      /* Secondary blue */
--green: #1b7a3d;      /* Correct / pass */
--amber: #b8790a;      /* Partial / flagged / warn */
--red: #c8102e;        /* Incorrect / fail */
--bg: #f2f4f7;         /* Page background */
--card: #ffffff;       /* Card surface */
--border: #dde2e8;     /* Borders */
--text: #1c2530;       /* Body text */
--muted: #667085;      /* Subdued text */

/* Dark theme overrides */
--navy: #1a1f2e;  --navy2: #252d3d;  --green: #2ecc71;
--amber: #f39c12; --red: #ff7a8a;   --bg: #0f1217;
--card: #1a1f2e;  --border: #2d3748; --text: #e2e8f0;
--muted: #cbd5e0;
```

---

## 9. Key Function Map (app.js)

| Function | Purpose |
|----------|---------|
| `showScreen(id)` | Toggle between `screenIntro`, `screenModePicker`, `screenExam`, `screenResults`, `screenDashboard` |
| `submitExam()` | Calculates score, calls `saveResult()`, shows completion modal |
| `runExam(questions, timeSeconds)` | Starts exam with given questions and timer |
| `renderMultipleChoice(q, container, idx)` | Renders mc/multi question options |
| `renderMatching(q, container, idx)` | Renders matching dropdown rows |
| `randomizeQuestionOptions(q)` | Shuffles options (skips T/F; pins "All of the above" last) |
| `checkAndRestoreExamState()` | Resumes saved exam from localStorage on page load |
| `buildReviewList()` / `renderReviewPage()` | Builds the post-exam review section |
| `showDashboard()` / `hideDashboard()` | Opens/closes the progress dashboard |
| `saveResult()` | In `results.js` — persists result to `aplus_progress_history` |

---

## 10. Recent Git History

```
6d54071  fixed some bugs
6064614  Merge branch 'main'
ee0e5a1  fixed some questions bugs
72916c1  reorder options in osi model question
43d551f  added new feature to module and domain modes
71289ff  fix: strip OCR trailing junk from 214 explanations
3b2bc86  Fixed type in a question
144b1ee  added no repeat questions function in every attempt
fa7cd26  added new features to the results page
6d854cc  feat: add question-count selector (25/50/75/100%)
03859eb  fix: accent-color for radio/checkbox visibility in dark theme
bc1204e  refactor: replace drag_drop with matching dropdown layout
13edc9a  fix: pin 'All of the above' as last option after shuffle
9cd4e13  fix: enforce True/False order on restore from localStorage
e59cb12  feat: simulation-style review page and True/False option order fix
```

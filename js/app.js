// Global State
let appState = {
  examCode: null,
  questions: [],
  currentQuestionIndex: 0,
  answers: {},
  flagged: new Set(),
  autoFlagged: new Set(), // Track which questions were auto-flagged while unanswered
  checkedQuestions: new Set(), // Questions where "Check" has been pressed — feedback shown, locked
  examTimeAllotted: 0, // Time budget (seconds) of the current run — reused when retaking the same exam
  isDrillMode: false, // true for "Retake Missed Questions" — submitExam() skips persistence when true
  
  displayedQuestionIds: new Set(), // Track question IDs already displayed to prevent duplicates
  validatedDragDrops: new Set(), // Track which drag-drop questions have been validated
  timerInterval: null,
  timeRemaining: 0,
  examStartTime: null,
  // P5 mode state
  examMode: 'practice',        // 'practice' | 'simulation' | 'domain' | 'module'
  feedbackEnabled: true,       // false in simulation mode (no mid-exam correctness colors)
  activeFilter: null,          // { type: 'domain'|'module', value: string, label: string } or null
  // Question-count picker: holds the pending launch config while the size modal is open.
  // { pool: object[], mode: 'practice'|'domain'|'module', filter: {type,value,label}|null }
  pendingLaunch: null
};

// Theme Management
function initializeTheme() {
  const savedTheme = localStorage.getItem('theme-preference');
  const isDarkTheme = savedTheme === 'dark' || savedTheme === null; // Default to dark
  
  if (isDarkTheme) {
    document.body.classList.add('dark-theme');
    updateThemeToggleButton(true);
  } else {
    document.body.classList.remove('dark-theme');
    updateThemeToggleButton(false);
  }
}

function toggleTheme() {
  const isDarkTheme = document.body.classList.toggle('dark-theme');
  
  // Save preference to localStorage
  localStorage.setItem('theme-preference', isDarkTheme ? 'dark' : 'light');
  
  // Update toggle button icon
  updateThemeToggleButton(isDarkTheme);
}

function updateThemeToggleButton(isDarkTheme) {
  const btn = document.getElementById('themeToggle');
  if (btn) {
    // Show sun icon (☀️) when dark theme is active (to switch to light)
    // Show moon icon (🌙) when light theme is active (to switch to dark)
    btn.textContent = isDarkTheme ? '☀️' : '🌙';
    btn.title = isDarkTheme ? 'Switch to light theme' : 'Switch to dark theme';
  }
}

// Initialize
window.addEventListener('DOMContentLoaded', async () => {
  // Set current year in footer
  document.getElementById('year').textContent = new Date().getFullYear();
  
  // Initialize theme from localStorage (default to dark theme)
  initializeTheme();
  
  // Load questions from JSON
  try {
    // Cache-bust every fetch with a timestamp query param so edits to these
    // JSON files always show up on reload, even if the browser/dev server
    // would otherwise serve a stale cached response for a plain fetch().
    const response = await fetch('exam_assets/questions.json?v=' + Date.now());
    const data = await response.json();
    window.questionBank = data;
    
    // Load acronyms quiz
    const acronymsResponse = await fetch('exam_assets/acronyms_quiz.json?v=' + Date.now());
    const acronymsData = await acronymsResponse.json();
    
    // Convert acronyms to exam format compatible with existing code.
    // questions/timeLimit mirror the fields the JSON-backed exams carry so that
    // examQuestionCount() and examTimeLimit() work uniformly across all exams.
    window.questionBank.exams['acronyms'] = {
      name: 'Acronyms Quiz',
      code: 'Practice',
      questions: 25,   // draw 25 per attempt from the full acronym bank
      timeLimit: 10,   // minutes; acronym recall is fast
      minScore: 0,
      maxScore: 100,
      passingScore: 80,
      questionBank: acronymsData.acronymsQuiz.questions.map(q => ({
        id: q.id,
        stem: q.stem,
        options: q.options || [],
        correctAnswer: q.correctAnswer || [],
        type: q.type, // Use the actual type from JSON (mc or multi)
        domain: q.domain || 'Acronyms',
        difficulty: q.difficulty || 'medium',
        explanation: q.explanation || ''
      }))
    };
    
    // Load Others (reference tables) quiz
    try {
      const othersResponse = await fetch('exam_assets/others_quiz.json?v=' + Date.now());
      if (!othersResponse.ok) throw new Error('HTTP ' + othersResponse.status);
      const othersData = await othersResponse.json();
      if (!othersData || !othersData.othersQuiz || !Array.isArray(othersData.othersQuiz.questions)) {
        throw new Error('Unexpected format in others_quiz.json');
      }
      window.questionBank.exams['others'] = {
        name: 'Reference Tables',
        code: 'Reference',
        questions: 9,
        timeLimit: 20,
        minScore: 0,
        maxScore: 100,
        passingScore: 80,
        questionBank: othersData.othersQuiz.questions
      };
    } catch (othersErr) {
      console.error('Failed to load others_quiz.json:', othersErr);
      // Non-fatal: Core 1/2 and Acronyms still work; Others card will be disabled.
      const othCard = document.getElementById('cardOthers');
      if (othCard) {
        othCard.style.opacity = '0.4';
        othCard.style.pointerEvents = 'none';
        othCard.title = 'Reference Tables failed to load — check others_quiz.json';
      }
    }

    // Fill in the intro cards now that every exam's bank size is known
    populateIntroCards();
    
    // Check if there's a saved exam in progress
    checkAndRestoreExamState();
  } catch (error) {
    console.error('Error loading questions:', error);
    alert('Failed to load question bank. Make sure questions.json and acronyms_quiz.json are in exam_assets folder.');
  } finally {
    // Reveal the page whether or not the restore succeeded, so a failed load
    // never leaves the user staring at a hidden body.
    document.body.classList.remove('resuming-exam');
  }
});

// Check and restore exam state from localStorage
function checkAndRestoreExamState() {
  // Check if there's a saved exam in progress
  const savedState = localStorage.getItem('aplus_exam_state');
  if (savedState) {
    try {
      const state = JSON.parse(savedState);
      
      // Restore the exam state
      appState.examCode = state.examCode;
      appState.isDrillMode = state.isDrillMode || false;
      appState.currentQuestionIndex = state.currentQuestionIndex || 0;
      appState.answers = state.answers || {};
      appState.flagged = new Set(state.flagged || []);
      appState.autoFlagged = new Set(state.autoFlagged || []);
      appState.checkedQuestions = new Set(state.checkedQuestions || []);
      // saveExamState() persists this, so it must be rehydrated too or validated
      // drag-drop answers unlock themselves after a resume.
      appState.validatedDragDrops = new Set(state.validatedDragDrops || []);
      appState.displayedQuestionIds = new Set(state.displayedQuestionIds || []);
      appState.timeRemaining = state.timeRemaining || 0;
      appState.examStartTime = state.examStartTime || Date.now();
      // P5 mode state. Default to practice/feedback-on for pre-P5 saved states so
      // an older resume behaves exactly as it did before.
      appState.examMode = state.examMode || 'practice';
      appState.feedbackEnabled = state.feedbackEnabled !== undefined ? state.feedbackEnabled : true;
      appState.activeFilter = state.activeFilter || null;
      
      // CRITICAL: Restore the SAVED questions, not generate new ones
      if (state.questions && state.questions.length > 0) {
        // Re-enforce True/False order on restore — saved state may carry a
        // shuffled order from before the fix was deployed.
        appState.questions = state.questions.map(q => {
          if (q.options && q.options.length === 2 &&
              q.options.every(o => o.toLowerCase() === 'true' || o.toLowerCase() === 'false')) {
            q.options = ['True', 'False'];
          }
          // Re-enforce "All of the above" as last option
          if (q.options) {
            const allAboveIdx = q.options.findIndex(o => o.toLowerCase() === 'all of the above');
            if (allAboveIdx > -1 && allAboveIdx !== q.options.length - 1) {
              const [allAbove] = q.options.splice(allAboveIdx, 1);
              q.options.push(allAbove);
            }
          }
          return q;
        });
        
        // Show exam screen
        const exam = window.questionBank.exams[state.examCode];
        if (exam) {
          showScreen('screenExam');
          document.getElementById('topbarExamName').textContent = exam.name + ' (' + exam.code + ')';
          
          // Restore the mode badge + filter note so the resumed exam shows its context
          applyModeHeader();
          
          // Build navigator
          buildNavigator();
          
          // Load the current question
          loadQuestion(appState.currentQuestionIndex);
          
          // Start timer
          startTimer();
          
          return true; // Successfully restored
        }
      }
    } catch (error) {
      console.error('Error restoring exam state:', error);
    }
  }
  
  return false; // No saved state to restore
}

// Save exam state to localStorage
function saveExamState() {
  const state = {
    examCode: appState.examCode,
    isDrillMode: appState.isDrillMode,
    currentQuestionIndex: appState.currentQuestionIndex,
    questions: appState.questions, // SAVE the actual questions
    answers: appState.answers,
    flagged: Array.from(appState.flagged),
    autoFlagged: Array.from(appState.autoFlagged),
    checkedQuestions: Array.from(appState.checkedQuestions),
    timeRemaining: appState.timeRemaining,
    examStartTime: appState.examStartTime,
    // P5 mode state — required so resume restores the correct mode/feedback/filter
    examMode: appState.examMode,
    feedbackEnabled: appState.feedbackEnabled,
    activeFilter: appState.activeFilter
  };
  
  localStorage.setItem('aplus_exam_state', JSON.stringify(state));
}

// ---------------------------------------------------------------------------
// Exam configuration helpers
//
// These are the single source of truth for "how many questions" and "how long".
// Both startExam() and the intro screen read through them, so the numbers the
// user is shown are always the numbers the exam will actually use.
// ---------------------------------------------------------------------------

/**
 * Number of questions an exam will serve.
 * Uses the exam's configured `questions` count, clamped to the number actually
 * available in its bank so a partially-filled bank degrades gracefully.
 * @param {object} exam - An entry from window.questionBank.exams
 * @returns {number}
 */
function examQuestionCount(exam) {
  const bankSize = exam && exam.questionBank ? exam.questionBank.length : 0;
  const configured = Number(exam && exam.questions) || bankSize;
  return Math.min(configured, bankSize);
}

/**
 * Time limit for an exam, in minutes.
 * Falls back to one minute per question when the exam defines no timeLimit.
 * @param {object} exam - An entry from window.questionBank.exams
 * @returns {number}
 */
function examTimeLimit(exam) {
  return Number(exam && exam.timeLimit) || examQuestionCount(exam);
}

/**
 * Passing score as display text: "675/900" for scaled exams, "80%" for exams
 * scored out of 100.
 * @param {object} exam - An entry from window.questionBank.exams
 * @returns {string}
 */
function formatPassScore(exam) {
  if (!exam) return '\u2014';
  return exam.maxScore === 100
    ? exam.passingScore + '%'
    : exam.passingScore + '/' + exam.maxScore;
}

/** Button label per exam; falls back to the exam's own name. */
const EXAM_BUTTON_LABELS = {
  '220-1201': 'Begin Core 1 Exam',
  '220-1202': 'Begin Core 2 Exam',
  'acronyms': 'Begin Acronyms Quiz',
  'others':   'Begin Reference Tables'
};

/** Maps each intro card's element-id prefix to its exam code. */
const INTRO_CARDS = [
  { prefix: 'c1', code: '220-1201' },
  { prefix: 'c2', code: '220-1202' },
  { prefix: 'acr', code: 'acronyms' },
  { prefix: 'oth', code: 'others' }
];

function setElementText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

/**
 * Populate every intro card with its real bank size, per-exam question count,
 * time limit and passing score. Called once the question banks have loaded.
 */
function populateIntroCards() {
  INTRO_CARDS.forEach(({ prefix, code }) => {
    const exam = window.questionBank && window.questionBank.exams[code];
    if (!exam) return;
    const bankSize = exam.questionBank ? exam.questionBank.length : 0;
    setElementText(prefix + 'Bank', bankSize);
    setElementText(prefix + 'Exam', examQuestionCount(exam));
    setElementText(prefix + 'Time', examTimeLimit(exam) + ' min');
    setElementText(prefix + 'Pass', formatPassScore(exam));
  });
}

// ---------------------------------------------------------------------------
// Two-step launch flow (P5)
//
// Step 1: clicking an exam card calls selectExam(), which stores the exam and
//         opens the mode picker (it no longer starts an exam directly).
// Step 2: the mode picker offers Practice / Simulation / Practice by Domain /
//         Practice by Study Module. A mode function configures appState.examMode
//         + feedbackEnabled + activeFilter, then calls runExam() with a question
//         set and timer.
// ---------------------------------------------------------------------------

// Screen visibility helper: show exactly one of the top-level screens.
function showScreen(id) {
  ['screenIntro', 'screenModePicker', 'screenOthersPicker', 'screenExam', 'screenResults', 'screenDashboard'].forEach(s => {
    const el = document.getElementById(s);
    if (el) el.classList.toggle('hidden', s !== id);
  });
}

// Step 1 — an exam card was clicked. Store it and open the mode picker.
function selectExam(examCode) {
  appState.examCode = examCode;
  document.getElementById('card1201').classList.toggle('selected', examCode === '220-1201');
  document.getElementById('card1202').classList.toggle('selected', examCode === '220-1202');
  document.getElementById('cardAcronyms').classList.toggle('selected', examCode === 'acronyms');
  document.getElementById('cardOthers').classList.toggle('selected', examCode === 'others');

  // Others skips the standard mode picker — it has its own topic picker
  // (All Topics combined, or one of the 11 individual reference tables).
  if (examCode === 'others') { openOthersPicker(); return; }

  openModePicker();
}

/** Open the mode-picker screen for the currently selected exam. */
/**
 * Results page button: jump back to the mode picker (Practice / Simulation /
 * Domain / Module) for the exam just taken, instead of going all the way to
 * the home screen. For "Others" (Reference Tables), there is no mode picker —
 * it opens the topic picker, which fills the equivalent role.
 */
function goToModeSelect() {
  clearInterval(appState.timerInterval);
  if (appState.examCode === 'others') {
    openOthersPicker();
    return;
  }
  openModePicker();
}

/**
 * Results page button: jump back to the specific sub-picker (Domain, Module,
 * or Others topic) used for the exam just taken. Falls back to the mode
 * picker if the exam wasn't run in a filterable mode (e.g. Practice/Simulation).
 */
function goToFilterSelect() {
  clearInterval(appState.timerInterval);
  if (appState.examCode === 'others') {
    openOthersPicker();
    return;
  }
  if (appState.examMode === 'domain') { openModePicker(); openDomainPicker(); return; }
  if (appState.examMode === 'module') { openModePicker(); openModulePicker(); return; }
  // Practice / Simulation (no domain/module filter) — the mode picker is the
  // closest equivalent "selection" screen for this exam.
  openModePicker();
}

function openModePicker() {
  const exam = window.questionBank && window.questionBank.exams[appState.examCode];
  if (!exam) { alert('Please select an exam'); return; }

  document.getElementById('modePickerTitle').textContent = exam.name + ' — Choose a Mode';
  document.getElementById('modePickerSubtitle').textContent =
    'Select how you want to practice ' + exam.name + ' (' + exam.code + ').';

  // Show mode cards, hide any open sub-picker.
  document.getElementById('modeCards').classList.remove('hidden');
  document.getElementById('domainPicker').classList.add('hidden');
  document.getElementById('modulePicker').classList.add('hidden');

  // Fill per-mode meta lines.
  const bank = exam.questionBank || [];
  setElementText('metaPractice', 'Choose 25\u2013100% of ' + bank.length + ' questions \u00b7 feedback on');
  const simN = Math.min(SIMULATION_QUESTION_COUNT, bank.length);
  setElementText('metaSimulation',
    simN + ' questions \u00b7 ' + examTimeLimit(exam) + ' min \u00b7 no feedback');

  // Domain / Module modes require metadata. The acronyms synthetic exam has none,
  // so disable those two cards for it rather than hiding them.
  const hasDomains = !!(exam.domainWeights && Object.keys(exam.domainWeights).length);
  const hasModules = !!(exam.modules && Object.keys(exam.modules).length);
  setModeCardEnabled('modeDomain', hasDomains,
    hasDomains ? Object.keys(exam.domainWeights).length + ' domains' : 'Not available for this exam');
  setModeCardEnabled('modeModule', hasModules,
    hasModules ? Object.keys(exam.modules).length + ' modules' : 'Not available for this exam');

  // Others exam: disable domain/module filters (9 reference-table questions, filtering N/A)
  if (appState.examCode === 'others') {
    setModeCardEnabled('modeDomain', false, 'Not available for this exam');
    setModeCardEnabled('modeModule', false, 'Not available for this exam');
  }

  showScreen('screenModePicker');
}

/** Enable/disable a mode card and set its meta line. */
function setModeCardEnabled(id, enabled, meta) {
  const card = document.getElementById(id);
  card.classList.toggle('disabled', !enabled);
  const metaId = 'meta' + id.replace('mode', '');
  setElementText(metaId, meta);
}

/** Back button on the mode picker: if a sub-picker is open, return to mode cards;
 *  otherwise return to the exam cards (Step 1). */
function modePickerBack() {
  const domainOpen = !document.getElementById('domainPicker').classList.contains('hidden');
  const moduleOpen = !document.getElementById('modulePicker').classList.contains('hidden');
  if (domainOpen || moduleOpen) {
    document.getElementById('domainPicker').classList.add('hidden');
    document.getElementById('modulePicker').classList.add('hidden');
    document.getElementById('modeCards').classList.remove('hidden');
  } else {
    showScreen('screenIntro');
  }
}

// Count questions in a bank matching a field value (domain or module).
function countBy(bank, field, value) {
  return bank.filter(q => q[field] === value).length;
}

/** Practice by Domain sub-picker: one button per domainWeights key, with counts. */
/**
 * Build the mastery progress-bar HTML for a .filter-btn: a background fill
 * sized to `percent`, color-coded red (<50%) / yellow (50-85%) / green (>85%).
 */
function _buildMasteryBarHtml(percent) {
  const colorClass = percent > 85 ? 'mastery-green' : percent >= 50 ? 'mastery-yellow' : 'mastery-red';
  return '<div class="filter-btn-mastery-bar ' + colorClass + '" style="width:' + percent + '%"></div>';
}

function openDomainPicker() {
  const exam = window.questionBank.exams[appState.examCode];
  if (!exam || !exam.domainWeights) return;
  const bank = exam.questionBank || [];
  const container = document.getElementById('domainButtons');
  container.innerHTML = '';

  Object.keys(exam.domainWeights).forEach(domain => {
    const n = countBy(bank, 'domain', domain);
    const btn = document.createElement('button');
    btn.className = 'filter-btn';
    btn.disabled = n === 0;
    const domainIds = bank.filter(q => q.domain === domain).map(q => q.id);
    const pct = _getMasteryPercent(appState.examCode, domainIds);
    btn.innerHTML = _buildMasteryBarHtml(pct) +
      '<span class="filter-btn-content"><span>' + escapeHtml(domain) + '</span>' +
      '<span class="filter-count">(' + n + ' question' + (n === 1 ? '' : 's') + ')</span></span>';
    if (n > 0) btn.onclick = () => startFilteredExam('domain', domain, domain);
    container.appendChild(btn);
  });

  document.getElementById('modeCards').classList.add('hidden');
  document.getElementById('modulePicker').classList.add('hidden');
  document.getElementById('domainPicker').classList.remove('hidden');
}

/** Practice by Study Module sub-picker: one button per module, with counts. */
function openModulePicker() {
  const exam = window.questionBank.exams[appState.examCode];
  if (!exam || !exam.modules) return;
  const bank = exam.questionBank || [];
  const container = document.getElementById('moduleButtons');
  container.innerHTML = '';

  Object.keys(exam.modules).forEach(moduleNum => {
    const n = countBy(bank, 'module', moduleNum);
    const title = exam.modules[moduleNum];
    const label = 'Module ' + moduleNum + ': ' + title;
    const btn = document.createElement('button');
    btn.className = 'filter-btn';
    btn.disabled = n === 0;
    const moduleIds = bank.filter(q => q.module === moduleNum).map(q => q.id);
    const pct = _getMasteryPercent(appState.examCode, moduleIds);
    btn.innerHTML = _buildMasteryBarHtml(pct) +
      '<span class="filter-btn-content"><span>' + escapeHtml(label) + '</span>' +
      '<span class="filter-count">(' + n + ' question' + (n === 1 ? '' : 's') + ')</span></span>';
    if (n > 0) btn.onclick = () => startFilteredExam('module', moduleNum, label);
    container.appendChild(btn);
  });

  document.getElementById('modeCards').classList.add('hidden');
  document.getElementById('domainPicker').classList.add('hidden');
  document.getElementById('modulePicker').classList.remove('hidden');
}

/** Minimal HTML escape for values interpolated into innerHTML. */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Select unique questions ensuring no duplicates
// ---------------------------------------------------------------------------
// Mastery tracking — Core 1 only. Powers the per-domain/per-module progress
// bars shown on the Domain/Module picker buttons.
//
// "Mastered" = your MOST RECENT attempt at a question was 100% correct.
// This can go backward: get it right once, then wrong later, and it drops
// back out of the mastered count. One map per exam code, keyed by question
// ID -> boolean (true = correct last time, false = incorrect last time).
// Unattempted questions simply have no entry (treated as not mastered).
// ---------------------------------------------------------------------------

const MASTERY_KEY = 'aplus_question_mastery';
const MASTERY_EXAM_CODES = ['220-1201']; // Core 1 only, per spec.

function _loadMasteryMap() {
  try {
    const raw = localStorage.getItem(MASTERY_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch (e) {
    return {};
  }
}

function _saveMasteryMap(map) {
  try {
    localStorage.setItem(MASTERY_KEY, JSON.stringify(map));
  } catch (e) {
    console.warn('Failed to save mastery map:', e);
  }
}

/** Record the latest result (true/false) for one question under its exam code. */
function _recordMastery(examCode, questionId, wasCorrect) {
  if (!MASTERY_EXAM_CODES.includes(examCode)) return;
  const map = _loadMasteryMap();
  if (!map[examCode]) map[examCode] = {};
  map[examCode][questionId] = wasCorrect;
  _saveMasteryMap(map);
}

/**
 * Mastery percent (0-100) for a specific set of question IDs (e.g. all
 * questions in one domain or module). Returns 0 if the exam isn't tracked
 * or the set is empty.
 */
function _getMasteryPercent(examCode, questionIds) {
  if (!MASTERY_EXAM_CODES.includes(examCode) || questionIds.length === 0) return 0;
  const map = _loadMasteryMap();
  const examMap = map[examCode] || {};
  const masteredCount = questionIds.filter(id => examMap[id] === true).length;
  return Math.round((masteredCount / questionIds.length) * 100);
}

// ---------------------------------------------------------------------------
// Coverage tracking ("no-repeat until exhausted") — Core 1 only.
//
// One shared seen-question ledger per exam code, persisted in localStorage.
// Every draw (Practice Exam, Simulation, Domain, Module) pulls unseen
// questions first; once the entire bank for that exam has been served at
// least once, the ledger silently resets so repeats become possible again
// in a fresh random order. Scope is intentionally the WHOLE exam bank, not
// per-domain/per-module — a question seen in domain practice also counts as
// seen for a later full Practice Exam draw, and vice versa.
// ---------------------------------------------------------------------------

const COVERAGE_KEY = 'aplus_seen_questions';
const COVERAGE_EXAM_CODES = ['220-1201']; // Core 1 only, per spec.

/** Load the full coverage map ({ examCode: [ids] }) from localStorage. */
function _loadCoverageMap() {
  try {
    const raw = localStorage.getItem(COVERAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch (e) {
    return {};
  }
}

/** Persist the full coverage map back to localStorage. */
function _saveCoverageMap(map) {
  try {
    localStorage.setItem(COVERAGE_KEY, JSON.stringify(map));
  } catch (e) {
    console.warn('Failed to save coverage map:', e);
  }
}

/**
 * Mark a batch of question IDs as seen for the given exam code. Silently
 * resets JUST the current draw pool's IDs (not the whole ledger) once every
 * question IN THAT POOL has been covered — e.g. a 70-question module cycles
 * on its own 70, a domain cycles on its own set, and Practice/Simulation
 * (whose pool IS the whole bank) cycle on the whole bank. Everything else
 * already marked seen (from other modules/domains) is left untouched, so
 * the shared ledger still carries over between modes as designed.
 */
function _markQuestionsSeen(examCode, questionIds, poolIds) {
  const map = _loadCoverageMap();
  const seen = new Set(map[examCode] || []);
  questionIds.forEach(id => seen.add(id));

  // Cycle complete for THIS pool: every question in the pool just drawn from
  // (module/domain/whole-bank) has now been served at least once. Reset
  // silently — no message — by removing only this pool's IDs from the seen
  // set so it can draw everything fresh again, next time.
  const poolCovered = poolIds.length > 0 && poolIds.every(id => seen.has(id));

  if (poolCovered) {
    const poolSet = new Set(poolIds);
    map[examCode] = [...seen].filter(id => !poolSet.has(id));
  } else {
    map[examCode] = [...seen];
  }
  _saveCoverageMap(map);
}

/** Set of question IDs already seen for the given exam code (empty if none / not tracked). */
function _getSeenIds(examCode) {
  if (!COVERAGE_EXAM_CODES.includes(examCode)) return new Set();
  const map = _loadCoverageMap();
  return new Set(map[examCode] || []);
}

/**
 * Pick `count` unique questions from `questionBank`.
 *
 * Draw order (strict tiers), used only when `prioritizeMissed` is true:
 *   1. Missed last time   (latest mastery result is wrong/partial)
 *   2. Never attempted    (no mastery record yet)
 *   3. Answered correctly last time
 * Inside each tier, questions NOT yet in the no-repeat coverage ledger come
 * first, then already-seen ones; each group is shuffled. With
 * `prioritizeMissed` false (Simulation, non-Core-1 exams) every question sits
 * in one tier, so the draw is the plain unseen-first behavior.
 */
function selectUniqueQuestions(questionBank, count, prioritizeMissed = false) {
  const selected = [];
  const seenIds = new Set();

  const examCode = appState.examCode;
  const trackCoverage = COVERAGE_EXAM_CODES.includes(examCode);
  const previouslySeen = trackCoverage ? _getSeenIds(examCode) : new Set();
  const masteryMap = (prioritizeMissed && MASTERY_EXAM_CODES.includes(examCode))
    ? (_loadMasteryMap()[examCode] || {})
    : null;

  // 0 = missed last time, 1 = never attempted, 2 = answered correctly last time.
  const tierOf = q => {
    if (!masteryMap) return 0;
    const lastResult = masteryMap[q.id];
    if (lastResult === false) return 0;
    return lastResult === undefined ? 1 : 2;
  };

  const orderedCandidates = [];
  for (let tier = 0; tier <= 2; tier++) {
    const inTier = questionBank.filter(q => tierOf(q) === tier);
    orderedCandidates.push(
      ...shuffleArray(inTier.filter(q => !previouslySeen.has(q.id))),
      ...shuffleArray(inTier.filter(q => previouslySeen.has(q.id)))
    );
  }

  for (const q of orderedCandidates) {
    if (selected.length >= count) break;
    if (!seenIds.has(q.id)) {
      selected.push(q);
      seenIds.add(q.id);
    }
  }

  // If we don't have enough unique questions, log warning
  if (selected.length < count) {
    console.warn(`Requested ${count} unique questions but only ${selected.length} available`);
  }

  // Record this draw in the shared coverage ledger. The cycle-reset check is
  // scoped to THIS draw's own pool (module/domain, or whole bank for Practice).
  if (trackCoverage && selected.length > 0) {
    _markQuestionsSeen(examCode, selected.map(q => q.id), questionBank.map(q => q.id));
  }

  return selected;
}
// ---------------------------------------------------------------------------
// Mode entry points (Step 2). Each configures examMode / feedbackEnabled /
// activeFilter, picks a question set, then hands off to runExam().
// ---------------------------------------------------------------------------

// Practice Exam: choose a size (25/50/75/100% of the full bank) via the count
// modal, then run a random set of that many questions, 1 min/question, feedback on.
function startPracticeExam() {
  const exam = window.questionBank.exams[appState.examCode];
  if (!exam) { alert('Exam not found'); return; }
  const pool = exam.questionBank || [];
  if (!pool.length) { alert('No questions available for this exam'); return; }
  openCountPicker({ pool, mode: 'practice', filter: null, label: 'Practice Exam' });
}

// Others exam: all 9 reference-table questions, full configured time, feedback on.
function startOthersExam() {
  const exam = window.questionBank.exams['others'];
  if (!exam) { alert('Reference Tables exam not loaded — check others_quiz.json'); return; }
  const questions = selectUniqueQuestions(exam.questionBank, exam.questionBank.length);
  appState.examMode = 'practice';
  appState.feedbackEnabled = true;
  appState.activeFilter = null;
  runExam(questions, examTimeLimit(exam) * 60);
}

/** Others topic picker: one "All Topics" card (unchanged combined mode) plus
 *  one card per individual reference table (single-question practice). */
function openOthersPicker() {
  const exam = window.questionBank.exams['others'];
  const container = document.getElementById('othersTopicButtons');
  if (!exam || !container) return;
  container.innerHTML = '';

  const allBtn = document.createElement('button');
  allBtn.className = 'filter-btn';
  allBtn.innerHTML = '<span>📋 All Topics (Combined)</span>' +
    '<span class="filter-count">(' + exam.questionBank.length + ' questions)</span>';
  allBtn.onclick = startOthersExam;
  container.appendChild(allBtn);

  exam.questionBank.forEach(q => {
    // topicLabel is set explicitly on each question in others_quiz.json.
    const label = q.topicLabel || q.id;
    const btn = document.createElement('button');
    btn.className = 'filter-btn';
    btn.innerHTML = '<span>' + escapeHtml(label) + '</span>' +
      '<span class="filter-count">(1 question)</span>';
    btn.onclick = () => startOthersTopic(q.id);
    container.appendChild(btn);
  });

  showScreen('screenOthersPicker');
}

/** Launch a single reference-table question as its own 1-question practice run. */
function startOthersTopic(questionId) {
  const exam = window.questionBank.exams['others'];
  if (!exam) return;
  const question = exam.questionBank.find(q => q.id === questionId);
  if (!question) { alert('Question not found: ' + questionId); return; }
  appState.examMode = 'practice';
  appState.feedbackEnabled = true;
  // Reuse activeFilter to carry the topic name through to the exam header
  // badge and the Progress Dashboard's saved history label (_buildExamLabel).
  appState.activeFilter = { type: 'topic', value: question.id, label: question.topicLabel || question.id };
  runExam([question], 20 * 60);
}

// Simulation Exam: always a fixed 90-question timed exam (clamped to bank size),
// feedback OFF. No size prompt — simulation mimics the real exam length.
const SIMULATION_QUESTION_COUNT = 90;
function startSimulationExam() {
  const exam = window.questionBank.exams[appState.examCode];
  if (!exam) { alert('Exam not found'); return; }
  const bank = exam.questionBank || [];
  const count = Math.min(SIMULATION_QUESTION_COUNT, bank.length);
  const questions = selectUniqueQuestions(bank, count);
  appState.examMode = 'simulation';
  appState.feedbackEnabled = false;
  appState.activeFilter = null;
  runExam(questions, examTimeLimit(exam) * 60);
}

// Practice by Domain / Module: choose a size (25/50/75/100% of the filtered set)
// via the count modal, then run that many random questions, feedback on.
function startFilteredExam(type, value, label) {
  const exam = window.questionBank.exams[appState.examCode];
  if (!exam) { alert('Exam not found'); return; }
  const field = type === 'domain' ? 'domain' : 'module';
  const pool = (exam.questionBank || []).filter(q => q[field] === value);
  if (pool.length === 0) return; // guarded by disabled buttons, but be safe
  openCountPicker({ pool, mode: type, filter: { type, value, label }, label });
}

// ---------------------------------------------------------------------------
// Question-count picker modal. Lets the user pick 25/50/75/100% of the pending
// question pool (whole bank for Practice, filtered set for Domain/Module) before
// the exam starts. Simulation mode does not use this.
// ---------------------------------------------------------------------------

/** Number of questions for a given pool size and percentage: ceil, min 1. */
function questionsForPercent(poolSize, pct) {
  return Math.max(1, Math.min(poolSize, Math.ceil(poolSize * pct / 100)));
}

/** Open the size modal, stashing the pending launch config in appState. */
function openCountPicker(spec) {
  appState.pendingLaunch = spec;
  const subtitle = document.getElementById('countPickerSubtitle');
  if (subtitle) {
    subtitle.textContent = spec.mode === 'practice'
      ? 'Choose what portion of the full question bank to include (' +
        spec.pool.length + ' available).'
      : 'Choose what portion of "' + spec.label + '" to include (' +
        spec.pool.length + ' available).';
  }
  // Reset the dropdown to 100% each time the modal opens.
  const sel = document.getElementById('countPickerSelect');
  if (sel) sel.value = '100';
  updateCountPickerCount();
  const modal = document.getElementById('countPickerModal');
  if (modal) modal.classList.remove('hidden');
}

/** Live-update the "N questions" line as the dropdown changes. */
function updateCountPickerCount() {
  if (!appState.pendingLaunch) return;
  const sel = document.getElementById('countPickerSelect');
  const pct = Number(sel && sel.value) || 100;
  const n = questionsForPercent(appState.pendingLaunch.pool.length, pct);
  const line = document.getElementById('countPickerCount');
  if (line) line.textContent = n + ' question' + (n === 1 ? '' : 's') + ' will be included.';
}

/** Cancel: close the modal and discard the pending launch. */
function closeCountPicker() {
  const modal = document.getElementById('countPickerModal');
  if (modal) modal.classList.add('hidden');
  appState.pendingLaunch = null;
}

/** Continue: build the sized question set and launch the exam. */
function countPickerContinue() {
  const spec = appState.pendingLaunch;
  if (!spec) return;
  const sel = document.getElementById('countPickerSelect');
  const pct = Number(sel && sel.value) || 100;
  const count = questionsForPercent(spec.pool.length, pct);
  const questions = selectUniqueQuestions(spec.pool, count, /* prioritizeMissed */ true);

  appState.examMode = spec.mode;                 // 'practice' | 'domain' | 'module'
  appState.feedbackEnabled = true;
  appState.activeFilter = spec.filter;           // null for practice, {type,value,label} otherwise

  const modal = document.getElementById('countPickerModal');
  if (modal) modal.classList.add('hidden');
  appState.pendingLaunch = null;

  runExam(questions, count * 60);                // 1 minute per question
}

// Human-readable label for the current mode (badge + persistence display).
function modeDisplayName() {
  switch (appState.examMode) {
    case 'simulation': return 'Simulation';
    case 'domain': return 'Practice \u00b7 Domain';
    case 'module': return 'Practice \u00b7 Module';
    default: return 'Practice';
  }
}

/**
 * Shared exam runner. Randomizes options, resets per-attempt state, wires the
 * header/badge/filter-note, then starts the exam screen. Used by every mode and
 * (indirectly) by resume.
 * @param {object[]} selectedQuestions - already-filtered question set
 * @param {number} timeSeconds - timer duration in seconds
 */
function runExam(selectedQuestions, timeSeconds, drillMode = false) {
  const exam = window.questionBank.exams[appState.examCode];

  appState.questions = selectedQuestions.map(q => randomizeQuestionOptions(q));
  appState.examTimeAllotted = timeSeconds; // Remembered so a retake can reuse the same time budget.
  // Drill mode (Retake Missed Questions): scoring/review work exactly as normal,
  // but submitExam() skips localStorage/history persistence. See submitExam().
  appState.isDrillMode = drillMode;
  appState.currentQuestionIndex = 0;
  appState.answers = {};
  appState.flagged.clear();
  appState.autoFlagged.clear();
  appState.checkedQuestions.clear();
  appState.validatedDragDrops.clear();
  appState.displayedQuestionIds.clear();
  appState.examStartTime = Date.now();
  appState.timeRemaining = timeSeconds;

  showScreen('screenExam');
  document.getElementById('topbarExamName').textContent = exam.name + ' (' + exam.code + ')';
  applyModeHeader();

  buildNavigator();
  loadQuestion(0);
  startTimer();
}

/** Set the exam-header mode badge and the optional active-filter note. */
function applyModeHeader() {
  const badge = document.getElementById('qModeBadge');
  if (badge) {
    badge.textContent = modeDisplayName();
    badge.classList.toggle('simulation', appState.examMode === 'simulation');
  }
  const note = document.getElementById('qFilterNote');
  if (note) {
    if (appState.activeFilter) {
      note.textContent = 'Filtered: ' + appState.activeFilter.label +
        ' (' + appState.questions.length + ' question' +
        (appState.questions.length === 1 ? '' : 's') + ')';
      note.classList.remove('hidden');
    } else {
      note.textContent = '';
      note.classList.add('hidden');
    }
  }
}

// Fisher-Yates shuffle algorithm
function shuffleArray(array) {
  const shuffled = [...array];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
}

// Randomize options within a question
function randomizeQuestionOptions(question) {
  const q = JSON.parse(JSON.stringify(question)); // Deep copy to avoid modifying original

  // Detect True/False questions and enforce True-first order — never shuffle them
  const isTrueFalse = q.options && q.options.length === 2 &&
    q.options.every(o => o.toLowerCase() === 'true' || o.toLowerCase() === 'false');
  if (isTrueFalse) {
    q.options = ['True', 'False'];
    return q;
  }

  if (q.type === 'mc') {
    // For multiple choice: shuffle options and track new correct answer index
    const correctAnswerText = Array.isArray(q.correctAnswer) ? q.correctAnswer[0] : q.correctAnswer;
    
    // Ensure we have options to shuffle
    if (!q.options || q.options.length === 0) {
      console.warn('Question has no options:', q.id);
      return q;
    }
    
    // Create array with both option text and a marker for the correct answer
    const optionsWithCorrectMarker = q.options.map((opt, idx) => ({
      text: opt,
      isCorrect: opt === correctAnswerText
    }));

    // Pull out any "All of the above" option before shuffling — it always goes last
    const allAboveIdx = optionsWithCorrectMarker.findIndex(o => o.text.toLowerCase() === 'all of the above');
    const allAboveItem = allAboveIdx > -1 ? optionsWithCorrectMarker.splice(allAboveIdx, 1)[0] : null;
    
    // Shuffle
    const shuffled = shuffleArray(optionsWithCorrectMarker);
    if (allAboveItem) shuffled.push(allAboveItem);
    
    // Update options and find new correct answer index
    q.options = shuffled.map(item => item.text);
    const newCorrectIndex = shuffled.findIndex(item => item.isCorrect);
    q.correctAnswer = [q.options[newCorrectIndex]]; // Keep as array of text
  } 
  else if (q.type === 'multi') {
    // For multi-select: shuffle options while preserving which ones are correct
    const correctAnswerTexts = q.correctAnswer; // Already array of strings
    
    const optionsWithCorrectMarker = q.options.map((opt, idx) => ({
      text: opt,
      isCorrect: correctAnswerTexts.includes(opt)
    }));

    // Pull out any "All of the above" option before shuffling — it always goes last
    const allAboveIdx = optionsWithCorrectMarker.findIndex(o => o.text.toLowerCase() === 'all of the above');
    const allAboveItem = allAboveIdx > -1 ? optionsWithCorrectMarker.splice(allAboveIdx, 1)[0] : null;
    
    // Shuffle
    const shuffled = shuffleArray(optionsWithCorrectMarker);
    if (allAboveItem) shuffled.push(allAboveItem);
    
    // Update options and correct answers
    q.options = shuffled.map(item => item.text);
    q.correctAnswer = shuffled.filter(item => item.isCorrect).map(item => item.text);
  } 
  
  // table_match — shuffle each column's option list once so the order stays
  // consistent for the entire session (renderTableMatch won't re-shuffle).
  // Dropdown options are sorted A→Z (not shuffled), and the row order (first
  // column) is randomized instead of the bank's fixed order — applies to
  // every "Others" reference-table topic, EXCEPT TBL-006 (Laser Printer
  // Imaging Process), whose "Step" column is a fixed sequence (1–7) and must
  // stay in ascending order — only its dropdown columns get sorted A→Z.
  else if (q.type === 'table_match') {
    const sortedOpts = {};
    Object.keys(q.columnOptions || {}).forEach(col => {
      sortedOpts[col] = [...q.columnOptions[col]].sort((a, b) => a.localeCompare(b));
    });
    q.columnOptions = sortedOpts;
    if (q.id !== 'TBL-006') {
      q.rows = shuffleArray(q.rows || []);
    }
  }

  return q;
}

// Build navigator grid
function buildNavigator() {
  const navGrid = document.getElementById('navGrid');
  navGrid.innerHTML = '';
  
  appState.questions.forEach((q, idx) => {
    const cell = document.createElement('div');
    cell.className = 'nav-cell';
    cell.textContent = idx + 1;
    cell.onclick = () => jumpToQuestion(idx);
    cell.id = 'nav-' + idx;
    navGrid.appendChild(cell);
  });
  
  updateNavigator();
}

// Update navigator cell status
function updateNavigator() {
  appState.questions.forEach((q, idx) => {
    const cell = document.getElementById('nav-' + idx);
    if (!cell) return;
    
    cell.classList.remove('answered', 'answered-neutral', 'incorrect', 'flagged', 'locked', 'current', 'partial');
    
    if (idx === appState.currentQuestionIndex) {
      cell.classList.add('current');
    }
    
    // Check if question is answered or flagged
    const isAnswered = (appState.questions[idx] && appState.questions[idx].type === 'table_match')
      ? isTableMatchComplete(appState.questions[idx], appState.answers[idx])
      : appState.answers[idx] !== undefined;
    const isFlagged = appState.flagged.has(idx);
    const userAnswer = appState.answers[idx];
    const isChecked = appState.checkedQuestions.has(idx);
    // Correctness is revealed only once feedback is enabled AND the question has
    // actually been "Checked" (Simulation mode never reveals it at all).
    const revealCorrectness = appState.feedbackEnabled && isChecked;
    
    // FLAGGED takes precedence over answered/unanswered
    if (isFlagged) {
      // Flagged questions are always yellow, regardless of answer state
      cell.classList.add('flagged');
    } else if (isAnswered) {
      if (!revealCorrectness) {
        // Answered but correctness not shown yet: Simulation mode, or a
        // practice-mode question that's answered but "Check" hasn't been
        // pressed. Neutral blue fill. Only locked once actually checked
        // (Simulation) or checked (practice) — stays editable until then.
        cell.classList.add('answered-neutral');
        if (!appState.feedbackEnabled || isChecked) {
          cell.classList.add('locked');
        }
      } else {
        // Practice modes: reveal correctness via color.
        const isCorrect = checkAnswerCorrect(q, userAnswer);
        
        if (typeof isCorrect === 'number') {
          // Multi-select scoring: 100 = green, 50 = yellow, 0 = red
          if (isCorrect === 100) {
            cell.classList.add('answered');  // Green
          } else if (isCorrect === 50) {
            cell.classList.add('partial');  // Yellow (partial credit)
          } else if (isCorrect === 0) {
            cell.classList.add('incorrect');  // Red
          }
        } else if (isCorrect === true) {
          cell.classList.add('answered');  // Green
        } else {
          cell.classList.add('incorrect');  // Red
        }
        // Add locked class since it's answered and not flagged
        cell.classList.add('locked');  // Disable cursor and reduce opacity
      }
    }
    // If not answered and not flagged, stays gray (default state)
  });
}

// Helper: true when every cell in a table_match is filled
function isTableMatchComplete(question, answer) {
  if (!answer || !question.rows || !question.headers) return false;
  var colHeaders = question.headers.slice(1);
  return question.rows.every(function(row) {
    return colHeaders.every(function(h) {
      return answer[row.key] && answer[row.key][h];
    });
  });
}

// Load question

/**
 * "Check" button handler for every practice mode except Simulation.
 * Scores the current question, marks it checked (locks inputs), paints
 * inline correctness feedback using the same colors as the review page,
 * and flips the Next/Check button back to "Next" — it does NOT advance.
 */
/**
 * Lightweight button-only refresh, called from option onchange handlers so the
 * Next/Check label updates immediately on selection without re-rendering the
 * whole question (which would wipe the user's in-progress picks). Only takes
 * effect in feedback-enabled modes (everything except Simulation); Simulation
 * mode never shows "Check" and keeps its original Next/Submit label.
 */
function refreshCheckButton(questionIndex) {
  if (!appState.feedbackEnabled) return;
  if (appState.checkedQuestions.has(questionIndex)) return; // already checked — button stays as-is

  // Mirror loadQuestion()'s isAnswered rule: table_match needs every cell
  // filled; other types just need an answer object/value present.
  const question = appState.questions[questionIndex];
  const isAnswered = question && question.type === 'table_match'
    ? isTableMatchComplete(question, appState.answers[questionIndex])
    : appState.answers[questionIndex] !== undefined;
  if (!isAnswered) return; // not answered enough yet — leave button as Next/disabled state

  const btnNext = document.getElementById('btnNext');
  if (!btnNext) return;
  btnNext.textContent = 'Check';
  btnNext.className = 'btn primary';
  btnNext.onclick = checkCurrentQuestion;
}

function checkCurrentQuestion() {
  const index = appState.currentQuestionIndex;
  appState.checkedQuestions.add(index);

  // Clear any auto-flag now that the question has been answered + checked.
  if (appState.autoFlagged.has(index)) {
    appState.flagged.delete(index);
    appState.autoFlagged.delete(index);
  }

  saveExamState();
  // loadQuestion() recomputes isLocked/needsCheck from checkedQuestions and will
  // now render the question locked + colored, with the button already correct
  // ("Next" / "Submit Exam") — no manual button fixup needed here.
  loadQuestion(index);
}

/**
 * Paints correct/incorrect/missed coloring directly onto the just-rendered
 * options for the given question, reusing the same classes/colors as the
 * review page. Called after a question has been checked (or when revisiting
 * an already-checked question).
 */
function applyInlineFeedback(question, container, questionIndex) {
  const answer = appState.answers[questionIndex];

  if (question.type === 'matching') {
    const userMap = (answer && typeof answer === 'object') ? answer : {};
    const correctMap = question.correctAnswer || {};
    container.querySelectorAll('.matching-row').forEach((row, i) => {
      const key = question.items[i];
      const isRight = userMap[key] === correctMap[key];
      row.classList.add(isRight ? 'review-correct' : 'review-incorrect');
    });
  } else if (question.type === 'table_match') {
    // Color each dropdown cell green/red based on the saved answer vs correctAnswer.
    const userMap = (answer && typeof answer === 'object') ? answer : {};
    const correctMap = question.correctAnswer || {};
    const colHeaders = (question.headers || []).slice(1);

    container.querySelectorAll('.table-match-row').forEach((tr, rowIdx) => {
      const row = question.rows[rowIdx];
      if (!row) return;
      const cells = tr.querySelectorAll('.table-match-cell');
      colHeaders.forEach((colHeader, colIdx) => {
        const cell = cells[colIdx];
        if (!cell) return;
        const userVal = (userMap[row.key] || {})[colHeader];
        const correctVal = (correctMap[row.key] || {})[colHeader];
        cell.classList.add(userVal === correctVal ? 'tmr-correct' : 'tmr-wrong');
      });
    });
  } else {
    // mc / multi
    const correctAnswers = Array.isArray(question.correctAnswer) ? question.correctAnswer :
      (typeof question.correctAnswer === 'string' ? [question.correctAnswer] : []);
    const userAnswers = Array.isArray(answer) ? answer : (typeof answer === 'string' ? [answer] : []);
    const isMulti = question.type === 'multi' ||
      (!question.type && Array.isArray(question.correctAnswer) && question.correctAnswer.length > 1);

    container.querySelectorAll('.option').forEach(label => {
      const optText = label.querySelector('.opt-text');
      const option = optText ? optText.textContent : '';
      const isCorrectOption = correctAnswers.includes(option);
      const userPicked = userAnswers.includes(option);

      if (isCorrectOption && userPicked) {
        label.classList.add('opt-correct');
      } else if (!isCorrectOption && userPicked) {
        label.classList.add('opt-incorrect');
      } else if (isCorrectOption && !userPicked && isMulti) {
        label.classList.add('opt-missed');
      } else if (isCorrectOption && !userPicked && !isMulti) {
        label.classList.add('opt-correct');
      }
    });
  }
}

function loadQuestion(index) {
  if (index < 0 || index >= appState.questions.length) return;
  
  appState.currentQuestionIndex = index;
  const question = appState.questions[index];
  
  // Track this question ID to prevent duplicates
  appState.displayedQuestionIds.add(question.id);
  
  // For table_match: only lock when ALL cells are filled (not on first cell)
  const isAnswered = question.type === 'table_match'
    ? isTableMatchComplete(question, appState.answers[index])
    : appState.answers[index] !== undefined;
  const isFlagged = appState.flagged.has(index);

  // Lock condition differs by mode:
  //  - Simulation (feedbackEnabled=false): unchanged legacy behavior — locked as
  //    soon as it's answered (you can't revisit/edit a past question).
  //  - All other modes: options stay editable until the user presses "Check".
  //    Flagging always unlocks (existing escape hatch), same as before.
  const isLocked = appState.feedbackEnabled
    ? (appState.checkedQuestions.has(index) && !isFlagged)
    : (isAnswered && !isFlagged);
  
  // Update header
  document.getElementById('qNumber').textContent = 'Q' + (index + 1) + ' of ' + appState.questions.length;
  document.getElementById('qDomainTag').textContent = question.domain;
  
  // Update question text
  const qStem = document.getElementById('qStem');
  
  qStem.textContent = question.stem;
  
  // Lock indicator lives below the nav buttons (outside the question/options
  // container), not above the stem. Rebuilt fresh on every loadQuestion call.
  const lockSlot = document.getElementById('lockIndicatorSlot');
  if (lockSlot) {
    lockSlot.innerHTML = '';
  }
  if (isLocked && lockSlot) {
    const lockIndicator = document.createElement('div');
    lockIndicator.className = 'lock-indicator';
    lockIndicator.textContent = '🔒 This question is locked. Only flagged questions can be revisited.';
    lockSlot.appendChild(lockIndicator);
  }
  
  // Show hint for multi-select — mirrors the isMulti derivation in renderMultipleChoice
  const isMultiQuestion = question.type === 'multi' ||
    (!question.type && Array.isArray(question.correctAnswer) && question.correctAnswer.length > 1);
  document.getElementById('qHint').classList.toggle('hidden', !isMultiQuestion);
  
  // Render options based on type
  const optionsContainer = document.getElementById('qOptions');
  optionsContainer.innerHTML = '';
  
  if (question.type === 'mc' || question.type === 'multi' || isMultiQuestion) {
    renderMultipleChoice(question, optionsContainer, index, isLocked);
  } else if (question.type === 'matching') {
    renderMatching(question, optionsContainer, index, isLocked);
  } else if (question.type === 'table_match') {
    renderTableMatch(question, optionsContainer, index, isLocked);
  }

  // Once checked (or, in Simulation mode, once answered+locked isn't shown —
  // Simulation withholds feedback entirely), paint correctness coloring.
  const showFeedbackNow = appState.feedbackEnabled && appState.checkedQuestions.has(index);
  if (showFeedbackNow) {
    applyInlineFeedback(question, optionsContainer, index);
  }
  
  // Update buttons
  document.getElementById('btnPrev').disabled = index === 0;
  const isLastQuestion = index === appState.questions.length - 1;
  const btnNext = document.getElementById('btnNext');
  
  // Simulation mode: unchanged legacy Next/Submit behavior, no Check step.
  // All other modes: show "Check" until the question has been checked, then
  // behave exactly like today (Next / Submit Exam).
  const needsCheck = appState.feedbackEnabled &&
    isAnswered && !appState.checkedQuestions.has(index) && !isFlagged;

  if (needsCheck) {
    btnNext.disabled = false;
    btnNext.textContent = 'Check';
    btnNext.className = 'btn primary';
    btnNext.onclick = checkCurrentQuestion;
  } else {
    if (isLastQuestion) {
      btnNext.disabled = false;
      btnNext.textContent = 'Submit Exam';
      btnNext.className = 'btn danger';
      btnNext.onclick = submitExam;
    } else {
      btnNext.disabled = false;
      btnNext.textContent = 'Next →';
      btnNext.className = 'btn primary';
      btnNext.onclick = nextQuestion;
    }
  }
  
  // Update flag button
  document.getElementById('btnFlag').classList.toggle('active', isFlagged);
  
  // Update navigator
  updateNavigator();
  
  // Save current exam state to localStorage
  saveExamState();
}

// Render multiple choice
function renderMultipleChoice(question, container, questionIndex, isLocked) {
  // Derive isMulti from the type field, with a fallback to check correctAnswer length.
  // This guards against stale localStorage data where the type field may be missing.
  const isMulti = question.type === 'multi' ||
    (!question.type && Array.isArray(question.correctAnswer) && question.correctAnswer.length > 1);
  
  const currentAnswers = appState.answers[questionIndex] || (isMulti ? [] : null);
  // isLocked is now computed once in loadQuestion() and passed in, so it stays
  // consistent with the Check/Next state machine (checkedQuestions-based lock).
  
  question.options.forEach((option, idx) => {
    const label = document.createElement('label');
    label.className = 'option';
    
    const inputType = isMulti ? 'checkbox' : 'radio';
    const input = document.createElement('input');
    input.type = inputType;
    input.name = 'answer-' + questionIndex;
    input.value = idx; // This is just for HTML, we won't use it
    
    // Disable input if question is locked
    if (isLocked) {
      input.disabled = true;
      label.style.opacity = '0.6';
      label.style.cursor = 'not-allowed';
    }
    
    if (isMulti) {
      // For multi: check if option text is in the saved answers (which are now text-based)
      const savedAnswers = currentAnswers || [];
      input.checked = savedAnswers.includes(option);
      
      input.onchange = function(e) {
        if (isLocked) return;
        
        const answers = appState.answers[questionIndex] || [];
        if (this.checked) {
          // Store as text, not index
          if (!answers.includes(option)) {
            answers.push(option);
          }
        } else {
          // Remove by text
          const findIdx = answers.indexOf(option);
          if (findIdx > -1) {
            answers.splice(findIdx, 1);
          }
        }
        appState.answers[questionIndex] = answers;
        label.classList.toggle('selected', this.checked);
        
        // If this question was auto-flagged and now has an answer, remove auto-flag
        // But don't validate yet - wait until user clicks Next
        if (appState.autoFlagged.has(questionIndex) && answers.length > 0) {
          appState.flagged.delete(questionIndex);
          appState.autoFlagged.delete(questionIndex);
        }
        // Don't call updateNavigator() — validation happens on Check/Next button click.
        saveExamState();
        refreshCheckButton(questionIndex);
      };
    } else {
      // For single choice: check if option text matches saved answer
      const savedAnswer = currentAnswers; // Will be a string (option text) or null
      input.checked = option === savedAnswer;
      
      input.onchange = function(e) {
        if (isLocked) return;
        // Store as text, not index
        appState.answers[questionIndex] = option;
        // Update all labels
        document.querySelectorAll('label[name="answer-' + questionIndex + '"]').forEach(l => l.classList.remove('selected'));
        label.classList.add('selected');
        
        // If this question was auto-flagged and now has an answer, remove auto-flag
        // But don't validate yet - wait until user clicks Next
        if (appState.autoFlagged.has(questionIndex)) {
          appState.flagged.delete(questionIndex);
          appState.autoFlagged.delete(questionIndex);
        }
        // Don't call updateNavigator() — validation happens on Check/Next button click.
        saveExamState();
        refreshCheckButton(questionIndex);
      };
    }
    
    const text = document.createElement('span');
    text.className = 'opt-text';
    text.textContent = option;
    
    label.appendChild(input);
    label.appendChild(text);
    label.setAttribute('name', 'answer-' + questionIndex);
    
    // Check if this option should be marked as selected
    if (isMulti) {
      const savedAnswers = currentAnswers || [];
      if (savedAnswers.includes(option)) {
        label.classList.add('selected');
      }
    } else {
      if (option === currentAnswers) {
        label.classList.add('selected');
      }
    }
    
    container.appendChild(label);
  });
}

function renderMatching(question, container, questionIndex, isLocked) {
  // Normalise both schemas into a unified rows/choices structure:
  //   rows    — array of { key, label } — the left-column items
  //   choices — array of strings        — the right-column dropdown options
  //   correct — { key: correctValue }
  //
  // matching schema:  items[] (strings) + options[] (strings)
  const choices = question.options || [];
  const rows = question.items.map(item => ({
    key: item,
    label: item,
    correct: (question.correctAnswer && question.correctAnswer[item]) || ''
  }));

  // Saved answer: flat object { rowKey: chosenValue }
  const savedAnswer = appState.answers[questionIndex] || {};
  // isLocked is now computed once in loadQuestion() and passed in.

  rows.forEach(row => {
    const rowEl = document.createElement('div');
    rowEl.className = 'matching-row';

    const labelEl = document.createElement('span');
    labelEl.className = 'matching-label';
    labelEl.textContent = row.label;

    const select = document.createElement('select');
    select.className = 'matching-select';
    select.disabled = isLocked;

    // Blank placeholder
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '— Select an answer —';
    placeholder.disabled = true;
    placeholder.selected = !savedAnswer[row.key];
    select.appendChild(placeholder);

    choices.forEach(choice => {
      const opt = document.createElement('option');
      opt.value = choice;
      opt.textContent = choice;
      opt.selected = savedAnswer[row.key] === choice;
      select.appendChild(opt);
    });

    select.onchange = () => {
      if (isLocked) return;
      const current = appState.answers[questionIndex] || {};
      current[row.key] = select.value;
      appState.answers[questionIndex] = current;

      // Check if all rows have a selection — mark answered when complete
      const allFilled = rows.every(r => current[r.key]);
      if (allFilled && appState.autoFlagged.has(questionIndex)) {
        appState.flagged.delete(questionIndex);
        appState.autoFlagged.delete(questionIndex);
      }
      saveExamState();
      // Don't call updateNavigator() — wait for Check/Next button click, same as mc/multi.
      refreshCheckButton(questionIndex);
    };

    rowEl.appendChild(labelEl);
    rowEl.appendChild(select);
    container.appendChild(rowEl);
  });
}

// Render a table-match question — multi-column matching table
function renderTableMatch(question, container, questionIndex, isLocked) {
  const headers    = question.headers || [];
  const colHeaders = headers.slice(1);
  const rows       = question.rows || [];
  const colOpts    = question.columnOptions || {};

  const savedAnswer = appState.answers[questionIndex] || {};
  // isLocked is now computed once in loadQuestion() and passed in.

  const wrapper = document.createElement('div');
  wrapper.className = 'table-match-wrapper';

  const table = document.createElement('table');
  table.className = 'table-match';

  // Header row
  const thead = document.createElement('thead');
  const hRow  = document.createElement('tr');
  headers.forEach(h => {
    const th = document.createElement('th');
    th.className = 'table-match-th';
    th.textContent = h;
    hRow.appendChild(th);
  });
  thead.appendChild(hRow);
  table.appendChild(thead);

  // Body rows
  const tbody = document.createElement('tbody');
  rows.forEach(row => {
    const tr = document.createElement('tr');
    tr.className = 'table-match-row';

    // Fixed key cell
    const keyTd = document.createElement('td');
    keyTd.className = 'table-match-key';
    keyTd.textContent = row.key;
    tr.appendChild(keyTd);

    // Dropdown cell for each non-key column
    colHeaders.forEach(colHeader => {
      const td = document.createElement('td');
      td.className = 'table-match-cell';

      const select = document.createElement('select');
      select.className = 'matching-select table-match-select';
      select.disabled = isLocked;

      // Placeholder
      const ph = document.createElement('option');
      ph.value = '';
      ph.textContent = '— Select —';
      ph.disabled = true;
      const savedCell = (savedAnswer[row.key] || {})[colHeader];
      ph.selected = !savedCell;
      select.appendChild(ph);

      // Shuffled options
      const opts = colOpts[colHeader] || [];
      opts.forEach(opt => {
        const o = document.createElement('option');
        o.value = opt;
        o.textContent = opt;
        o.selected = savedCell === opt;
        select.appendChild(o);
      });

      select.onchange = () => {
        if (isLocked) return;
        const current = appState.answers[questionIndex] || {};
        if (!current[row.key]) current[row.key] = {};
        current[row.key][colHeader] = select.value;
        appState.answers[questionIndex] = current;

        // Clear auto-flag if all cells are now filled
        if (isTableMatchComplete(question, current) && appState.autoFlagged.has(questionIndex)) {
          appState.flagged.delete(questionIndex);
          appState.autoFlagged.delete(questionIndex);
        }
        saveExamState();
        // Don't call updateNavigator() — wait for Check/Next button click, same as mc/multi.
        refreshCheckButton(questionIndex);
      };

      td.appendChild(select);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });

  table.appendChild(tbody);
  wrapper.appendChild(table);
  container.appendChild(wrapper);
}


// Navigation
function prevQuestion() {
  const currentQuestion = appState.questions[appState.currentQuestionIndex];
  const isAnswered = appState.answers[appState.currentQuestionIndex] !== undefined;
  
  if (!isAnswered) {
    // Auto-flag unanswered questions
    appState.flagged.add(appState.currentQuestionIndex);
    appState.autoFlagged.add(appState.currentQuestionIndex);
  }
  
  saveExamState();
  
  if (appState.currentQuestionIndex > 0) {
    loadQuestion(appState.currentQuestionIndex - 1);
  }
}

function nextQuestion() {
  const currentQuestion = appState.questions[appState.currentQuestionIndex];
  const isAnswered = appState.answers[appState.currentQuestionIndex] !== undefined;
  
  if (!isAnswered) {
    // Auto-flag unanswered questions
    appState.flagged.add(appState.currentQuestionIndex);
    appState.autoFlagged.add(appState.currentQuestionIndex);
  }
  
  saveExamState();
  
  if (appState.currentQuestionIndex < appState.questions.length - 1) {
    loadQuestion(appState.currentQuestionIndex + 1);
  }
}

function jumpToQuestion(index) {
  // Always navigate to the clicked question, even if it's locked — locked
  // just means its inputs are disabled (read-only view), not that it's
  // unreachable. loadQuestion() renders the lock indicator/colors/disabled
  // inputs itself based on the same isLocked rule, so nothing else needed here.
  if (index < 0 || index >= appState.questions.length) return;

  loadQuestion(index);
  updateNavigator(); // Update navigator when jumping to a question
}

// Flag question
function toggleFlag() {
  const idx = appState.currentQuestionIndex;
  if (appState.flagged.has(idx)) {
    appState.flagged.delete(idx);
  } else {
    appState.flagged.add(idx);
  }
  updateNavigator();
  saveExamState();
  document.getElementById('btnFlag').classList.toggle('active');
}

// Timer
function startTimer() {
  clearInterval(appState.timerInterval);
  document.getElementById('timerDisplay').classList.remove('hidden');
  // Draw the starting value right away. Without this, a retake/restart keeps
  // showing the previous run's last value until the first 1-second tick.
  updateTimerDisplay();
  
  appState.timerInterval = setInterval(() => {
    appState.timeRemaining--;
    updateTimerDisplay();
    
    if (appState.timeRemaining <= 0) {
      clearInterval(appState.timerInterval);
      submitExam();
    }
  }, 1000);
}

function updateTimerDisplay() {
  const mins = Math.floor(appState.timeRemaining / 60);
  const secs = appState.timeRemaining % 60;
  const display = String(mins).padStart(2, '0') + ':' + String(secs).padStart(2, '0');
  const timerEl = document.getElementById('timerDisplay');
  timerEl.textContent = display;
  // 5 min warning. Toggled (not just added) so a fresh run with plenty of
  // time left doesn't inherit the previous run's red warning state.
  timerEl.classList.toggle('warn', appState.timeRemaining <= 300);
}

// Submit exam
function submitExam() {
  clearInterval(appState.timerInterval);
  
  // Calculate results
  let perfect = 0;    // 100% correct
  let partial = 0;    // 50% partial credit
  let incorrect = 0;  // 0% wrong (includes 0 score from multi-select)
  let unanswered = 0;
  
  appState.questions.forEach((q, idx) => {
    if (appState.answers[idx] === undefined) {
      unanswered++;
    } else {
      const result = checkAnswerCorrect(q, appState.answers[idx]);
      // Mastery tracking: record this question's most-recent result,
      // regardless of mode (Practice/Simulation/Domain/Module/drill).
      const isFullyCorrect = typeof result === 'number' ? result === 100 : result === true;
      _recordMastery(appState.examCode, q.id, isFullyCorrect);
      
      if (typeof result === 'number') {
        // Multi-select scoring
        if (result === 100) {
          perfect++;
        } else if (result === 50) {
          partial++;
        } else if (result === 0) {
          incorrect++;
        }
      } else if (result === true) {
        // MC or drag-drop correct
        perfect++;
      } else {
        // MC or drag-drop incorrect
        incorrect++;
      }
    }
  });
  
  // For binary pass/fail: treat 50% as wrong (don't count toward passing score)
  const binaryCorrect = perfect;  // Only perfect scores count toward pass
  const rawScore = (binaryCorrect / appState.questions.length) * 100;
  const exam = window.questionBank.exams[appState.examCode];
  const scaledScore = Math.round((rawScore / 100) * (exam.maxScore - exam.minScore) + exam.minScore);
  const passed = scaledScore >= exam.passingScore;
  
  // Store results data
  const examResults = {
    perfect: perfect,
    partial: partial,
    incorrect: incorrect,
    unanswered: unanswered,
    examLabel: typeof _buildExamLabel === 'function' ? _buildExamLabel(appState, exam) : exam.name,
    scaledScore: scaledScore,
    passingScore: exam.passingScore,
    passed: passed,
    examCode: appState.examCode,
    questions: appState.questions,
    answers: appState.answers
  };
  
  window.examResults = examResults;
  
  // Clear the in-progress exam state so a page reload after submission
  // never restores this session as an unfinished exam.
  localStorage.removeItem('aplus_exam_state');

  // Drill mode ("Retake Missed Questions"): results still display normally,
  // but nothing is persisted — no localStorage snapshot, no Progress
  // Dashboard history entry, and no "retake this run" buttons (a drill isn't
  // a real attempt worth saving or re-drilling itself).
  if (!appState.isDrillMode) {
    // Save to localStorage
    localStorage.setItem('aplus_exam_results', JSON.stringify({
      perfect: perfect,
      partial: partial,
      incorrect: incorrect,
      unanswered: unanswered,
      scaledScore: scaledScore,
      passingScore: exam.passingScore,
      passed: passed,
      examCode: appState.examCode
    }));

    // Persist result to progress history before showing modal
    if (typeof saveResult === 'function') {
      saveResult(examResults, appState, exam);
    }
  }

  // Single-topic Others run (1 question): remember which topic so "Start Over"
  // can relaunch the exact same question. Hidden for every other exam/mode.
  const btnStartOver = document.getElementById('btnStartOverTopic');
  if (btnStartOver) {
    const isSingleOthersTopic = !appState.isDrillMode &&
      appState.examCode === 'others' && appState.questions.length === 1;
    btnStartOver.classList.toggle('hidden', !isSingleOthersTopic);
    if (isSingleOthersTopic) {
      window.lastOthersTopicId = appState.questions[0].id;
    }
  }

  // "Select Exam Mode" is redundant for Others — it has no mode picker, so
  // that button and "Select Domain / Module / Topic" both just reopen the
  // same topic picker. Keep only the one, more descriptive, button for it.
  const btnSelectExamMode = document.getElementById('btnSelectExamMode');
  if (btnSelectExamMode) {
    btnSelectExamMode.classList.toggle('hidden', appState.isDrillMode || appState.examCode === 'others');
  }

  // Remember this run's exact question set + settings so "Retake Same Exam"
  // can relaunch them in a freshly shuffled order (options are re-randomized
  // too, same as any other new run, via randomizeQuestionOptions in runExam).
  // Skipped for single-question runs (Others topic mode) — "Start Over" above
  // already covers that case and reordering 1 question is meaningless.
  // Also skipped entirely for drill mode runs.
  if (!appState.isDrillMode) {
    window.lastExamRetakeInfo = {
      examCode: appState.examCode,
      questions: appState.questions,
      timeSeconds: appState.examTimeAllotted || (appState.questions.length * 60),
      examMode: appState.examMode,
      feedbackEnabled: appState.feedbackEnabled,
      activeFilter: appState.activeFilter
    };
  }
  const btnRetake = document.getElementById('btnRetakeShuffled');
  if (btnRetake) {
    const isSingleQuestionRun = appState.isDrillMode || appState.questions.length <= 1;
    btnRetake.classList.toggle('hidden', isSingleQuestionRun);
  }

  // Show/hide the "Retake Missed Questions" button itself: only offered when
  // this attempt actually had partial/incorrect answers to drill, and this
  // isn't already a drill run (no drilling a drill).
  const btnRetakeMissed = document.getElementById('btnRetakeMissed');
  if (btnRetakeMissed) {
    const hasMissed = (partial + incorrect) > 0;
    btnRetakeMissed.classList.toggle('hidden', appState.isDrillMode || !hasMissed);
    if (hasMissed) {
      window.lastMissedQuestions = appState.questions.filter((q, idx) => {
        const ans = appState.answers[idx];
        if (ans === undefined) return false; // unanswered isn't "missed", it's skipped
        const result = checkAnswerCorrect(q, ans);
        return typeof result === 'number' ? result < 100 : result !== true;
      });
    }
  }

  // Show completion modal first
  showCompletionModal();
}

/** Relaunch the same single reference-table question the user just finished. */
function restartOthersTopic() {
  if (!window.lastOthersTopicId) { backToMenu(); return; }
  startOthersTopic(window.lastOthersTopicId);
}

/**
 * Retake the exam just finished, with the exact same set of questions but in
 * a freshly randomized order. Option order is also re-shuffled per question,
 * same as any fresh run, via randomizeQuestionOptions() inside runExam().
 * Same mode (practice/simulation/domain/module), same time budget, same
 * feedback setting, and same active filter (if any) as the original run.
 */
function retakeSameExamShuffled() {
  const info = window.lastExamRetakeInfo;
  if (!info || !info.questions || info.questions.length === 0) { backToMenu(); return; }

  appState.examCode = info.examCode;
  appState.examMode = info.examMode;
  appState.feedbackEnabled = info.feedbackEnabled;
  appState.activeFilter = info.activeFilter;

  const shuffledQuestions = shuffleArray(info.questions);
  runExam(shuffledQuestions, info.timeSeconds);
}

/**
 * "Retake Partial Credit & Incorrect Questions" — results page button.
 * Launches a drill of only the questions that were partial-credit or
 * incorrect on the attempt just finished (unanswered questions are excluded,
 * same as how "missed" is scored elsewhere in the app). Runs through the
 * exact same Check/Next practice flow and lands on its own results screen,
 * but — being a drill — nothing about it is saved: no Progress Dashboard
 * history entry, and the original attempt's score/history is untouched.
 */
function retakeMissedQuestions() {
  const missed = window.lastMissedQuestions;
  if (!missed || missed.length === 0) { backToMenu(); return; }

  appState.examMode = 'practice';
  appState.feedbackEnabled = true;
  appState.activeFilter = { type: 'drill', value: 'missed', label: 'Retake: Partial/Incorrect' };

  const questions = shuffleArray(missed);
  runExam(questions, questions.length * 60, /* drillMode */ true);
}

// Show completion modal
function showCompletionModal() {
  const modal = document.getElementById('completionModal');
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
}

/**
 * Build a results tile label: the category name plus that category's share of the
 * whole exam, e.g. "Partial Credit (28%)".
 *
 * The percentage here is a proportion of the total question count. It is NOT the
 * per-question score tier (100/50/0) returned by computeMultiSelectScore, which is
 * what the old "100% Correct" / "50% Partial" / "0% Incorrect" labels were showing.
 * Those read as proportions of the exam and misled accordingly.
 *
 * @param {string} name - Category name, e.g. "Correct"
 * @param {number} count - Number of questions in this category
 * @param {number} total - Total questions in the exam
 * @returns {string}
 */
function formatResultLabel(name, count, total) {
  const share = total > 0 ? Math.round((count / total) * 100) : 0;
  return name + ' (' + share + '%)';
}

// Display exam results on the results page
function displayExamResults(results) {
  setElementText('resultsExamLabel', results.examLabel || '');
  document.getElementById('scaledScore').textContent = results.scaledScore;
  document.getElementById('passingScore').textContent = results.passingScore;
  
  // Total questions served. Falls back to the category sum, which equals the
  // question count by construction, and guards against divide-by-zero.
  const total = (results.questions && results.questions.length) ||
    (results.perfect + results.partial + results.incorrect + results.unanswered);
  
  setElementText('rPerfect', results.perfect);
  setElementText('rPartial', results.partial);
  setElementText('rIncorrect', results.incorrect);
  setElementText('rUnanswered', results.unanswered);
  
  setElementText('lblPerfect', formatResultLabel('Correct', results.perfect, total));
  setElementText('lblPartial', formatResultLabel('Partial Credit', results.partial, total));
  setElementText('lblIncorrect', formatResultLabel('Incorrect', results.incorrect, total));
  setElementText('lblUnanswered', formatResultLabel('Unanswered', results.unanswered, total));
  
  const passFail = document.getElementById('passFail');
  passFail.textContent = results.passed ? 'PASS' : 'FAIL';
  passFail.className = 'pass-fail ' + (results.passed ? 'pass' : 'fail');
  
  // Build review list
  buildReviewList();
}

// Close completion modal and show results
function closeCompletionModal() {
  const modal = document.getElementById('completionModal');
  modal.classList.add('hidden');
  modal.style.display = 'none';
  
  // Now show results screen with calculated data
  showScreen('screenResults');
  document.getElementById('timerDisplay').classList.add('hidden');
  
  // Use stored results data
  const results = window.examResults;
  displayExamResults(results);
}

// Build review list with pagination
let reviewPaginationState = {
  currentPage: 0,
  itemsPerPage: 10,
  totalItems: 0,
  currentFilter: 'correct'  // Track current filter
};

function buildReviewList() {
  const reviewList = document.getElementById('reviewList');
  reviewList.innerHTML = '';
  
  reviewPaginationState.totalItems = appState.questions.length;
  reviewPaginationState.currentPage = 0;
  reviewPaginationState.currentFilter = 'perfect';
  
  // Update visual state to show 'perfect' as active
  document.getElementById('statCorrect').classList.add('active');
  document.getElementById('statPartial').classList.remove('active');
  document.getElementById('statIncorrect').classList.remove('active');
  document.getElementById('statUnanswered').classList.remove('active');
  
  // Count questions by score category
  let perfectCount = 0, partialCount = 0, incorrectCount = 0, unansweredCount = 0;
  appState.questions.forEach((q, idx) => {
    const answer = appState.answers[idx];
    const isUnanswered = answer === undefined;
    
    if (isUnanswered) {
      unansweredCount++;
    } else {
      const result = checkAnswerCorrect(q, answer);
      if (typeof result === 'number') {
        // Multi-select score
        if (result === 100) {
          perfectCount++;
        } else if (result === 50) {
          partialCount++;
        } else {
          incorrectCount++;
        }
      } else if (result === true) {
        perfectCount++;
      } else {
        incorrectCount++;
      }
    }
  });
  
  // All answered message is now shown in completion modal
  
  const totalPages = Math.ceil(reviewPaginationState.totalItems / reviewPaginationState.itemsPerPage);
  
  if (totalPages > 1) {
    showPaginationControls(totalPages);
  } else {
    document.getElementById('paginationControls').style.display = 'none';
  }
  
  renderReviewPage();
}

// Filter review by type and render
function filterReview(type) {
  reviewPaginationState.currentFilter = type;
  reviewPaginationState.currentPage = 0;
  
  // Update active states
  document.getElementById('statCorrect').classList.toggle('active', type === 'perfect');
  document.getElementById('statPartial').classList.toggle('active', type === 'partial');
  document.getElementById('statIncorrect').classList.toggle('active', type === 'incorrect');
  document.getElementById('statUnanswered').classList.toggle('active', type === 'unanswered');
  
  renderReviewPage();
}

function renderReviewPage() {
  const reviewList = document.getElementById('reviewList');
  reviewList.innerHTML = '';
  
  // Filter questions by type
  const filteredIndices = [];
  appState.questions.forEach((q, idx) => {
    const answer = appState.answers[idx];
    const result = checkAnswerCorrect(q, answer);
    const isUnanswered = answer === undefined;
    
    // Determine score category
    let scoreCategory = 'unanswered';
    if (!isUnanswered) {
      if (typeof result === 'number') {
        // Multi-select score
        if (result === 100) {
          scoreCategory = 'perfect';
        } else if (result === 50) {
          scoreCategory = 'partial';
        } else {
          scoreCategory = 'incorrect';
        }
      } else if (result === true) {
        scoreCategory = 'perfect';
      } else {
        scoreCategory = 'incorrect';
      }
    }
    
    if (reviewPaginationState.currentFilter === scoreCategory) {
      filteredIndices.push(idx);
    }
  });
  
  // Check if filter has no results
  if (filteredIndices.length === 0) {
    // Friendly per-filter empty message (never expose the internal filter key).
    const EMPTY_MESSAGES = {
      all: 'No questions to display',
      perfect: 'No correct answers to display',
      partial: 'No partial credit answers to display',
      incorrect: 'No incorrect answers to display',
      unanswered: 'No unanswered questions to display'
    };
    const msg = EMPTY_MESSAGES[reviewPaginationState.currentFilter] || 'No questions to display';
    const emptyMsg = document.createElement('div');
    emptyMsg.className = 'review-empty-msg';
    emptyMsg.innerHTML = '<div class="review-empty-text">' + msg + '</div>';
    reviewList.appendChild(emptyMsg);
    return;
  }
  
  const start = reviewPaginationState.currentPage * reviewPaginationState.itemsPerPage;
  const end = Math.min(start + reviewPaginationState.itemsPerPage, filteredIndices.length);
  
  for (let i = start; i < end; i++) {
    const idx = filteredIndices[i];
    const q = appState.questions[idx];
    const answer = appState.answers[idx];
    const result = checkAnswerCorrect(q, answer);
    const isUnanswered = answer === undefined;

    // Resolve correct answers as an array of text strings
    const correctAnswers = Array.isArray(q.correctAnswer) ? q.correctAnswer :
      (typeof q.correctAnswer === 'string' ? [q.correctAnswer] : []);

    // Resolve user answers as an array of text strings
    let userAnswers = [];
    if (!isUnanswered) {
      if (Array.isArray(answer)) {
        userAnswers = answer;
      } else if (typeof answer === 'string') {
        userAnswers = [answer];
      }
    }

    // Determine card-level score label and accent color
    let accentColor = 'var(--muted)';
    let scoreLabel = 'Unanswered';
    if (!isUnanswered) {
      if (typeof result === 'number') {
        if (result === 100)      { accentColor = 'var(--green)'; scoreLabel = '100% Correct'; }
        else if (result === 50)  { accentColor = 'var(--amber)'; scoreLabel = '50% Partial';  }
        else                     { accentColor = 'var(--red)';   scoreLabel = '0% Incorrect'; }
      } else if (result === true) {
        accentColor = 'var(--green)'; scoreLabel = '100% Correct';
      } else {
        accentColor = 'var(--red)'; scoreLabel = '0% Incorrect';
      }
    }

    // ── Question card ──────────────────────────────────────────────────────
    const item = document.createElement('div');
    item.className = 'review-item-card';
    item.style.borderLeftColor = accentColor;

    // Header: Q number • domain + score label
    const header = document.createElement('div');
    header.className = 'review-item-header';
    header.innerHTML = '<span>Q' + (idx + 1) + ' &nbsp;·&nbsp; ' + escapeHtml(q.domain) + '</span>' +
      '<span style="font-weight: 600; color: ' + accentColor + ';">' + scoreLabel + '</span>';

    // Question stem
    const stem = document.createElement('div');
    stem.className = 'review-item-stem';
    stem.textContent = q.stem;

    // Multi-select hint
    const isMulti = q.type === 'multi' ||
      (!q.type && Array.isArray(q.correctAnswer) && q.correctAnswer.length > 1);
    if (isMulti) {
      const hint = document.createElement('div');
      hint.className = 'review-item-hint';
      hint.textContent = 'Select all that apply';
      item.appendChild(header);
      item.appendChild(stem);
      item.appendChild(hint);
    } else {
      item.appendChild(header);
      item.appendChild(stem);
    }

    // ── Option rows ────────────────────────────────────────────────────────
    const optionsWrap = document.createElement('div');

    if (q.type === 'table_match') {
      // Render table_match as a comparison table: key col fixed, other cols show user vs correct
      const userMap    = (answer && typeof answer === 'object') ? answer : {};
      const correctMap = (q.correctAnswer && typeof q.correctAnswer === 'object') ? q.correctAnswer : {};
      const colHeaders = (q.headers || []).slice(1);

      const tbl = document.createElement('table');
      tbl.className = 'table-match-review-table';

      // Header row
      const tHead = document.createElement('tr');
      [(q.headers || [])[0] || 'Item'].concat(colHeaders).forEach(h => {
        const th = document.createElement('th');
        th.textContent = h;
        tHead.appendChild(th);
      });
      tbl.appendChild(tHead);

      (q.rows || []).forEach(row => {
        const tr = document.createElement('tr');

        const keyTd = document.createElement('td');
        keyTd.className = 'tmr-key';
        keyTd.textContent = row.key;
        tr.appendChild(keyTd);

        colHeaders.forEach(colH => {
          const correctVal = (correctMap[row.key] || {})[colH] || '';
          const userVal    = (userMap[row.key]    || {})[colH] || '';
          const isRight    = !isUnanswered && userVal === correctVal;
          const isEmpty    = !userVal;

          const td = document.createElement('td');
          if (!isUnanswered && !isEmpty) {
            td.className = isRight ? 'tmr-correct' : 'tmr-wrong';
          }

          if (isUnanswered || isEmpty) {
            td.innerHTML = '<span style="color:var(--muted)">—</span>';
          } else if (isRight) {
            td.textContent = userVal + ' ✓';
          } else {
            td.innerHTML = '<span style="text-decoration:line-through;opacity:0.6">' + escapeHtml(userVal) + '</span>'
              + ' <span style="color:var(--green)">→ ' + escapeHtml(correctVal) + '</span>';
          }
          tr.appendChild(td);
        });
        tbl.appendChild(tr);
      });

      const wrap = document.createElement('div');
      wrap.className = 'table-match-review-wrap';
      wrap.appendChild(tbl);
      optionsWrap.appendChild(wrap);

    } else if (q.type === 'matching') {
      // Render matching rows: left = item label, right = user's pick vs correct
      const userMap    = (answer && typeof answer === 'object') ? answer : {};
      const correctMap = (q.correctAnswer && typeof q.correctAnswer === 'object') ? q.correctAnswer : {};

      q.items.forEach(itemKey => {
        const userPick   = userMap[itemKey] || '';
        const correctVal = correctMap[itemKey] || '';
        const isRight    = userPick === correctVal;

        const row = document.createElement('div');
        row.className = 'matching-row ' + (isUnanswered ? '' : isRight ? 'review-correct' : 'review-incorrect');

        const labelEl = document.createElement('span');
        labelEl.className = 'matching-label';
        labelEl.textContent = itemKey;

        const pickedEl = document.createElement('span');
        pickedEl.className = 'review-match-picked';
        pickedEl.textContent = userPick || '—';

        const badge = document.createElement('span');
        badge.className = 'matching-answer-badge ' + (isUnanswered ? '' : isRight ? 'correct' : 'incorrect');
        if (!isUnanswered && !isRight) {
          badge.textContent = '✓ ' + correctVal;
        } else if (!isUnanswered && isRight) {
          badge.textContent = '✓';
        }

        row.appendChild(labelEl);
        row.appendChild(pickedEl);
        if (badge.textContent) row.appendChild(badge);
        optionsWrap.appendChild(row);
      });
    } else {
      // mc / multi option rows
      // For each option determine its visual state:
      //   • correct   → green  (it IS a correct answer)
      //   • incorrect → red    (user picked it AND it is wrong)
      //   • missed    → amber  (user did NOT pick it but it was correct — partial only)
      //   • neutral   → default border (not picked, not correct)
      (q.options || []).forEach(option => {
        const isCorrectOption = correctAnswers.includes(option);
        const userPicked      = userAnswers.includes(option);

        let optClass = 'review-option';
        let markerSymbol = '';

        if (isCorrectOption && userPicked) {
          optClass += ' review-correct';
          markerSymbol = '✓';
        } else if (!isCorrectOption && userPicked) {
          optClass += ' review-incorrect';
          markerSymbol = '✗';
        } else if (isCorrectOption && !userPicked && isMulti) {
          optClass += ' review-missed';
          markerSymbol = '!';
        } else if (isCorrectOption && !userPicked && !isMulti) {
          optClass += ' review-correct';
          markerSymbol = '✓';
        }

        const row = document.createElement('div');
        row.className = optClass;

        const marker = document.createElement('span');
        marker.className = 'review-option-marker';
        marker.textContent = markerSymbol;

        const text = document.createElement('span');
        text.textContent = option;

        row.appendChild(marker);
        row.appendChild(text);
        optionsWrap.appendChild(row);
      });
    }

    item.appendChild(optionsWrap);
    reviewList.appendChild(item);

    // ── Explanation block (separate container, outside card) ───────────────
    if (q.explanation) {
      const expBlock = document.createElement('div');
      expBlock.className = 'review-explanation';
      expBlock.innerHTML = '<strong>Explanation</strong>' + escapeHtml(q.explanation);
      reviewList.appendChild(expBlock);
    } else {
      // Close-off the rounded bottom even without explanation
      item.style.borderRadius = '8px';
      item.style.marginBottom = '20px';
    }
  }
  
  // Update pagination for filtered results
  const totalFilteredPages = Math.ceil(filteredIndices.length / reviewPaginationState.itemsPerPage);
  if (totalFilteredPages > 1) {
    showPaginationControls(totalFilteredPages);
  } else {
    document.getElementById('paginationControls').style.display = 'none';
  }
}

function formatUserAnswer(question, answer) {
  if (answer === undefined) {
    return '<em style="color: var(--red);">Not answered</em>';
  }
  
  if (question.type === 'mc') {
    // answer is now stored as TEXT (string), not index
    return answer || '<em>No answer selected</em>';
  } else if (question.type === 'multi') {
    // answer is now stored as array of TEXT strings
    if (Array.isArray(answer)) {
      return answer.join(', ') || '<em>No answer selected</em>';
    }
    return '<em>No answer selected</em>';
  } else if (question.type === 'matching') {
    if (answer && typeof answer === 'object') {
      return Object.entries(answer)
        .map(([k, v]) => '<div>' + escapeHtml(k) + ': <strong>' + escapeHtml(v) + '</strong></div>')
        .join('') || '<em>No answer selected</em>';
    }
    return '<em>No answer selected</em>';
  } else if (question.type === 'table_match') {
    if (!answer || typeof answer !== 'object') return '<em>Not answered</em>';
    const colHeaders = (question.headers || []).slice(1);
    return (question.rows || []).map(row => {
      const cells = colHeaders.map(h => {
        const val = (answer[row.key] || {})[h] || '—';
        return '<em>' + escapeHtml(h) + ':</em> ' + escapeHtml(val);
      }).join(' &middot; ');
      return '<div><strong>' + escapeHtml(row.key) + '</strong> &rarr; ' + cells + '</div>';
    }).join('');
  }
  return 'N/A';
}

function formatCorrectAnswer(question) {
  if (question.type === 'mc') {
    // Check if correctAnswer is array (new format) or index (old format)
    if (Array.isArray(question.correctAnswer)) {
      return question.correctAnswer[0]; // text-based
    } else if (typeof question.correctAnswer === 'number') {
      return question.options[question.correctAnswer]; // index-based (legacy)
    } else if (typeof question.correctAnswer === 'string') {
      return question.correctAnswer; // direct string
    }
  } else if (question.type === 'multi') {
    // Check if correctAnswers or correctAnswer
    const correctAnswers = question.correctAnswers || question.correctAnswer;
    if (Array.isArray(correctAnswers) && correctAnswers.length > 0) {
      if (typeof correctAnswers[0] === 'number') {
        return correctAnswers.map(idx => question.options[idx]).join(', ');
      } else {
        return correctAnswers.join(', ');
      }
    }
  } else if (question.type === 'matching') {
    if (question.correctAnswer && typeof question.correctAnswer === 'object') {
      return Object.entries(question.correctAnswer)
        .map(([k, v]) => '<div>' + escapeHtml(k) + ': <strong>' + escapeHtml(v) + '</strong></div>')
        .join('');
    }
  } else if (question.type === 'table_match') {
    if (!question.correctAnswer || typeof question.correctAnswer !== 'object') return 'N/A';
    const colHeaders = (question.headers || []).slice(1);
    return (question.rows || []).map(row => {
      const correct = question.correctAnswer[row.key] || {};
      const cells = colHeaders.map(h => '<em>' + escapeHtml(h) + ':</em> <strong>' + escapeHtml(correct[h] || '—') + '</strong>').join(' &middot; ');
      return '<div><strong>' + escapeHtml(row.key) + '</strong> &rarr; ' + cells + '</div>';
    }).join('');
  }
  return 'N/A';
}

function showPaginationControls(totalPages) {
  const controls = document.getElementById('paginationControls');
  controls.style.display = 'flex';
  controls.innerHTML = '';
  
  // Previous button
  const prevBtn = document.createElement('button');
  prevBtn.className = 'pagination-btn';
  prevBtn.textContent = '← Previous';
  prevBtn.disabled = reviewPaginationState.currentPage === 0;
  prevBtn.onclick = () => {
    if (reviewPaginationState.currentPage > 0) {
      reviewPaginationState.currentPage--;
      renderReviewPage();
      updatePaginationButtons(totalPages);
      document.getElementById('reviewList').scrollIntoView({ behavior: 'smooth' });
    }
  };
  controls.appendChild(prevBtn);
  
  // Page buttons
  for (let i = 0; i < totalPages; i++) {
    const btn = document.createElement('button');
    btn.className = 'pagination-btn' + (i === reviewPaginationState.currentPage ? ' active' : '');
    btn.textContent = i + 1;
    btn.onclick = () => {
      reviewPaginationState.currentPage = i;
      renderReviewPage();
      updatePaginationButtons(totalPages);
      document.getElementById('reviewList').scrollIntoView({ behavior: 'smooth' });
    };
    controls.appendChild(btn);
  }
  
  // Next button
  const nextBtn = document.createElement('button');
  nextBtn.className = 'pagination-btn';
  nextBtn.textContent = 'Next →';
  nextBtn.disabled = reviewPaginationState.currentPage === totalPages - 1;
  nextBtn.onclick = () => {
    if (reviewPaginationState.currentPage < totalPages - 1) {
      reviewPaginationState.currentPage++;
      renderReviewPage();
      updatePaginationButtons(totalPages);
      document.getElementById('reviewList').scrollIntoView({ behavior: 'smooth' });
    }
  };
  controls.appendChild(nextBtn);
}

function updatePaginationButtons(totalPages) {
  const controls = document.getElementById('paginationControls');
  const buttons = controls.querySelectorAll('.pagination-btn');
  
  buttons[0].disabled = reviewPaginationState.currentPage === 0;
  buttons[buttons.length - 1].disabled = reviewPaginationState.currentPage === totalPages - 1;
  
  for (let i = 1; i < buttons.length - 1; i++) {
    buttons[i].classList.toggle('active', i - 1 === reviewPaginationState.currentPage);
  }
}

// Navigation
function saveAndExit() {
  if (confirm('Save progress and exit exam?')) {
    // Persist the in-progress exam, then leave it in place so the next page
    // load resumes it via checkAndRestoreExamState().
    saveExamState();
    backToMenu(false);
  }
}

function exitWithoutSave() {
  if (confirm('Exit without saving? Your progress will be lost.')) {
    backToMenu(true);
  }
}

/**
 * Return to the intro screen.
 * @param {boolean} [clearState=true] - When true, discard any saved in-progress
 *   exam. Pass false to keep it so the attempt can be resumed later.
 */
function backToMenu(clearState = true) {
  clearInterval(appState.timerInterval);
  showScreen('screenIntro');
  document.getElementById('timerDisplay').classList.add('hidden');
  document.getElementById('topbarExamName').textContent = 'Select an exam';
  
  if (clearState) {
    localStorage.removeItem('aplus_exam_state');
  }
  localStorage.removeItem('aplus_exam_results');
}

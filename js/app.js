// Global State
let appState = {
  examCode: null,
  questions: [],
  currentQuestionIndex: 0,
  answers: {},
  flagged: new Set(),
  autoFlagged: new Set(), // Track which questions were auto-flagged while unanswered
  
  displayedQuestionIds: new Set(), // Track question IDs already displayed to prevent duplicates
  validatedDragDrops: new Set(), // Track which drag-drop questions have been validated
  timerInterval: null,
  timeRemaining: 0,
  examStartTime: null,
  // P5 mode state
  examMode: 'practice',        // 'practice' | 'simulation' | 'domain' | 'module'
  feedbackEnabled: true,       // false in simulation mode (no mid-exam correctness colors)
  activeFilter: null           // { type: 'domain'|'module', value: string, label: string } or null
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
    const response = await fetch('exam_assets/questions.json');
    const data = await response.json();
    window.questionBank = data;
    
    // Load acronyms quiz
    const acronymsResponse = await fetch('exam_assets/acronyms_quiz.json');
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
      appState.currentQuestionIndex = state.currentQuestionIndex || 0;
      appState.answers = state.answers || {};
      appState.flagged = new Set(state.flagged || []);
      appState.autoFlagged = new Set(state.autoFlagged || []);
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
    currentQuestionIndex: appState.currentQuestionIndex,
    questions: appState.questions, // SAVE the actual questions
    answers: appState.answers,
    flagged: Array.from(appState.flagged),
    autoFlagged: Array.from(appState.autoFlagged),
    validatedDragDrops: Array.from(appState.validatedDragDrops),
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
  'acronyms': 'Begin Acronyms Quiz'
};

/** Maps each intro card's element-id prefix to its exam code. */
const INTRO_CARDS = [
  { prefix: 'c1', code: '220-1201' },
  { prefix: 'c2', code: '220-1202' },
  { prefix: 'acr', code: 'acronyms' }
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
  ['screenIntro', 'screenModePicker', 'screenExam', 'screenResults'].forEach(s => {
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
  openModePicker();
}

/** Open the mode-picker screen for the currently selected exam. */
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
  const practiceN = Math.min(25, bank.length);
  setElementText('metaPractice', practiceN + ' questions \u00b7 ' + practiceN + ' min \u00b7 feedback on');
  setElementText('metaSimulation',
    examQuestionCount(exam) + ' questions \u00b7 ' + examTimeLimit(exam) + ' min \u00b7 no feedback');

  // Domain / Module modes require metadata. The acronyms synthetic exam has none,
  // so disable those two cards for it rather than hiding them.
  const hasDomains = !!(exam.domainWeights && Object.keys(exam.domainWeights).length);
  const hasModules = !!(exam.modules && Object.keys(exam.modules).length);
  setModeCardEnabled('modeDomain', hasDomains,
    hasDomains ? Object.keys(exam.domainWeights).length + ' domains' : 'Not available for this exam');
  setModeCardEnabled('modeModule', hasModules,
    hasModules ? Object.keys(exam.modules).length + ' modules' : 'Not available for this exam');

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
    btn.innerHTML = '<span>' + escapeHtml(domain) + '</span>' +
      '<span class="filter-count">(' + n + ' question' + (n === 1 ? '' : 's') + ')</span>';
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
    btn.innerHTML = '<span>' + escapeHtml(label) + '</span>' +
      '<span class="filter-count">(' + n + ' question' + (n === 1 ? '' : 's') + ')</span>';
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
function selectUniqueQuestions(questionBank, count) {
  const selected = [];
  const seenIds = new Set();
  const shuffled = shuffleArray([...questionBank]);
  
  for (const q of shuffled) {
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
  
  return selected;
}
// ---------------------------------------------------------------------------
// Mode entry points (Step 2). Each configures examMode / feedbackEnabled /
// activeFilter, picks a question set, then hands off to runExam().
// ---------------------------------------------------------------------------

// Practice Exam: up to 25 random from the full bank, 1 min/question, feedback on.
function startPracticeExam() {
  const exam = window.questionBank.exams[appState.examCode];
  if (!exam) { alert('Exam not found'); return; }
  const count = Math.min(25, (exam.questionBank || []).length);
  const questions = selectUniqueQuestions(exam.questionBank, count);
  appState.examMode = 'practice';
  appState.feedbackEnabled = true;
  appState.activeFilter = null;
  runExam(questions, count * 60);
}

// Simulation Exam: exam's configured count + timeLimit, feedback OFF.
function startSimulationExam() {
  const exam = window.questionBank.exams[appState.examCode];
  if (!exam) { alert('Exam not found'); return; }
  const count = examQuestionCount(exam);
  const questions = selectUniqueQuestions(exam.questionBank, count);
  appState.examMode = 'simulation';
  appState.feedbackEnabled = false;
  appState.activeFilter = null;
  runExam(questions, examTimeLimit(exam) * 60);
}

// Practice by Domain / Module: up to 25 random from the filtered set, feedback on.
function startFilteredExam(type, value, label) {
  const exam = window.questionBank.exams[appState.examCode];
  if (!exam) { alert('Exam not found'); return; }
  const field = type === 'domain' ? 'domain' : 'module';
  const filtered = (exam.questionBank || []).filter(q => q[field] === value);
  const count = Math.min(25, filtered.length);
  if (count === 0) return; // guarded by disabled buttons, but be safe
  const questions = selectUniqueQuestions(filtered, count);
  appState.examMode = type;               // 'domain' | 'module'
  appState.feedbackEnabled = true;
  appState.activeFilter = { type, value, label };
  // 1 minute per (filtered) question
  runExam(questions, count * 60);
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
function runExam(selectedQuestions, timeSeconds) {
  const exam = window.questionBank.exams[appState.examCode];

  appState.questions = selectedQuestions.map(q => randomizeQuestionOptions(q));
  appState.currentQuestionIndex = 0;
  appState.answers = {};
  appState.flagged.clear();
  appState.autoFlagged.clear();
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
    const isAnswered = appState.answers[idx] !== undefined;
    const isFlagged = appState.flagged.has(idx);
    const userAnswer = appState.answers[idx];
    
    // FLAGGED takes precedence over answered/unanswered
    if (isFlagged) {
      // Flagged questions are always yellow, regardless of answer state
      cell.classList.add('flagged');
    } else if (isAnswered) {
      // Question is answered but not flagged
      if (!appState.feedbackEnabled) {
        // Simulation mode: reveal that a question is answered, but NOT whether it
        // is correct. Neutral blue fill, still locked. Correctness waits for results.
        cell.classList.add('answered-neutral');
        cell.classList.add('locked');
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

// Load question
function loadQuestion(index) {
  if (index < 0 || index >= appState.questions.length) return;
  
  appState.currentQuestionIndex = index;
  const question = appState.questions[index];
  
  // Track this question ID to prevent duplicates
  appState.displayedQuestionIds.add(question.id);
  
  // Check if question is locked
  const isAnswered = appState.answers[index] !== undefined;
  const isFlagged = appState.flagged.has(index);
  const isLocked = isAnswered && !isFlagged;
  
  // Update header
  document.getElementById('qNumber').textContent = 'Q' + (index + 1) + ' of ' + appState.questions.length;
  document.getElementById('qDomainTag').textContent = question.domain;
  
  // Update question text
  const qStem = document.getElementById('qStem');
  
  // Remove any existing lock indicators from previous questions
  const existingLockIndicator = qStem.parentElement.querySelector('[data-lock-indicator]');
  if (existingLockIndicator) {
    existingLockIndicator.remove();
  }
  
  qStem.textContent = question.stem;
  
  // Add lock indicator if question is locked
  if (isLocked) {
    const lockIndicator = document.createElement('div');
    lockIndicator.setAttribute('data-lock-indicator', 'true');
    lockIndicator.style.cssText = 'background: #fbe6e9; border-left: 4px solid var(--red); padding: 10px 14px; margin-bottom: 14px; border-radius: 4px; font-size: 13px; color: var(--red); font-weight: 600;';
    lockIndicator.textContent = '🔒 This question is locked. Only flagged questions can be revisited.';
    qStem.parentElement.insertBefore(lockIndicator, qStem);
  }
  
  // Show hint for multi-select — mirrors the isMulti derivation in renderMultipleChoice
  const isMultiQuestion = question.type === 'multi' ||
    (!question.type && Array.isArray(question.correctAnswer) && question.correctAnswer.length > 1);
  document.getElementById('qHint').classList.toggle('hidden', !isMultiQuestion);
  
  // Render options based on type
  const optionsContainer = document.getElementById('qOptions');
  optionsContainer.innerHTML = '';
  
  if (question.type === 'mc' || question.type === 'multi' || isMultiQuestion) {
    renderMultipleChoice(question, optionsContainer, index);
  } else if (question.type === 'matching') {
    renderMatching(question, optionsContainer, index);
  }
  
  // Update buttons
  document.getElementById('btnPrev').disabled = index === 0;
  const isLastQuestion = index === appState.questions.length - 1;
  const btnNext = document.getElementById('btnNext');
  
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
  
  // Update flag button
  document.getElementById('btnFlag').classList.toggle('active', isFlagged);
  
  // Update navigator
  updateNavigator();
  
  // Save current exam state to localStorage
  saveExamState();
}

// Render multiple choice
function renderMultipleChoice(question, container, questionIndex) {
  // Derive isMulti from the type field, with a fallback to check correctAnswer length.
  // This guards against stale localStorage data where the type field may be missing.
  const isMulti = question.type === 'multi' ||
    (!question.type && Array.isArray(question.correctAnswer) && question.correctAnswer.length > 1);
  
  const currentAnswers = appState.answers[questionIndex] || (isMulti ? [] : null);
  
  // Check if this question is locked (answered but not flagged)
  const isAnswered = appState.answers[questionIndex] !== undefined;
  const isFlagged = appState.flagged.has(questionIndex);
  const isLocked = isAnswered && !isFlagged;
  
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
          saveExamState();
          // Don't call updateNavigator() - validation happens on Next button click
        }
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
          saveExamState();
          // Don't call updateNavigator() - validation happens on Next button click
        }
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

function renderMatching(question, container, questionIndex) {
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
  const isAnswered = appState.answers[questionIndex] !== undefined;
  const isFlagged  = appState.flagged.has(questionIndex);
  const isLocked   = isAnswered && !isFlagged;

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
      updateNavigator();
    };

    rowEl.appendChild(labelEl);
    rowEl.appendChild(select);
    container.appendChild(rowEl);
  });
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
  // Check if question is answered but not flagged - if so, prevent navigation
  const isAnswered = appState.answers[index] !== undefined;
  const isFlagged = appState.flagged.has(index);
  
  if (isAnswered && !isFlagged) {
    // Question is answered and not flagged - locked, cannot navigate
    // Silently prevent navigation, the disabled cursor feedback is enough
    return;
  }
  
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
  document.getElementById('timerDisplay').textContent = display;
  
  if (appState.timeRemaining <= 300) { // 5 min warning
    document.getElementById('timerDisplay').classList.add('warn');
  }
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
    scaledScore: scaledScore,
    passingScore: exam.passingScore,
    passed: passed,
    examCode: appState.examCode,
    questions: appState.questions,
    answers: appState.answers
  };
  
  window.examResults = examResults;
  
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
  
  // Show completion modal first
  showCompletionModal();
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
    emptyMsg.style.cssText = 'text-align: center; padding: 40px 20px; color: var(--muted);';
    emptyMsg.innerHTML = '<div style="font-size: 14px;">' + msg + '</div>';
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
    item.style.cssText = 'background: var(--card); border: 1px solid var(--border); border-left: 5px solid ' + accentColor + '; border-radius: 8px 8px 0 0; padding: 16px 18px 14px; margin-bottom: 0;';

    // Header: Q number • domain + score label
    const header = document.createElement('div');
    header.style.cssText = 'font-size: 12px; color: var(--muted); margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;';
    header.innerHTML = '<span>Q' + (idx + 1) + ' &nbsp;·&nbsp; ' + escapeHtml(q.domain) + '</span>' +
      '<span style="font-weight: 600; color: ' + accentColor + ';">' + scoreLabel + '</span>';

    // Question stem
    const stem = document.createElement('div');
    stem.style.cssText = 'font-weight: 600; font-size: 14.5px; line-height: 1.5; margin-bottom: 14px;';
    stem.textContent = q.stem;

    // Multi-select hint
    const isMulti = q.type === 'multi' ||
      (!q.type && Array.isArray(q.correctAnswer) && q.correctAnswer.length > 1);
    if (isMulti) {
      const hint = document.createElement('div');
      hint.style.cssText = 'font-size: 12px; font-style: italic; color: var(--muted); margin-bottom: 10px;';
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

    if (q.type === 'matching') {
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
        pickedEl.style.cssText = 'flex: 1; font-size: 13.5px;';
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

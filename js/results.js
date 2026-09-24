// results.js — Exam history persistence for the Progress Dashboard.
// Depends on: scoring.js (checkAnswerCorrect) being loaded first.
// Globals used from app.js: appState, window.examResults
//
// localStorage key: 'aplus_progress_history'  (array of result objects)

const RESULTS_KEY = 'aplus_progress_history';
const MAX_HISTORY  = 200;   // cap to keep localStorage lean

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Build and persist one result record from the just-completed exam.
 * Call this inside submitExam() immediately before showCompletionModal().
 *
 * @param {object} examResults  - the examResults object built in submitExam()
 * @param {object} appStateSnap - reference to the live appState
 * @param {object} examConfig   - window.questionBank.exams[appState.examCode]
 */
function saveResult(examResults, appStateSnap, examConfig) {
  try {
    const now        = Date.now();
    const elapsed    = appStateSnap.examStartTime
      ? Math.round((now - appStateSnap.examStartTime) / 1000)
      : 0;
    const total      = examResults.perfect + examResults.partial +
                       examResults.incorrect + examResults.unanswered;
    const scorePct   = total > 0
      ? Math.round((examResults.perfect / total) * 100)
      : 0;

    // Build per-domain breakdown by iterating every question
    const breakdown = {};
    (appStateSnap.questions || []).forEach((q, idx) => {
      const domain = q.domain || 'Unknown';
      if (!breakdown[domain]) {
        breakdown[domain] = { correct: 0, incorrect: 0, incomplete: 0, total: 0 };
      }
      breakdown[domain].total++;

      const ans = appStateSnap.answers[idx];
      if (ans === undefined) {
        breakdown[domain].incomplete++;
        return;
      }
      const result = checkAnswerCorrect(q, ans);
      const isCorrect = (typeof result === 'number') ? result === 100 : result === true;
      if (isCorrect) {
        breakdown[domain].correct++;
      } else {
        breakdown[domain].incorrect++;
      }
    });

    // Derive a human-readable exam label
    const examLabel = _buildExamLabel(appStateSnap, examConfig);

    const record = {
      id:              String(now) + '_' + Math.random().toString(36).slice(2, 7),
      date:            new Date(now).toISOString(),
      examCode:        appStateSnap.examCode,
      examType:        appStateSnap.examMode,   // practice|simulation|domain|module|acronyms
      examLabel:       examLabel,
      totalQuestions:  total,
      correct:         examResults.perfect,
      partial:         examResults.partial,
      incorrect:       examResults.incorrect,
      incomplete:      examResults.unanswered,
      score:           scorePct,
      scaledScore:     examResults.scaledScore,
      passingScore:    examResults.passingScore,
      passed:          examResults.passed,
      durationSeconds: elapsed,
      breakdown:       breakdown
    };

    const history = loadResults();
    history.unshift(record);          // newest first
    if (history.length > MAX_HISTORY) history.length = MAX_HISTORY;
    localStorage.setItem(RESULTS_KEY, JSON.stringify(history));
  } catch (e) {
    console.warn('saveResult failed:', e);
  }
}

/** Return the full history array, newest-first. Never throws. */
function loadResults() {
  try {
    const raw = localStorage.getItem(RESULTS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    return [];
  }
}

/** Wipe all history (after confirmation). */
function clearResults() {
  localStorage.removeItem(RESULTS_KEY);
}

/**
 * Aggregate per-domain stats across all history records.
 * Returns an array sorted by avgScore ascending (weakest first).
 *
 * Each element:
 * {
 *   domain:      string,
 *   total:       number,   // total questions answered across all sessions
 *   correct:     number,
 *   avgScore:    number,   // percentage 0–100
 *   trend:       '↑'|'↓'|'→',
 *   focusFlag:   '🔴'|'🟡'|'🟢'
 * }
 */
function getWeaknessSummary(history) {
  if (!history || history.length === 0) return [];

  // Accumulate across all sessions
  const domainMap = {};

  history.forEach(record => {
    if (!record.breakdown) return;
    Object.entries(record.breakdown).forEach(([domain, stats]) => {
      if (!domainMap[domain]) {
        domainMap[domain] = { domain, total: 0, correct: 0, sessions: [] };
      }
      domainMap[domain].total   += stats.total;
      domainMap[domain].correct += stats.correct;
      // Track per-session score for trend calculation
      const sessionScore = stats.total > 0
        ? Math.round((stats.correct / stats.total) * 100)
        : 0;
      domainMap[domain].sessions.push(sessionScore);
    });
  });

  return Object.values(domainMap)
    .map(d => {
      const avgScore = d.total > 0 ? Math.round((d.correct / d.total) * 100) : 0;
      const trend    = _calcTrend(d.sessions);
      const focusFlag = avgScore >= 80 ? '🟢' : avgScore >= 65 ? '🟡' : '🔴';
      return {
        domain:    d.domain,
        total:     d.total,
        correct:   d.correct,
        avgScore,
        trend,
        focusFlag
      };
    })
    .sort((a, b) => a.avgScore - b.avgScore);  // weakest first
}

// ── Private helpers ───────────────────────────────────────────────────────────

function _buildExamLabel(appStateSnap, examConfig) {
  const mode = appStateSnap.examMode;
  const code = appStateSnap.examCode;

  if (code === 'acronyms') return 'Acronyms Quiz';

  const examName = examConfig ? examConfig.name : code;

  switch (mode) {
    case 'simulation': return examName + ' — Full Simulation';
    case 'practice':   return examName + ' — Practice';
    case 'domain': {
      const label = appStateSnap.activeFilter && appStateSnap.activeFilter.label
        ? appStateSnap.activeFilter.label
        : 'Domain';
      return examName + ' — ' + label;
    }
    case 'module': {
      const label = appStateSnap.activeFilter && appStateSnap.activeFilter.label
        ? appStateSnap.activeFilter.label
        : 'Module';
      return examName + ' — ' + label;
    }
    default: return examName;
  }
}

/**
 * Compare the average of the last 3 sessions vs the 3 before that.
 * sessions[] is ordered oldest-first (appended as each session completes).
 */
function _calcTrend(sessions) {
  if (!sessions || sessions.length < 2) return '→';

  const recent = sessions.slice(-3);
  const prior  = sessions.slice(-6, -3);

  const avg = arr => arr.reduce((s, v) => s + v, 0) / arr.length;

  if (prior.length === 0) return '→';

  const diff = avg(recent) - avg(prior);
  if (diff >= 5)  return '↑';
  if (diff <= -5) return '↓';
  return '→';
}

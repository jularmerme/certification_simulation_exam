// Scoring functions for the CompTIA A+ Practice Exam Simulator.
// Shared between the app (via <script src>) and tests (via require()).

// Compute multi-select partial credit score (100/50/0)
// Returns: 100 if perfect match, 50 if partial/mixed, 0 if no matches
function computeMultiSelectScore(userAnswers, correctAnswers) {
  if (!Array.isArray(userAnswers) || userAnswers.length === 0) {
    return 0; // No answers selected
  }
  
  if (!Array.isArray(correctAnswers) || correctAnswers.length === 0) {
    return 0; // No correct answers defined
  }
  
  // Count matches (user selections that are in correctAnswers)
  const matches = userAnswers.filter(answer => correctAnswers.includes(answer)).length;
  
  // Count wrong selections (user selections that are NOT in correctAnswers)
  const wrong = userAnswers.filter(answer => !correctAnswers.includes(answer)).length;
  
  // Perfect match: all user selections are correct AND all correct answers were selected
  if (matches === correctAnswers.length && wrong === 0) {
    return 100;
  }
  
  // No matches: either no correct answers selected OR only wrong answers selected
  if (matches === 0) {
    return 0;
  }
  
  // Partial match: some correct answers selected, or some wrong answers mixed in
  // This covers: some right + missing some right, or some right + some wrong
  return 50;
}

// Check answer correctness (returns boolean for MC, number 0/50/100 for multi-select)
function checkAnswerCorrect(question, userAnswer) {
  if (userAnswer === null || userAnswer === undefined) {
    return false;
  }
  
  // table_match — MUST be first: type='table_match' is not 'matching', so without
  // this guard it falls into the mc/single branch and always returns false.
  if (question.type === 'table_match') {
    if (!userAnswer || typeof userAnswer !== 'object') return 0;
    const correct = question.correctAnswer;
    if (!correct || typeof correct !== 'object') return 0;
    let totalCells = 0, correctCells = 0;
    Object.keys(correct).forEach(rowKey => {
      const rowCorrect = correct[rowKey];
      if (rowCorrect && typeof rowCorrect === 'object') {
        Object.keys(rowCorrect).forEach(colHeader => {
          totalCells++;
          if (userAnswer[rowKey] && userAnswer[rowKey][colHeader] === rowCorrect[colHeader]) {
            correctCells++;
          }
        });
      }
    });
    if (totalCells === 0) return 0;
    const pct = Math.round((correctCells / totalCells) * 100);
    return pct === 100 ? 100 : pct > 0 ? 50 : 0;
  }

  // Derive question type defensively (same logic as renderMultipleChoice / loadQuestion)
  const isMultiType = question.type === 'multi' ||
    (!question.type && Array.isArray(question.correctAnswer) && question.correctAnswer.length > 1);

  if (!isMultiType && question.type !== 'matching') {
    // Single-choice (mc or unknown single-answer type)
    const correctOptions = question.correctAnswer; // Array of text
    return Array.isArray(correctOptions) ? correctOptions.includes(userAnswer) : correctOptions === userAnswer;
  } else if (isMultiType) {
    // Multi-select: userAnswer is array of option texts (strings)
    // Now returns score (0, 50, or 100) instead of boolean
    if (!Array.isArray(userAnswer)) {
      return 0;
    }
    return computeMultiSelectScore(userAnswer, question.correctAnswer);
// table_match: score cells correct / total cells → 100 / 50 / 0
  } else if (question.type === 'table_match') {
    if (!userAnswer || typeof userAnswer !== 'object') return 0;
    const correct = question.correctAnswer;
    if (!correct || typeof correct !== 'object') return 0;
    let totalCells = 0, correctCells = 0;
    Object.keys(correct).forEach(rowKey => {
      const rowCorrect = correct[rowKey];
      if (rowCorrect && typeof rowCorrect === 'object') {
        Object.keys(rowCorrect).forEach(colHeader => {
          totalCells++;
          if (userAnswer[rowKey] && userAnswer[rowKey][colHeader] === rowCorrect[colHeader]) {
            correctCells++;
          }
        });
      }
    });
    if (totalCells === 0) return 0;
    const pct = Math.round((correctCells / totalCells) * 100);
    if (pct === 100) return 100;
    if (pct > 0) return 50;
    return 0;
  } else if (question.type === 'matching') {
    // userAnswer is a flat object { rowKey: chosenValue }
    // correctAnswer is a flat object { rowKey: correctValue }
    if (!userAnswer || typeof userAnswer !== 'object') return false;
    const correct = question.correctAnswer;
    return Object.keys(correct).every(key => userAnswer[key] === correct[key]);
  }
  
  return false;
}

// Node.js interop: lets tests require() these directly. Browsers have no
// `module` global, so this block is skipped there and both functions simply
// remain available as globals for js/app.js.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { computeMultiSelectScore, checkAnswerCorrect };
}

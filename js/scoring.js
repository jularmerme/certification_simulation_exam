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
  
  // Derive question type defensively (same logic as renderMultipleChoice / loadQuestion)
  const isMultiType = question.type === 'multi' ||
    (!question.type && Array.isArray(question.correctAnswer) && question.correctAnswer.length > 1);

  if (!isMultiType && question.type !== 'drag_drop') {
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
  } else if (question.type === 'drag_drop') {
    for (let zone of question.dropZones) {
      const placed = userAnswer[zone.id] || [];
      const correct = zone.correctItems;
      // Compare order-independently, but sort COPIES. This function is called
      // repeatedly from updateNavigator and the review renderers, so sorting in
      // place would reorder the stored answer and the question's own
      // correctItems array as a side effect.
      const placedSorted = [...placed].sort();
      const correctSorted = [...correct].sort();
      if (JSON.stringify(placedSorted) !== JSON.stringify(correctSorted)) {
        return false;
      }
    }
    return true;
  }
  
  return false;
}

// Node.js interop: lets tests require() these directly. Browsers have no
// `module` global, so this block is skipped there and both functions simply
// remain available as globals for js/app.js.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { computeMultiSelectScore, checkAnswerCorrect };
}

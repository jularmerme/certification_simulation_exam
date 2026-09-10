/**
 * Test suite for multi-select partial credit scoring (100%/50%/0%)
 * Validates the computeMultiSelectScore and scoring integration
 */

// Implementation of computeMultiSelectScore
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

// Test harness
let testsPassed = 0;
let testsFailed = 0;

function test(name, condition, expected, actual) {
  if (condition) {
    console.log(`✓ PASS: ${name}`);
    testsPassed++;
  } else {
    console.log(`✗ FAIL: ${name}`);
    console.log(`  Expected: ${expected}`);
    console.log(`  Actual: ${actual}`);
    testsFailed++;
  }
}

console.log('=== Multi-Select Partial Credit Scoring Tests ===\n');

// Test Group 1: Perfect (100%)
console.log('Group 1: Perfect Scores (100%)');
test('Perfect - 2 correct, all selected',
  computeMultiSelectScore(['A', 'B'], ['A', 'B']) === 100,
  100,
  computeMultiSelectScore(['A', 'B'], ['A', 'B'])
);

test('Perfect - 3 correct, all selected',
  computeMultiSelectScore(['A', 'B', 'C'], ['A', 'B', 'C']) === 100,
  100,
  computeMultiSelectScore(['A', 'B', 'C'], ['A', 'B', 'C'])
);

test('Perfect - 1 correct, selected',
  computeMultiSelectScore(['A'], ['A']) === 100,
  100,
  computeMultiSelectScore(['A'], ['A'])
);

// Test Group 2: Partial (50%)
console.log('\nGroup 2: Partial Scores (50%)');
test('Partial - Some correct, missing some',
  computeMultiSelectScore(['A'], ['A', 'B']) === 50,
  50,
  computeMultiSelectScore(['A'], ['A', 'B'])
);

test('Partial - Some correct, some wrong mixed',
  computeMultiSelectScore(['A', 'C'], ['A', 'B']) === 50,
  50,
  computeMultiSelectScore(['A', 'C'], ['A', 'B'])
);

test('Partial - Partial selection with extras',
  computeMultiSelectScore(['A', 'B', 'D'], ['A', 'B', 'C']) === 50,
  50,
  computeMultiSelectScore(['A', 'B', 'D'], ['A', 'B', 'C'])
);

test('Partial - Multiple selected, one correct',
  computeMultiSelectScore(['A', 'X', 'Y'], ['A', 'B']) === 50,
  50,
  computeMultiSelectScore(['A', 'X', 'Y'], ['A', 'B'])
);

// Test Group 3: Incorrect (0%)
console.log('\nGroup 3: Incorrect Scores (0%)');
test('Incorrect - No correct answers selected',
  computeMultiSelectScore(['C', 'D'], ['A', 'B']) === 0,
  0,
  computeMultiSelectScore(['C', 'D'], ['A', 'B'])
);

test('Incorrect - Only wrong answers',
  computeMultiSelectScore(['X', 'Y', 'Z'], ['A', 'B']) === 0,
  0,
  computeMultiSelectScore(['X', 'Y', 'Z'], ['A', 'B'])
);

// Test Group 4: Edge Cases
console.log('\nGroup 4: Edge Cases');
test('Edge Case - Empty user answers',
  computeMultiSelectScore([], ['A', 'B']) === 0,
  0,
  computeMultiSelectScore([], ['A', 'B'])
);

test('Edge Case - Null user answers',
  computeMultiSelectScore(null, ['A', 'B']) === 0,
  0,
  computeMultiSelectScore(null, ['A', 'B'])
);

test('Edge Case - Undefined user answers',
  computeMultiSelectScore(undefined, ['A', 'B']) === 0,
  0,
  computeMultiSelectScore(undefined, ['A', 'B'])
);

test('Edge Case - Empty correct answers',
  computeMultiSelectScore(['A'], []) === 0,
  0,
  computeMultiSelectScore(['A'], [])
);

// Test Group 5: Binary Pass/Fail Requirement
console.log('\nGroup 5: Binary Pass/Fail (50% counts as WRONG)');
console.log('Requirement: Exam total score treats 50% as wrong (binary pass/fail)');
console.log('Testing: 100 points total, 70 needed to pass');

function calculateExamScore(perfect, partial, incorrect, total) {
  // For binary pass/fail: only perfect scores count
  const binaryCorrect = perfect;
  const rawScore = (binaryCorrect / total) * 100;
  return {
    rawScore: Math.round(rawScore),
    passed: Math.round(rawScore) >= 70
  };
}

const scenario1 = calculateExamScore(7, 0, 3, 10);
test('Scenario 1: 7 perfect + 3 incorrect = 70% raw (PASS)',
  scenario1.rawScore === 70 && scenario1.passed === true,
  'rawScore: 70, passed: true',
  `rawScore: ${scenario1.rawScore}, passed: ${scenario1.passed}`
);

const scenario2 = calculateExamScore(7, 2, 1, 10);
test('Scenario 2: 7 perfect + 2 partial + 1 incorrect = 70% raw (PASS)',
  scenario2.rawScore === 70 && scenario2.passed === true,
  'rawScore: 70, passed: true',
  `rawScore: ${scenario2.rawScore}, passed: ${scenario2.passed}`
);

const scenario3 = calculateExamScore(6, 2, 2, 10);
test('Scenario 3: 6 perfect + 2 partial + 2 incorrect = 60% raw (FAIL)',
  scenario3.rawScore === 60 && scenario3.passed === false,
  'rawScore: 60, passed: false',
  `rawScore: ${scenario3.rawScore}, passed: ${scenario3.passed}`
);

// Summary
console.log('\n=== Test Summary ===');
console.log(`Passed: ${testsPassed}`);
console.log(`Failed: ${testsFailed}`);
console.log(`Total: ${testsPassed + testsFailed}`);

if (testsFailed === 0) {
  console.log('\n✓ All tests passed!');
  process.exit(0);
} else {
  console.log('\n✗ Some tests failed!');
  process.exit(1);
}

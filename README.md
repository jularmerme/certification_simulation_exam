# CompTIA A+ Practice Exam Simulator

A comprehensive, single-file HTML/JavaScript application for practicing CompTIA A+ certification exams (Core 1: 220-1201 and Core 2: 220-1202).

## Features

✅ **Two Exam Versions**
- Core 1 (220-1201): Mobile devices, networking, hardware, virtualization, troubleshooting
- Core 2 (220-1202): Operating systems, security, software, operational procedures

✅ **Question Types**
- Multiple Choice (single select)
- Multi-Select (select all that apply)
- Drag-and-Drop (matching, ordering)

✅ **Realistic Exam Experience**
- 90-minute countdown timer with 5-minute warning
- Question navigator with color-coded feedback:
  - 🟢 Green: Correct answer
  - 🔴 Red: Incorrect answer
  - 🟡 Amber: Flagged for review
  - ⚪ Gray: Unanswered
- Flag questions for later review
- Real-time score calculation

✅ **Progress Tracking**
- Automatic answer saving (client-side storage)
- Session persistence across browser reloads
- Detailed result review with explanations

✅ **Fully Responsive**
- Desktop, tablet, and mobile layouts
- Touch-friendly interface
- Adaptive question navigator

## Quick Start

### Requirements
- Modern web browser (Chrome, Firefox, Safari, Edge)
- Internet connection (for initial load only)
- No installation needed

### Usage

1. **Open the application:**
   - Navigate to `index.html` in your browser
   - Or use a local web server: `python -m http.server 8000`

2. **Select your exam:**
   - Click on either "Core 1" or "Core 2"
   - Button becomes enabled when selection is made

3. **Begin the exam:**
   - Click "Begin Exam" to start
   - 90-minute timer begins immediately

4. **Answer questions:**
   - For MC/Multi: click/check options
   - For Drag-Drop: drag items to drop zones
   - Click "Flag" to mark for review
   - Navigate with Previous/Next buttons
   - Click question numbers in navigator to jump

5. **Submit exam:**
   - Click "Submit Exam" button
   - Timer must expire or you manually submit
   - Results display immediately

6. **Review results:**
   - See scaled score and pass/fail status
   - View correct/incorrect count
   - Read detailed explanations
   - Return to menu to retake exam

## File Structure

```
compTia A+/
├── index.html                          # Main application (1108 lines)
├── exam_assets/
│   ├── questions.json                  # Question bank (23 Core1 + 15 Core2)
│   ├── QUESTION_BANK_README.md        # Question format documentation
│   └── QUESTION_EXAMPLES.md           # Example questions with rendering code
├── README.md                           # This file
└── IMPLEMENTATION_SUMMARY.md           # Technical overview
```

## How It Works

### Application Flow

```
Start → Select Exam → Load Questions → Answer Questions → Submit → View Results → Review
```

### Data Structure

Questions are stored in `exam_assets/questions.json`:

```json
{
  "exams": {
    "220-1201": {
      "name": "CompTIA A+ Core 1",
      "code": "220-1201",
      "passingScore": 675,
      "questionBank": [
        {
          "id": "1201-001",
          "domain": "1.0 Mobile Devices",
          "type": "mc",
          "stem": "Question text?",
          "options": [...],
          "correctAnswer": 1,
          "explanation": "Why this is correct..."
        }
      ]
    },
    "220-1202": { ... }
  }
}
```

### Scoring Algorithm

1. **Raw Score**: (Correct Answers / Total Questions) × 100
2. **Scaled Score**: (Raw Score / 100) × (900 - 100) + 100
3. **Result**: 
   - Core 1: 675+ = PASS
   - Core 2: 700+ = PASS

### Color Coding

Navigator cells update in real-time:
- **Green** (#1b7a3d): Question answered correctly
- **Red** (#c8102e): Question answered incorrectly
- **Amber** (#b8790a): Question flagged for review
- **Gray** (#f4f6f8): Question not yet answered

## Features in Detail

### Question Types

#### Multiple Choice (MC)
- Single correct answer from 4 options
- Click option to select
- Updates automatically

#### Multi-Select
- Multiple correct answers (typically 2-3 from 5 options)
- Check all that apply
- Must select ALL correct options

#### Drag and Drop
- Match items to categories
- Arrange items in order
- Drag items between zones
- Real-time validation

### Timer

- Starts when exam begins
- Displays in MM:SS format
- Turns red at 5 minutes remaining
- Auto-submits when time expires
- Can manually stop via "Exit" button

### Progress Preservation

- Answers saved automatically (LocalStorage)
- Can close browser without losing progress
- Session survives page reload
- Each exam version tracked separately

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `←` | Previous question |
| `→` | Next question |
| `Tab` | Navigate options |
| `Space` | Select/check option |

## Customization

### Adding Questions

1. Edit `exam_assets/questions.json`
2. Add question objects to appropriate `questionBank` array
3. Maintain structure as shown in `QUESTION_EXAMPLES.md`
4. Refresh browser (no restart needed)

### Modifying Styling

Core colors defined as CSS variables in `index.html`:

```css
:root {
  --navy: #0f2540;
  --accent: #c8102e;
  --green: #1b7a3d;
  --amber: #b8790a;
  /* ... */
}
```

### Changing Timer Duration

Find in `startExam()` function:
```javascript
appState.timeRemaining = exam.timeLimit * 60; // Modify timeLimit
```

## Browser Compatibility

✅ Chrome 90+
✅ Firefox 88+
✅ Safari 14+
✅ Edge 90+
✅ Mobile browsers (iOS Safari, Chrome Mobile)

## Technical Details

### Technologies Used

- **HTML5**: Semantic structure
- **CSS3**: Grid, flexbox, variables
- **JavaScript (ES6+)**:
  - Fetch API for loading questions
  - LocalStorage for persistence
  - HTML5 Drag and Drop API
  - DOM manipulation

### No External Dependencies

- Pure vanilla JavaScript
- No frameworks or libraries
- No build process required
- Single HTML file deployment

### Performance

- Fast load time (<1s on typical connection)
- Minimal memory footprint
- Smooth animations (60fps)
- Efficient DOM updates

## Troubleshooting

### Questions not loading
- Verify `exam_assets/questions.json` exists
- Check browser console for errors (F12)
- Ensure JSON is valid

### Timer not starting
- Check browser JavaScript is enabled
- Verify DOMContentLoaded event fires
- Review console for errors

### Answers not saving
- Check browser allows LocalStorage
- Verify storage quota not exceeded
- Try different browser

### Drag-drop not working
- Ensure browser supports HTML5 Drag API
- Check console for JavaScript errors
- Try different browser

## Future Enhancements

- [ ] Performance-based questions (PBQ) with simulations
- [ ] Image-based questions
- [ ] Statistics dashboard with trend analysis
- [ ] Study mode with hints
- [ ] Spaced repetition scheduling
- [ ] Collaborative study rooms
- [ ] Mobile app wrapper

## Development Notes

### Code Organization

1. **Global State** (appState object)
   - Tracks exam, questions, answers, timer

2. **UI Functions**
   - Screen management (intro, exam, results)
   - Question rendering
   - Navigator updates

3. **Logic Functions**
   - Answer evaluation
   - Score calculation
   - Timer management

4. **Event Handlers**
   - User interactions
   - Navigation
   - Question submission

### Adding Question Type

To add a new question type:

1. Create render function: `renderNewType()`
2. Add condition in `loadQuestion()` to call render
3. Add evaluation logic in `checkAnswerCorrect()`
4. Add to `questions.json` with new `type` value

## License

Educational use only. CompTIA A+ is a trademark of CompTIA, Inc.

## Support

For questions or issues:
1. Check troubleshooting section above
2. Review browser console (F12)
3. Verify file structure and paths
4. Try different browser

## Changelog

### Version 1.0 (July 2026)
- Initial release
- Core 1 and Core 2 exams
- 3 question types (MC, Multi, Drag-drop)
- Timer and scoring
- Progress tracking
- Responsive design
- 38 starter questions

---

**Status**: Production Ready
**Last Updated**: July 27, 2026
**Question Bank**: 38 questions (expandable to 180+ total)

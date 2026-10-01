// dashboard.js — Progress Dashboard renderer.
// Depends on: results.js (loadResults, clearResults, getWeaknessSummary)
// Called by: showDashboard() / hideDashboard() (globals used by index.html)
// Depends on: js/vendor/exceljs.min.js (window.ExcelJS) for downloadProgressExcel()

// ── Sort state ────────────────────────────────────────────────────────────────
let _sortCol = 'date';
let _sortDir = 'desc';   // 'asc' | 'desc'

// ── Entry points ─────────────────────────────────────────────────────────────

/** Called by the 📊 My Progress topbar button. */
function showDashboard() {
  // Don't allow opening dashboard while an exam is in progress
  const examScreen = document.getElementById('screenExam');
  if (examScreen && !examScreen.classList.contains('hidden')) return;

  showScreen('screenDashboard');
  renderDashboard();
}

/** Called by the ← Back button inside the dashboard. */
function hideDashboard() {
  showScreen('screenIntro');
}

/** Re-render all three sections from current localStorage data. */
function renderDashboard() {
  const history = loadResults();
  _renderSummaryCards(history);
  _renderHistoryTable(history);
  _renderWeaknessTable(history);
}

// ── A. Summary cards ──────────────────────────────────────────────────────────

function _renderSummaryCards(history) {
  const total   = history.length;
  const best    = total > 0 ? Math.max(...history.map(r => r.score)) : null;
  const latest  = total > 0 ? history[0].score : null;   // newest-first
  const last5   = history.slice(0, 5);
  const avg5    = last5.length > 0
    ? Math.round(last5.reduce((s, r) => s + r.score, 0) / last5.length)
    : null;

  _setText('dbTotalSessions', total > 0 ? total : '—');
  _setText('dbBestScore',     best   !== null ? best   + '%' : '—');
  _setText('dbLatestScore',   latest !== null ? latest + '%' : '—');
  _setText('dbAvgScore',      avg5   !== null ? avg5   + '%' : '—');

  // Colour the latest and avg cards by score band
  _setScoreColour('dbLatestScore', latest);
  _setScoreColour('dbAvgScore',    avg5);
}

// ── B. History table ──────────────────────────────────────────────────────────

function _renderHistoryTable(history) {
  const tbody    = document.getElementById('dbHistoryBody');
  const emptyMsg = document.getElementById('dbEmptyMsg');
  const table    = document.getElementById('dbHistoryTable');

  if (!tbody) return;
  tbody.innerHTML = '';

  if (history.length === 0) {
    table  && (table.style.display   = 'none');
    emptyMsg && emptyMsg.classList.remove('hidden');
    return;
  }

  table  && (table.style.display   = '');
  emptyMsg && emptyMsg.classList.add('hidden');

  // Sort
  const sorted = _sortHistory(history, _sortCol, _sortDir);

  sorted.forEach((rec, rowIdx) => {
    const tr = document.createElement('tr');
    tr.className = 'db-tr';
    tr.setAttribute('data-idx', rowIdx);
    tr.style.cursor = 'pointer';
    tr.onclick = () => _toggleBreakdown(tr, rec);

    tr.innerHTML =
      '<td class="db-td">'  + _fmtDate(rec.date)            + '</td>' +
      '<td class="db-td">'  + _escHtml(rec.examLabel || rec.examCode) + '</td>' +
      '<td class="db-td db-num">' + (rec.totalQuestions || 0) + '</td>' +
      '<td class="db-td db-num db-correct">'   + (rec.correct   || 0) + '</td>' +
      '<td class="db-td db-num db-incorrect">' + (rec.incorrect || 0) + '</td>' +
      '<td class="db-td db-num db-skipped">'   + (rec.incomplete || 0) + '</td>' +
      '<td class="db-td db-num">' + _scoreCell(rec.score)    + '</td>' +
      '<td class="db-td db-num">' + _fmtDuration(rec.durationSeconds) + '</td>';

    tbody.appendChild(tr);
  });

  _syncSortHeaders();
}

function _toggleBreakdown(tr, rec) {
  // If an expansion row is already open for this row, close it
  const next = tr.nextElementSibling;
  if (next && next.classList.contains('db-breakdown-row')) {
    next.remove();
    tr.classList.remove('db-tr-expanded');
    return;
  }

  // Close any other open expansion first
  const existingOpen = document.querySelector('.db-breakdown-row');
  if (existingOpen) {
    const parentTr = existingOpen.previousElementSibling;
    if (parentTr) parentTr.classList.remove('db-tr-expanded');
    existingOpen.remove();
  }

  tr.classList.add('db-tr-expanded');

  const expandTr = document.createElement('tr');
  expandTr.className = 'db-breakdown-row';

  const td = document.createElement('td');
  td.colSpan = 8;
  td.className = 'db-breakdown-cell';

  const breakdown = rec.breakdown || {};
  const domains   = Object.keys(breakdown);

  if (domains.length === 0) {
    td.innerHTML = '<em style="color: var(--muted);">No domain breakdown available.</em>';
  } else {
    let inner = '<table class="db-breakdown-table"><thead><tr>' +
      '<th>Domain</th><th>Correct</th><th>Incorrect</th><th>Skipped</th><th>Total</th><th>Score %</th>' +
      '</tr></thead><tbody>';
    domains.forEach(domain => {
      const d = breakdown[domain];
      const pct = d.total > 0 ? Math.round((d.correct / d.total) * 100) : 0;
      inner += '<tr>' +
        '<td>' + _escHtml(domain) + '</td>' +
        '<td class="db-num db-correct">'   + d.correct   + '</td>' +
        '<td class="db-num db-incorrect">' + d.incorrect + '</td>' +
        '<td class="db-num db-skipped">'   + d.incomplete + '</td>' +
        '<td class="db-num">'              + d.total      + '</td>' +
        '<td class="db-num">'              + _scoreCell(pct) + '</td>' +
        '</tr>';
    });
    inner += '</tbody></table>';
    td.innerHTML = inner;
  }

  expandTr.appendChild(td);
  tr.parentNode.insertBefore(expandTr, tr.nextSibling);
}

// ── C. Weakness tracker ───────────────────────────────────────────────────────

function _renderWeaknessTable(history) {
  const tbody    = document.getElementById('dbWeaknessBody');
  const emptyMsg = document.getElementById('dbWeaknessEmptyMsg');
  const table    = document.getElementById('dbWeaknessTable');

  if (!tbody) return;
  tbody.innerHTML = '';

  const summary = getWeaknessSummary(history);

  if (summary.length === 0) {
    table    && (table.style.display = 'none');
    emptyMsg && emptyMsg.classList.remove('hidden');
    return;
  }

  table    && (table.style.display = '');
  emptyMsg && emptyMsg.classList.add('hidden');

  summary.forEach(row => {
    const tr = document.createElement('tr');
    tr.className = 'db-tr';
    tr.innerHTML =
      '<td class="db-td">'      + _escHtml(row.domain)   + '</td>' +
      '<td class="db-td db-num">' + row.total             + '</td>' +
      '<td class="db-td db-num">' + _scoreCell(row.avgScore) + '</td>' +
      '<td class="db-td db-num db-trend">' + row.trend    + '</td>' +
      '<td class="db-td db-num">' + row.focusFlag          + '</td>';
    tbody.appendChild(tr);
  });
}

// ── Sorting ───────────────────────────────────────────────────────────────────

function _sortHistory(history, col, dir) {
  return [...history].sort((a, b) => {
    let av = a[col], bv = b[col];

    // Normalise strings for comparison
    if (typeof av === 'string') av = av.toLowerCase();
    if (typeof bv === 'string') bv = bv.toLowerCase();

    if (av === undefined || av === null) av = '';
    if (bv === undefined || bv === null) bv = '';

    if (av < bv) return dir === 'asc' ? -1 :  1;
    if (av > bv) return dir === 'asc' ?  1 : -1;
    return 0;
  });
}

function _syncSortHeaders() {
  document.querySelectorAll('#dbHistoryTable .db-th.sortable').forEach(th => {
    const col  = th.getAttribute('data-col');
    const icon = th.querySelector('.db-sort-icon');
    if (!icon) return;

    th.classList.remove('db-sort-asc', 'db-sort-desc');
    icon.textContent = '';

    if (col === _sortCol) {
      th.classList.add(_sortDir === 'asc' ? 'db-sort-asc' : 'db-sort-desc');
      icon.textContent = _sortDir === 'asc' ? '↑' : '↓';
    }
  });
}

// Attach sort click listeners once the DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('#dbHistoryTable .db-th.sortable').forEach(th => {
    th.style.cursor = 'pointer';
    th.onclick = () => {
      const col = th.getAttribute('data-col');
      if (_sortCol === col) {
        _sortDir = _sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        _sortCol = col;
        _sortDir = col === 'date' ? 'desc' : 'asc';
      }
      renderDashboard();
    };
  });
});

// ── Clear history ─────────────────────────────────────────────────────────────

function confirmClearHistory() {
  if (confirm('Clear all session history? This cannot be undone.')) {
    clearResults();
    renderDashboard();
  }
}

// ── Formatting helpers ────────────────────────────────────────────────────────

function _fmtDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) +
      ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  } catch (e) { return iso; }
}

function _fmtDuration(secs) {
  if (!secs && secs !== 0) return '—';
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return m + 'm ' + String(s).padStart(2, '0') + 's';
}

/** Return a coloured score badge string (inline style). */
function _scoreCell(pct) {
  if (pct === null || pct === undefined) return '—';
  const cls = pct >= 75 ? 'db-score-green' : pct >= 60 ? 'db-score-amber' : 'db-score-red';
  return '<span class="db-score-badge ' + cls + '">' + pct + '%</span>';
}

/** Apply a score colour class directly to a summary card value element. */
function _setScoreColour(id, pct) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('db-score-green', 'db-score-amber', 'db-score-red');
  if (pct === null || pct === undefined) return;
  el.classList.add(pct >= 75 ? 'db-score-green' : pct >= 60 ? 'db-score-amber' : 'db-score-red');
}

function _setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function _escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Excel export ──────────────────────────────────────────────────────────────

/**
 * "Download Table" button — exports both the Session History table and the
 * Domain Weakness Tracker into one formatted .xlsx workbook (two sheets),
 * using the data currently loaded in the dashboard (same sort order as shown
 * on screen for Session History).
 */
async function downloadProgressExcel() {
  if (typeof ExcelJS === 'undefined') {
    alert('Excel export library failed to load. Check your internet/file setup and reload the page.');
    return;
  }

  const history = loadResults();
  const sortedHistory = _sortHistory(history, _sortCol, _sortDir);
  const weakness = getWeaknessSummary(history);

  const wb = new ExcelJS.Workbook();
  wb.creator = 'CompTIA A+ Practice Exam Simulator';
  wb.created = new Date();

  const NAVY   = 'FF1A2B4D';
  const WHITE  = 'FFFFFFFF';
  const LIGHT  = 'FFF4F6F8';
  const GREEN  = 'FFD9ECDF';
  const AMBER  = 'FFFDEECB';
  const RED    = 'FFFBE6E9';
  const BORDER = { style: 'thin', color: { argb: 'FFD0D5DD' } };
  const THIN_BORDER = { top: BORDER, bottom: BORDER, left: BORDER, right: BORDER };

  function styleHeaderRow(row) {
    row.eachCell(cell => {
      cell.font = { bold: true, color: { argb: WHITE }, size: 11 };
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: NAVY } };
      cell.alignment = { vertical: 'middle', horizontal: 'center', wrapText: true };
      cell.border = THIN_BORDER;
    });
    row.height = 26;
  }

  function scoreFillFor(pct) {
    if (pct === null || pct === undefined) return null;
    return pct >= 75 ? GREEN : pct >= 60 ? AMBER : RED;
  }

  // ── Sheet 1: Session History ────────────────────────────────────────────────
  const histSheet = wb.addWorksheet('Session History', { views: [{ state: 'frozen', ySplit: 1 }] });
  histSheet.columns = [
    { header: 'Date & Time',  key: 'date',    width: 20 },
    { header: 'Exam / Mode',  key: 'exam',    width: 32 },
    { header: 'Questions',    key: 'total',   width: 11 },
    { header: 'Correct',      key: 'correct', width: 10 },
    { header: 'Incorrect',    key: 'incorrect', width: 10 },
    { header: 'Skipped',      key: 'skipped', width: 10 },
    { header: 'Score %',      key: 'score',   width: 10 },
    { header: 'Duration',     key: 'duration', width: 12 }
  ];
  styleHeaderRow(histSheet.getRow(1));

  sortedHistory.forEach((rec, i) => {
    const row = histSheet.addRow({
      date: _fmtDate(rec.date),
      exam: rec.examLabel || rec.examCode || '—',
      total: rec.totalQuestions || 0,
      correct: rec.correct || 0,
      incorrect: rec.incorrect || 0,
      skipped: rec.incomplete || 0,
      score: rec.score ?? 0,
      duration: _fmtDuration(rec.durationSeconds)
    });
    const zebra = i % 2 === 1 ? LIGHT : null;
    row.eachCell((cell, colNum) => {
      cell.border = THIN_BORDER;
      cell.alignment = { vertical: 'middle', horizontal: colNum <= 2 ? 'left' : 'center' };
      if (zebra) cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: zebra } };
    });
    const scoreCell = row.getCell(7);
    scoreCell.numFmt = '0"%"';
    const fill = scoreFillFor(rec.score);
    if (fill) {
      scoreCell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: fill } };
      scoreCell.font = { bold: true };
    }
  });

  if (sortedHistory.length === 0) {
    const row = histSheet.addRow({ date: 'No sessions recorded yet.' });
    row.getCell(1).font = { italic: true, color: { argb: 'FF888888' } };
  }

  histSheet.autoFilter = sortedHistory.length > 0 ? { from: 'A1', to: 'H1' } : undefined;

  // ── Sheet 2: Domain Weakness Tracker ─────────────────────────────────────────
  const weakSheet = wb.addWorksheet('Domain Weakness', { views: [{ state: 'frozen', ySplit: 1 }] });
  weakSheet.columns = [
    { header: 'Domain',          key: 'domain', width: 34 },
    { header: 'Total Answered',  key: 'total',  width: 16 },
    { header: 'Avg Score %',     key: 'avg',    width: 14 },
    { header: 'Trend',           key: 'trend',  width: 10 },
    { header: 'Focus?',          key: 'focus',  width: 10 }
  ];
  styleHeaderRow(weakSheet.getRow(1));

  weakness.forEach((row, i) => {
    const r = weakSheet.addRow({
      domain: row.domain,
      total: row.total,
      avg: row.avgScore,
      trend: row.trend,
      focus: row.focusFlag
    });
    const zebra = i % 2 === 1 ? LIGHT : null;
    r.eachCell((cell, colNum) => {
      cell.border = THIN_BORDER;
      cell.alignment = { vertical: 'middle', horizontal: colNum === 1 ? 'left' : 'center' };
      if (zebra) cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: zebra } };
    });
    const avgCell = r.getCell(3);
    avgCell.numFmt = '0"%"';
    const fill = scoreFillFor(row.avgScore);
    if (fill) {
      avgCell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: fill } };
      avgCell.font = { bold: true };
    }
  });

  if (weakness.length === 0) {
    const row = weakSheet.addRow({ domain: 'No domain data yet — complete at least one exam.' });
    row.getCell(1).font = { italic: true, color: { argb: 'FF888888' } };
  }

  weakSheet.autoFilter = weakness.length > 0 ? { from: 'A1', to: 'E1' } : undefined;

  // ── Trigger browser download ─────────────────────────────────────────────────
  const buffer = await wb.xlsx.writeBuffer();
  const blob = new Blob([buffer], { type: 'application/octet-stream' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const stamp = new Date().toISOString().slice(0, 10);
  a.href = url;
  a.download = 'CompTIA_A+_Progress_' + stamp + '.xlsx';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

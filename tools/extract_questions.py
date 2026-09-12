#!/usr/bin/env python3
"""
extract_questions.py — extract CompTIA A+ quiz questions from CertMaster JPG
screenshots using FREE local OCR (Tesseract + Pillow), and write structured JSON
(one file per source folder) ready for review before merge into
exam_assets/questions.json.

Pipeline: discover -> preprocess -> OCR (Tesseract) -> parse -> classify
(rule-based keyword matching against Core 1 metadata) -> deduplicate (Jaccard vs
existing bank + within batch) -> validate -> write per-folder JSON + a summary.

Zero cost, no API key. This script never modifies questions.json; it only READS it
(as the classification reference and dedup source) and WRITES new extracted_*.json
files to --output.

Requirements:
  System: Tesseract OCR engine
    Windows installer: https://github.com/UB-Mannheim/tesseract/wiki
    Default path: C:\\Program Files\\Tesseract-OCR\\tesseract.exe
  pip: pip install -r tools/requirements_extract.txt   (pytesseract, Pillow, tqdm)

Usage:
  python tools/extract_questions.py \
      --source "C:\\Users\\mercadjn\\Downloads\\pdf images" \
      --output exam_assets/ \
      --bank exam_assets/questions.json \
      --workers 10
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

# --- optional / required deps: degrade gracefully --------------------------
try:
    from PIL import Image, ImageEnhance, ImageOps
    _HAVE_PIL = True
except ImportError:
    _HAVE_PIL = False

try:
    import pytesseract
    _HAVE_TESS = True
except ImportError:
    _HAVE_TESS = False

try:
    from tqdm import tqdm
    _HAVE_TQDM = True
except ImportError:
    _HAVE_TQDM = False

    def tqdm(iterable=None, total=None, desc=None, **kwargs):
        """Minimal print-based fallback when tqdm is unavailable."""
        if iterable is None:
            iterable = range(total or 0)
        count = 0
        total = total if total is not None else (len(iterable) if hasattr(iterable, "__len__") else None)
        for item in iterable:
            count += 1
            if total:
                print(f"\r  {desc or 'progress'}: {count}/{total}", end="", file=sys.stderr, flush=True)
            yield item
        if total:
            print("", file=sys.stderr)

# --- tunables ---------------------------------------------------------------
MIN_UPSCALE_EDGE = 2000        # scale UP to at least this on the long side
DEFAULT_THRESHOLD = 160        # binarization threshold (0-255)
CONTRAST_FACTOR = 1.5
SHARPNESS_FACTOR = 2.0
DUP_THRESHOLD = 0.85
MIN_OCR_CHARS = 50             # below this, flag the image as unreadable
MIN_OPTIONS = 3                # CertMaster questions have 3-6 options
MAX_OPTIONS = 8
TESSERACT_CONFIG = "--psm 6 --oem 3"


# ---------------------------------------------------------------------------
# Discovery (unchanged)
# ---------------------------------------------------------------------------
def module_from_folder(folder_name):
    """CertMaster folder prefix -> module key 'X.0'. 'X.Y ...' or 'X ...'."""
    m = re.match(r"^(\d+)\.(\d+)", folder_name)
    if m:
        return f"{int(m.group(1))}.0", int(m.group(1)), int(m.group(2))
    m = re.match(r"^(\d+)\b", folder_name)
    if m:
        return f"{int(m.group(1))}.0", int(m.group(1)), 0
    return "?.0", 999, 999


def sanitize_folder(folder_name):
    """'5.1 Network Types.pdf' -> '5.1_Network_Types' (drop trailing .pdf)."""
    name = re.sub(r"\.pdf$", "", folder_name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", "_", name.strip())
    name = re.sub(r"[^0-9A-Za-z._-]", "", name)
    return name


def discover(source):
    """Return folders sorted by (module, lesson), each with its jpg paths."""
    root = Path(source)
    folders = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        mod_key, mod_n, les_n = module_from_folder(d.name)
        jpgs = sorted(
            [p for p in d.iterdir() if p.suffix.lower() in (".jpg", ".jpeg")],
            key=lambda p: p.name,
        )
        if jpgs:
            folders.append({"path": d, "name": d.name, "module": mod_key,
                            "mod_n": mod_n, "les_n": les_n, "images": jpgs})
    folders.sort(key=lambda f: (f["mod_n"], f["les_n"], f["name"]))
    return folders


# ---------------------------------------------------------------------------
# Step 2: preprocessing
# ---------------------------------------------------------------------------
def preprocess(path, threshold):
    """Grayscale, upscale, contrast, sharpen, binarize. Returns a PIL image."""
    im = Image.open(path).convert("L")           # grayscale
    w, h = im.size
    scale = MIN_UPSCALE_EDGE / max(w, h)
    if scale > 1:                                # scale UP (Tesseract likes big)
        im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    im = ImageEnhance.Contrast(im).enhance(CONTRAST_FACTOR)
    im = ImageEnhance.Sharpness(im).enhance(SHARPNESS_FACTOR)
    # binarize at threshold
    im = im.point(lambda p: 255 if p >= threshold else 0, mode="1")
    return im


# ---------------------------------------------------------------------------
# Step 3: OCR
# ---------------------------------------------------------------------------
def ocr_image(im):
    return pytesseract.image_to_string(im, config=TESSERACT_CONFIG)


# ---------------------------------------------------------------------------
# Step 4: parse questions from raw OCR text
# ---------------------------------------------------------------------------
# CertMaster Individual Response OCR artifacts (observed in real Tesseract output):
#
#   Question header:   "Question 4 © Correct" / "Question 1 @ Correct"
#     -> the radio-icon (@ selected, © / (C) unselected) + status must be stripped.
#
#   Unselected option: "© A."  "oO B"  "O B"  "© 8"(B->8)  "Oc X"  "OA X"  "Ood"
#   Selected option:   "@ ¢"(C misread)  "@C"  "@A"  "@D"  "@ C"
#     -> a leading icon glob (© ® @ o O ( ) C copyright/at/paren noise), then the
#        option LETTER (which itself may be misread: ¢->C, 8->B, o/O near a letter),
#        then optional punctuation, then the option text.
#
#   Correct marker (end of the correct option's line): "Y Correct" / "y Correct"
#     / "/ Correct".  Selected options also begin with "@".
#
# Icon glob preceding the real option letter (selected '@', unselected '©'/'®'/
# '(C)', and the letters o/O/0 that Tesseract emits for the radio circle).
_ICON = r"[©®()oO0\u2022\-\*]"
# Option line. Accepted shapes, ordered to avoid matching ordinary stem lines that
# start with a lowercase word ("a city?"):
#   (a) selected: '@' then the option letter (any case, incl. misread ¢/8). The '@'
#       is itself the radio icon, so an intervening icon char is optional.
#   (b) unselected: a real icon prefix (© ® ( ) o O 0), then the option letter.
#   (c) bare: NO icon, but an UPPERCASE letter A-H (or 8=B) — a plain "A Foo" option.
# Group 1 = '@' if selected; the letter is whichever of the letter groups matched.
_OPT_CORE = (r"(?:@\s*" + _ICON + r"*\s*([A-Ha-h¢8])"   # (a) selected
             r"|" + _ICON + r"+\s*([A-Ha-h¢8])"          # (b) unselected icon
             r"|([A-H8]))")                               # (c) bare uppercase
OPTION_RE = re.compile(r"^\s*(@)?\s*" + _OPT_CORE + r"[\._:\)\-]*\s+(\S.*)$")
OPTION_BARE_RE = re.compile(r"^\s*(@)?\s*" + _OPT_CORE + r"[\._:\)\-]*\s*$")

# Question header, tolerant of the OCR'd status icon after the number. The status
# word (Correct/Incorrect) is matched EXPLICITLY (not via the icon class) so its
# leading 'C' is fully consumed and never leaks into the stem as "orrect".
# Group 1 = question number. Group 2 = the status word (Correct/Incorrect) if
# present, so process_folder can tell whether the attempt was right. Group 3 = any
# residual text on the header line (rare). The status icon (@ © ® ( ) X x) AND the
# status word are both fully consumed so neither leaks into the stem.
QUESTION_HDR_RE = re.compile(
    r"^\s*Question\s+(\d+)\b[\s@©®()Xx✓✔/\\]*\s*(correct|incorrect)?\b\s*(.*)$",
    re.IGNORECASE)

# Trailing correct-answer marker on an option line: "Y Correct" / "y Correct"
# / "/ Correct" / "\/ Correct" / a bare checkmark.
CORRECT_MARKER_RE = re.compile(r"\s*[Yy/\\✓✔]+\s*correct\s*$", re.IGNORECASE)
# Trailing incorrect marker: "X Incorrect" / "XX Incorrect" / "x Incorrect".
INCORRECT_MARKER_RE = re.compile(r"\s*[Xx]+\s*incorrect\s*$", re.IGNORECASE)
# Either marker (for stripping any status suffix from option text).
ANY_MARKER_RE = re.compile(r"\s*[Yy/\\Xx✓✔]+\s*(?:in)?correct\s*$", re.IGNORECASE)
CORRECT_TOKEN_RE = re.compile(r"\b(correct|✓|✔)\b", re.IGNORECASE)

# Letterless option prefix (Format B): a leading radio-button icon, then text.
# Two safe shapes so real words like "Open"/"Overload" aren't mistaken for an
# 'O' icon:
#   (a) a distinctive icon (@ © ® ( ) • - *), optionally repeated, then text. These
#       never begin an English word, so no space is required after them.
#   (b) a bare circle letter (o O 0) ONLY when followed by a space/underscore and
#       then the text — "O damage", "0 the computer". "Open" (no space) is excluded.
# A leading '@' (selected) is captured in group 1 in both shapes.
_ICON_STRONG = r"[@©®()\u2022]"
OPTION_B_RE = re.compile(
    r"^\s*(@)?\s*(?:" + _ICON_STRONG + r"[@©®()_\s\u2022]*|[oO0][_\s]+)\s*(\S.*)$")

# Metadata/boilerplate lines to drop before parsing.
_META_RES = [
    re.compile(r"Individual Response", re.IGNORECASE),
    re.compile(r"^\s*(Julian Mercado|.*@gmail\.com)", re.IGNORECASE),
    re.compile(r"^\s*Date:\s", re.IGNORECASE),
    re.compile(r"^\s*Time Spent:", re.IGNORECASE),
    re.compile(r"^\s*Score:\s.*Passing Score:", re.IGNORECASE),
    re.compile(r"^\s*Score:\s", re.IGNORECASE),
    re.compile(r"^\s*(https?|hitps)://", re.IGNORECASE),   # 'hitps' = OCR of https
    re.compile(r"Copyright.*CompTIA", re.IGNORECASE),
    re.compile(r"resources[\\/].*question.*\.xml", re.IGNORECASE),  # source-path noise
    re.compile(r"^\s*\.\s*$"),                             # lone dot artifact line
    re.compile(r"^\s*\d+\s*$"),                            # lone page number
    re.compile(r"^\s*\d+/\d+\s*$"),                        # "3/3" page indicator
]


def _norm_option_letter(ch):
    """Normalize a possibly-misread option letter to uppercase A-H."""
    ch = ch.upper()
    return {"¢": "C", "8": "B", "0": "O"}.get(ch, ch)


def strip_metadata(raw):
    """Drop CertMaster header/footer boilerplate lines."""
    kept = []
    for line in raw.splitlines():
        if any(r.search(line) for r in _META_RES):
            continue
        kept.append(line)
    return "\n".join(kept)


def clean_text(s):
    """Trim OCR noise: pipes, stray single chars, collapse whitespace."""
    s = s.replace("|", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # drop leading stray artifact chars like "© " or "= " if present
    s = re.sub(r"^[^\w(]+", "", s)
    return s.strip()


def split_question_blocks(raw):
    """Split OCR text into blocks at each 'Question N' header.
    Returns a list of (is_question, status, lines):
      - is_question: True if the block was introduced by a 'Question N' header
      - status: the attempt status word (Correct/Incorrect), defaulting to Correct
      - lines: the lines after the header
    Text before the first header (or a page with no header at all) is returned as a
    single is_question=False block, which lets the caller skip non-question pages."""
    lines = raw.splitlines()
    blocks = []
    current, status, in_question = [], "Correct", False
    started = False
    for line in lines:
        m = QUESTION_HDR_RE.match(line)
        if m:
            if started:
                blocks.append((in_question, status, current))
            started = True
            in_question = True
            status = (m.group(2) or "").strip() or "Correct"
            current = []
            trailing = (m.group(3) or "").strip()
            if trailing:
                current.append(trailing)
        else:
            if not started:
                started = True
                in_question = False
            current.append(line)
    if started:
        blocks.append((in_question, status, current))
    return blocks


def _parse_option_line(line):
    """If `line` is an option, return (letter, text, selected, marked); else None.
    Group layout after the optional leading '@' (group 1):
      group 2 = letter via selected '@...' branch (a)
      group 3 = letter via unselected icon branch (b)
      group 4 = letter via bare uppercase branch (c)
    In OPTION_RE the final group is the option text.
    selected == leading '@' (group 1) OR branch (a) matched (group 2).
    """
    def unpack(m, has_text):
        g1 = m.group(1)
        letter = m.group(2) or m.group(3) or m.group(4)
        selected = bool(g1) or bool(m.group(2))
        text = m.group(m.lastindex) if has_text else ""
        marked = bool(CORRECT_MARKER_RE.search(text))
        text = CORRECT_MARKER_RE.sub("", text)
        text = re.sub(r"_+$", "", text.strip())      # trailing underscore artifact
        return (_norm_option_letter(letter), clean_text(text), selected, marked)

    m = OPTION_RE.match(line)
    if m:
        return unpack(m, has_text=True)
    mb = OPTION_BARE_RE.match(line)
    if mb:
        return unpack(mb, has_text=False)
    return None


def _fix_ocr_words(s):
    """Fix a few known OCR word-merges/artifacts in option/stem text."""
    s = re.sub(r"\bAuser\b", "A user", s)
    return s


def _parse_options_lettered(body_lines):
    """FORMAT A: icon + letter (A-D) + text. Returns list of option dicts.
    This is the original 5.1-style path, kept intact for regression."""
    options = []
    seen_option = False
    stem_parts = []
    for ln in body_lines:
        parsed = _parse_option_line(ln)
        if parsed:
            letter, text, selected, marked = parsed
            options.append({"text": text, "selected": selected, "marked": marked,
                            "incorrect": bool(INCORRECT_MARKER_RE.search(ln))})
            seen_option = True
        elif not seen_option:
            stem_parts.append(ln)
        elif options and ln.strip():
            # continuation of the current option's text
            extra = ANY_MARKER_RE.sub("", ln)
            if CORRECT_MARKER_RE.search(ln):
                options[-1]["marked"] = True
            if INCORRECT_MARKER_RE.search(ln):
                options[-1]["incorrect"] = True
            options[-1]["text"] = clean_text(options[-1]["text"] + " " + extra)
    return stem_parts, options


def _parse_options_letterless(body_lines):
    """FORMAT B: icon (no letter) + text, options often multi-line. An icon line
    starts a new option; a non-icon, non-empty line continues the current option
    (or, before any option, is stem text).

    Handles the wrapped case where the option text begins on a NON-icon line and the
    icon appears on the following line (e.g. 'Open the computer case ... physical' /
    'O damage.'): such a pre-icon text line is buffered and prepended to the option
    the icon starts.
    """
    options = []
    stem_parts = []
    seen_option = False
    pending = []          # non-icon text seen since the last option (potential
                          # wrapped-option lead-in OR stem before the first option)

    for ln in body_lines:
        if not ln.strip():
            pending = []          # blank line: separator, discard buffered lead-in
            continue
        mb = OPTION_B_RE.match(ln)
        if mb:
            selected = bool(mb.group(1))
            text = mb.group(2)
            marked = bool(CORRECT_MARKER_RE.search(text))
            incorrect = bool(INCORRECT_MARKER_RE.search(text))
            text = ANY_MARKER_RE.sub("", text)
            # Prepend any buffered pre-icon lead-in (wrapped option first line).
            lead = " ".join(pending).strip()
            pending = []
            full = clean_text(((lead + " ") if lead else "") + text)
            options.append({"text": full, "selected": selected, "marked": marked,
                            "incorrect": incorrect})
            seen_option = True
        else:
            if not seen_option:
                # Could be stem, or the lead-in of the first (wrapped) option. Keep
                # it as both a stem candidate and a pending lead-in; if an icon
                # follows, pending wins and we retroactively treat it as option text.
                pending.append(ln)
                stem_parts.append(ln)
            elif options:
                # continuation of the current option
                extra = ANY_MARKER_RE.sub("", ln)
                if CORRECT_MARKER_RE.search(ln):
                    options[-1]["marked"] = True
                if INCORRECT_MARKER_RE.search(ln):
                    options[-1]["incorrect"] = True
                options[-1]["text"] = clean_text(options[-1]["text"] + " " + extra)

    # If the first option absorbed a lead-in that was ALSO added to stem_parts,
    # remove those lead-in lines from the stem (they belong to the option).
    if options and pending is not None:
        pass  # pending already cleared; stem cleanup handled below
    return stem_parts, options


def parse_questions(raw):
    """Parse OCR text into question dicts, returning (questions, had_header).

    had_header is True if any 'Question N' header was present. process_folder uses
    it to distinguish a SKIP (no question on the page) from an ERROR (a question was
    present but could not be parsed).

    Each question dict: stem, options, correctAnswer, explanation, questionType,
    plus a private _flags list of review reasons and _truncated flag.
    """
    raw = strip_metadata(raw)
    blocks = split_question_blocks(raw)
    had_header = any(is_q for is_q, _st, _ln in blocks)
    results = []

    for is_question, header_status, block_lines in blocks:
        if not is_question:
            continue  # pre-header / non-question text
        # Locate the Explanation marker (everything after it is the explanation).
        expl_idx = None
        for i, ln in enumerate(block_lines):
            if re.match(r"^\s*explanation\b", ln, re.IGNORECASE):
                expl_idx = i
                break
        body_lines = block_lines[:expl_idx] if expl_idx is not None else block_lines
        expl_lines = block_lines[expl_idx + 1:] if expl_idx is not None else []

        # FORMAT A first (lettered). Fall back to FORMAT B (letterless) if A finds
        # fewer than 2 options.
        stem_parts, options = _parse_options_lettered(body_lines)
        if len(options) < 2:
            stem_parts, options = _parse_options_letterless(body_lines)
            # In Format B, a wrapped option's lead-in line was also captured as a
            # stem part; drop any stem line that is a prefix of an option's text.
            opt_texts_lower = [o["text"].lower() for o in options]
            stem_parts = [s for s in stem_parts
                          if not any(o.startswith(clean_text(s).lower()[:25]) and clean_text(s)
                                     for o in opt_texts_lower)]

        if len(options) < 2:
            continue  # header present but unparseable -> caller logs as error

        stem = _fix_ocr_words(clean_text(" ".join(stem_parts)))
        option_texts = [_fix_ocr_words(o["text"]) for o in options if o["text"]]
        explanation = _fix_ocr_words(clean_text(" ".join(expl_lines)))

        header_incorrect = bool(header_status and re.search(r"incorrect", header_status, re.IGNORECASE))

        # Correct-answer logic:
        #  - explicit "/ Correct" / "Y Correct" markers always win.
        #  - else if the header says the attempt was correct, the SELECTED (@) option
        #    is the correct answer.
        #  - if the header says incorrect, the selected option is WRONG; rely on the
        #    /Correct marker (handled above) or the explanation fallback.
        marked_correct = [o["text"] for o in options if o["marked"] and o["text"]]
        if marked_correct:
            correct = [_fix_ocr_words(t) for t in marked_correct]
        elif not header_incorrect:
            correct = [_fix_ocr_words(o["text"]) for o in options if o["selected"] and o["text"]]
        else:
            correct = []
        found = bool(correct)

        if not found:
            correct, found = _correct_from_explanation(option_texts, explanation)

        qtype = "multi" if len(correct) > 1 else "mc"
        if re.search(r"\bdrag\b|\bdrop\b|match each", (stem + " " + raw).lower()):
            qtype = "drag_drop"

        # Truncated-option detection: CertMaster options normally end in sentence
        # punctuation. A short option (<15 chars) with no ending .?! is very likely
        # cut off at the image boundary ("Escalate the", "Pe", "O documentation,").
        truncated = any(len(t) < 15 and not re.search(r"[.?!]$", t) for t in option_texts)

        flags = []
        if not found:
            flags.append("correctAnswer not detected by OCR")
        if len(option_texts) < MIN_OPTIONS:
            flags.append(f"only {len(option_texts)} options parsed (<{MIN_OPTIONS})")
        if len(option_texts) > MAX_OPTIONS:
            flags.append(f"{len(option_texts)} options parsed (>{MAX_OPTIONS})")
        if truncated:
            flags.append("truncated option text")

        if stem:
            results.append({
                "stem": stem, "options": option_texts, "correctAnswer": correct,
                "explanation": explanation, "questionType": qtype, "_flags": flags,
            })

    # Drop OCR-stuttered duplicate stems within the same image.
    seen, deduped = set(), []
    for q in results:
        key = q["stem"].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(q)
    return deduped, had_header


def _correct_from_explanation(options, explanation):
    """Fallback: infer correct option(s) from the explanation text."""
    expl = (explanation or "").lower()
    correct = []
    for opt in options:
        ol = opt.lower()
        if (f"correct answer is {ol}" in expl or f"{ol} is correct" in expl
                or f"{ol} is the correct" in expl):
            if opt not in correct:
                correct.append(opt)
    if correct:
        return correct, True
    # "X because ..." near the start of the explanation names the correct option.
    for opt in options:
        ol = re.escape(opt.lower())
        if re.search(rf"^{ol}\b.*\bbecause\b", expl) or re.search(rf"\b{ol}\b[^.]*\bbecause\b", expl[:120]):
            if opt not in correct:
                correct.append(opt)
    return correct, bool(correct)


# ---------------------------------------------------------------------------
# Step 5: rule-based classification (keyword matching, no API)
# ---------------------------------------------------------------------------
_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text):
    return _WORD_RE.findall((text or "").lower())


# Tokens that appear in many objective descriptions carry little discriminating
# power. Down-weight them so a question about "network types" isn't dragged toward
# every objective that merely contains the word "network".
_STOPWORDS = {"given", "scenario", "compare", "contrast", "explain", "summarize",
              "identify", "configure", "install", "use", "types", "type", "common",
              "basic", "and", "the", "for", "their", "purposes", "features",
              "concepts", "appropriate", "various", "of", "a", "an", "to", "or",
              "with", "on", "in", "each"}


def build_objective_index(meta):
    """Precompute per-objective token sets and phrases, plus an IDF-style weight
    for each token (rarer across objectives = more discriminating)."""
    from collections import Counter
    df = Counter()
    per_obj_tokens = {}
    for obj, desc in meta["objectives"].items():
        toks = set(t for t in _words(desc) if t not in _STOPWORDS and len(t) > 2)
        per_obj_tokens[obj] = toks
        for t in toks:
            df[t] += 1
    n = len(meta["objectives"])
    idx = {}
    for obj, desc in meta["objectives"].items():
        toks = per_obj_tokens[obj]
        # weight: tokens in few objectives score high; ubiquitous ones ~0.
        weights = {t: (1.0 + (n - df[t]) / n) for t in toks}
        phrases = [p for p in re.findall(r"[a-z]+(?:\s+[a-z]+)+", desc.lower()) if len(p) > 6]
        idx[obj] = {"tokens": toks, "weights": weights, "phrases": phrases}
    return idx


def classify_question(q, meta, obj_index, folder_module):
    """Score every objective by IDF-weighted keyword/phrase overlap; pick best.
    Returns dict: domain, objective, module, confidence, reasoning."""
    text = " ".join([q.get("stem", "")] + q.get("options", []) + [q.get("explanation", "")])
    qtoks = set(_words(text))
    tl = text.lower()

    scored = []
    for obj, info in obj_index.items():
        score = sum(info["weights"][t] for t in (qtoks & info["tokens"]))
        score += sum(3 for p in info["phrases"] if p in tl)  # phrase match bonus
        scored.append((score, obj))
    scored.sort(reverse=True)

    top_score, top_obj = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0

    # confidence from the ratio of top to second-best
    if second_score == 0:
        conf = "high" if top_score > 0 else "low"
    elif top_score >= 2 * second_score:
        conf = "high"
    elif top_score >= 1.3 * second_score:
        conf = "medium"
    else:
        conf = "low"

    # Folder-module tiebreak. The CertMaster folder maps to a single module and is
    # a far more reliable module signal than keyword overlap on short questions,
    # where generic tokens ("network", "device", "connectivity") routinely pull the
    # top objective into the wrong domain. So: if the keyword winner's module does
    # not match the folder, and some objective that DOES match the folder scored
    # non-trivially (>= 40% of the top score) within the top 5, prefer it. A keyword
    # winner that already matches the folder module is kept and treated as high
    # confidence.
    keyword_winner = top_obj
    folder_backed = [(sc, o) for sc, o in scored[:5]
                     if OBJ_TO_MODULE.get(o) == folder_module]
    if OBJ_TO_MODULE.get(top_obj) != folder_module and folder_backed:
        best_fb_score, best_fb_obj = folder_backed[0]
        if best_fb_score >= 0.4 * top_score or top_score == 0:
            top_obj = best_fb_obj
            conf = "medium"  # overridden by folder signal, not pure keyword agreement
    elif OBJ_TO_MODULE.get(top_obj) == folder_module and conf != "high":
        conf = "high"  # keyword and folder agree -> trust it

    domain = next((d for d in meta["domains"] if d.split(".")[0] == top_obj.split(".")[0]), "")
    module = OBJ_TO_MODULE.get(top_obj, folder_module)
    if top_obj != keyword_winner:
        reasoning = (f"objective {top_obj} via folder-module tiebreak "
                     f"(keyword winner {keyword_winner} disagreed with folder module {folder_module})")
    else:
        reasoning = f"top objective {top_obj} (score {top_score:.1f} vs 2nd {second_score:.1f})"
    return {"domain": domain, "objective": top_obj, "module": module,
            "confidence": conf, "reasoning": reasoning}


# objective -> module. Single-valued mapping (P4a). Split objectives resolve to
# their most common module; classification confidence + folder tiebreak handle
# the ambiguous ones.
OBJ_TO_MODULE = {
    "1.1": "9.0", "1.2": "9.0", "1.3": "9.0",
    "2.1": "6.0", "2.2": "5.0", "2.3": "7.0", "2.4": "6.0", "2.5": "5.0",
    "2.6": "6.0", "2.7": "5.0", "2.8": "5.0",
    "3.1": "2.0", "3.2": "2.0", "3.3": "3.0", "3.4": "3.0", "3.5": "2.0",
    "3.6": "3.0", "3.7": "10.0", "3.8": "10.0",
    "4.1": "8.0", "4.2": "8.0",
    "5.1": "4.0", "5.2": "4.0", "5.3": "4.0", "5.4": "9.0", "5.5": "7.0", "5.6": "10.0",
}


# ---------------------------------------------------------------------------
# Dedup + validation (unchanged)
# ---------------------------------------------------------------------------
def tokens(stem):
    return set(w for w in re.sub(r"[^a-z0-9 ]", " ", (stem or "").lower()).split() if w)


def jaccard(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def validate_question(q, meta):
    errs = []
    if q["domain"] not in meta["domains"]:
        errs.append("domain not a valid domainWeights key")
    if q["objective"] not in meta["objectives"]:
        errs.append("objective not a valid objectives key")
    if q["module"] not in meta["modules"]:
        errs.append("module not a valid modules key")
    if q["objective"].split(".")[0] != q["domain"].split(".")[0]:
        errs.append("objective domain-prefix does not match domain")
    if q["type"] not in ("mc", "multi", "drag_drop"):
        errs.append("type not one of mc/multi/drag_drop")
    if q["type"] in ("mc", "multi"):
        if not isinstance(q["correctAnswer"], list):
            errs.append("correctAnswer must be an array for mc/multi")
        else:
            for a in q["correctAnswer"]:
                if a not in q["options"]:
                    errs.append(f'correctAnswer "{a}" not in options')
    if not (q.get("stem") or "").strip():
        errs.append("stem is empty")
    if not isinstance(q.get("options"), list) or len(q["options"]) < 2:
        errs.append("options has fewer than 2 entries")
    if not isinstance(q.get("source"), str) or not q["source"].strip():
        errs.append("source is empty or not a string")
    return errs


# ---------------------------------------------------------------------------
# Per-folder processing
# ---------------------------------------------------------------------------
def process_folder(folder, meta, obj_index, existing_stems, batch_seen,
                   id_counter, threshold, debug_dir):
    """OCR + parse + classify + dedup + validate one folder. Returns output dict."""
    name = folder["name"]
    folder_module = folder["module"]
    result = {
        "source": {"folder": name, "moduleFromFolder": folder_module,
                   "totalImages": len(folder["images"]), "totalQuestionsFound": 0,
                   "questionsKept": 0, "duplicatesSkipped": 0, "imagesSkipped": 0,
                   "errors": 0},
        "questions": [], "duplicates": [], "errors": [], "skipped": [], "mismatches": [],
    }

    raw_items = []  # (imageFile, parsed question dict)
    for img in folder["images"]:
        try:
            im = preprocess(img, threshold)
            text = ocr_image(im)
            if debug_dir:
                dbg = debug_dir / sanitize_folder(name)
                dbg.mkdir(parents=True, exist_ok=True)
                im.save(dbg / (img.stem + "_pre.png"))
                (dbg / (img.stem + "_ocr.txt")).write_text(text, encoding="utf-8")
            if len(text.strip()) < MIN_OCR_CHARS:
                result["errors"].append({"imageFile": img.name,
                    "reason": f"OCR returned <{MIN_OCR_CHARS} chars (image likely unreadable)"})
                continue
            parsed, had_header = parse_questions(text)
            if not parsed:
                if not had_header:
                    # No 'Question N' on the page: a score/URL/copyright/etc. page.
                    # Not an error — just nothing to extract.
                    result["skipped"].append({"imageFile": img.name,
                        "reason": "no question on page (non-question content)"})
                else:
                    # A question header was present but parsing failed: a real error.
                    result["errors"].append({"imageFile": img.name,
                        "reason": "question header found but no options parsed",
                        "rawOcr": text[:500]})
                continue
            for q in parsed:
                raw_items.append((img.name, q))
        except Exception as e:
            result["errors"].append({"imageFile": img.name, "reason": str(e)[:200]})

    result["source"]["totalQuestionsFound"] = len(raw_items)
    result["source"]["errors"] = len(result["errors"])
    result["source"]["imagesSkipped"] = len(result["skipped"])
    if not raw_items:
        return result

    for img_name, q in raw_items:
        stem = q.get("stem", "")

        # dedup vs existing bank + within batch
        best_id, best_score = None, 0.0
        for ex_id, ex_stem in existing_stems:
            s = jaccard(stem, ex_stem)
            if s > best_score:
                best_id, best_score = ex_id, s
        for seen_id, seen_stem in batch_seen:
            s = jaccard(stem, seen_stem)
            if s > best_score:
                best_id, best_score = seen_id, s
        if best_score >= DUP_THRESHOLD:
            result["duplicates"].append({
                "imageFile": img_name, "stemPreview": stem[:80],
                "matchedId": best_id, "similarity": round(best_score, 3)})
            continue

        cls = classify_question(q, meta, obj_index, folder_module)
        # Sequential ID continuing from the bank's max (e.g. 1201-716), one
        # continuous counter across all folders. No zero padding.
        qid = f"1201-{next(id_counter)}"

        # Field order matches the production schema:
        # id, domain, objective, module, type, difficulty, stem, options,
        # correctAnswer, explanation, source, classification.
        qobj = {
            "id": qid,
            "domain": cls["domain"],
            "objective": cls["objective"],
            "module": cls["module"],
            "type": q.get("questionType", "mc"),
            "difficulty": "medium",
            "stem": stem,
            "options": q.get("options", []),
            "correctAnswer": q.get("correctAnswer", []),
            "explanation": q.get("explanation", ""),
            "source": "certmaster",
            "classification": {"confidence": cls["confidence"], "reasoning": cls["reasoning"]},
        }

        v = validate_question(qobj, meta)
        if v:
            qobj["validationErrors"] = v

        # manual-review flag: empty correctAnswer, <3 options, low confidence, or
        # any OCR parse flag.
        review_reasons = list(q.get("_flags", []))
        if not qobj["correctAnswer"]:
            review_reasons.append("empty correctAnswer")
        if len(qobj["options"]) < MIN_OPTIONS:
            review_reasons.append(f"fewer than {MIN_OPTIONS} options")
        if cls["confidence"] == "low":
            review_reasons.append("low classification confidence")
        if review_reasons:
            qobj["needsReview"] = True
            qobj["reviewReasons"] = sorted(set(review_reasons))

        if cls["module"] and cls["module"] != folder_module:
            result["mismatches"].append({
                "id": qid, "folderModule": folder_module,
                "contentModule": cls["module"], "reason": cls["reasoning"]})

        result["questions"].append(qobj)
        batch_seen.append((qid, stem))

    result["source"]["questionsKept"] = len(result["questions"])
    result["source"]["duplicatesSkipped"] = len(result["duplicates"])
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Extract CertMaster quiz questions from JPGs via Tesseract OCR.")
    ap.add_argument("--source", required=True)
    ap.add_argument("--output", default="exam_assets/")
    ap.add_argument("--bank", default="exam_assets/questions.json")
    ap.add_argument("--tesseract-path", default=None,
                    help="path to tesseract.exe (auto-detected if on PATH)")
    ap.add_argument("--workers", type=int, default=10,
                    help="parallel folder workers (OCR is CPU-bound)")
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                    help="binarization threshold 0-255 (default 160)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--folder", default=None, help="glob to limit folders (e.g. '5.1*')")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--debug", action="store_true",
                    help="save preprocessed images + raw OCR text under <output>/debug/")
    args = ap.parse_args()

    if not _HAVE_PIL:
        print("ERROR: Pillow is not installed. Run: pip install -r tools/requirements_extract.txt", file=sys.stderr)
        sys.exit(2)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = (out_dir / "debug") if args.debug else None

    # Load bank: metadata + existing stems for dedup.
    bank = json.loads(Path(args.bank).read_text(encoding="utf-8"))
    core1 = bank["exams"]["220-1201"]
    meta = {
        "domains": list(core1["domainWeights"].keys()),
        "objectives": dict(core1["objectives"]),
        "modules": dict(core1["modules"]),
    }
    obj_index = build_objective_index(meta)
    existing_stems = [(q["id"], q.get("stem", "")) for q in core1["questionBank"]]

    # Highest numeric ID suffix in the Core 1 bank; extracted IDs continue from it.
    # (Robust to ids like "1201-715" and any "prefix-...-NNN" shape: take the last
    #  hyphen segment that parses as an int.)
    max_id = 0
    for q in core1["questionBank"]:
        parts = str(q.get("id", "")).split("-")
        try:
            max_id = max(max_id, int(parts[-1]))
        except (ValueError, IndexError):
            continue
    next_id_start = max_id + 1

    # Discover.
    folders = discover(args.source)
    if args.folder:
        import fnmatch
        folders = [f for f in folders if fnmatch.fnmatch(f["name"], args.folder)]
    total_images = sum(len(f["images"]) for f in folders)
    print(f"Discovered {len(folders)} folder(s), {total_images} image(s).")
    est_min = (total_images * 3) / max(args.workers, 1) / 60  # ~3s/image OCR
    print(f"Rough estimate: ~{est_min:.1f} min with {args.workers} workers.")

    # Tesseract availability check (after discovery so --help/inventory still work).
    if not _HAVE_TESS:
        print("ERROR: pytesseract is not installed. Run: pip install -r tools/requirements_extract.txt", file=sys.stderr)
        sys.exit(2)
    if args.tesseract_path:
        pytesseract.pytesseract.tesseract_cmd = args.tesseract_path
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        print("ERROR: the Tesseract OCR engine was not found.\n"
              "  Windows: install from https://github.com/UB-Mannheim/tesseract/wiki\n"
              "  Default path: C:\\Program Files\\Tesseract-OCR\\tesseract.exe\n"
              "  Then add it to PATH or pass --tesseract-path.", file=sys.stderr)
        sys.exit(2)

    id_counter = iter(range(next_id_start, next_id_start + 1_000_000))
    print(f"Continuing extracted IDs from 1201-{next_id_start} (bank max {max_id}).")
    batch_seen = []  # cross-folder dedup within this run
    summary = {
        "totalFolders": len(folders), "totalImages": total_images,
        "totalQuestionsFound": 0, "totalQuestionsKept": 0,
        "totalDuplicatesSkipped": 0, "totalImagesSkipped": 0, "totalErrors": 0,
        "totalNeedsReview": 0,
        "processingTimeSeconds": 0.0, "averageSecondsPerImage": 0.0,
        "confidence": {"high": 0, "medium": 0, "low": 0},
        "perModule": {}, "perFolder": [], "validationFailures": [],
    }

    def bump_module(mod, kept, dupes, errs):
        m = summary["perModule"].setdefault(mod, {"kept": 0, "duplicates": 0, "errors": 0})
        m["kept"] += kept
        m["duplicates"] += dupes
        m["errors"] += errs

    start = time.time()
    interrupted = False
    for folder in tqdm(folders, desc="folders", total=len(folders)):
        out_file = out_dir / f"extracted_{sanitize_folder(folder['name'])}.json"
        if out_file.exists() and not args.force:
            print(f"  skip (cached): {out_file.name}")
            continue
        try:
            result = process_folder(folder, meta, obj_index, existing_stems,
                                     batch_seen, id_counter, args.threshold, debug_dir)
        except KeyboardInterrupt:
            interrupted = True
            print("\nInterrupted — writing completed folders and exiting.", file=sys.stderr)
            break

        src = result["source"]
        summary["totalQuestionsFound"] += src["totalQuestionsFound"]
        summary["totalQuestionsKept"] += src["questionsKept"]
        summary["totalDuplicatesSkipped"] += src["duplicatesSkipped"]
        summary["totalImagesSkipped"] += src.get("imagesSkipped", 0)
        summary["totalErrors"] += src["errors"]
        bump_module(folder["module"], src["questionsKept"],
                    src["duplicatesSkipped"], src["errors"])
        summary["perFolder"].append({
            "folder": folder["name"], "images": src["totalImages"],
            "found": src["totalQuestionsFound"], "kept": src["questionsKept"],
            "dupes": src["duplicatesSkipped"], "skipped": src.get("imagesSkipped", 0),
            "errors": src["errors"]})
        for q in result["questions"]:
            summary["confidence"][q["classification"]["confidence"]] += 1
            if q.get("needsReview"):
                summary["totalNeedsReview"] += 1
            for rule in q.get("validationErrors", []):
                summary["validationFailures"].append(
                    {"id": q["id"], "rule": rule, "detail": q["stem"][:80]})

        if not args.dry_run:
            out_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    elapsed = time.time() - start
    summary["processingTimeSeconds"] = round(elapsed, 1)
    done_images = sum(pf["images"] for pf in summary["perFolder"]) or 1
    summary["averageSecondsPerImage"] = round(elapsed / done_images, 2)
    if not args.dry_run:
        (out_dir / "extraction_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    # Report
    print("\n=== EXTRACTION REPORT ===")
    print(f"Folders: {len(summary['perFolder'])}  Images: {summary['totalImages']}  "
          f"Found: {summary['totalQuestionsFound']}  Kept: {summary['totalQuestionsKept']}  "
          f"Dupes: {summary['totalDuplicatesSkipped']}  Skipped: {summary['totalImagesSkipped']}  "
          f"Errors: {summary['totalErrors']}")
    print("Per module (module: kept / dupes / errors):")
    for mod in sorted(summary["perModule"], key=lambda k: float(k.split(".")[0])):
        m = summary["perModule"][mod]
        print(f"  {mod:>4}  {m['kept']:>3} / {m['duplicates']:>3} / {m['errors']:>3}")
    print(f"Classification confidence: high={summary['confidence']['high']} "
          f"medium={summary['confidence']['medium']} low={summary['confidence']['low']}")
    print(f"Needs manual review: {summary['totalNeedsReview']}")
    print(f"Processing time: {summary['processingTimeSeconds']}s "
          f"({summary['averageSecondsPerImage']}s/image)")
    if summary["validationFailures"]:
        print(f"Validation failures: {len(summary['validationFailures'])}")
        for vf in summary["validationFailures"][:20]:
            print(f"  {vf['id']}: {vf['rule']} — {vf['detail']}")
    if debug_dir:
        print(f"Debug output: {debug_dir}")
    if interrupted:
        print("(run was interrupted; partial output written)")


if __name__ == "__main__":
    main()

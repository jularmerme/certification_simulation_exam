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
# An option line begins with a single letter A-H, optionally wrapped/punctuated
# ("A.", "A)", "(A)", "A:") OR just "A " with no punctuation (common in OCR of
# CertMaster pages), followed by the option text. Bullet markers also count.
# Requiring 2+ following chars avoids matching a stray capital at line start.
OPTION_RE = re.compile(r"^\s*(?:\(?([A-Ha-h])\)?[\.\):]?\s+|[•\-\*]\s+)(\S.{1,})$")
QUESTION_HDR_RE = re.compile(r"^\s*Question\s+(\d+)\s*[:\.]?\s*(.*)$", re.IGNORECASE)
CORRECT_TOKEN_RE = re.compile(r"\b(correct|✓|✔)\b", re.IGNORECASE)


def clean_text(s):
    """Trim OCR noise: pipes, stray single chars, collapse whitespace."""
    s = s.replace("|", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # drop leading stray artifact chars like "© " or "= " if present
    s = re.sub(r"^[^\w(]+", "", s)
    return s.strip()


def split_question_blocks(raw):
    """Split OCR text into blocks, one per 'Question N' header.
    Falls back to a single block if no headers are found."""
    lines = raw.splitlines()
    blocks, current, header = [], [], None
    for line in lines:
        m = QUESTION_HDR_RE.match(line)
        if m:
            if current or header is not None:
                blocks.append((header, current))
            header = m.group(1)
            current = []
            trailing = m.group(2).strip()
            if trailing:
                current.append(trailing)
        else:
            current.append(line)
    if current or header is not None:
        blocks.append((header, current))
    if not blocks:
        blocks = [(None, lines)]
    return blocks


def find_correct_answers(block_lines, options, explanation):
    """Detect correct option(s) via a priority fallback chain.
    Returns (list_of_option_texts, found_bool)."""
    correct = []

    # Priority 1: an explicit 'Correct' / checkmark marker on an option line.
    for line in block_lines:
        m = OPTION_RE.match(line)
        if m and CORRECT_TOKEN_RE.search(line):
            txt = clean_text(re.sub(CORRECT_TOKEN_RE, "", m.group(2)))
            for opt in options:
                if txt and (opt.lower().startswith(txt.lower()[:20]) or txt.lower().startswith(opt.lower()[:20])):
                    if opt not in correct:
                        correct.append(opt)
    if correct:
        return correct, True

    expl = (explanation or "").lower()

    # Priority 2: "correct answer is X" / "X is correct".
    for opt in options:
        ol = opt.lower()
        if f"correct answer is {ol}" in expl or f"{ol} is correct" in expl or f"{ol} is the correct" in expl:
            if opt not in correct:
                correct.append(opt)
    if correct:
        return correct, True

    # Priority 3: "X because ..." pattern where X is an option (explanation opens
    # by naming the correct option).
    for opt in options:
        ol = re.escape(opt.lower())
        if re.search(rf"^{ol}\b.*\bbecause\b", expl) or re.search(rf"\b{ol}\b[^.]*\bbecause\b", expl[:120]):
            if opt not in correct:
                correct.append(opt)
    if correct:
        return correct, True

    # Priority 4: give up — caller flags for manual review.
    return [], False


def parse_questions(raw):
    """Parse OCR text into a list of question dicts.
    Each dict: stem, options, correctAnswer, explanation, questionType,
    plus a private _flags list for review reasons."""
    results = []
    for _hdr, block_lines in split_question_blocks(raw):
        opt_indices = [i for i, ln in enumerate(block_lines) if OPTION_RE.match(ln)]
        if len(opt_indices) < 2:
            # Fallback: numbered lines (1. 2. 3.) as options
            numbered = [(i, ln) for i, ln in enumerate(block_lines)
                        if re.match(r"^\s*\d+[\.\)]\s+\S", ln)]
            if len(numbered) >= 2:
                opt_indices = [i for i, _ in numbered]
            else:
                # no parseable options; skip this block (caller logs if whole
                # image yields nothing)
                continue

        first_opt = opt_indices[0]
        stem = clean_text(" ".join(block_lines[:first_opt]))

        # explanation begins after an "Explanation" marker if present, else after
        # the last option line.
        last_opt = opt_indices[-1]
        expl_start = None
        for i in range(first_opt, len(block_lines)):
            if re.match(r"^\s*explanation\b", block_lines[i], re.IGNORECASE):
                expl_start = i
                break
        if expl_start is None:
            expl_start = last_opt + 1

        options = []
        for oi in opt_indices:
            if oi >= expl_start:
                break
            m = OPTION_RE.match(block_lines[oi])
            body = m.group(2) if m else block_lines[oi]
            # option text may continue onto following lines until the next option
            nxt = [j for j in opt_indices if j > oi]
            end = min(nxt[0], expl_start) if nxt else expl_start
            cont = " ".join(block_lines[oi + 1:end])
            opt_text = clean_text((body + " " + cont))
            # strip a trailing 'Correct' word from the visible option
            opt_text = clean_text(re.sub(CORRECT_TOKEN_RE, "", opt_text))
            if opt_text:
                options.append(opt_text)

        expl_lines = block_lines[expl_start:]
        if expl_lines and re.match(r"^\s*explanation\b", expl_lines[0], re.IGNORECASE):
            expl_lines = [re.sub(r"^\s*explanation\b[:\s]*", "", expl_lines[0], flags=re.IGNORECASE)] + expl_lines[1:]
        explanation = clean_text(" ".join(expl_lines))

        correct, found = find_correct_answers(block_lines, options, explanation)
        qtype = "multi" if len(correct) > 1 else "mc"
        if re.search(r"\bdrag\b|\bdrop\b|match each", (stem + " " + raw).lower()):
            qtype = "drag_drop"

        flags = []
        if not found:
            flags.append("correctAnswer not detected by OCR")
        if len(options) < MIN_OPTIONS:
            flags.append(f"only {len(options)} options parsed (<{MIN_OPTIONS})")
        if len(options) > MAX_OPTIONS:
            flags.append(f"{len(options)} options parsed (>{MAX_OPTIONS})")

        if stem:
            results.append({
                "stem": stem, "options": options, "correctAnswer": correct,
                "explanation": explanation, "questionType": qtype, "_flags": flags,
            })

    # Step: drop OCR-stuttered duplicate stems within the same image.
    seen, deduped = set(), []
    for q in results:
        key = q["stem"].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(q)
    return deduped


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
                   "questionsKept": 0, "duplicatesSkipped": 0, "errors": 0},
        "questions": [], "duplicates": [], "errors": [], "mismatches": [],
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
            parsed = parse_questions(text)
            if not parsed:
                result["errors"].append({"imageFile": img.name,
                    "reason": "no questions parsed", "rawOcr": text[:500]})
                continue
            for q in parsed:
                raw_items.append((img.name, q))
        except Exception as e:
            result["errors"].append({"imageFile": img.name, "reason": str(e)[:200]})

    result["source"]["totalQuestionsFound"] = len(raw_items)
    result["source"]["errors"] = len(result["errors"])
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
        qid = f"1201-IMG-{next(id_counter):03d}"

        qobj = {
            "id": qid, "domain": cls["domain"], "objective": cls["objective"],
            "module": cls["module"], "type": q.get("questionType", "mc"),
            "stem": stem, "options": q.get("options", []),
            "correctAnswer": q.get("correctAnswer", []),
            "explanation": q.get("explanation", ""),
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

    id_counter = iter(range(1, 100_000))
    batch_seen = []  # cross-folder dedup within this run
    summary = {
        "totalFolders": len(folders), "totalImages": total_images,
        "totalQuestionsFound": 0, "totalQuestionsKept": 0,
        "totalDuplicatesSkipped": 0, "totalErrors": 0,
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
        summary["totalErrors"] += src["errors"]
        bump_module(folder["module"], src["questionsKept"],
                    src["duplicatesSkipped"], src["errors"])
        summary["perFolder"].append({
            "folder": folder["name"], "images": src["totalImages"],
            "found": src["totalQuestionsFound"], "kept": src["questionsKept"],
            "dupes": src["duplicatesSkipped"], "errors": src["errors"]})
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
          f"Dupes: {summary['totalDuplicatesSkipped']}  Errors: {summary['totalErrors']}")
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

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
from difflib import SequenceMatcher

# --- optional / required deps: degrade gracefully --------------------------
try:
    from PIL import Image, ImageEnhance, ImageOps
    _HAVE_PIL = True
except ImportError:
    _HAVE_PIL = False

try:
    import pytesseract
    # Point pytesseract at the local Tesseract engine so live runs work without
    # requiring the engine to be on the system PATH. (--tesseract-path still
    # overrides this at runtime if a different location is needed.)
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
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
# ===========================================================================
# CertMaster "Individual Response" pages use several distinct option layouts.
# The FULL inventory of real Tesseract artifacts observed across 501 images:
#
#   RADIO, unselected (wrong, single-select):
#     "(C) A text"  "(C) text"  "(C). text"  "(C)) text"  "(C)_ text"
#     "O text"  "0 text"  "oO text"  "QO text"  "Q text"  "re) text"
#     ((C) = the copyright char ©; (R) = the registered char ®)
#   RADIO, selected (student's answer):
#     "@ text"  "@(C) text"  "@(R) text"  "@ (C) text"
#   CHECKBOX, unchecked (wrong, multi-select):
#     "[_] text"  "(] text"  "(]_ text"  "(J text"  "L] text"  "L)_ text"
#     "[J text"  "LD text"  "(# text"  "Ol text"  "Lj text"  "[ text"
#   CHECKBOX, checked (correct, multi-select):
#     "[] text"  or an icon-less line ending in a Correct marker.
#
#   CORRECT markers (end of the option's line):
#     "Y Correct" "y Correct" "/ Correct" "\\/ Correct" "./ Correct"
#     "JY Correct" "VY Correct" and the bare word "Correct".
#   INCORRECT markers: "X Incorrect" "XX Incorrect" "X_ Incorrect".
#   HEADER status: "Question N (C) Correct" / "Question N X Incorrect"
#     / "Question N -- Partial" (em dash / double hyphen).
#
# Three detection modes are tried in order (A lettered, B letterless radio,
# C checkbox), then a loose fallback for icon-less/number options (e.g. voltage
# lists "12 / 24 / 15 ..."). Whichever finds >= 2 options wins.
# ---------------------------------------------------------------------------

# Icon character class shared by several patterns. Includes the copyright/
# registered glyphs Tesseract emits for radio circles, plus the bracket/paren/
# L glyphs it emits for checkboxes.
_ICON_CHARS = r"@©®()\[\]{}Ll\u2022\u2013\u2014*#/\\_JD"

# --- correct / incorrect markers (trailing suffix on an option line) --------
# The garbled check glyph that can precede "Correct". Real variants observed:
#   Y  y  / \/ ./ JY  VY  Y/  and the smart quotes " " ' ' (U+201C/D, U+2018/9)
#   plus the true check marks (U+2713/4). Built once and reused below.
# A standalone glyph token (space- or start-anchored) so a real word's trailing
# letter (e.g. "they") isn't mistaken for a "Y Correct" marker.
_CHECK_GLYPH = (r"(?:(?<=\s)|(?<=^))(?:[YyJjVv]{1,3}[/\\.]*"
                r"|[/\\.]+|[\u2713\u2714\u201c\u201d\u2018\u2019]+)")
# Correct: an optional garbled check glyph + "Correct", OR the bare word "Correct"
# at end of line. Anchored to end-of-string.
CORRECT_MARKER_RE = re.compile(
    r"\s*" + _CHECK_GLYPH + r"*\s*correct\s*$", re.IGNORECASE)
# A stricter test used to DECIDE correctness (must have a check-glyph OR the bare
# word "correct" as a standalone trailing token — avoids matching "...is correct"
# mid-sentence, which is handled by trimming only end-of-line).
CORRECT_DECIDE_RE = re.compile(
    _CHECK_GLYPH + r"\s*correct\s*$"
    r"|(?<![A-Za-z])correct\s*$",
    re.IGNORECASE)
# Incorrect: "X" / "XX" / "X_" + "Incorrect".
INCORRECT_MARKER_RE = re.compile(r"\s*[Xx]+_?\s*incorrect\s*$", re.IGNORECASE)
# Combined stripper: remove any trailing correct/incorrect marker from text.
ANY_MARKER_RE = re.compile(
    r"\s*(?:" + _CHECK_GLYPH + r"|[Xx]+_?)*\s*(?:in)?correct\s*$",
    re.IGNORECASE)

# --- question header --------------------------------------------------------
# "Question N" + optional icon glyphs + optional status word.
# Group 1 = number; group 2 = status (correct/incorrect/partial); group 3 = the
# residual text on the line (rare). The status word is matched explicitly so its
# leading letter is fully consumed and never leaks into the stem.
QUESTION_HDR_RE = re.compile(
    r"^\s*Question\s+(\d+)\b"
    r"[\s@©®()\[\]Xx/\\.\u2013\u2014\u2713\u2714-]*"
    r"(correct|incorrect|partial)?\b\s*(.*)$",
    re.IGNORECASE)

# --- Format A: lettered options (icon + letter A-H + text) ------------------
_ICON_A = r"[@©®()oO0Qq\u2022\-\*]"
_OPT_CORE = (r"(?:@\s*" + _ICON_A + r"*\s*([A-Ha-h\u00a28])"   # (a) selected
             r"|" + _ICON_A + r"+\s*([A-Ha-h\u00a28])"          # (b) unselected icon
             r"|([A-H8]))")                                     # (c) bare uppercase
OPTION_RE = re.compile(r"^\s*(@)?\s*" + _OPT_CORE + r"[\._:\)\-]*\s+(\S.*)$")
OPTION_BARE_RE = re.compile(r"^\s*(@)?\s*" + _OPT_CORE + r"[\._:\)\-]*\s*$")

# --- Format D: icon + bare letter label (A-H), NO punctuation (Modules 5-10) -
# A REQUIRED radio icon, then a single letter label A-H, then the option text.
# The icon requirement is what distinguishes this from a stem line that merely
# starts with a capital ("A user ..."), which Format A's bare-letter branch wrongly
# ate. Real icon variants: © @ ® and combinations @© @® @©® ®, plus circle O / 0.
# After the letter, OCR often glues a garbled char (_ ¢ € .) which is discarded.
#   group 1 = '@' (or other selected glyph) -> selected
#   group 2 = the letter label
#   group 3 = the option text
_ICON_D = r"(?:@[©®\u00a9\u00ae8]*|[©®\u00a9\u00ae]+|[O0])"
# The letter label: A-H, or a glyph Tesseract emits for one (¢=C, €=E), optionally
# with a garbled duplicate (e.g. "cC"). The whole label is stripped from the text.
_LETTER_D = r"([A-Ha-h\u00a2\u20ac])[A-Ha-h\u00a2\u20ac]?"
OPTION_D_RE = re.compile(
    r"^\s*(@)?\s*" + _ICON_D + r"\s*"
    + _LETTER_D +
    r"(?:"
    r"[.\)\u00a2\u20ac]?\s+(\S.*)"      # letter, optional garble, SPACE, text
    r"|_\s*(\S.*)"                       # letter '_' glued to text ("A_uSATA")
    r")$")
# A bare "icon + letter" with the text on the NEXT line (multi-line Format D).
OPTION_D_BARE_RE = re.compile(
    r"^\s*(@)?\s*" + _ICON_D + r"\s*" + _LETTER_D +
    r"(?:[_\u00a2\u20ac.\)]|\s*[_\u00a2\u20ac])?\s*$")

# --- Format B: letterless radio (icon + text, no letter) --------------------
# A distinctive radio glyph, optionally combined (@©, @®, ©), ©., re)), then text.
# The bare circle letters o/O/0/Q only count as an icon when followed by a
# space/underscore so real words ("Open", "Overload") are not eaten.
_ICON_STRONG = r"[@©®\u2022]"
# Two shapes:
#   (1) a leading '@' (selected) followed by whitespace, then optional extra glyph
#       + the text — covers "@ Heatsink", "@© Have you", "@® Modular", "@(R) ...".
#   (2) no '@': a distinctive radio glyph / garbled circle / "(C)" then text.
OPTION_B_RE = re.compile(
    r"^\s*(?:"
    r"(@)\s*[@©®()_.\s\u2022]*"                          # (1) selected '@ ...'
    r"|(6)\s+(?=[A-Z])"                                  # (1b) digit-6 = misread '@'
    r"|" + _ICON_STRONG + r"[@©®()_.\s\u2022]*"          # (2a) strong radio glyph(s)
    r"|re\)\s+"                                          # (2b) 're)' garbled radio
    r"|[QO0][QO0]?[_\s]+"                                 # (2c) circle letter (QO/OQ) + sep
    r"|\(\s*[CR]\s*\)[._)\s]*"                           # (2d) '(C)' / '(R)' text
    r")\s*(\S.*)$")

# --- Format C: checkbox (multi-select) --------------------------------------
# Checkbox glyphs Tesseract emits: [] [_] (] (]_ (J L] L)_ [J LD Lj [ ( and a
# leading Ol / (# garble. Requires either a following space, or an immediate
# capital letter (e.g. "[An", "(J A...") since checkbox text often abuts.
CHECKBOX_RE = re.compile(
    r"^\s*(?:"
    r"\[\s*\]"                     # []  (checked)
    r"|\[\s*_\s*\]"               # [_]
    r"|\[\s*[Jj]\s*\]?"           # [J  [J]
    r"|\[\s*[A-Z]?"               # [   [An...
    r"|\(\s*\]_?"                 # (]  (]_
    r"|\(\s*[Jj]\b"               # (J
    r"|[Ll]\s*\]"                 # L]
    r"|[Ll]\s*\)_?"               # L)  L)_
    r"|[Ll][Jj]\b"                # Lj
    r"|[Ll][Dd]\b"                # LD
    r"|\(\s*#"                    # (#
    r"|O[Il1]\b"                  # Ol / OI / O1
    r"|in\]"                      # in]  (garbled checkbox)
    r"|\(\s*_\s*\]"               # (_]  (Patch 7)
    r"|\[\s*_\s*\)"               # [_)  (Patch 7)
    r"|\(\s*-\s*\)"               # (-)  (Patch 7)
    r"|\(\s*_\s*\)"               # (_)  (Patch 7)
    r"|\(\s*\)"                   # ()   (Patch 7, empty parens = OCR'd empty box)
    r")[\s._|]*(\S.*)$")
# Does the line merely LOOK like it starts with a checkbox glyph? (used for
# continuation detection — a continuation must NOT start a new option).
CHECKBOX_LEAD_RE = re.compile(
    r"^\s*(?:\[|\(\s*[\]Jj#_)-]|[Ll]\s*[\])JjDd]|O[Il1]\b)")

# Lines that terminate the option region / start the explanation-or-metadata tail.
_STOP_RE = re.compile(
    r"^\s*(?:explanation\b|related\s+content\b|resources[\\/]|https?://|hitps://"
    r"|copyright\b)", re.IGNORECASE)

# "(Select two)" / "(Select three)" etc. in the stem => multi-select checkbox.
SELECT_N_RE = re.compile(r"\(\s*select\s+(two|three|four|\d+)\b", re.IGNORECASE)

# --- metadata / boilerplate lines dropped before parsing --------------------
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
    re.compile(r"resources[\\/]questions[\\/]", re.IGNORECASE),
    re.compile(r"^\s*\.\s*$"),                             # lone dot artifact line
    re.compile(r"^\s*\d+\s*$"),                            # lone page number
    re.compile(r"^\s*\d+/\d+\s*$"),                        # "3/3" page indicator
    # Lesson cross-references at end of a Related Content block:
    #   "(B) 3.1.4 ..."  "B) 3.1.4 ..."  "5) 3.1.4 ..."  "BS) ..."  "(3 3.1.4 ..."
    #   "85) 3.1.5 ..."  "(GB 3.1.4 ..."  — a short garbled bullet then "N.N.N text".
    re.compile(r"^\s*(?:\(?[A-Z0-9]{1,3}\)?|\(GB|\(3)\s+\d+\.\d+\.\d+\b", re.IGNORECASE),
    # Timestamp header: "1/19/26, 11:13 PM" (with or without trailing text).
    re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}\s*(AM|PM)?", re.IGNORECASE),
]


def strip_metadata(raw):
    """Drop CertMaster header/footer boilerplate lines."""
    kept = []
    for line in raw.splitlines():
        if any(r.search(line) for r in _META_RES):
            continue
        kept.append(line)
    return "\n".join(kept)


def clean_text(s):
    """Trim OCR noise: pipes, stray leading artifact chars, collapse whitespace."""
    s = s.replace("|", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # drop leading stray artifact chars like "© " or "= " if present, but keep a
    # leading '(' (real content like "(PSU)" or "(Select two)").
    s = re.sub(r"^[^\w(]+", "", s)
    return s.strip()


def _strip_leading_icons(s):
    """Remove any run of leading icon/checkbox glyphs + separators from option text."""
    prev = None
    while prev != s:
        prev = s
        # Note: bare circle letters (Q/O/0) only count as an icon when followed by a
        # separator, so real words like "Open"/"Overload" keep their leading letter.
        s = re.sub(
            r"^\s*(?:@|\(\s*[CR]\s*\)|©|®|re\)|\[\s*[_JjA-Z]?\s*\]?|\(\s*[\]Jj#]?"
            r"|[Ll]\s*[\])JjDd]|O[Il1]\b|[QO0](?=[._):|\s])|\u2022)[._):|\s]*",
            "", s)
    return s.strip()


def _fix_ocr_words(s):
    """Fix known OCR word-merges/artifacts in option/stem text."""
    fixes = [
        (r"\bAuser\b", "A user"),
        (r"\bandis\b", "and is"),
        (r"\bToinstail\b", "To install"),
        (r"\btoa\b", "to a"),
        (r"\bwiil\b", "will"),
        (r"\bvoitage\b", "voltage"),
        (r"\bWattrating\b", "Watt rating"),
        (r"\bTestthesolution\b", "Test the solution"),
        (r"\bToenable\b", "To enable"),
        (r"\b7-pinconnector\b", "7-pin connector"),
        (r"\bSecureboot\b", "Secure boot"),
        (r"\bDisabie\b", "Disable"),
        (r"\b480Mbps\b", "480 Mbps"),
        # Module 9 merges/artifacts.
        (r"\bResourceusage\b", "Resource usage"),
        (r"\bDustanddebris\b", "Dust and debris"),
        (r"\bCloudSynchronization\b", "Cloud Synchronization"),
        (r"\bConfigure anaccount\b", "Configure an account"),
        (r"\bnon-tech-sawvy\b", "non-tech-savvy"),
        (r"\bcalted\b", "called"),
        # Module 6 (networking) merges/artifacts.
        (r"\bHostID\b", "Host ID"),
        (r"\bThelPv6\b", "The IPv6"),
        (r"\bnetworkID\b", "network ID"),
        (r"\bTransportLayer\b", "Transport Layer"),
        (r"\bPTRRecord\b", "PTR Record"),
        (r"\bCNAMERecord\b", "CNAME Record"),
        (r"\bARecord\b", "A Record"),
        (r"\bAAAARecord\b", "AAAA Record"),
        (r"\bMXRecord\b", "MX Record"),
        (r"Protocol\(UDP\)", "Protocol (UDP)"),
        (r"\bAnRG6\b", "An RG6"),
        (r"\bAwireless\b", "A wireless"),
        (r"\bAlaptop\b", "A laptop"),
        (r"\bAUSB\b", "A USB"),
        (r"\bAkeyboard\b", "A keyboard"),
        (r"\b35inch\b", "3.5 inch"),
        (r"\b95mm\b", "9.5mm"),
        (r"\bWiFi\b", "Wi-Fi"),       # 'WiFi' -> 'Wi-Fi' ('Wi-Fi' already lacks \bWiFi\b)
        (r"\bAX\b", "ATX"),          # 3.1 Q4 'AX' / Q15 'AMX' -> ATX form factor
        # --- Modules 1-4 OCR misreads (diagnostic scan, Sep 2026) ---
        (r"\bRAIDO\b", "RAID 0"),
        (r"\bRAIDS\b", "RAID 5"),
        (r"\bRAID1\b", "RAID 1"),
        (r"\bPCle\b", "PCIe"),
        (r"\bDVi\b", "DVI"),
        (r"\bUVEFL\b", "UEFI"),
        (r"\bBIOs2\b", "BIOS"),
        (r"\bBIOs\b", "BIOS"),
        (r"\bcmos\b", "CMOS"),
        (r"\bDispiayPort\b", "DisplayPort"),
        (r"\bjacking\b", "lacking"),
        (r"\bmanuaily\b", "manually"),
        (r"\bgraphicai\b", "graphical"),
        (r"\boptima!\b", "optimal"),
        # --- Modules 1-4 word joins (diagnostic scan, Sep 2026) ---
        (r"\bItis\b", "It is"),
        (r"\bIteliminates\b", "It eliminates"),
        (r"\bItallows\b", "It allows"),
        (r"\bToincrease\b", "To increase"),
        (r"\bByusing\b", "By using"),
        (r"\bByhalving\b", "By halving"),
        (r"\bBymultiplying\b", "By multiplying"),
        (r"\bLaptopcomputers\b", "Laptop computers"),
        (r"\bLaptopcomputer\b", "Laptop computer"),
        (r"\bSmartphoneTablets\b", "Smartphones and Tablets"),
        (r"\bInthe\b", "In the"),
        (r"\bforaset\b", "for a set"),
        (r"\bAnHSM\b", "An HSM"),
        (r"\bsDcard\b", "SD card"),
        (r"\bLandGrid\b", "Land Grid"),
        (r"\bBuyanew\b", "Buy a new"),
        (r"\banewone\b", "a new one"),
        # --- Batch 2 OCR misreads (diagnostic scan, Sep 2026) ---
        (r"\bRuna\b", "Run a"),
        (r"\bAnoutdated\b", "An outdated"),
        (r"\bAbulbis\b", "A bulb is"),
        (r"\bsyne\b", "sync"),
        (r"\burparvolag\b", "underpowered"),
        (r"\bAtechnician\b", "A technician"),
        (r"\btoowarm\b", "too warm"),
        (r"\bAfan\b", "A fan"),
        (r"\bAnaccumulation\b", "An accumulation"),
        (r"\bemove\b", "Remove"),
        (r"\bhandie\b", "handle"),
        (r"\bonthe\b", "on the"),
        (r"\bBIOS/UEFL\b", "BIOS/UEFI"),
        (r"\bOod\b", "and"),
        (r"\borsplitters\b", "or splitters"),
        (r"\bF-typeconnector\b", "F-type connector"),
        (r"\bcabies\b", "cables"),
        (r"\bItmanages\b", "It manages"),
        (r"\bItassigns\b", "It assigns"),
        (r"\bFirewails\b", "Firewalls"),
        (r"\bByconverting\b", "By converting"),
        (r"\bByincreasing\b", "By increasing"),
        (r"\bByfiltering\b", "By filtering"),
        (r"\bsamme\b", "same"),
        (r"\bseqment\b", "segment"),
        (r"\bToperform\b", "To perform"),
        (r"\bjocal\b", "local"),
        (r"\bconnectioniess\b", "connectionless"),
        (r"\bToidentify\b", "To identify"),
        (r"\bToensure\b", "To ensure"),
        (r"\bAremote\b", "A remote"),
        (r"\bAvideo\b", "A video"),
        (r"\bRI11\b", "RJ11"),
        (r"\bfines\b(?=.*(?:telephone|cable|data))", "lines"),
        # --- Batch 4 OCR misreads (final scan, Sep 2026) ---
        (r"\bAppie\b", "Apple"),
        (r"\bapproachemphasises\b", "approach emphasises"),
        (r"\bUsea\b", "Use a"),
        (r"\bina\b(?=\s+(?:a|an|the|single|photo))", "in a"),
        (r"\btypicaily\b", "typically"),
        (r"\bpiace\b", "place"),
        (r"\bAnaging\b", "An aging"),
        (r"\bfroma\b", "from a"),
        (r"\bNEFC\b", "NFC"),
        (r"\bLithiumIon\b", "Lithium-Ion"),
        (r"\bUSB-Cconnector\b", "USB-C connector"),
        (r"\bThesmartphone\b", "The smartphone"),
        (r"\bperrorm\b", "perform"),
        (r"\bAlocalprinter\b", "A local printer"),
        (r"\bAnetwork\b(?=\s+printer)", "A network"),
        (r"\bAshared\b", "A shared"),
        (r"\bAweb-enabled\b", "A web-enabled"),
        (r"\bqualit\b", "quality"),
        (r"\biton\b", "it on"),
        (r"\bfiim\b", "film"),
        (r"\bsopropy\b", "isopropyl"),
        (r"\bChargingStage\b", "Charging Stage"),
        (r"\bDotmatrix\b", "Dot matrix"),
        (r"\bAtractorfeed\b", "A tractor feed"),
        (r"\bAhand\b", "A hand"),
        (r"\bAduplexing\b", "A duplexing"),
        (r"\bAstepper\b", "A stepper"),
        (r"\bIsopropy!\b", "Isopropyl"),
        (r"\bAppstore\b", "App store"),
        # --- Batch 3 catchup OCR misreads (Modules 6.4-9.1) ---
        (r"\bToactasa\b", "To act as a"),
        (r"\bToassign\b", "To assign"),
        (r"\bail\b(?=\s+(?:servers|network|device|outbound|inbound))", "all"),
        (r"\bFITC\b", "FTTC"),
        (r"\bmuitiple\b", "multiple"),
        (r"\bRapidelasticity\b", "Rapid elasticity"),
        (r"\bATime\b", "A Time"),
        (r"\bD_Itcan\b", "It can"),
        (r"\bQos\b", "QoS"),
        (r"\bPublicCloud\b", "Public Cloud"),
        (r"\bSiMcard\b", "SIM card"),
        # --- Patch 5: validation failure OCR word-joins ---
        (r"\bDatachunkorder\b", "Data chunk order"),
        (r"\bFilepath\b", "File path"),
        (r"\bBaremetal\b", "Bare metal"),
        (r"\bAweb\b", "A web"),
    ]
    for pat, repl in fixes:
        s = re.sub(pat, repl, s)
    return s


# --- CertMaster UI garble (mid-text artifacts surviving _split_markers) -----
# OCR interpretations of checkmark icons, radio buttons, overlay text, and
# UI borders that _split_markers does not catch (it only strips trailing markers).
_UI_GARBLE_PATTERNS = [
    (re.compile(r"\s*9 ycev['\u2019] lat\s*"), ""),
    (re.compile(r"\s*Y Correct\s*"),            ""),
    (re.compile(r"\s*Y/Y\s*"),                  ""),
    (re.compile(r"\s*P 9 g\s*"),                ""),
    (re.compile(r"\s*@\(c\) 8B\s*", re.I),      ""),
    (re.compile(r"\s*@ 8B\s*"),                 ""),
    (re.compile(r"\s*@\(c\)\s*", re.I),         ""),
    (re.compile(r"\s*@\(r\)\s*", re.I),         ""),
    (re.compile(r"\s*Q\)_\s*"),                 ""),
    (re.compile(r"\s*TM~\s*"),                  ""),
    (re.compile(r'\s*"~~\s*'),                  ""),
    (re.compile(r"\s*yc t\s*"),                 ""),
    (re.compile(r"\s*j F\s*"),                  ""),
    (re.compile(r"\s*oO\s*"),                   ""),
    (re.compile(r"\s*\u00a5\s*"),               ""),      # yen = checkmark
    (re.compile(r"\s*\u00a7\s*"),               " "),     # section symbol
    (re.compile(r"\s+orre\s*$"),                ""),      # orphan "orrect"
    (re.compile(r"\s+orrect\s*$"),              ""),
    (re.compile(r"(?<=[a-z])\s+orrect(?=\s)"),  ""),
    (re.compile(r"\s*\bQ\s(?=[A-Z])"),          " "),     # lone Q before caps
    # --- Batch 2 garble patterns (smart quotes, degree, symbols) ---
    (re.compile(r"\s*oY FOP givsP\s*"),         ""),
    (re.compile(r"\s*@\u00a9sB\.?\s*"),         ""),
    (re.compile(r"\s*/\u00a5\s*"),              " "),
    (re.compile(r"\s*@o\.\s*\.\s*"),            ""),
    (re.compile(r"\s*=\s*\((?=server|printer|workstation)"), " ("),
    (re.compile(r"\s*ome\s*:\s*9\s*\u00b0?\s*"), ""),
    (re.compile(r"\s*un\s*\u00b0\s*\"?\s*"),    ""),
    (re.compile(r"[\u201c\u201d]+(?=\w)"),      ""),
    (re.compile(r"[\u2018\u2019]+(?=\w)"),      ""),
    (re.compile(r"\s*~+\s*(?=[a-z])"),          " "),
    (re.compile(r"\s*\u2122~?\s*(?=[a-z])"),    " "),
    # --- Batch 4 garble patterns (@ markers, P-prefix, OA variant) ---
    (re.compile(r"\s*@\u00a9?o\.?\s*[.,;]*\s*,?\s*Y/Y\s*"),   ""),
    (re.compile(r"\s*@od\s+p\s*\.?\s*"),                        ""),
    (re.compile(r"\s*@oD\s+y\s+ps\s+pany\s*"),                  ""),
    (re.compile(r"\s*@\u00a98?\s*j\s*"),                        ""),
    (re.compile(r"\s*@\u00ae\.\s*y\s+wiping\s+propy\s*"),       ""),
    (re.compile(r"\s*@8\s*;\s*;\s*i\s*Y~?\s*"),                 ""),
    (re.compile(r"\s*P\s+Orie\s+laptop\s*"),                    ""),
    (re.compile(r"\s*P\s+perrorm\s*g?\s*"),                     ""),
    (re.compile(r"\s*P\s+with\s+sopropy['\u2019]?\s*"),         ""),
    (re.compile(r"\s*Souanyupesting\s*;\s*"),                   ""),
    (re.compile(r"\s*ore\s+9\s+yrep\s*"),                       ""),
    (re.compile(r"\s*9gee\s*"),                                 ""),
    (re.compile(r"\s*ge\s*:\s*9\s*"),                           ""),
    (re.compile(r"\s*OA,\s*"),                                  ""),
    (re.compile(r"\s*QD\s+"),                                   " "),
    (re.compile(r"\s*B_\s+(?=[A-Z])"),                          ""),
    (re.compile(r"\(\s*(?=charging)"),                          ""),
    # --- Patch 5: bracket garble in multi-select answers ---
    (re.compile(r"\s*\(\s*_\s*\]\s*"),                          " "),
    (re.compile(r"\s*\[\s*_\s*\)\s*"),                          " "),
    (re.compile(r"\s*\(\s*_\s*\)\s*"),                          " "),
]


def _strip_ui_garble(text):
    """Strip CertMaster UI artifacts (checkmarks, radio buttons, overlay text)
    that appear mid-text and survive _split_markers / _strip_leading_icons."""
    if not text:
        return text
    for pattern, repl in _UI_GARBLE_PATTERNS:
        text = pattern.sub(repl, text)
    text = re.sub(r"  +", " ", text)
    text = re.sub(r"\.\s*\.$", ".", text)
    return text.strip()


def _normalize_for_compare(text):
    """Strip trailing punctuation/whitespace for answer<->option comparison, so
    'fan is not working.' matches 'fan is not working'. (Patch 5)"""
    return re.sub(r"[.\s!?;,]+$", "", text or "").strip()


# Patch 7: OCR mangles checkbox glyphs into "(_]", "()", "(-)", "DB", "OB", etc.
# When these open a line they should START a NEW option, but the raw forms aren't
# recognized, so the line gets appended to the previous option (fused mega-option).
# Normalize any leading garbled checkbox glyph to a canonical "[ ] " so the checkbox
# parser reliably begins a new option. The "[DO] + label" branch is intentionally
# conservative (lookahead requires a single A-H label then a capital word) so real
# words like "Database ..." are never touched.
_GARBLED_CB_RE = re.compile(
    r"^(\s*)"
    r"(?:"
    r"\(\s*_\s*\]|\[\s*_\s*\)|\(\s*\)|\(\s*-\s*\)|\[\s*_\s*\]|\(\s*_\s*\)"  # bracket garble
    r"|[DO]\s?(?=[A-H]\s+[A-Z])"                                            # D/O + label
    r")"
    r"\s*")


# After a checkbox glyph, CertMaster prints the option-label letter (A-H). Strip it
# so every checkbox option is uniformly label-free ("[ ] B Need..." -> "[ ] Need...")
# and the split answers match. Also handles a bare label with a dropped glyph
# ("A Need..." at line start). Only applied to checkbox-mode lines, so a leading
# single letter here is a label, never the article "A" of a radio option.
_CB_LABEL_RE = re.compile(r"^(\s*)(?:\[\s*[ xX]?\s*\]\s*)?[A-H]\s+(?=[A-Z])")


def _normalize_checkbox_glyphs(lines):
    """Convert leading garbled checkbox glyphs to a canonical '[ ] ' and drop the
    following option-label letter (Patch 7)."""
    out = []
    for ln in lines:
        ln = _GARBLED_CB_RE.sub(r"\1[ ] ", ln)
        ln = _CB_LABEL_RE.sub(r"\1[ ] ", ln)
        out.append(ln)
    return out


# Patch 8 (Phase 1): OCR renders the radio circle (●/○) as O, o, 0, or ©, or drops
# it. When two radio options land on one OCR line, they fuse. We split ONLY where a
# radio glyph clearly survived as a standalone token between two options. This is
# conservative: glyph-less fusions ("SATA SCSI") are deferred to a future phase.
_RADIO_GLYPH_LINE_RE = re.compile(
    r"^(\s*)[Oo0\u00a9]\s+(?=[A-Z])")           # line-start "O SATA"
_RADIO_GLYPH_MID_RE = re.compile(
    r"(?<=\S)\s+[Oo0\u00a9]\s+(?=[A-Z][A-Za-z])")  # mid-line " O SCSI" split point


def _normalize_radio_glyphs(lines):
    """Split mid-line radio-glyph fusions into separate option lines (Patch 8).
    "SATA O SCSI O PCIe" -> ["SATA", "SCSI", "PCIe"]. The " O " delimiter is
    consumed by the split. Only runs on radio-format (Format A/B) lines."""
    out = []
    for line in lines:
        parts = _RADIO_GLYPH_MID_RE.split(line)
        if len(parts) > 1:
            for part in parts:
                part = part.strip()
                if part:
                    out.append(part)
        else:
            out.append(line)
    return out


def _match_option(answer, options):
    """4-tier match of a correctAnswer against the option list (Patch 5):
    exact -> trailing-punctuation-normalized -> substring -> fuzzy.
    Returns (best_option_or_None, ratio). The OPTION's exact text is the canonical
    answer, so the caller assigns the returned option, not the stripped answer."""
    if not options:
        return None, 0.0
    # 1. exact
    if answer in options:
        return answer, 1.0
    ca_norm = _normalize_for_compare(answer)
    # 2. normalized (trailing punctuation stripped from both sides)
    for opt in options:
        if ca_norm == _normalize_for_compare(opt):
            return opt, 1.0
    # 3. substring (one contains the other), guarded to avoid short false matches
    ca_lower = ca_norm.lower()
    if len(ca_lower) > 15:
        for opt in options:
            opt_lower = _normalize_for_compare(opt).lower()
            if ca_lower in opt_lower or opt_lower in ca_lower:
                return opt, 0.95
    # 4. fuzzy
    best_opt, best_ratio = None, 0.0
    for opt in options:
        ratio = SequenceMatcher(None, ca_norm, _normalize_for_compare(opt)).ratio()
        if ratio > best_ratio:
            best_opt, best_ratio = opt, ratio
    return best_opt, best_ratio


def _has_ui_garble_marker(text):
    """True if text contains a CertMaster correct-answer UI marker. Used to
    detect the correct option BEFORE garble stripping removes the signal."""
    if not text:
        return False
    return bool(re.search(
        r"Y Correct|Y/Y|\u00a5|' Y Correct|e a\. \. '|@\s*8\s*B|@o[dD]\s|@\u00a9o|Souanyupesting|ore 9 yrep|OA,",
        text))


def _is_garbled(text):
    """True if option `text` is mostly OCR noise:
      * fewer than 3 alphanumeric characters, or
      * more than 50% of non-space characters are non-alphanumeric, or
      * it contains no "real word" (no whitespace token of >= 4 letters) — a run of
        tiny fragments like "asp , pp" that survived icon/marker cleanup.
    """
    if not text:
        return True
    alnum = sum(c.isalnum() for c in text)
    if alnum < 3:
        return True
    non_space = [c for c in text if not c.isspace()]
    if not non_space:
        return True
    non_alnum = sum(not c.isalnum() for c in non_space)
    if non_alnum > 0.5 * len(non_space):
        return True
    # A standalone stray-punctuation token ("asp , pp" -> tokens 'asp' ',' 'pp')
    # with no real word (>= 4 letters) present is almost certainly gibberish. This
    # keeps clean short acronym options ("VGA", "HDMI", "RJ-45") from being flagged.
    toks = text.split()
    has_real_word = any(len(re.sub(r"[^A-Za-z]", "", t)) >= 4 for t in toks)
    has_punct_token = any(not re.search(r"[A-Za-z0-9]", t) for t in toks)
    if has_punct_token and not has_real_word:
        return True
    return False


def _looks_like_icon_line_noise(text):
    """True if `text` (the fragment sitting ON a Format-D icon line, between a wrapped
    lead-in and a continuation) is OCR garbage: very short (< 10 chars) or made up
    mostly of punctuation/digits — e.g. ". p 9 9", ": a", "a ; ; ;", ". ;". Such a
    fragment must be discarded so the real option text comes from the surrounding
    lines. Only ever applied when a lead-in exists, so it can't drop a real option."""
    t = text.strip()
    if not t:
        return True
    if len(t) < 10:
        return True
    letters = sum(c.isalpha() for c in t)
    non_space = [c for c in t if not c.isspace()]
    # Mostly non-letters (punctuation/digits) => noise.
    return letters < 0.4 * len(non_space) if non_space else True


def _norm_option_letter(ch):
    """Normalize a possibly-misread option letter to uppercase A-H."""
    ch = ch.upper()
    return {"\u00a2": "C", "8": "B", "0": "O"}.get(ch, ch)


# ---------------------------------------------------------------------------
# Block splitting: one block per "Question N" header.
# ---------------------------------------------------------------------------
def split_question_blocks(raw):
    """Split OCR text into blocks at each 'Question N' header.
    Returns a list of (is_question, status, lines):
      - is_question: True if the block was introduced by a 'Question N' header
      - status: attempt status word (correct/incorrect/partial), default 'correct'
      - lines: the lines after the header
    Text before the first header (or a page with no header at all) is returned as a
    single is_question=False block, letting the caller skip non-question pages."""
    lines = raw.splitlines()
    blocks = []
    current, status, in_question = [], "correct", False
    started = False
    for line in lines:
        m = QUESTION_HDR_RE.match(line)
        if m:
            if started:
                blocks.append((in_question, status, current))
            started = True
            in_question = True
            status = (m.group(2) or "").strip().lower() or "correct"
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


# ---------------------------------------------------------------------------
# Option-line parsing (per format)
# ---------------------------------------------------------------------------
def _split_markers(text):
    """Return (clean_text, marked_correct, marked_incorrect) after stripping any
    trailing correct/incorrect marker from `text`."""
    marked = bool(CORRECT_DECIDE_RE.search(text))
    incorrect = bool(INCORRECT_MARKER_RE.search(text))
    stripped = ANY_MARKER_RE.sub("", text)
    return stripped.strip(), marked, incorrect


def _finalize_option(text):
    """Full cleanup of a raw option string -> display text."""
    # Patch 7: strip any residual checkbox glyph (raw or canonicalized) at the start.
    text = re.sub(
        r"^\s*(?:\(\s*_\s*\]|\[\s*_\s*\)|\(\s*\)|\(\s*-\s*\)|\[\s*_\s*\]|\(\s*_\s*\)"
        r"|\[\s*[ xX]?\s*\])\s*", "", text)
    # Patch 8: strip a residual radio glyph left at the start of an option after a
    # mid-line split (e.g. "O SATA" -> "SATA"). Only when followed by an uppercase
    # word, so "o'clock"/"0-based"/"Open" content is not touched.
    text = re.sub(r"^\s*[Oo0\u00a9]\s+(?=[A-Z])", "", text)
    text = _strip_leading_icons(text)
    text, _m, _i = _split_markers(text)
    text = _strip_leading_icons(text)          # icon may sit after a stripped marker
    # B4: strip a leaked "icon + letter label" prefix such as "OA It acts as ..."
    # (icon O/0/©/@/® directly followed by a single A-H label and a space).
    text = re.sub(r"^\s*[O0©®@\u00a9\u00ae]\s*[A-H]\s+(?=[A-Za-z])", "", text)
    # B5: drop a short garbled chunk sitting BETWEEN readable words when it clearly
    # carries an OCR icon glyph, e.g. "upp @bD TCP" -> "upp TCP". Only icon-bearing
    # tokens (and adjacent pure-symbol tokens) are removed, never plain short words
    # or standalone numbers (which are often real content like "USB 2.0"/"IP67").
    text = re.sub(
        r"(?<=\w)\s+[@©®\u00a9\u00ae][\w]{0,3}(?:\s+[^\w\s]{1,3})*\s+(?=[A-Za-z]{2,})",
        " ", text)
    text = re.sub(r"[_]+$", "", text).strip()  # trailing underscore artifact
    text = re.sub(r"[,\s]+$", "", text)        # trailing comma/space if content remains
    # NEW: strip mid-text CertMaster UI garble (checkmarks, radio buttons, etc.)
    text = _strip_ui_garble(text)
    # NEW (v2): strip smart-quote artifacts (OCR'd UI borders/shadows).
    # Curly quotes glued to the next word: "networking -> networking
    text = re.sub(r'[\u201c\u201d\u2018\u2019]+(?=\w)', '', text)
    # Degree symbol + surrounding garble: "un ° " urparvolag" -> "underpowered"
    text = re.sub(r'\s*\u00b0\s*["\u201c\u201d]?\s*', ' ', text)
    # NEW: strip leaked option letter labels "B The USB..." -> "The USB..."
    # Only B/C/D as a bare letter — never a bare "A" (article false positives).
    text = re.sub(r"^([BCD])\s+(?=[A-Z])", "", text)
    # A letter with an EXPLICIT label separator ("A." / "A_" / "B_") is an
    # unambiguous option label (not the article "A "), so strip A-H here too.
    text = re.sub(r"^[A-H][._]\s+(?=[A-Za-z])", "", text)
    text = clean_text(text)
    return _fix_ocr_words(text)


def _parse_option_line(line):
    """FORMAT A helper: if `line` is a lettered option, return
    (letter, text, selected, marked, incorrect); else None."""
    def unpack(m, has_text):
        g1 = m.group(1)
        letter = m.group(2) or m.group(3) or m.group(4)
        selected = bool(g1) or bool(m.group(2))
        text = m.group(m.lastindex) if has_text else ""
        stripped, marked, incorrect = _split_markers(text)
        stripped = re.sub(r"_+$", "", stripped.strip())
        return (_norm_option_letter(letter), clean_text(stripped), selected,
                marked, incorrect)

    m = OPTION_RE.match(line)
    if m:
        return unpack(m, has_text=True)
    mb = OPTION_BARE_RE.match(line)
    if mb:
        return unpack(mb, has_text=False)
    return None


def _apply_marker_to_last(options, line):
    """Fold a continuation line's marker (if any) onto the last option and return
    the marker-stripped continuation text to be joined."""
    if CORRECT_DECIDE_RE.search(line):
        options[-1]["marked"] = True
    if INCORRECT_MARKER_RE.search(line):
        options[-1]["incorrect"] = True
    return ANY_MARKER_RE.sub("", line)


def _split_stem_leadin(pending):
    """Split a buffer of not-yet-assigned lines into (stem_lines, leadin_lines).

    The stem is a question ending in '?' (or ':'); any lines AFTER that terminator
    are the wrapped lead-in of the first option. If no line ends in a terminator,
    the whole buffer is treated as a lead-in (the stem was captured elsewhere)."""
    last_term = -1
    for i, ln in enumerate(pending):
        s = ln.strip()
        # A stem line ends in '?' or ':' (optionally followed by a "(Select N)"
        # instruction), or contains the "(Select N)" instruction itself.
        if (re.search(r"[?:]\s*(?:\(\s*select\b[^)]*\)?\s*)?$", s, re.IGNORECASE)
                or SELECT_N_RE.search(s)):
            last_term = i
    if last_term >= 0:
        return pending[:last_term + 1], pending[last_term + 1:]
    return [], pending


def _parse_options_letter_labeled(body_lines):
    """FORMAT D: a REQUIRED radio icon + a bare letter label (A-H, no punctuation) +
    option text (Modules 5-10). The icon requirement stops stem lines that merely
    start with a capital ("A user ...") from being mistaken for options.

    The letter label is stripped from the stored text. Options wrap across lines:
      * "ICON LETTER text..."      then continuation lines join;
      * "ICON LETTER" alone        then the text is on the following line(s);
      * a Correct/Incorrect marker may sit at the end of any of those lines, or on
        its own line, and folds onto the current option.
    Continuation lines are any non-blank line that is NOT another Format-D option and
    NOT a stop line."""
    options, stem_parts, seen_option = [], [], False
    pending = []      # non-icon lines since the last boundary (stem or wrapped lead-in)

    def _next_starts_option_d(idx):
        for j in range(idx + 1, len(body_lines)):
            nxt = body_lines[j]
            if not nxt.strip():
                continue
            if _STOP_RE.match(nxt):
                return False
            return bool(OPTION_D_RE.match(nxt) or OPTION_D_BARE_RE.match(nxt))
        return False

    for i, ln in enumerate(body_lines):
        if _STOP_RE.match(ln):
            break
        m = OPTION_D_RE.match(ln)
        mbare = None if m else OPTION_D_BARE_RE.match(ln)
        if m or mbare:
            hit = m or mbare
            selected = bool(hit.group(1))
            body = hit.group(hit.lastindex) if m else ""   # text is the last group
            body, marked, incorrect = _split_markers(body)
            # Prepend any wrapped lead-in that belonged to THIS option (the stem is
            # split off at the last '?'/':' line; 9.2 Q4 / 9.7 Q20 put the option's
            # first words on the line above the icon).
            stem_pend, lead_pend = _split_stem_leadin(pending)
            # Drop OCR noise sitting on the icon line ONLY when there is a wrapped
            # lead-in (multi-line option): "Set up ... to the" / "®A . p 9 9" /
            # "device." — the "p 9 9" / ": a" / "a ; ; ;" between real fragments is
            # garble. A normal single-line option (no lead-in) keeps its short body
            # like "M2"/"7mm"/"IP67".
            if lead_pend and _looks_like_icon_line_noise(body):
                body = ""
            stem_parts.extend(stem_pend)
            lead = " ".join(lead_pend).strip()
            pending = []
            full = ((lead + " ") if lead else "") + body
            options.append({"text": full.strip(), "selected": selected,
                            "marked": marked, "incorrect": incorrect})
            seen_option = True
        elif not seen_option:
            pending.append(ln)                 # stem or first option's lead-in
        elif options and ln.strip():
            cur_complete = bool(re.search(r"[.?!]\s*$", options[-1]["text"]))
            if _next_starts_option_d(i) and cur_complete:
                # The current option already looks complete AND another option
                # follows: this line is the wrapped lead-in of that NEXT option.
                pending.append(ln)
            else:
                # Continuation of the current option (join, folding any marker).
                extra = _apply_marker_to_last(options, ln)
                options[-1]["text"] = clean_text((options[-1]["text"] + " " + extra).strip())
    # Any trailing pending that never reached an option is stem.
    if pending and not options:
        stem_parts.extend(pending)
    return stem_parts, options


def _parse_options_lettered(body_lines):
    """FORMAT A: icon + letter (A-D) + text. Multi-line options join. Kept close to
    the original 5.1 path for regression safety."""
    body_lines = _normalize_radio_glyphs(body_lines)   # Patch 8: split radio fusions
    options, stem_parts, seen_option = [], [], False
    for ln in body_lines:
        if _STOP_RE.match(ln):
            break
        parsed = _parse_option_line(ln)
        if parsed:
            letter, text, selected, marked, incorrect = parsed
            options.append({"text": text, "selected": selected,
                            "marked": marked, "incorrect": incorrect})
            seen_option = True
        elif not seen_option:
            stem_parts.append(ln)
        elif options and ln.strip():
            extra = _apply_marker_to_last(options, ln)
            options[-1]["text"] = clean_text(options[-1]["text"] + " " + extra)
    return stem_parts, options


def _parse_options_letterless(body_lines):
    """FORMAT B: radio icon (no letter) + text; options often wrap across lines.

    Special cases handled:
      * lead-in text on a NON-icon line followed by the icon on the next line
        (the pre-icon text belongs to the option the icon starts);
      * '@' appearing on a NON-first line of an option = a selection indicator,
        not a new option boundary;
      * a Correct marker on line 1 with the option text continuing on line 2.
    """
    body_lines = _normalize_radio_glyphs(body_lines)   # Patch 8: split radio fusions
    options, stem_parts, seen_option = [], [], False
    pending = []       # non-icon text since the last option boundary

    def _next_nonblank_starts_option(idx):
        """True if the next non-blank line begins a NEW Format-B option (so the
        current non-icon line is that option's wrapped lead-in, not a continuation
        of the current option)."""
        for j in range(idx + 1, len(body_lines)):
            nxt = body_lines[j]
            if not nxt.strip():
                continue
            if _STOP_RE.match(nxt):
                return False
            return bool(OPTION_B_RE.match(nxt))
        return False

    for i, ln in enumerate(body_lines):
        if _STOP_RE.match(ln):
            break
        if not ln.strip():
            # A blank line separates wrapped lead-ins from options, but the stem is
            # often separated from the first option by a blank line too, and a
            # wrapped lead-in can be separated from ITS option by a blank line. Only
            # discard the buffer after an option AND when the next real line does not
            # itself start an option (i.e. the buffer is not that option's lead-in).
            if seen_option and not _next_nonblank_starts_option(i):
                pending = []
            continue
        mb = OPTION_B_RE.match(ln)
        if mb:
            # group 1 = '@' (selected), group 2 = digit-6 (misread '@', selected),
            # last group = option text.
            selected = bool(mb.group(1)) or bool(mb.group(2))
            body = mb.group(mb.lastindex)
            body, marked, incorrect = _split_markers(body)
            stem_pend, lead_pend = _split_stem_leadin(pending)
            stem_parts.extend(stem_pend)
            lead = " ".join(lead_pend).strip()
            pending = []
            full = clean_text(((lead + " ") if lead else "") + body)
            options.append({"text": full, "selected": selected,
                            "marked": marked, "incorrect": incorrect})
            seen_option = True
        elif re.match(r"^\s*@\s+\S", ln) and seen_option:
            # '@' on a continuation line: mark the current option selected and join.
            extra = _apply_marker_to_last(options, re.sub(r"^\s*@\s+", "", ln))
            options[-1]["selected"] = True
            options[-1]["text"] = clean_text(options[-1]["text"] + " " + extra)
        else:
            if not seen_option:
                pending.append(ln)      # stem-or-leadin; resolved when an icon hits
            elif _next_nonblank_starts_option(i):
                # Non-icon line whose FOLLOWING line starts a new option: this is the
                # wrapped lead-in of that next option, NOT a continuation of the
                # current one (3.1 / Module-1 "Check if ... to both" + "0 the ...").
                pending.append(ln)
            elif options:
                extra = _apply_marker_to_last(options, ln)
                options[-1]["text"] = clean_text(options[-1]["text"] + " " + extra)
    return stem_parts, options


def _parse_options_checkbox(body_lines):
    """FORMAT C: checkbox icon + text (multi-select). Each checkbox glyph starts a
    new option. An icon-less line that ends in a marker is its own checked/incorrect
    option (the checkbox glyph was dropped by OCR); a lone marker line folds onto the
    previous option; other icon-less lines continue the current option, or (before
    any option) are stem / a wrapped lead-in."""
    # Patch 7: canonicalize garbled checkbox glyphs so each option line starts a new
    # option instead of being fused into the previous one.
    body_lines = _normalize_checkbox_glyphs(body_lines)
    options, stem_parts, seen_option = [], [], False
    pending = []

    def open_option(body_text, marked, incorrect):
        """Start a new option, resolving stem vs wrapped lead-in from `pending`."""
        nonlocal pending, seen_option
        stem_pend, lead_pend = _split_stem_leadin(pending)
        stem_parts.extend(stem_pend)
        lead = " ".join(lead_pend).strip()
        pending = []
        full = clean_text(((lead + " ") if lead else "") + body_text)
        options.append({"text": full, "selected": False,
                        "marked": marked, "incorrect": incorrect})
        seen_option = True

    for ln in body_lines:
        if _STOP_RE.match(ln):
            break
        if not ln.strip():
            if seen_option:
                pending = []
            continue
        mb = CHECKBOX_RE.match(ln)
        if mb:
            body, marked, incorrect = _split_markers(mb.group(1))
            open_option(body, marked, incorrect)
            continue
        stripped, marked, incorrect = _split_markers(ln)
        is_marker_only = (marked or incorrect) and not stripped
        if is_marker_only and options:
            # lone "JY Correct" / "X_ Incorrect" line: attach to previous option.
            if marked:
                options[-1]["marked"] = True
            if incorrect:
                options[-1]["incorrect"] = True
            continue
        if marked or incorrect:
            # icon-less line WITH a marker: a checked/incorrect option whose checkbox
            # glyph OCR dropped (real in 3.1 Q9/Q13/Q14 — "24-pin ... / Correct").
            open_option(stripped, marked, incorrect)
        elif not seen_option:
            pending.append(ln)          # stem-or-leadin
        elif options:
            options[-1]["text"] = clean_text(options[-1]["text"] + " " + stripped)
    return stem_parts, options


def _parse_options_loose(body_lines):
    """REWRITE 3b — loose fallback: treat each non-blank, non-stop line AFTER the
    stem as an option. Strip leading icon garbage; keep the remainder. Used for
    unusual formats such as the voltage list (12 / 24 / 15 / 5 / 7 / 3.3).

    The stem (lines up to and including the last one ending in '?'/':' or carrying a
    "(Select N)" instruction) is dropped so its lines don't become bogus options
    (e.g. 4.1 Q11, whose only real option is truncated after a 5-line stem)."""
    # Locate the end of the stem.
    stem_end = -1
    for i, ln in enumerate(body_lines):
        s = ln.strip()
        if _STOP_RE.match(ln):
            break
        if re.search(r"[?:]\s*(?:\(\s*select\b[^)]*\)?\s*)?$", s, re.IGNORECASE) \
                or SELECT_N_RE.search(s):
            stem_end = i
    options = []
    for idx, ln in enumerate(body_lines):
        if idx <= stem_end:
            continue
        if _STOP_RE.match(ln) or not ln.strip():
            continue
        stripped, marked, incorrect = _split_markers(ln)
        text = _strip_leading_icons(stripped)
        text = clean_text(text)
        if not text or len(text) < 1:
            continue
        # skip a line that is pure garble (no alphanumeric content left)
        if not re.search(r"[A-Za-z0-9]", text):
            continue
        # A marker-less line that begins lowercase is a wrapped continuation of the
        # previous option, not a new one (4.1 Q11 "to increase the fan speed.").
        if options and not marked and not incorrect and re.match(r"^[a-z]", text):
            if marked:
                options[-1]["marked"] = True
            options[-1]["text"] = clean_text(options[-1]["text"] + " " + text)
            continue
        options.append({"text": text, "selected": False,
                        "marked": marked, "incorrect": incorrect})
    return options


# ---------------------------------------------------------------------------
# Whole-question parsing
# ---------------------------------------------------------------------------
def parse_questions(raw):
    """Parse OCR text into question dicts, returning (questions, had_header).

    had_header is True if any 'Question N' header was present. process_folder uses
    it to distinguish a SKIP (no question on the page) from an ERROR (a question was
    present but could not be parsed).

    Each question dict: stem, options, correctAnswer, explanation, questionType,
    and a private _flags list of review reasons.
    """
    raw = strip_metadata(raw)
    blocks = split_question_blocks(raw)
    had_header = any(is_q for is_q, _st, _ln in blocks)
    results = []

    for is_question, header_status, block_lines in blocks:
        if not is_question:
            continue

        # Explanation split: everything after the first "Explanation" line.
        expl_idx = None
        for i, ln in enumerate(block_lines):
            if re.match(r"^\s*explanation\b", ln, re.IGNORECASE):
                expl_idx = i
                break
        body_lines = block_lines[:expl_idx] if expl_idx is not None else block_lines
        expl_lines = block_lines[expl_idx + 1:] if expl_idx is not None else []
        # Truncate the explanation at the first metadata boundary.
        clean_expl_lines = []
        for ln in expl_lines:
            if _STOP_RE.match(ln):
                break
            clean_expl_lines.append(ln)

        # Provisional stem (Format A path) to detect "(Select N)" early.
        stem_probe = " ".join(l for l in body_lines if not _parse_option_line(l)
                              and not OPTION_B_RE.match(l) and not CHECKBOX_RE.match(l))
        select_n = bool(SELECT_N_RE.search(stem_probe)) or bool(SELECT_N_RE.search(" ".join(body_lines)))

        # MODE DETECTION: D -> A -> B -> C, take the first with >= 2 options.
        # If the stem says "(Select N)", prefer the checkbox (multi-select) mode.
        mode = None
        single_rescue = None   # best 1-option result (a truncated question)
        stem_parts, options = [], []
        if select_n:
            # Multi-select: checkbox first.
            sp_c, opt_c = _parse_options_checkbox(body_lines)
            if len(opt_c) >= 2:
                stem_parts, options, mode = sp_c, opt_c, "C"
        # FORMAT D (icon + bare letter label) is the most specific single-select
        # format, so it is tried FIRST. It requires an icon before the letter, which
        # prevents a stem line starting with a capital ("A user ...") from being
        # swallowed as an option (the root cause of the Module 5-10 errors).
        if len(options) < 2:
            sp_d, opt_d = _parse_options_letter_labeled(body_lines)
            if len(opt_d) >= 2:
                stem_parts, options, mode = sp_d, opt_d, "D"
            elif len(opt_d) == 1 and opt_d[0].get("marked"):
                single_rescue = (sp_d, opt_d, "D")
        if len(options) < 2:
            sp_a, opt_a = _parse_options_lettered(body_lines)
            if len(opt_a) >= 2:
                stem_parts, options, mode = sp_a, opt_a, "A"
        if len(options) < 2:
            sp_b, opt_b = _parse_options_letterless(body_lines)
            if len(opt_b) >= 2:
                stem_parts, options, mode = sp_b, opt_b, "B"
            elif len(opt_b) == 1 and opt_b[0].get("marked"):
                single_rescue = (sp_b, opt_b, "B")   # truncated single option
        if len(options) < 2:
            sp_c, opt_c = _parse_options_checkbox(body_lines)
            if len(opt_c) >= 2:
                stem_parts, options, mode = sp_c, opt_c, "C"
        if len(options) < 2:
            opt_loose = _parse_options_loose(body_lines)
            if len(opt_loose) >= 2:
                # stem = the lines that were not consumed as loose options
                stem_parts = [l for l in body_lines
                              if not any(clean_text(_strip_leading_icons(l)).lower()
                                         == o["text"].lower() for o in opt_loose)]
                options, mode = opt_loose, "loose"
            elif len(opt_loose) == 1 and opt_loose[0].get("marked") and not single_rescue:
                single_rescue = (body_lines, opt_loose, "loose")

        # For B/C/D, a wrapped option's lead-in was also captured as a stem part.
        if mode in ("B", "C", "D"):
            opt_prefixes = [o["text"].lower()[:25] for o in options if o["text"]]
            stem_parts = [s for s in stem_parts
                          if clean_text(s).lower()[:25] not in opt_prefixes]

        if len(options) < 2:
            # Truncated question rescue: a single option carrying a Correct marker is
            # kept (image cut off the rest); it will be flagged for review below.
            if single_rescue:
                stem_parts, options, mode = single_rescue
            else:
                continue  # header present but unparseable -> caller logs as error

        # NEW: detect mid-text garble markers BEFORE finalization to recover
        # correct-answer signal. CertMaster overlays a checkmark on the correct
        # option — OCR renders it as "Y Correct" / yen / "Y/Y" mid-text.
        for o in options:
            if not o.get("marked") and _has_ui_garble_marker(o["text"]):
                o["marked"] = True

        # NEW (Patch 4): split on the @8B / @(c)8B correct-answer marker that OCR
        # leaves BETWEEN two fused options. This must run BEFORE _finalize_option,
        # which (via _strip_ui_garble) erases the "@ 8B" split point. The first
        # part is the correct answer; the remainder is the next option.
        if not ((mode == "C") or select_n):
            split_out = []
            for o in options:
                if re.search(r"@\s*[\u00a9\u00ae]?\s*8\s*B", o["text"]):
                    parts = re.split(r"\s*@\s*[\u00a9\u00ae]?\s*8\s*B\s*", o["text"])
                    for j, part in enumerate([p.strip() for p in parts if p.strip()]):
                        if j == 0:
                            new_o = dict(o)
                            new_o["text"] = part
                            new_o["marked"] = True   # first part IS correct
                            split_out.append(new_o)
                        else:
                            split_out.append({"text": part, "selected": False,
                                              "marked": False, "incorrect": False})
                else:
                    split_out.append(o)
            options = split_out

        # Finalize option display text.
        for o in options:
            o["text"] = _finalize_option(o["text"])

        # NEW (v2): split merged options. CertMaster renders 4 options per
        # question; OCR frequently fuses two adjacent options into one string.
        # The fusion point is marked by a LEAKED OPTION LABEL: Op, Os, Oo, On,
        # or Oop (OCR misread of radio-button glyph + letter). Split on these
        # first; fall back to sentence boundaries for non-label merges.
        if not ((mode == "C") or select_n):
            expanded = []
            for o in options:
                # Primary: split on leaked label (". Op/Os/Oo/On/Oop/OA, ")
                if len(o["text"]) > 80 and re.search(
                        r"[.!?)\"\u201d]\s+(?:Op|Os|Oo|On|Oop|OA,?)\s+[A-Z]", o["text"]):
                    parts = re.split(
                        r"(?<=[.!?)\"\u201d])\s+(?:Op|Os|Oo|On|Oop|OA,?)\s+(?=[A-Z])",
                        o["text"])
                    for j, part in enumerate(parts):
                        part = part.strip()
                        if not part:
                            continue
                        if j == 0:
                            new_o = dict(o)
                            new_o["text"] = part
                            expanded.append(new_o)
                        else:
                            expanded.append({"text": part, "selected": False,
                                             "marked": False, "incorrect": False})
                # Secondary: split on plain sentence boundary (>120 chars only)
                elif len(o["text"]) > 120 and re.search(
                        r"\.\s+[A-Z][a-z]", o["text"]):
                    parts = re.split(r"(?<=\.)\s+(?=[A-Z][a-z])", o["text"])
                    for j, part in enumerate(parts):
                        part = part.strip()
                        if not part:
                            continue
                        if j == 0:
                            new_o = dict(o)
                            new_o["text"] = part
                            expanded.append(new_o)
                        else:
                            expanded.append({"text": part, "selected": False,
                                             "marked": False, "incorrect": False})
                # Tertiary: split on any residual @8B / @(c)8B marker (the pre-finalize
                # pass handles most; this catches any that reached here intact).
                elif re.search(r"@\s*[\u00a9\u00ae]?\s*8\s*B", o["text"]):
                    parts = re.split(
                        r"\s*@\s*[\u00a9\u00ae]?\s*8\s*B\s*", o["text"])
                    for j, part in enumerate(parts):
                        part = part.strip()
                        if not part:
                            continue
                        if j == 0:
                            new_o = dict(o)
                            new_o["text"] = part
                            new_o["marked"] = True  # first part IS correct
                            expanded.append(new_o)
                        else:
                            expanded.append({"text": part, "selected": False,
                                             "marked": False, "incorrect": False})
                else:
                    expanded.append(o)
            # Rejoin orphan fragments (<25 chars starting lowercase) to parent.
            final = []
            for o in expanded:
                if (len(o["text"]) < 25 and final
                        and not re.match(r"^[A-Z]", o["text"])):
                    final[-1]["text"] = final[-1]["text"].rstrip() + " " + o["text"]
                    if o.get("marked"):
                        final[-1]["marked"] = True
                else:
                    final.append(o)
            options = final

        options = [o for o in options if o["text"]]
        # Require >= 2 options, EXCEPT a truncated single-option rescue (1 option
        # that carries a Correct marker) which is kept and flagged for review.
        if len(options) < 2 and not (single_rescue and len(options) == 1
                                     and options[0].get("marked")):
            continue

        stem = _fix_ocr_words(_strip_ui_garble(clean_text(" ".join(stem_parts))))
        option_texts = [o["text"] for o in options]
        explanation = _fix_ocr_words(_strip_ui_garble(clean_text(" ".join(clean_expl_lines))))

        # Is this a multi-select question? Checkbox mode OR "(Select N)" in stem.
        is_multi = (mode == "C") or select_n

        header_incorrect = header_status == "incorrect"

        # ---- CORRECT-ANSWER DETECTION (signal priority) --------------------
        # Signal 1: explicit Correct marker on the option line (strongest).
        marked_correct = [o["text"] for o in options if o["marked"] and o["text"]]
        # Signal 3 pre-computed: options explicitly marked Incorrect are eliminated.
        marked_incorrect = {o["text"] for o in options if o["incorrect"]}

        if marked_correct:
            correct = list(dict.fromkeys(marked_correct))
        elif is_multi:
            # multi-select but no markers survived truncation: nothing reliable
            correct = []
        elif not header_incorrect:
            # Signal 2: header says correct -> the selected (@) option is right.
            correct = [o["text"] for o in options if o["selected"] and o["text"]]
        else:
            # header incorrect + no marker: the @ option is WRONG; eliminate it and
            # any Incorrect-marked option, then fall through to explanation mining.
            correct = []

        found = bool(correct)
        if not found:
            correct, found = _correct_from_explanation(option_texts, explanation)
            # Never let an eliminated option be the answer.
            correct = [c for c in correct if c not in marked_incorrect]
            found = bool(correct)

        # ---- TYPE --------------------------------------------------------
        if is_multi or len(correct) > 1:
            qtype = "multi"
        else:
            qtype = "mc"
        if re.search(r"\bdrag\b|\bdrop\b|match each", (stem + " " + raw).lower()):
            qtype = "drag_drop"

        # Truncated-option detection: a short option (<15 chars) without ending
        # punctuation is likely cut off at the image boundary.
        truncated = any(len(t) < 15 and not re.search(r"[.?!]$", t) for t in option_texts)

        flags = []
        if not found:
            flags.append("correctAnswer not detected by OCR")
        if len(option_texts) < 2:
            # Fewer than 2 complete options: the image almost certainly cut off the
            # rest. Keep the question but flag it for manual review.
            flags.append("truncated options")
        if len(option_texts) < MIN_OPTIONS:
            flags.append(f"only {len(option_texts)} options parsed (<{MIN_OPTIONS})")
        if len(option_texts) > MAX_OPTIONS:
            flags.append(f"{len(option_texts)} options parsed (>{MAX_OPTIONS})")
        if truncated:
            flags.append("truncated option text")
        if is_multi and len(correct) < 2 and found:
            flags.append("multi-select but fewer than 2 correct answers detected")
        # Garbled-option detection: an option that survived cleanup as mostly noise
        # (fewer than 3 alphanumerics, or >50% non-alphanumeric excluding spaces).
        if any(_is_garbled(t) for t in option_texts):
            flags.append("garbled option text")

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
    # B2: module is ALWAYS the folder-derived module. Content keyword scoring is used
    # only for the objective/domain/confidence fields, never to pick the module.
    module = folder_module
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
    # B1: "mc" -> correctAnswer is a STRING; "multi" -> ARRAY of strings.
    if q["type"] == "mc":
        if not isinstance(q["correctAnswer"], str):
            errs.append("correctAnswer must be a string for mc")
        elif q["correctAnswer"] and q["correctAnswer"] not in q["options"]:
            errs.append(f'correctAnswer "{q["correctAnswer"]}" not in options')
    elif q["type"] == "multi":
        if not isinstance(q["correctAnswer"], list):
            errs.append("correctAnswer must be an array for multi")
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

        qtype = q.get("questionType", "mc")
        # B1: schema expects correctAnswer as a STRING for "mc" (single-select) and
        # an ARRAY for "multi". The parser tracks answers internally as a list.
        answers = q.get("correctAnswer", [])
        if not isinstance(answers, list):
            answers = [answers] if answers else []
        if qtype == "mc":
            correct_answer = answers[0] if answers else ""
        else:
            correct_answer = answers

        # NEW (Patch 4): strip leaked letter prefixes from multi-select answers.
        # OCR sometimes yields ["C Disconnect the AC power.", "B_ Lack of ..."]
        # instead of ["Disconnect the AC power.", "Lack of ..."].
        if isinstance(correct_answer, list):
            correct_answer = [re.sub(r"^[A-H][._]?\s+", "", ans) for ans in correct_answer]

        # NEW (Patch 5): an answer may contain two answers fused by a leaked
        # mid-string letter label, e.g. "Need to bring costs down B Need for
        # software...". This shows up either as a bare string OR as a single list
        # element (checkbox multi-select). Split conservatively (lowercase/period
        # before a lone B-H then a capital) and promote to multi-select.
        _FUSED_RE = re.compile(r"(?<=[a-z.])\s+[B-H]\s+(?=[A-Z])")
        if isinstance(correct_answer, str) and correct_answer:
            fused_parts = _FUSED_RE.split(correct_answer)
            if len(fused_parts) > 1:
                correct_answer = [p.strip() for p in fused_parts if p.strip()]
                qtype = "multi"   # the qobj is built below from qtype
        elif isinstance(correct_answer, list):
            split_list = []
            for ans in correct_answer:
                parts = _FUSED_RE.split(ans)
                split_list.extend(p.strip() for p in parts if p.strip())
            correct_answer = split_list

        # Field order matches the production schema:
        # id, domain, objective, module, type, difficulty, stem, options,
        # correctAnswer, explanation, source, classification.
        qobj = {
            "id": qid,
            "domain": cls["domain"],
            "objective": cls["objective"],
            # B2: module is ALWAYS the folder-derived module, never a content guess.
            "module": folder_module,
            "type": qtype,
            "difficulty": "medium",
            "stem": stem,
            "options": q.get("options", []),
            "correctAnswer": correct_answer,
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

        # NEW: sync correctAnswer to match a cleaned option. Option text is cleaned
        # further after the answer was captured, so a once-identical answer can
        # drift; re-align it via 4-tier matching (exact -> trailing-punctuation
        # normalized -> substring -> fuzzy) and assign the OPTION's exact text.
        if qobj["type"] == "mc" and qobj["correctAnswer"]:
            if qobj["correctAnswer"] not in qobj["options"]:
                best_opt, best_ratio = _match_option(qobj["correctAnswer"], qobj["options"])
                if best_opt is not None and best_ratio >= 0.80:
                    qobj["correctAnswer"] = best_opt
                else:
                    review_reasons.append(
                        f"correctAnswer not in options after cleanup (best ratio: {best_ratio:.2f})")
        elif qobj["type"] == "multi" and isinstance(qobj["correctAnswer"], list):
            synced = []
            for ans in qobj["correctAnswer"]:
                if ans in qobj["options"]:
                    synced.append(ans)
                else:
                    best_opt, best_ratio = _match_option(ans, qobj["options"])
                    if best_opt is not None and best_ratio >= 0.80:
                        synced.append(best_opt)
                    else:
                        review_reasons.append(
                            f"multi correctAnswer not in options (ratio: {best_ratio:.2f})")
                        synced.append(ans)
            qobj["correctAnswer"] = synced
        # Re-evaluate review flag after sync (new reasons may have been added).
        if review_reasons:
            qobj["needsReview"] = True
            qobj["reviewReasons"] = sorted(set(review_reasons))

        # B2: module is folder-derived and authoritative; a content-derived module
        # is never used to override it, so there are no module "mismatches".

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

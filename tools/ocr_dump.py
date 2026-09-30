"""
ocr_dump.py — dump RAW Tesseract OCR text for every CertMaster screenshot to JSON.

This is Step 1 of the AI-assisted extraction plan. It does NO parsing, NO regex,
and NO question extraction — it only runs OCR and writes the raw text so a human or
an AI assistant can read it and extract questions in a later step.

Pipeline: discover subfolders -> for each image: grayscale + Tesseract (--psm 6) ->
write one JSON file per folder + a summary file.

This script is standalone: it does not import from extract_questions.py, and it
never touches questions.json.

Requirements (already installed on this machine):
  - Pillow (PIL)
  - pytesseract
  - Tesseract OCR engine (on system PATH)

Usage:
  python tools/ocr_dump.py \
      --source "C:\\Users\\mercadjn\\Downloads\\pdf images" \
      --output exam_assets/ocr_dump/ \
      --workers 4
"""

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# --- dependencies -----------------------------------------------------------
try:
    from PIL import Image
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

IMAGE_EXTS = (".jpg", ".jpeg", ".png")
TESSERACT_CONFIG = "--psm 6"

# Common Windows install locations, tried when the engine isn't on PATH.
_TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def resolve_tesseract(explicit=None):
    """Point pytesseract at a real tesseract.exe. Prefer an explicit --tesseract-path,
    then PATH, then the common Windows install locations. Returns True on success."""
    import os
    import shutil

    if explicit:
        pytesseract.pytesseract.tesseract_cmd = explicit
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        pass

    # Try PATH, then well-known locations, plus a per-user LOCALAPPDATA path.
    candidates = []
    on_path = shutil.which("tesseract")
    if on_path:
        candidates.append(on_path)
    candidates.extend(_TESSERACT_CANDIDATES)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(str(Path(local) / "Tesseract-OCR" / "tesseract.exe"))
        candidates.append(str(Path(local) / "Programs" / "Tesseract-OCR" / "tesseract.exe"))

    for cand in candidates:
        if cand and Path(cand).is_file():
            pytesseract.pytesseract.tesseract_cmd = cand
            try:
                pytesseract.get_tesseract_version()
                return True
            except Exception:
                continue
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def module_from_folder(folder_name):
    """Extract a module label from the leading number of a folder name.

    "5.1 Network Types.pdf"                     -> "5.1"
    "1 What does an IT Specialist Do.pdf"        -> "1.0"
    "2.6 Installing ... - Module Quiz.pdf"       -> "2.6"
    (no leading number)                          -> "unknown"
    """
    m = re.match(r"^\s*(\d+)\.(\d+)", folder_name)
    if m:
        return f"{int(m.group(1))}.{int(m.group(2))}"
    m = re.match(r"^\s*(\d+)\b", folder_name)
    if m:
        return f"{int(m.group(1))}.0"
    return "unknown"


def sanitize_folder(folder_name):
    """'5.1 Network Types.pdf' -> '5.1_Network_Types'.
    Drop a trailing .pdf, spaces -> underscores, keep [alnum . _ -]."""
    name = re.sub(r"\.pdf$", "", folder_name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", "_", name.strip())
    name = re.sub(r"[^0-9A-Za-z._-]", "", name)
    return name


def discover(source):
    """Return a list of {name, path, module, images} for each subfolder that has at
    least one image, sorted by (module-number, lesson-number, name)."""
    root = Path(source)
    folders = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        images = sorted(
            [p for p in d.iterdir() if p.suffix.lower() in IMAGE_EXTS],
            key=lambda p: p.name.lower(),
        )
        if not images:
            continue  # skip empty subfolders silently
        folders.append({
            "name": d.name,
            "path": d,
            "module": module_from_folder(d.name),
            "images": images,
        })

    def sort_key(f):
        m = re.match(r"^\s*(\d+)(?:\.(\d+))?", f["name"])
        if m:
            return (int(m.group(1)), int(m.group(2) or 0), f["name"].lower())
        return (10**9, 0, f["name"].lower())

    folders.sort(key=sort_key)
    return folders


def ocr_image(path):
    """Grayscale + Tesseract on a single image. Returns (text, error_or_None)."""
    try:
        with Image.open(path) as im:
            gray = im.convert("L")
            text = pytesseract.image_to_string(gray, config=TESSERACT_CONFIG)
        return text, None
    except Exception as e:  # keep the run alive on a single bad image
        return "", f"tesseract failed: {e}"


def process_folder(folder):
    """OCR every image in one folder. Returns the per-folder result dict."""
    images_out = []
    for idx, img in enumerate(folder["images"], start=1):
        text, err = ocr_image(img)
        entry = {
            "file": img.name,
            "index": idx,
            "ocrText": text,
            "charCount": len(text),
        }
        if err:
            entry["error"] = err
        images_out.append(entry)

    return {
        "folder": folder["name"],
        "moduleFromFolder": folder["module"],
        "totalImages": len(folder["images"]),
        "processedAt": datetime.now().isoformat(timespec="seconds"),
        "images": images_out,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Dump raw Tesseract OCR text per CertMaster folder to JSON "
                    "(Step 1 of AI-assisted extraction). No parsing.")
    ap.add_argument("--source", required=True,
                    help="root folder containing subfolders of images")
    ap.add_argument("--output", required=True,
                    help="directory to write the OCR JSON files")
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel OCR threads (default 4)")
    ap.add_argument("--folder", default=None,
                    help="glob to limit which subfolders are processed (e.g. '5.1*')")
    ap.add_argument("--tesseract-path", default=None,
                    help="path to tesseract.exe (auto-detected if on PATH or in a "
                         "standard install location)")
    args = ap.parse_args()

    if not _HAVE_PIL:
        print("ERROR: Pillow is not installed. Run: pip install pillow", file=sys.stderr)
        sys.exit(2)
    if not _HAVE_TESS:
        print("ERROR: pytesseract is not installed. Run: pip install pytesseract",
              file=sys.stderr)
        sys.exit(2)

    src = Path(args.source)
    if not src.is_dir():
        print(f"ERROR: --source is not a directory: {src}", file=sys.stderr)
        sys.exit(2)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Point pytesseract at a real engine (PATH or a standard install location).
    if not resolve_tesseract(args.tesseract_path):
        print("ERROR: the Tesseract OCR engine was not found.\n"
              "  Windows: install from https://github.com/UB-Mannheim/tesseract/wiki\n"
              "  Or pass --tesseract-path C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
              file=sys.stderr)
        sys.exit(2)

    folders = discover(src)
    if args.folder:
        import fnmatch
        folders = [f for f in folders if fnmatch.fnmatch(f["name"], args.folder)]

    if not folders:
        print("No folders with images found for the given --source/--folder.")
        sys.exit(0)

    total_images = sum(len(f["images"]) for f in folders)
    print(f"Discovered {len(folders)} folder(s), {total_images} image(s). "
          f"Workers: {args.workers}")

    summary_folders = []
    total_chars = 0
    start = time.time()

    # Process folders in parallel; each worker OCRs one whole folder.
    progress = tqdm(total=len(folders), desc="folders") if _HAVE_TQDM else None
    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        future_to_folder = {pool.submit(process_folder, f): f for f in folders}
        for future in as_completed(future_to_folder):
            f = future_to_folder[future]
            print(f"Processing: {f['name']} ({len(f['images'])} images)")
            result = future.result()

            out_name = f"ocr_{sanitize_folder(f['name'])}.json"
            (out_dir / out_name).write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")

            folder_chars = sum(img["charCount"] for img in result["images"])
            total_chars += folder_chars
            summary_folders.append({
                "folder": result["folder"],
                "module": result["moduleFromFolder"],
                "images": result["totalImages"],
                "outputFile": out_name,
                "totalChars": folder_chars,
            })

            completed += 1
            if progress is not None:
                progress.update(1)
            else:
                print(f"  {completed}/{len(folders)} folders complete")
    if progress is not None:
        progress.close()

    elapsed = round(time.time() - start, 1)

    # Keep the summary folder list in a stable, human-friendly order.
    summary_folders.sort(key=lambda s: s["outputFile"].lower())
    summary = {
        "totalFolders": len(folders),
        "totalImages": total_images,
        "totalCharacters": total_chars,
        "processingTimeSeconds": elapsed,
        "folders": summary_folders,
    }
    (out_dir / "ocr_dump_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("\n=== OCR DUMP COMPLETE ===")
    print(f"Folders:    {len(folders)}")
    print(f"Images:     {total_images}")
    print(f"Characters: {total_chars}")
    print(f"Time:       {elapsed}s")
    print(f"Output:     {out_dir}")


if __name__ == "__main__":
    main()

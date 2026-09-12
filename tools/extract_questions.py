#!/usr/bin/env python3
"""
extract_questions.py — extract CompTIA A+ quiz questions from CertMaster JPG
screenshots and write structured JSON (one file per source folder) ready for
review before merge into exam_assets/questions.json.

Pipeline: discover -> extract (Claude vision, parallel) -> classify (Claude text,
batched) -> deduplicate (Jaccard vs existing bank + within batch) -> validate ->
write per-folder JSON + a summary.

This script never modifies questions.json. It only reads it (as the classification
reference and dedup source) and writes new extracted_*.json files to --output.

Usage:
  python tools/extract_questions.py \
      --source "C:\\Users\\mercadjn\\Downloads\\pdf images" \
      --output exam_assets/ \
      --bank exam_assets/questions.json \
      --model claude-sonnet-4-20250514 \
      --workers 10

  ANTHROPIC_API_KEY is read from the environment by default; --api-key overrides.
"""

import argparse
import base64
import io
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# --- optional deps: degrade gracefully -------------------------------------
try:
    from PIL import Image
    _HAVE_PIL = True
except ImportError:
    _HAVE_PIL = False

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

try:
    import anthropic
    _HAVE_ANTHROPIC = True
except ImportError:
    _HAVE_ANTHROPIC = False

# --- pricing (Claude Sonnet 4) ----------------------------------------------
PRICE_INPUT_PER_MTOK = 3.0
PRICE_OUTPUT_PER_MTOK = 15.0
MAX_IMAGE_EDGE = 1024          # resize cap on the longest side
CLASSIFY_BATCH = 8             # questions per classification call
DUP_THRESHOLD = 0.85

EXTRACT_SYSTEM_PROMPT = """You are extracting quiz questions from a CertMaster certification exam screenshot.
For each question visible in the image, return a JSON array of objects with:
- stem: full question text
- options: array of full text of each option
- correctAnswer: array of full text of correct option(s)
- explanation: explanation text if visible, empty string if not
- questionType: mc if single correct, multi if multiple correct, drag_drop if drag-drop

Rules:
- The correct answer is highlighted/marked in green or with a checkmark
- Include ALL options exactly as written
- correctAnswer must contain the FULL option text, not just a letter
- If multiple questions appear in one image, return all of them
- If the image is not a quiz question, return an empty array
Return ONLY the JSON array, no prose."""


# ---------------------------------------------------------------------------
# Discovery
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
# Image prep
# ---------------------------------------------------------------------------
def load_image_b64(path):
    """Resize to <=MAX_IMAGE_EDGE on the long side, return base64 JPEG."""
    if _HAVE_PIL:
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            scale = MAX_IMAGE_EDGE / max(w, h)
            if scale < 1:
                im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=85)
            return base64.b64encode(buf.getvalue()).decode("ascii")
    # No Pillow: send raw bytes (still valid, just larger).
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


# ---------------------------------------------------------------------------
# Anthropic helpers (with backoff + usage tracking)
# ---------------------------------------------------------------------------
class Usage:
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0

    def add(self, resp):
        u = getattr(resp, "usage", None)
        if u:
            self.input_tokens += getattr(u, "input_tokens", 0) or 0
            self.output_tokens += getattr(u, "output_tokens", 0) or 0

    def cost(self):
        return (self.input_tokens / 1e6 * PRICE_INPUT_PER_MTOK
                + self.output_tokens / 1e6 * PRICE_OUTPUT_PER_MTOK)


def _call_with_backoff(fn, retries=3, base=2.0):
    """Retry on 429/529 with exponential backoff. Re-raises other errors."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:  # anthropic raises typed errors; match by status
            status = getattr(e, "status_code", None)
            transient = status in (429, 529) or "overloaded" in str(e).lower() or "rate" in str(e).lower()
            if transient and attempt < retries:
                time.sleep(base * (2 ** attempt))
                continue
            raise


def _extract_json(text):
    """Pull the first JSON array/object out of a model response."""
    text = text.strip()
    # strip code fences if present
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # find outermost [...] or {...}
        for opener, closer in (("[", "]"), ("{", "}")):
            i, j = text.find(opener), text.rfind(closer)
            if i != -1 and j != -1 and j > i:
                try:
                    return json.loads(text[i:j + 1])
                except json.JSONDecodeError:
                    pass
        raise


def extract_from_image(client, model, path, usage):
    """Vision call: return list of raw question dicts for one image."""
    b64 = load_image_b64(path)

    def do(nudge=False):
        text = EXTRACT_SYSTEM_PROMPT + ("\n\nReturn valid JSON only." if nudge else "")
        return client.messages.create(
            model=model, max_tokens=4096,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                    "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": text},
            ]}],
        )

    resp = _call_with_backoff(do)
    usage.add(resp)
    raw = resp.content[0].text
    try:
        data = _extract_json(raw)
    except json.JSONDecodeError:
        resp = _call_with_backoff(lambda: do(nudge=True))
        usage.add(resp)
        data = _extract_json(resp.content[0].text)  # may raise -> caller logs error
    return data if isinstance(data, list) else [data]


def classify_batch(client, model, questions, folder_name, meta, usage):
    """Text call: classify a batch of questions. Returns list aligned to input."""
    dom_list = "\n".join(f"  - {k}" for k in meta["domains"])
    obj_list = "\n".join(f"  - {k}: {v}" for k, v in meta["objectives"].items())
    mod_list = "\n".join(f"  - {k}: {v}" for k, v in meta["modules"].items())
    items = "\n".join(
        f"[{i}] Question: {q.get('stem','')}\n"
        f"    Options: {q.get('options', [])}\n"
        f"    Explanation: {q.get('explanation','')}"
        for i, q in enumerate(questions)
    )
    prompt = f"""Classify each CompTIA A+ Core 1 (220-1201) exam question below.
Source folder: {folder_name} (CertMaster lesson numbering, NOT the CompTIA objective).

Available domains:
{dom_list}

Available objectives:
{obj_list}

Available modules:
{mod_list}

Questions:
{items}

Return a JSON array with one object per question, in order, each:
- index: the [n] index
- domain: exact domain key
- objective: exact objective key
- module: exact module key
- confidence: high, medium, or low
- reasoning: brief explanation

Rules:
- Match by question CONTENT, not folder name.
- objective prefix must match domain (e.g. objective 2.7 -> domain 2.0 Networking).
- module must be consistent with the objective-to-module mapping.
Return ONLY the JSON array."""

    def do():
        return client.messages.create(
            model=model, max_tokens=4096,
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        )

    resp = _call_with_backoff(do)
    usage.add(resp)
    data = _extract_json(resp.content[0].text)
    by_index = {int(d.get("index", i)): d for i, d in enumerate(data)}
    return [by_index.get(i, {}) for i in range(len(questions))]


# ---------------------------------------------------------------------------
# Dedup + validation
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
def process_folder(folder, client, model, meta, existing_stems, batch_seen,
                   id_counter, usage, dry_run):
    """Extract + classify + dedup + validate one folder. Returns the output dict."""
    name = folder["name"]
    folder_module = folder["module"]
    result = {
        "source": {"folder": name, "moduleFromFolder": folder_module,
                   "totalImages": len(folder["images"]), "totalQuestionsFound": 0,
                   "questionsKept": 0, "duplicatesSkipped": 0, "errors": 0},
        "questions": [], "duplicates": [], "errors": [], "mismatches": [],
    }

    # Step 2: extract from each image (parallel handled by caller via per-image
    # futures; here we run images sequentially so a folder is a coherent unit).
    raw = []  # (imageFile, question dict)
    for img in folder["images"]:
        try:
            qs = extract_from_image(client, model, img, usage)
            for q in qs:
                raw.append((img.name, q))
        except Exception as e:
            result["errors"].append({"imageFile": img.name, "reason": str(e)[:200]})
    result["source"]["totalQuestionsFound"] = len(raw)
    result["source"]["errors"] = len(result["errors"])

    if not raw:
        return result

    # Step 3: classify (batched, text-only)
    classifications = []
    plain = [q for _, q in raw]
    for i in range(0, len(plain), CLASSIFY_BATCH):
        chunk = plain[i:i + CLASSIFY_BATCH]
        try:
            classifications.extend(classify_batch(client, model, chunk, name, meta, usage))
        except Exception as e:
            classifications.extend([{"error": str(e)[:120]}] * len(chunk))

    # Steps 4-6: dedup, validate, assemble
    for (img_name, q), cls in zip(raw, classifications):
        stem = q.get("stem", "")
        qtype = q.get("questionType") or q.get("type") or "mc"

        # dedup vs existing bank
        best_id, best_score = None, 0.0
        for ex_id, ex_stem in existing_stems:
            s = jaccard(stem, ex_stem)
            if s > best_score:
                best_id, best_score = ex_id, s
        # dedup within this batch
        for seen_id, seen_stem in batch_seen:
            s = jaccard(stem, seen_stem)
            if s > best_score:
                best_id, best_score = seen_id, s

        if best_score >= DUP_THRESHOLD:
            result["duplicates"].append({
                "imageFile": img_name, "stemPreview": stem[:80],
                "matchedId": best_id, "similarity": round(best_score, 3)})
            continue

        qid = f"1201-IMG-{next(id_counter):03d}"
        domain = cls.get("domain", "")
        objective = cls.get("objective", "")
        content_module = cls.get("module", "")

        qobj = {
            "id": qid, "domain": domain, "objective": objective,
            "module": content_module, "type": qtype, "stem": stem,
            "options": q.get("options", []),
            "correctAnswer": q.get("correctAnswer", []),
            "explanation": q.get("explanation", ""),
            "classification": {"confidence": cls.get("confidence", "low"),
                               "reasoning": cls.get("reasoning", "")},
        }
        v = validate_question(qobj, meta)
        if v:
            qobj["validationErrors"] = v

        # module mismatch log (content vs folder)
        if content_module and content_module != folder_module:
            result["mismatches"].append({
                "id": qid, "folderModule": folder_module,
                "contentModule": content_module,
                "reason": cls.get("reasoning", "content classified to a different module")})

        result["questions"].append(qobj)
        batch_seen.append((qid, stem))

    result["source"]["questionsKept"] = len(result["questions"])
    result["source"]["duplicatesSkipped"] = len(result["duplicates"])
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Extract CertMaster quiz questions from JPGs.")
    ap.add_argument("--source", required=True)
    ap.add_argument("--output", default="exam_assets/")
    ap.add_argument("--bank", default="exam_assets/questions.json")
    ap.add_argument("--model", default="claude-sonnet-4-20250514")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--folder", default=None, help="glob to limit folders (e.g. '5.1*')")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load bank: metadata + existing stems for dedup.
    bank = json.loads(Path(args.bank).read_text(encoding="utf-8"))
    core1 = bank["exams"]["220-1201"]
    meta = {
        "domains": list(core1["domainWeights"].keys()),
        "objectives": dict(core1["objectives"]),
        "modules": dict(core1["modules"]),
    }
    existing_stems = [(q["id"], q.get("stem", "")) for q in core1["questionBank"]]

    # Discover.
    folders = discover(args.source)
    if args.folder:
        import fnmatch
        folders = [f for f in folders if fnmatch.fnmatch(f["name"], args.folder)]
    total_images = sum(len(f["images"]) for f in folders)
    print(f"Discovered {len(folders)} folder(s), {total_images} image(s).")
    # rough time estimate: ~image reads / workers, ~4s per vision call
    est_min = (total_images * 4) / max(args.workers, 1) / 60
    print(f"Rough estimate: ~{est_min:.1f} min with {args.workers} workers.")

    if not _HAVE_ANTHROPIC:
        print("ERROR: the 'anthropic' package is not installed. "
              "Run: pip install -r tools/requirements_extract.txt", file=sys.stderr)
        sys.exit(2)

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: no API key. Set ANTHROPIC_API_KEY or pass --api-key.", file=sys.stderr)
        sys.exit(2)
    client = anthropic.Anthropic(api_key=api_key)

    usage = Usage()
    id_counter = iter(range(1, 10_000))
    batch_seen = []  # cross-folder dedup within this run
    summary = {
        "totalFolders": len(folders), "totalImages": total_images,
        "totalQuestionsFound": 0, "totalQuestionsKept": 0,
        "totalDuplicatesSkipped": 0, "totalErrors": 0,
        "estimatedCostUSD": 0.0, "totalInputTokens": 0, "totalOutputTokens": 0,
        "perModule": {}, "perFolder": [], "validationFailures": [],
    }

    def bump_module(mod, kept, dupes, errs):
        m = summary["perModule"].setdefault(mod, {"kept": 0, "duplicates": 0, "errors": 0})
        m["kept"] += kept
        m["duplicates"] += dupes
        m["errors"] += errs

    interrupted = False
    for folder in tqdm(folders, desc="folders", total=len(folders)):
        out_file = out_dir / f"extracted_{sanitize_folder(folder['name'])}.json"
        if out_file.exists() and not args.force:
            print(f"  skip (cached): {out_file.name}")
            continue
        try:
            result = process_folder(folder, client, args.model, meta,
                                     existing_stems, batch_seen, id_counter,
                                     usage, args.dry_run)
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
            if "validationErrors" in q:
                for rule in q["validationErrors"]:
                    summary["validationFailures"].append(
                        {"id": q["id"], "rule": rule, "detail": q["stem"][:80]})

        if not args.dry_run:
            out_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    summary["totalInputTokens"] = usage.input_tokens
    summary["totalOutputTokens"] = usage.output_tokens
    summary["estimatedCostUSD"] = round(usage.cost(), 4)
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
    print(f"Tokens: in={usage.input_tokens} out={usage.output_tokens}  "
          f"Est. cost: ${usage.cost():.4f}")
    if summary["validationFailures"]:
        print(f"Validation failures: {len(summary['validationFailures'])}")
        for vf in summary["validationFailures"][:20]:
            print(f"  {vf['id']}: {vf['rule']} — {vf['detail']}")
    if interrupted:
        print("(run was interrupted; partial output written)")


if __name__ == "__main__":
    main()

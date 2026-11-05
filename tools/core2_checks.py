"""Shared safety checks for the Core 2 question banks.

Used by build_questions_core2.py and build_questions_core2_topics.py, which refuse to
write their output if any check fails.  You can also run it on its own; it only reads:

    python tools/core2_checks.py

and it checks exam_assets/questions_core2.json and questions_core2_topics.json.
"""
import json, os, re, sys

DOMAINS = ["1.0 Operating Systems", "2.0 Security",
           "3.0 Software Troubleshooting", "4.0 Operational Procedures"]
REQUIRED = ["id", "domain", "objective", "module", "type", "difficulty",
            "stem", "explanation", "correctAnswer", "origin"]
WORD_COUNT = {"two": 2, "three": 3, "four": 4, "2": 2, "3": 3, "4": 4}
COUNT_RE = re.compile(r"select\s+(two|three|four|[234])\b", re.I)


def answers(q):
    ca = q.get("correctAnswer")
    return ca if isinstance(ca, list) else ([ca] if isinstance(ca, str) else [])


def check_bank(bank, extra_required=()):
    """Return a list of problems (empty list = the bank is safe to save)."""
    problems = []
    ids = [q.get("id") for q in bank]
    dups = sorted({i for i in ids if ids.count(i) > 1}, key=str)
    if dups:
        problems.append("duplicate IDs: " + str(dups))
    for q in bank:
        qid = q.get("id", "?")
        miss = [k for k in list(REQUIRED) + list(extra_required) if k not in q]
        if miss:
            problems.append("%s: missing field(s) %s" % (qid, miss))
            continue
        if q["domain"] not in DOMAINS:
            problems.append("%s: domain '%s' is not one of the four Core 2 domains" % (qid, q["domain"]))
        t = q["type"]
        if t == "drag_drop":
            problems.append("%s: type drag_drop is not supported by the app - use 'matching'" % qid)
        elif t == "matching":
            ca = q["correctAnswer"]
            if not (isinstance(ca, dict) and q.get("items") and all(i in ca for i in q["items"])
                    and all(v in (q.get("options") or []) for v in ca.values())):
                problems.append("%s: matching needs items[], options[] and a {item: option} correctAnswer" % qid)
        elif t in ("mc", "multi"):
            opts = q.get("options") or []
            ans = answers(q)
            if not ans:
                problems.append("%s: no correct answer" % qid)
                continue
            if any((not isinstance(a, str)) or (not a.strip()) for a in ans):
                problems.append("%s: empty entry in correctAnswer" % qid)
            if len(set(ans)) != len(ans):
                problems.append("%s: duplicate entries in correctAnswer" % qid)
            if len(set(opts)) != len(opts):
                problems.append("%s: duplicate options" % qid)
            if any(a not in opts for a in ans):
                problems.append("%s: correctAnswer not in options" % qid)
            n = len(set(ans))
            if t == "mc" and n != 1:
                problems.append("%s: type 'mc' (radio buttons) but %d correct answers - must be 'multi'" % (qid, n))
            if t == "multi" and n < 2:
                problems.append("%s: type 'multi' (checkboxes) but only %d correct answer - must be 'mc'" % (qid, n))
            if n >= len(opts):
                problems.append("%s: every option is marked correct" % qid)
            m = COUNT_RE.search(q["stem"])
            if m and WORD_COUNT[m.group(1).lower()] != n:
                problems.append("%s: stem says '%s' but %d answers are stored" % (qid, m.group(0), n))
        else:
            problems.append("%s: unknown type '%s'" % (qid, t))
    return problems


def report(label, problems):
    if problems:
        print("NOT WRITTEN - fix these first (%s):" % label)
        for p in problems[:40]:
            print("  ", p)
        if len(problems) > 40:
            print("   ... and %d more" % (len(problems) - 40))
    return not problems


def _load(path):
    return json.load(open(path, encoding="utf-8"))["exams"]["220-1202"]["questionBank"]


def main():
    assets = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exam_assets")
    main_bank = _load(os.path.join(assets, "questions_core2.json"))
    topic_bank = _load(os.path.join(assets, "questions_core2_topics.json"))
    ok = True
    for label, bank, extra in (("questions_core2.json", main_bank, ()),
                               ("questions_core2_topics.json", topic_bank, ("topic",))):
        probs = check_bank(bank, extra)
        print("%-30s %4d questions | %d problem(s)" % (label, len(bank), len(probs)))
        for p in probs[:40]:
            print("    ", p)
        ok = ok and not probs
    clash = sorted({q["id"] for q in main_bank} & {q["id"] for q in topic_bank})
    if clash:
        ok = False
        print("IDs used in both banks (mastery is keyed by id):", clash[:20])
    print("ALL CHECKS PASSED" if ok else "CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

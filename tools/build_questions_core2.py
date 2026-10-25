"""Rebuild exam_assets/questions_core2.json from every extracted Core 2 file.

Run:  python tools/build_questions_core2.py
Sources : exam_assets/study_material_core2/*.json and exam_assets/practice_tests_core2/*.json
Output  : exam_assets/questions_core2.json   (questions.json is never touched)
Rules   : never drops a question (duplicates are kept and listed in
          questions_core2_duplicate_groups.json); IDs must stay unique.
"""
import glob, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "exam_assets")
SRC_DIRS = ["study_material_core2", "practice_tests_core2"]
REQUIRED = ["id", "domain", "objective", "module", "type", "difficulty",
            "stem", "explanation", "correctAnswer", "origin"]  # matching has no list-style correctAnswer

# Header values the web app reads. domainWeights KEYS must equal the `domain`
# tags on the questions (the Practice-by-Domain picker matches on them).
DOMAIN_WEIGHTS = {"1.0 Operating Systems": 28, "2.0 Security": 28,
                  "3.0 Software Troubleshooting": 23, "4.0 Operational Procedures": 21}
EXAM_LENGTH, TIME_LIMIT = 90, 90


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def main():
    old = json.load(open(os.path.join(ASSETS, "questions_core2.json"), encoding="utf-8"))
    hdr = {k: v for k, v in old["exams"]["220-1202"].items() if k != "questionBank"}

    bank = []
    for d in SRC_DIRS:
        for f in sorted(glob.glob(os.path.join(ASSETS, d, "*.json"))):
            bank += json.load(open(f, encoding="utf-8"))

    problems = []
    ids = [q.get("id") for q in bank]
    if len(ids) != len(set(ids)):
        problems.append("duplicate IDs: " + str(sorted({i for i in ids if ids.count(i) > 1})))
    for q in bank:
        if any(k not in q for k in REQUIRED):
            problems.append(q.get("id", "?") + ": missing field")
        elif q["type"] == "drag_drop":
            problems.append(q["id"] + ": type drag_drop is not supported by the app - use 'matching'")
        elif q["type"] == "matching":
            ca = q["correctAnswer"]
            if not (isinstance(ca, dict) and all(i in ca for i in q.get("items", []))
                    and all(v in (q.get("options") or []) for v in ca.values())):
                problems.append(q["id"] + ": matching needs items[], options[] and a {item: option} correctAnswer")
        elif not all(a in (q.get("options") or []) for a in q["correctAnswer"]):
            problems.append(q["id"] + ": correctAnswer not in options")
        elif q["domain"] not in DOMAIN_WEIGHTS:
            problems.append(q["id"] + ": domain '" + q["domain"] + "' not in domainWeights")
    if problems:
        print("NOT WRITTEN - fix these first:")
        for p in problems:
            print("  ", p)
        sys.exit(1)

    hdr.update(domainWeights=DOMAIN_WEIGHTS, questions=EXAM_LENGTH, timeLimit=TIME_LIMIT)
    out = {"exams": {"220-1202": dict(hdr, questionBank=bank)}}
    json.dump(out, open(os.path.join(ASSETS, "questions_core2.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    seen = {}
    for q in bank:
        seen.setdefault(norm(q["stem"]), []).append(q["id"])
    groups = [v for v in seen.values() if len(v) > 1]
    json.dump(groups, open(os.path.join(ASSETS, "questions_core2_duplicate_groups.json"), "w"), indent=1)
    print("Wrote %d questions | %d duplicate groups kept" % (len(bank), len(groups)))


if __name__ == "__main__":
    main()

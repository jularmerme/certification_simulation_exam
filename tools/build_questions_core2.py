"""Rebuild exam_assets/questions_core2.json from every extracted Core 2 file.

Run:  python tools/build_questions_core2.py
Sources : exam_assets/study_material_core2/*.json and exam_assets/practice_tests_core2/*.json
Output  : exam_assets/questions_core2.json   (questions.json is never touched)
Rules   : never drops a question (duplicates are kept and listed in
          questions_core2_duplicate_groups.json); IDs must stay unique.
"""
import glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core2_checks

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

    problems = core2_checks.check_bank(bank)

    # Never lose questions: every ID already in the bank must still be in the rebuilt one.
    # (The lesson files only cover Modules 11-15 and the originals, so rebuilding from them
    #  alone would drop the questions that exist only inside questions_core2.json.)
    prev_ids = [q["id"] for q in old["exams"]["220-1202"]["questionBank"]]
    new_ids = {q.get("id") for q in bank}
    lost = [i for i in prev_ids if i not in new_ids]
    if lost and "--force" not in sys.argv:
        problems.append("this rebuild would DROP %d of the %d questions now in questions_core2.json "
                        "(first ones: %s). Add their source files, or pass --force if you really mean it."
                        % (len(lost), len(prev_ids), ", ".join(lost[:5])))
    if problems:
        core2_checks.report("questions_core2.json", problems)
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

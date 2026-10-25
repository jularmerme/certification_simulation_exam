"""Rebuild exam_assets/questions_core2_topics.json (Core 2 "Practice by Topic").

Run:  python tools/build_questions_core2_topics.py
Sources: exam_assets/topic_quizzes_core2/*.json  (one file per ExamCompass topic;
         every question carries a "topic" field and a unique id)
Output : exam_assets/questions_core2_topics.json
Rules  : never drops a question; ids must be unique and must not collide with
         ids in questions_core2.json (mastery progress is keyed by id).
"""
import glob, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "exam_assets")
TOPIC_ORDER = [
    "Common OS Types",
    "Filesystem Types",
    "OS Boot Methods",
    "OS Installation Methods",
    "Microsoft Windows Editions",
    "MS Windows Basic Features",
    "Windows Task Manager",
    "Windows MMC Snap-ins",
    "Windows Additional Admin Tools",
    "Microsoft Command-Line Tools",
    "Microsoft Windows Settings",
    "Windows Networking Features",
    "macOS",
    "Linux Command Line",
    "Linux OS Features & Tools",
    "Physical Security Concepts",
    "Logical Security Concepts",
    "Windows OS Security",
    "NTFS & Share Permissions",
    "Active Directory",
    "Wireless Security",
    "Malware",
    "Social Engineering",
    "Threats & Vulnerabilities",
    "Malware Removal Procedures",
    "Workstation Security",
    "Mobile Device Security",
    "Data Destruction & Disposal Methods",
    "SOHO Network Security",
    "Web Browser Security",
    "Windows OS Troubleshooting",
    "Mobile OS and App Troubleshooting",
    "Common PC Security Issues Troubleshooting",
    "Ticketing Systems",
    "Asset Management",
    "Change Management Procedures",
    "Backup & Recovery Methods",
    "Common Safety Procedures",
    "Environmental Impacts & Controls",
    "Incident Response",
    "Software Licensing Concepts",
    "Regulated Data",
    "Communication & Professionalism",
    "Scripting Basics",
    "Remote Access Technologies",
    "Basic AI Concepts",
]

REQUIRED = ["id", "topic", "domain", "objective", "module", "type", "difficulty",
            "stem", "explanation", "correctAnswer", "origin"]


def main():
    bank = []
    for f in sorted(glob.glob(os.path.join(ASSETS, "topic_quizzes_core2", "*.json"))):
        bank += json.load(open(f, encoding="utf-8"))

    main_ids = set()
    mp = os.path.join(ASSETS, "questions_core2.json")
    if os.path.exists(mp):
        main_ids = {q["id"] for q in json.load(open(mp, encoding="utf-8"))["exams"]["220-1202"]["questionBank"]}

    problems, ids = [], [q.get("id") for q in bank]
    if len(ids) != len(set(ids)):
        problems.append("duplicate IDs: " + str(sorted({i for i in ids if ids.count(i) > 1})))
    for i in sorted(set(ids) & main_ids):
        problems.append(i + ": id also exists in questions_core2.json")
    for q in bank:
        if any(k not in q for k in REQUIRED):
            problems.append(q.get("id", "?") + ": missing field")
        elif q["type"] == "drag_drop":
            problems.append(q["id"] + ": drag_drop is not supported - use 'matching'")
        elif q["type"] == "matching":
            ca = q["correctAnswer"]
            if not (isinstance(ca, dict) and all(i in ca for i in q.get("items", []))
                    and all(v in (q.get("options") or []) for v in ca.values())):
                problems.append(q["id"] + ": malformed matching question")
        elif not all(a in (q.get("options") or []) for a in q["correctAnswer"]):
            problems.append(q["id"] + ": correctAnswer not in options")
    if problems:
        print("NOT WRITTEN - fix these first:")
        for p in problems:
            print("  ", p)
        sys.exit(1)

    unknown = sorted({q["topic"] for q in bank} - set(TOPIC_ORDER))
    if unknown:
        print("NOT WRITTEN - topic(s) not in TOPIC_ORDER (fix the name or add it to the list):", unknown)
        sys.exit(1)
    topics = list(TOPIC_ORDER)   # every topic is listed in the app, in this order; empty ones show as disabled
    out = {"exams": {"220-1202": {
        "name": "CompTIA A+ Core 2 - Practice by Topic", "code": "220-1202",
        "source": "ExamCompass", "topics": topics, "questions": len(bank),
        "questionBank": bank}}}
    json.dump(out, open(os.path.join(ASSETS, "questions_core2_topics.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    print("Wrote %d questions in %d topic(s): %s" % (len(bank), len(topics), ", ".join(topics)))


if __name__ == "__main__":
    main()

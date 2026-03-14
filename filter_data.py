import json
from pathlib import Path

# Important keywords that indicate real admission/academic information
KWS = ["fee", "tuition", "admission", "eligibility", "scholarship", "hostel", "syllabus", "placement", "btech"]

def filter_srm_data():
    path = Path("data/raw/srm_data.json")
    if not path.exists():
        print("srm_data.json not found")
        return

    with open(path, "r", encoding="utf-8") as f:
        docs = json.load(f)

    filtered_docs = []
    dropped = 0

    for d in docs:
        text = d["content"].lower()
        cat = d.get("category", "general")
        
        # Keep non-course/non-campus pages as they are rare and often valuable
        if cat not in ["course_info", "campus_life", "general"]:
            filtered_docs.append(d)
            continue
            
        # For course_info and campus_life, enforce stricter quality checks
        # Drop if no tables AND (too short OR doesn't contain at least one important keyword)
        has_tables = len(d.get("tables", [])) > 0
        if not has_tables and (len(text) < 800 or not any(kw in text for kw in KWS)):
            dropped += 1
            continue
            
        filtered_docs.append(d)

    print(f"Original documents: {len(docs)}")
    print(f"Dropped documents: {dropped}")
    print(f"Remaining documents: {len(filtered_docs)}")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(filtered_docs, f, indent=2, ensure_ascii=False)
        print("Saved filtered data back to srm_data.json.")

if __name__ == "__main__":
    filter_srm_data()

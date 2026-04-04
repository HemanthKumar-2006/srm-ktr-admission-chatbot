import json, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

OUT = []
def p(s=""):
    OUT.append(str(s))

KG_PATH = os.path.join("vector_db_qdrant", "knowledge_graph.json")
AP_PATH = os.path.join("vector_db_qdrant", "admission_profiles.json")

p(f"admission_profiles.json exists: {os.path.exists(AP_PATH)}")
p(f"knowledge_graph.json exists: {os.path.exists(KG_PATH)}")

with open(KG_PATH, "r", encoding="utf-8") as f:
    kg_data = json.load(f)

entities = kg_data["entities"]
rels = kg_data["relationships"]

p(f"\nTotal entities: {len(entities)}")
p(f"Total relationships: {len(rels)}")

# Count entity types
from collections import Counter
type_counts = Counter(e["entity_type"] for e in entities.values())
p(f"\nEntity type counts:")
for t, c in sorted(type_counts.items()):
    p(f"  {t}: {c}")

# Check if any admission entities exist
p("\n=== ADMISSION ENTITIES ===")
adm_entities = {eid: e for eid, e in entities.items() if e["entity_type"] == "admission"}
p(f"Count: {len(adm_entities)}")
for eid, e in adm_entities.items():
    attrs = e.get("attributes", {})
    p(f"  {eid}: {e['name']}")
    p(f"    url: {e.get('url','')}")
    p(f"    attrs: {attrs}")

# AI/ML programs
p("\n=== AI/ML PROGRAMS ===")
for eid, e in entities.items():
    if e["entity_type"] != "program":
        continue
    nl = e["name"].lower()
    if any(kw in nl for kw in ["artificial","machine learning"]):
        parents = [r["source_id"] for r in rels if r["target_id"]==eid and r["relation_type"]=="offers_program"]
        ag = [r["source_id"] for r in rels if r["target_id"]==eid and r["relation_type"]=="admission_governs"]
        p(f"  {eid}: {e['name']}")
        p(f"    parents: {parents}")
        p(f"    adm_governs: {ag}")

# Law programs  
p("\n=== LAW PROGRAMS ===")
for eid, e in entities.items():
    if e["entity_type"] != "program":
        continue
    nl = e["name"].lower()
    if any(kw in nl for kw in ["law","llb","llm"]):
        parents = [r["source_id"] for r in rels if r["target_id"]==eid and r["relation_type"]=="offers_program"]
        ag = [r["source_id"] for r in rels if r["target_id"]==eid and r["relation_type"]=="admission_governs"]
        p(f"  {eid}: {e['name']}")
        p(f"    parents: {parents}")
        p(f"    adm_governs: {ag}")

# Law entities (all types)
p("\n=== LAW ENTITIES (ALL TYPES) ===")
for eid, e in entities.items():
    if "law" in eid.lower() or "law" in e["name"].lower():
        p(f"  {eid}: {e['name']} (type={e['entity_type']})")

# Check admission relationship types  
p("\n=== ADMISSION RELATIONSHIP TYPES ===")
adm_rel_types = Counter()
for r in rels:
    if "admission" in r["source_id"] or "admission" in r["target_id"] or "admission" in r["relation_type"]:
        adm_rel_types[r["relation_type"]] += 1
for rt, c in sorted(adm_rel_types.items()):
    p(f"  {rt}: {c}")

# Test _infer_exam_name
p("\n=== _infer_exam_name RESULTS ===")
from backend.admission_profiles import _infer_exam_name
test_cases = [
    ("B.Tech", "Artificial Intelligence and Machine Learning", "", ""),
    ("B.Tech", "Computer Science Engineering", "", ""),
    ("BA LLB", "Law", "", ""),
    ("BBA LLB", "Law", "", ""),
    ("LL.M.", "Corporate Law", "", ""),
    ("M.Tech", "Computer Science", "", ""),
    ("MBA", "Finance", "", ""),
    ("B.Arch", "Architecture", "", ""),
    ("B.Tech", "AI", "SRMJEEE", ""),
    ("BA LLB", "Law", "SRMJEEL", ""),
]
for deg, spec, criteria, how in test_cases:
    result = _infer_exam_name(deg, spec, criteria, how)
    p(f"  {deg} + {spec} (criteria={criteria or 'empty'}) -> {result or '(NO EXAM INFERRED)'}")

# Check scraped admission pages
p("\n=== SCRAPED ADMISSION PAGES ===")
data_path = os.path.join("backend", "data", "srm_docs")
if os.path.exists(data_path):
    admission_pages = []
    for folder in os.listdir(data_path):
        meta_path = os.path.join(data_path, folder, "metadata.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                url = meta.get("url", "")
                if "admission" in url.lower():
                    admission_pages.append(url)
            except:
                pass
    p(f"Total admission-related pages: {len(admission_pages)}")
    for u in sorted(admission_pages)[:20]:
        p(f"  {u}")
else:
    p(f"Data path {data_path} not found")

# Write output
result_path = os.path.join("_inspect_result.txt")
with open(result_path, "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print(f"Output written to {result_path} ({len(OUT)} lines)")

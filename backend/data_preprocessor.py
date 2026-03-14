"""
backend/data_preprocessor.py
SRM Chatbot — Data Preprocessing & Quality Pipeline

Fixes addressed:
  FACT 1: Category name mismatch between scraper output and RAG pipeline
  FACT 2: fee_structure records polluted with irrelevant pages
  FACT 3: Two distinct table row formats (proper dict vs {"columns": [...]})
  FACT 4: Table data often already duplicated in content field
  FACT 5: Domestic INR B.Tech fee data is not well-structured (flagged as warning)

Run:
    python backend/data_preprocessor.py

Input:  data/raw/srm_data.json
Output: data/processed/srm_data_cleaned.json
"""

import json
import os
from pathlib import Path

# ================== PATHS ==================
INPUT_PATH = Path("data/raw/srm_data.json")
OUTPUT_PATH = Path("data/processed/srm_data_cleaned.json")

# ================== STOPWORDS ==================
STOPWORDS = {
    "the", "a", "an", "is", "in", "of", "and", "for", "to",
    "with", "at", "by", "on", "or", "as", "be", "it", "are",
    "this", "that", "was", "were", "has", "have", "had", "not",
    "from", "but", "also", "its", "our", "their", "all",
}

# ================== 1A: CATEGORY NORMALIZATION MAP ==================
# Maps old scraper category names → new RAG pipeline-compatible names
CATEGORY_NORMALIZE_MAP = {
    "admission":    "admission_process",
    "hostel":       "hostel_info",
    "course_info":  "course_details",
    "general":      "general_query",
    # These two already match — leave them:
    # "fee_structure" -> "fee_structure"
    # "campus_life"   -> "campus_life"
}

# ================== 1B: URL/TITLE RECATEGORIZATION RULES ==================
# Priority-ordered: first match wins
CATEGORY_URL_RULES = {
    "fee_structure": [
        "fee", "fees", "tuition", "charges", "payment",
        "financial", "admission-international", "admission-india",
    ],
    "admission_process": [
        "admission", "apply", "application", "frro",
        "visa", "international-admission", "enroll", "register",
        "ir/",
    ],
    "hostel_info": [
        "hostel", "accommodation", "residence", "boarding",
        "mess", "srm-hostels",
    ],
    "course_details": [
        "department", "program", "curriculum", "syllabus",
        "infrastructure", "faculty", "research", "patent",
        "lab", "publication", "project",
    ],
    "campus_life": [
        "campus", "club", "activity", "sports", "event",
        "cultural", "fest", "blog", "news",
    ],
    "eligibility": [
        "eligibility", "criteria", "cutoff", "jee",
        "entrance", "merit", "qualification",
    ],
}

# Override: if URL strongly indicates NOT a fee page, un-assign fee_structure
NON_FEE_OVERRIDES = [
    "/faculty/", "/lab/", "/department/", "/blog/",
    "/news/", "/awards", "/accolades", "/publications",
    "/research/", "/projects/",
]

# ================== 1B: RECATEGORIZE ==================
def recategorize(record: dict) -> str:
    """
    Assigns category based on URL + title using priority-ordered rules.
    Applies a second-pass override to prevent polluted fee_structure assignments.
    """
    url = record.get("url", "").lower()
    title = record.get("title", "").lower()
    haystack = url + " " + title

    matched_category = None
    for category, keywords in CATEGORY_URL_RULES.items():
        if any(kw in haystack for kw in keywords):
            matched_category = category
            break

    if matched_category == "fee_structure":
        # Second pass: override if URL strongly suggests it's not a fee page
        if any(pat in url for pat in NON_FEE_OVERRIDES):
            # Re-run without fee_structure rule
            matched_category = None
            for category, keywords in CATEGORY_URL_RULES.items():
                if category == "fee_structure":
                    continue
                if any(kw in haystack for kw in keywords):
                    matched_category = category
                    break
            if matched_category is None:
                matched_category = "course_details"

    return matched_category  # None = no match found; caller handles fallback

# ================== 1C: TABLE-TO-NATURAL-LANGUAGE ==================
def table_to_nl(table: dict, page_title: str) -> str:
    """
    Converts a table dict into readable natural language sentences.

    Handles two row formats:
    - Format A (normal): {"Campus": "KTR", "Degree": "B.Tech", "Fee": "2,10,000"}
    - Format B (malformed): {"columns": ["KTR", "B.Tech", "2,10,000"]}

    Rules:
    - Skip values that are empty / None / whitespace
    - Skip rows producing fewer than 2 valid key-value pairs
    - Returns "" if all rows were skipped
    """
    headers = table.get("headers", [])
    rows = table.get("rows", [])
    prefix = f"[Title: {page_title}]"
    sentences = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        if "columns" in row and isinstance(row["columns"], list):
            # Format B — malformed, try to pair with headers
            col_values = row["columns"]
            if len(headers) == len(col_values):
                pairs = {
                    str(h): str(v)
                    for h, v in zip(headers, col_values)
                    if v is not None and str(v).strip()
                }
            else:
                # Header count mismatch — fallback to plain listing
                clean_vals = [str(v) for v in col_values if v is not None and str(v).strip()]
                if len(clean_vals) < 2:
                    continue
                sentences.append(f"{prefix} Row data: {', '.join(clean_vals)}.")
                continue
        else:
            # Format A — normal key-value dict
            pairs = {
                str(k): str(v)
                for k, v in row.items()
                if v is not None and str(v).strip() and k != "columns"
            }

        if len(pairs) < 2:
            continue  # too sparse

        kv_str = ", ".join(f"{k}: {v}" for k, v in pairs.items())
        sentences.append(f"{prefix} {kv_str}.")

    return "\n".join(sentences)


def is_duplicate_content(new_text: str, existing_content: str) -> bool:
    """
    Returns True if >50% of unique non-stopword tokens in new_text already
    appear in existing_content — meaning the data is already present.
    """
    new_words = set(new_text.lower().split()) - STOPWORDS
    if len(new_words) == 0:
        return True
    overlap = sum(1 for w in new_words if w in existing_content.lower())
    return (overlap / len(new_words)) > 0.5


# ================== 1D: CONTENT ENRICHMENT LOOP ==================
def process_record(record: dict, stats: dict) -> dict:
    """
    Applies category normalization, re-categorization, and table NL enrichment
    to a single record. Mutates stats dict for summary reporting.
    """
    record = dict(record)  # shallow copy

    # Step 1: Category normalization (1A)
    original_cat = record.get("category", "")
    normalized_cat = CATEGORY_NORMALIZE_MAP.get(original_cat, original_cat)
    if normalized_cat != original_cat:
        stats["normalized"][original_cat] = stats["normalized"].get(original_cat, 0) + 1
    record["category"] = normalized_cat

    # Step 2: URL/title based re-categorization (1B)
    new_cat = recategorize(record)
    if new_cat is not None and new_cat != normalized_cat:
        record["category"] = new_cat
        # Track fee_structure re-cleans specifically
        if normalized_cat == "fee_structure" and new_cat != "fee_structure":
            stats["fee_recleaned"] = stats.get("fee_recleaned", 0) + 1

    # Step 3: Table-to-NL enrichment (1C, 1D)
    tables = record.get("tables", [])
    existing_content = record.get("content", "")
    appended_count = 0
    skipped_count = 0
    malformed_count = 0

    for table in tables:
        # Count malformed rows
        for row in table.get("rows", []):
            if isinstance(row, dict) and "columns" in row:
                malformed_count += 1

        nl_block = table_to_nl(table, record.get("title", ""))
        if not nl_block:
            continue
        if is_duplicate_content(nl_block, existing_content):
            skipped_count += 1
            continue
        existing_content = existing_content + "\n\n" + nl_block
        appended_count += 1

    record["content"] = existing_content
    stats["nl_appended"] = stats.get("nl_appended", 0) + appended_count
    stats["nl_skipped"] = stats.get("nl_skipped", 0) + skipped_count
    stats["malformed_rows"] = stats.get("malformed_rows", 0) + malformed_count

    return record


# ================== 1E: DOMESTIC FEE GAP WARNING ==================
def print_domestic_fee_warning(records: list):
    """
    Counts records with domestic INR fee indicators and warns if sparse.
    (FACT 5 — domestic fee data is not well-structured in this dataset)
    """
    domestic_fee_keywords = ["INR", "₹", "per annum"]
    count = sum(
        1 for r in records
        if r.get("category") == "fee_structure"
        and r.get("campus", "").lower() == "ktr"
        and any(kw in r.get("content", "") for kw in domestic_fee_keywords)
    )

    print(f"""
⚠️  DOMESTIC FEE DATA WARNING:
    Only {count} records contain structured domestic (INR) fee data.
    The dataset is primarily international (USD) fee data.
    Consider re-scraping: https://www.srmist.edu.in/admission-india/
    for domestic B.Tech fee tables before deploying this chatbot.
""")


# ================== 1G: QUICK AUDIT ==================
def quick_audit(filepath="data/processed/srm_data_cleaned.json"):
    """
    Prints a diagnostic report to verify re-categorization worked correctly.
    Run after preprocessing to confirm fee data is accessible.
    """
    print("\n" + "=" * 50)
    print("📋 QUICK AUDIT REPORT")
    print("=" * 50)

    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    fee_keywords = ["fee", "fees", "tuition", "charges", "admission-international", "admission-india"]

    fee_url_records = [
        r for r in data
        if any(kw in r.get("url", "").lower() for kw in fee_keywords)
    ]

    correct = sum(1 for r in fee_url_records if r.get("category") == "fee_structure")
    incorrect = len(fee_url_records) - correct

    print(f"\nRecords with fee-related URLs: {len(fee_url_records)}")
    print(f"  ✅ Correctly categorized as fee_structure: {correct}")
    print(f"  ❌ Incorrectly categorized (not fee_structure): {incorrect}")

    if incorrect > 0:
        print("\n  Incorrectly categorized records (first 5):")
        shown = 0
        for r in fee_url_records:
            if r.get("category") != "fee_structure":
                print(f"    title={r['title']!r}")
                print(f"    url={r['url']}")
                print(f"    category={r['category']}")
                print()
                shown += 1
                if shown >= 5:
                    break

    # Print all fee-url records with their categories for visibility
    print("\n  All fee-URL records:")
    for r in fee_url_records:
        print(f"    [{r['category']:20s}] {r['title'][:60]}")
        print(f"     {r['url']}")

    # Top 3 richest records (by content length)
    top3 = sorted(data, key=lambda r: len(r.get("content", "")), reverse=True)[:3]
    print("\n\nTop 3 richest records (longest content):")
    for i, r in enumerate(top3, 1):
        print(f"  [{i}] {r['title']} ({len(r.get('content',''))} chars)")
        print(f"      category={r['category']} | url={r['url']}")

    print("\n" + "=" * 50)


# ================== 4B: CATEGORY CONSISTENCY CHECK ==================
FORBIDDEN_OLD_CATEGORIES = {"course_info", "admission", "hostel", "general"}


def check_category_consistency(filepath="data/processed/srm_data_cleaned.json"):
    """
    Verifies no old category names remain in the processed file.
    Must pass (0 violations) before re-ingesting into ChromaDB.
    """
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    violations = [d for d in data if d.get("category") in FORBIDDEN_OLD_CATEGORIES]
    if violations:
        print(f"\n❌ CONSISTENCY ERROR: {len(violations)} records still have old category names!")
        for v in violations[:5]:
            print(f"   url={v['url']} category={v['category']}")
    else:
        print(f"\n✅ Category consistency check passed — all {len(data)} records use new names.")


# ================== 1F: MAIN EXECUTION BLOCK ==================
if __name__ == "__main__":
    print("🚀 SRM Data Preprocessor starting...")

    if not INPUT_PATH.exists():
        print(f"❌ Input file not found: {INPUT_PATH}")
        exit(1)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(INPUT_PATH, encoding="utf-8") as f:
        raw_data = json.load(f)

    input_count = len(raw_data)
    print(f"   Loaded {input_count} records from {INPUT_PATH}")

    stats = {
        "normalized": {},   # old_cat -> count
        "nl_appended": 0,
        "nl_skipped": 0,
        "malformed_rows": 0,
        "fee_recleaned": 0,
    }

    # Track category distribution before processing
    cat_before = {}
    for r in raw_data:
        c = r.get("category", "unknown")
        cat_before[c] = cat_before.get(c, 0) + 1

    # Process all records
    processed_data = [process_record(r, stats) for r in raw_data]

    # Track category distribution after processing
    cat_after = {}
    for r in processed_data:
        c = r.get("category", "unknown")
        cat_after[c] = cat_after.get(c, 0) + 1

    # Write output
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(processed_data, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Output written to {OUTPUT_PATH}")

    # Print summary
    print("\n" + "=" * 45)
    print("=== SRM Data Preprocessor Summary ===")
    print("=" * 45)
    print(f"Input records:    {input_count}")
    print(f"Output records:   {len(processed_data)}  (no records removed)")

    print("\nCategory distribution (before → after):")
    normalize_display = {
        "course_info":  "course_details",
        "admission":    "admission_process",
        "hostel":       "hostel_info",
        "general":      "general_query",
        "fee_structure": "fee_structure",
        "campus_life":   "campus_life",
    }
    for old, new in normalize_display.items():
        before_n = cat_before.get(old, 0)
        after_n = cat_after.get(new, 0)
        suffix = "(unchanged)" if old == new else f"→ {new}:"
        if old != new:
            print(f"  {old:20s} → {new:25s} {before_n:5d} records (normalized)")
        else:
            print(f"  {old:20s} {'(unchanged):':26s} {after_n:5d} records")

    print(f"\n  fee_structure re-cleaned (removed from fee_structure): {stats.get('fee_recleaned', 0)} records")
    print(f"\nTable NL blocks appended: {stats['nl_appended']}")
    print(f"Table NL blocks skipped (duplicate): {stats['nl_skipped']}")
    print(f"Malformed rows (columns-key format) handled: {stats['malformed_rows']}")
    print("=" * 45)

    # 1E: Domestic fee gap warning
    print_domestic_fee_warning(processed_data)

    # 1G: Quick audit
    quick_audit(str(OUTPUT_PATH))

    # 4B: Category consistency check
    check_category_consistency(str(OUTPUT_PATH))

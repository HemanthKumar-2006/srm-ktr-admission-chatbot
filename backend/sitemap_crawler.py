import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from pathlib import Path
import json
import time
import re
from bs4 import BeautifulSoup
import random

# ================= CONFIG =================

SITEMAP_INDEX = "https://www.srmist.edu.in/sitemap.xml"
BASE_DOMAIN = "www.srmist.edu.in"

MAX_URLS = 8000
CRAWL_DELAY = (0.6, 1.2)
TIMEOUT = 25
MAX_RETRIES = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0 Safari/537.36"
    )
}

session = requests.Session()
session.headers.update(HEADERS)

# ================= CATEGORY CLASSIFICATION =================
# Shared with scraper.py — identical logic for consistency

CATEGORY_RULES = [
    {
        "category": "fee_structure",
        "url_keywords": ["fee", "tuition", "scholarship"],
        "content_keywords": ["fee", "tuition", "semester", "per annum", "₹", "inr", "scholarship"],
    },
    {
        "category": "admission",
        "url_keywords": ["admission", "apply", "entrance", "srmjeee", "eligibility"],
        "content_keywords": ["admission", "eligibility", "entrance", "apply", "srmjeee", "cutoff"],
    },
    {
        "category": "hostel",
        "url_keywords": ["hostel", "accommodation", "mess"],
        "content_keywords": ["hostel", "accommodation", "mess", "room", "warden", "boys", "girls"],
    },
    {
        "category": "course_info",
        "url_keywords": ["program", "course", "btech", "mtech", "mba", "department", "engineering", "curriculum"],
        "content_keywords": ["curriculum", "syllabus", "semester", "credit", "elective", "program", "degree"],
    },
    {
        "category": "campus_life",
        "url_keywords": ["campus", "life-at-srm", "placement", "club", "facility"],
        "content_keywords": ["campus", "placement", "club", "facility", "sports", "library", "lab"],
    },
]


def classify_category(url: str, text: str) -> str:
    """Classify a page into a domain category based on URL and content keywords."""
    url_lower = url.lower()
    text_lower = text.lower()

    best_category = "general"
    best_score = 0

    for rule in CATEGORY_RULES:
        score = 0
        for kw in rule["url_keywords"]:
            if kw in url_lower:
                score += 3
        for kw in rule["content_keywords"]:
            count = text_lower.count(kw)
            score += min(count, 5)

        if score > best_score:
            best_score = score
            best_category = rule["category"]

    if best_score < 3:
        return "general"

    return best_category


# ================= URL FILTER =================

def is_valid(url: str) -> bool:
    parsed = urlparse(url)

    if BASE_DOMAIN not in parsed.netloc:
        return False

    url_lower = url.lower()

    bad_words = [
        "wp-admin", "login", "signup", "news",
        "press", "sports", "events", "tournament",
        "jpeg", "jpg", "png", "gif", "svg", "#",
    ]

    if any(b in url_lower for b in bad_words):
        return False

    return True


# ================= ROBUST REQUEST =================

def fetch(url: str):
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(url, timeout=TIMEOUT)

            if r.status_code in (403, 429):
                time.sleep(2 + attempt)
                continue

            r.raise_for_status()
            return r.text

        except Exception:
            time.sleep(2 + attempt)

    return None


# ================= SITEMAP PARSER =================

def get_all_sitemaps():
    print("[INFO] Fetching sitemap index...")

    xml_text = fetch(SITEMAP_INDEX)
    if not xml_text:
        raise Exception("Failed to fetch sitemap index")

    root = ET.fromstring(xml_text)
    ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    sitemaps = [loc.text.strip() for loc in root.findall(".//ns:loc", ns)]

    print(f"[INFO] Found {len(sitemaps)} sitemap files")
    return sitemaps


def extract_urls_from_sitemap(sitemap_url):
    try:
        xml_text = fetch(sitemap_url)
        if not xml_text:
            return []

        root = ET.fromstring(xml_text)
        ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}

        urls = [loc.text.strip() for loc in root.findall(".//ns:loc", ns)]
        return urls

    except Exception as e:
        print(f"[ERROR] sitemap {sitemap_url} -> {e}")
        return []


# ================= METADATA EXTRACTION =================

def extract_page_title(soup: BeautifulSoup) -> str:
    """Extract the best available page title."""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
        if len(title) > 5:
            return title

    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)
        title = re.split(r"\s*[|–—-]\s*SRM", title, maxsplit=1)[0].strip()
        if len(title) > 3:
            return title

    return "Untitled Page"


def extract_tables_structured(soup: BeautifulSoup) -> list[dict]:
    """Extract tables as structured data (list of row-dicts)."""
    structured_tables = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        header_cells = rows[0].find_all(["th", "td"])
        headers = [cell.get_text(" ", strip=True) for cell in header_cells]

        table_data = []
        for row in rows[1:]:
            cols = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if cols:
                if headers and len(cols) == len(headers):
                    table_data.append(dict(zip(headers, cols)))
                else:
                    table_data.append({"columns": cols})

        if table_data:
            structured_tables.append({
                "headers": headers,
                "rows": table_data,
            })

    return structured_tables


# ================= CAMPUS CLASSIFICATION =================
# Shared with scraper.py — identical logic for consistency

CAMPUS_RULES = [
    {"id": "ktr", "names": ["ktr", "kattankulathur", "chennai main"]},
    {"id": "rmp", "names": ["rmp", "ramapuram"]},
    {"id": "vdp", "names": ["vdp", "vadapalani"]},
    {"id": "ncr", "names": ["ncr", "modinagar", "delhi"]},
    {"id": "trp", "names": ["trp", "tiruchirappalli", "trichy"]},
    {"id": "ap", "names": ["amaravati", "andhra pradesh"]},
]


def extract_campus(url: str, text: str) -> str:
    """Identify the specific campus from URL or content."""
    url_lower = url.lower()
    text_lower = text.lower()

    # Priority 1: URL path
    for campus in CAMPUS_RULES:
        if campus["id"] in url_lower:
            return campus["id"]
        for name in campus["names"]:
            if name in url_lower:
                return campus["id"]

    # Priority 2: Content mentions (count occurrences)
    campus_scores = {}
    for campus in CAMPUS_RULES:
        score = 0
        for name in campus["names"]:
            score += text_lower.count(name)
        if score > 0:
            campus_scores[campus["id"]] = score

    if campus_scores:
        # Return the one with highest mentions
        return max(campus_scores, key=campus_scores.get)

    return "ktr"  # Default to KTR as per project scope


# ================= TEXT CLEANER =================

def extract_page_data(html: str, url: str) -> dict | None:
    """Extract enriched page data with title, category, campus, tables, and clean content."""
    soup = BeautifulSoup(html, "html.parser")

    main = soup.find("main") or soup.find("article") or soup.body
    if not main:
        return None

    title = extract_page_title(soup)
    tables_structured = extract_tables_structured(soup)

    # Table text for embedding into content
    table_lines = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cols = [
                c.get_text(" ", strip=True)
                for c in row.find_all(["td", "th"])
            ]
            if cols:
                table_lines.append(" | ".join(cols))

    # Remove junk tags
    for tag in main([
        "script", "style", "nav", "footer",
        "header", "aside", "form", "noscript"
    ]):
        tag.decompose()

    text = main.get_text(" ", strip=True)

    if table_lines:
        text += " " + " ".join(table_lines)

    text = re.sub(r"\s+", " ", text).strip()

    # Quality filter
    if not text or len(text) < 400 or len(text.split()) < 80:
        return None

    category = classify_category(url, text)

    # Extract campus
    campus = extract_campus(url, text)

    return {
        "url": url,
        "title": title,
        "category": category,
        "campus": campus,
        "content": text,
        "tables": tables_structured,
    }


# ================= PRIORITY SORT =================

IMPORTANT_KEYWORDS = [
    "admission", "fee", "tuition", "btech",
    "engineering", "hostel", "campus",
    "course", "ktr",
]

def sort_urls(urls):
    priority = []
    normal = []

    for u in urls:
        if any(k in u.lower() for k in IMPORTANT_KEYWORDS):
            priority.append(u)
        else:
            normal.append(u)

    return priority + normal


# ================= MAIN =================

def crawl_from_sitemap():
    documents = []
    category_counts = {}

    sitemap_files = get_all_sitemaps()

    all_urls = set()

    for sm in sitemap_files:
        urls = extract_urls_from_sitemap(sm)
        all_urls.update(urls)

    print(f"[INFO] Total URLs discovered: {len(all_urls)}")

    # filter
    filtered_urls = [u for u in all_urls if is_valid(u)]
    filtered_urls = sort_urls(filtered_urls)

    print(f"[INFO] After filtering: {len(filtered_urls)}")

    visited = set()

    for i, url in enumerate(filtered_urls):
        if len(documents) >= MAX_URLS:
            break

        if url in visited:
            continue

        try:
            print(f"[CRAWL] {len(documents)+1}/{MAX_URLS} -> {url}")

            html = fetch(url)
            if not html:
                continue

            page_data = extract_page_data(html, url)

            if page_data:
                documents.append(page_data)
                visited.add(url)

                cat = page_data["category"]
                category_counts[cat] = category_counts.get(cat, 0) + 1

            time.sleep(random.uniform(*CRAWL_DELAY))

        except Exception as e:
            print(f"[ERROR] {url} -> {e}")

    # ================= SAVE =================

    out = Path("data/raw/srm_data.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out, "w", encoding="utf-8") as f:
        json.dump(documents, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Final documents: {len(documents)}")
    print(f"📊 Category breakdown: {json.dumps(category_counts, indent=2)}")


# ================= RUN =================

if __name__ == "__main__":
    crawl_from_sitemap()
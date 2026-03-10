import requests
from bs4 import BeautifulSoup
from pathlib import Path
import json
import time
from urllib.parse import urljoin, urlparse
import re
import random
from pypdf import PdfReader

# ================= CONFIG =================

BASE_DOMAIN = "www.srmist.edu.in"

SEED_URLS = [
    "https://www.srmist.edu.in/admission-india/",
    "https://www.srmist.edu.in/engineering/",
    "https://www.srmist.edu.in/srm-hostels/",
    "https://www.srmist.edu.in/life-at-srm/",
]

MAX_PAGES = 300
CRAWL_DELAY = (1.5, 2.5)
TIMEOUT = 30
MAX_RETRIES = 3

PRIORITY_KEYWORDS = [
    "admission", "fee", "tuition", "btech",
    "engineering", "hostel", "course",
    "program", "ktr"
]

EXCLUDE_KEYWORDS = [
    "wp-admin", "faculty", "research",
    "press-media", "staff", "library",
    "login", "signup"
]

SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".webp", ".gif",
    ".svg", ".mp4", ".mp3", ".zip", ".rar",
    ".doc", ".docx", ".xls", ".xlsx"
)

# ================= CATEGORY CLASSIFICATION =================

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
        # URL matches are weighted higher (more reliable signal)
        for kw in rule["url_keywords"]:
            if kw in url_lower:
                score += 3

        # Content keyword matches
        for kw in rule["content_keywords"]:
            count = text_lower.count(kw)
            score += min(count, 5)  # cap at 5 to avoid one keyword dominating

        if score > best_score:
            best_score = score
            best_category = rule["category"]

    # require a minimum confidence threshold
    if best_score < 3:
        return "general"

    return best_category


# ================= HEADERS =================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Connection": "keep-alive",
}

session = requests.Session()
session.headers.update(HEADERS)

# ================= URL FILTER =================

def is_valid_url(url: str) -> bool:
    parsed = urlparse(url)

    if BASE_DOMAIN not in parsed.netloc:
        return False

    url_lower = url.lower()

    for word in EXCLUDE_KEYWORDS:
        if word in url_lower:
            return False

    if url_lower.endswith(SKIP_EXTENSIONS):
        return False

    return True

# ================= ROBUST REQUEST =================

def fetch_url(url: str):
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(url, timeout=TIMEOUT)

            if r.status_code == 403:
                time.sleep(3)
                continue

            r.raise_for_status()
            return r.text

        except Exception:
            time.sleep(2 + attempt)

    raise Exception("Failed after retries")


# ================= METADATA EXTRACTION =================

def extract_page_title(soup: BeautifulSoup) -> str:
    """Extract the best available page title."""
    # Try <h1> first (most specific)
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
        if len(title) > 5:
            return title

    # Fallback to <title> tag
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)
        # Strip common suffixes like "| SRM IST" or "- SRMIST"
        title = re.split(r"\s*[|–—-]\s*SRM", title, maxsplit=1)[0].strip()
        if len(title) > 3:
            return title

    return "Untitled Page"


def extract_tables_structured(soup: BeautifulSoup) -> list[dict]:
    """Extract tables as structured data (list of row-dicts) instead of flat text."""
    structured_tables = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        # Try to get headers from the first row
        header_cells = rows[0].find_all(["th", "td"])
        headers = [cell.get_text(" ", strip=True) for cell in header_cells]

        table_data = []
        for row in rows[1:]:
            cols = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if cols:
                # Zip with headers if available, otherwise store as list
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


def extract_tables_text(soup: BeautifulSoup) -> str:
    """Extract tables as pipe-separated text for embedding (backwards compatible)."""
    table_texts = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cols = [
                c.get_text(" ", strip=True)
                for c in row.find_all(["td", "th"])
            ]
            if cols:
                table_texts.append(" | ".join(cols))
    return " ".join(table_texts)


# ================= CAMPUS CLASSIFICATION =================

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


# ================= CLEAN TEXT =================

def extract_page_data(html: str, url: str) -> dict | None:
    """Extract enriched page data with title, category, campus, tables, and clean content."""
    soup = BeautifulSoup(html, "html.parser")

    main_content = soup.find("main") or soup.find("article") or soup.body
    if not main_content:
        return None

    # Extract title before decomposing tags
    title = extract_page_title(soup)

    # Extract structured tables before decomposing
    tables_structured = extract_tables_structured(soup)
    tables_text = extract_tables_text(soup)

    # Remove noise tags
    for tag in main_content([
        "script", "style", "nav", "footer",
        "header", "aside", "form"
    ]):
        tag.decompose()

    text = main_content.get_text(" ", strip=True)

    # Append table text so it's searchable in the content field
    if tables_text:
        text += " " + tables_text

    text = re.sub(r"\s+", " ", text).strip()

    if len(text) < 250:
        return None

    # Classify into a domain category
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


# ================= LINK EXTRACTION =================

def extract_links(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    links = set()

    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]

        if is_valid_url(href):
            links.add(href)

    return links

# ================= PDF HANDLING =================

def is_pdf(url: str) -> bool:
    return url.lower().endswith(".pdf")

def process_pdf(url: str, out_dir: Path, documents: list):
    try:
        filename = url.split("/")[-1]
        path = out_dir / filename

        r = session.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        path.write_bytes(r.content)

        reader = PdfReader(str(path))
        pdf_text = ""

        for page in reader.pages:
            pdf_text += page.extract_text() or ""

        if len(pdf_text) > 200:
            # Classify PDF content
            category = classify_category(url, pdf_text)

            documents.append({
                "url": url,
                "title": filename.replace(".pdf", "").replace("-", " ").replace("_", " ").title(),
                "category": category,
                "content": pdf_text,
                "tables": [],
            })

        print(f"[PDF] Processed: {filename}")

    except Exception as e:
        print(f"[PDF ERROR] {url} -> {e}")

# ================= MAIN CRAWLER =================

def crawl_srm():
    visited = set()
    queue = list(SEED_URLS)
    documents = []

    # Stats tracking
    category_counts = {}

    pdf_dir = Path("data/pdfs")
    pdf_dir.mkdir(parents=True, exist_ok=True)

    while queue and len(visited) < MAX_PAGES:
        url = queue.pop(0)

        if url in visited:
            continue

        try:
            print(f"[INFO] Crawling: {url}")

            # ===== PDF =====
            if is_pdf(url):
                process_pdf(url, pdf_dir, documents)
                visited.add(url)
                continue

            html = fetch_url(url)
            page_data = extract_page_data(html, url)

            if page_data:
                documents.append(page_data)

                # Track category distribution
                cat = page_data["category"]
                category_counts[cat] = category_counts.get(cat, 0) + 1

            visited.add(url)

            # ===== discover links =====
            new_links = extract_links(html, url)

            priority_links = []
            normal_links = []

            for link in new_links:
                if link in visited or link in queue:
                    continue

                if any(k in link.lower() for k in PRIORITY_KEYWORDS):
                    priority_links.append(link)
                else:
                    normal_links.append(link)

            queue = priority_links + normal_links + queue

            time.sleep(random.uniform(*CRAWL_DELAY))

        except Exception as e:
            print(f"[ERROR] {url} -> {e}")

    # ================= SAVE =================

    out = Path("data/raw/srm_data.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out, "w", encoding="utf-8") as f:
        json.dump(documents, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Crawled pages: {len(documents)}")
    print(f"📄 PDFs processed: {len(list(pdf_dir.glob('*')))}")
    print(f"📊 Category breakdown: {json.dumps(category_counts, indent=2)}")

# ================= RUN =================

if __name__ == "__main__":
    crawl_srm()
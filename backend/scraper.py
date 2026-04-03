"""
SRM Advanced Web Scraper
- Async/concurrent fetching (10x+ faster)
- Retry with exponential backoff
- Resumable (skips already-scraped pages)
- robots.txt compliance
- Structured logging
- Progress tracking with ETA
- Graceful shutdown on Ctrl+C
"""

import asyncio
import aiohttp
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from pathlib import Path
import json
import re
import csv
import time
import hashlib
import logging
import signal
import sys
from dataclasses import dataclass, field
from typing import Optional
from bs4 import BeautifulSoup
from urllib.robotparser import RobotFileParser

# ================= CONFIG =================

@dataclass
class Config:
    sitemap_index: str = "https://www.srmist.edu.in/sitemap.xml"
    base_domain: str = "www.srmist.edu.in"
    base_dir: Path = Path(__file__).resolve().parent
    data_dir: Path = field(init=False)

    max_urls: int = 8000
    concurrency: int = 10          # Parallel requests
    request_timeout: int = 20
    min_content_len: int = 200

    # Retry
    max_retries: int = 3
    retry_base_delay: float = 1.5  # Exponential backoff base (seconds)

    # Politeness
    delay_between_batches: float = 0.3   # Seconds between concurrency batches
    respect_robots: bool = True

    user_agent: str = "Mozilla/5.0 (compatible; SRMScraper/2.0)"

    def __post_init__(self):
        self.data_dir = self.base_dir / "data" / "srm_docs"
        self.data_dir.mkdir(parents=True, exist_ok=True)

CFG = Config()

# ================= LOGGING =================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(CFG.base_dir / "scraper.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("srm_scraper")

# ================= PROGRESS TRACKER =================

class Progress:
    def __init__(self, total: int):
        self.total = total
        self.done = 0
        self.saved = 0
        self.failed = 0
        self.skipped = 0
        self.start_time = time.time()

    def update(self, result: str):
        self.done += 1
        if result == "saved":
            self.saved += 1
        elif result == "failed":
            self.failed += 1
        elif result == "skipped":
            self.skipped += 1

    def eta_str(self) -> str:
        elapsed = time.time() - self.start_time
        if self.done == 0:
            return "?"
        rate = self.done / elapsed
        remaining = (self.total - self.done) / rate if rate > 0 else 0
        mins, secs = divmod(int(remaining), 60)
        return f"{mins}m{secs:02d}s"

    def log(self):
        log.info(
            f"Progress: {self.done}/{self.total} | "
            f"Saved: {self.saved} | Failed: {self.failed} | "
            f"Skipped: {self.skipped} | ETA: {self.eta_str()}"
        )

# ================= ROBOTS.TXT =================

def load_robots(base_url: str, user_agent: str) -> Optional[RobotFileParser]:
    rp = RobotFileParser()
    robots_url = f"{base_url}/robots.txt"
    try:
        rp.set_url(robots_url)
        rp.read()
        log.info(f"Loaded robots.txt from {robots_url}")
        return rp
    except Exception as e:
        log.warning(f"Could not load robots.txt: {e}")
        return None

# ================= ASYNC FETCH =================

async def fetch(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """Fetch URL with exponential backoff retries."""
    for attempt in range(1, CFG.max_retries + 1):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=CFG.request_timeout)) as resp:
                if resp.status == 200:
                    return await resp.text(errors="replace")
                elif resp.status in (403, 404, 410):
                    log.debug(f"[{resp.status}] Skipping {url}")
                    return None
                else:
                    log.warning(f"[{resp.status}] Attempt {attempt}/{CFG.max_retries}: {url}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning(f"[ERROR] Attempt {attempt}/{CFG.max_retries} for {url}: {type(e).__name__}")

        if attempt < CFG.max_retries:
            await asyncio.sleep(CFG.retry_base_delay ** attempt)

    log.error(f"[FAILED] Exhausted retries: {url}")
    return None

# ================= SITEMAP =================

async def get_urls(session: aiohttp.ClientSession) -> list[str]:
    """Recursively fetch all URLs from sitemap index."""
    log.info(f"Fetching sitemap index: {CFG.sitemap_index}")
    xml_text = await fetch(session, CFG.sitemap_index)
    if not xml_text:
        log.error("Could not fetch sitemap index.")
        return []

    ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring(xml_text)

    sitemap_links = [loc.text for loc in root.findall(".//ns:loc", ns) if loc.text]
    log.info(f"Found {len(sitemap_links)} child sitemaps")

    url_tasks = [fetch(session, sm) for sm in sitemap_links]
    results = await asyncio.gather(*url_tasks)

    urls: set[str] = set()
    for xml_result in results:
        if not xml_result:
            continue
        try:
            child_root = ET.fromstring(xml_result)
            for loc in child_root.findall(".//ns:loc", ns):
                if loc.text:
                    urls.add(loc.text.strip())
        except ET.ParseError as e:
            log.warning(f"Sitemap parse error: {e}")

    log.info(f"Total URLs discovered: {len(urls)}")
    return list(urls)

# ================= EXTRACTION =================

def clean_text(soup: BeautifulSoup) -> str:
    main = soup.find("main") or soup.find("article") or soup.body
    if not main:
        return ""
    for tag in main(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    return re.sub(r"\s+", " ", main.get_text(" ", strip=True)).strip()


def extract_meta(soup: BeautifulSoup) -> dict:
    """Extract Open Graph, meta description, and keywords."""
    meta = {}
    for tag in soup.find_all("meta"):
        name = tag.get("name") or tag.get("property") or ""
        content = tag.get("content") or ""
        if name and content:
            meta[name.lower()] = content
    return {k: v for k, v in meta.items() if k in (
        "description", "keywords", "og:title", "og:description", "og:image"
    )}


def extract_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Extract all internal links from a page."""
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("/"):
            href = f"https://{CFG.base_domain}{href}"
        if CFG.base_domain in href and href.startswith("http"):
            links.append(href)
    return list(set(links))


def extract_infobox(soup: BeautifulSoup) -> dict:
    infobox = {}
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cols = row.find_all(["td", "th"])
            if len(cols) == 2:
                key = cols[0].get_text(strip=True)
                val = cols[1].get_text(strip=True)
                if len(key) < 40 and key:
                    infobox[key] = val
    return infobox


def extract_tables(soup: BeautifulSoup, folder: Path):
    tables = soup.find_all("table")
    if not tables:
        return
    table_dir = folder / "tables"
    table_dir.mkdir(exist_ok=True)
    for i, table in enumerate(tables):
        rows = []
        for tr in table.find_all("tr"):
            cols = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
            if cols:
                rows.append(cols)
        if rows:
            with open(table_dir / f"table_{i}.csv", "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows(rows)

# ================= SAVE =================

def page_folder(url: str) -> Path:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", url)
    h = hashlib.md5(url.encode()).hexdigest()[:8]
    return CFG.data_dir / f"{slug[:60]}_{h}"


def already_scraped(url: str) -> bool:
    folder = page_folder(url)
    return (folder / "content.txt").exists()


def save_page(url: str, html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    content = clean_text(soup)

    if len(content) < CFG.min_content_len:
        return False

    folder = page_folder(url)
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "content.txt").write_text(content, encoding="utf-8")
    (folder / "raw.html").write_text(html, encoding="utf-8")

    metadata = {
        "url": url,
        "title": soup.title.string.strip() if soup.title and soup.title.string else "SRM Page",
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "meta": extract_meta(soup),
        "internal_links": extract_links(soup, url),
    }
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    infobox = extract_infobox(soup)
    if infobox:
        (folder / "infobox.json").write_text(json.dumps(infobox, indent=2, ensure_ascii=False), encoding="utf-8")

    extract_tables(soup, folder)
    return True

# ================= WORKER =================

async def process_url(
    session: aiohttp.ClientSession,
    url: str,
    progress: Progress,
    robots: Optional[RobotFileParser],
    semaphore: asyncio.Semaphore,
):
    async with semaphore:
        # Robots check
        if robots and not robots.can_fetch(CFG.user_agent, url):
            log.debug(f"[ROBOTS] Disallowed: {url}")
            progress.update("skipped")
            return

        # Resumability
        if already_scraped(url):
            log.debug(f"[SKIP] Already scraped: {url}")
            progress.update("skipped")
            return

        html = await fetch(session, url)
        if not html:
            progress.update("failed")
            return

        saved = await asyncio.get_event_loop().run_in_executor(None, save_page, url, html)
        progress.update("saved" if saved else "skipped")

        if progress.done % 100 == 0:
            progress.log()

# ================= MAIN =================

async def main():
    log.info("=" * 60)
    log.info("SRM Scraper v2 — Starting")

    shutdown = asyncio.Event()

    def handle_signal(*_):
        log.warning("Interrupt received — shutting down gracefully...")
        shutdown.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    headers = {"User-Agent": CFG.user_agent}
    connector = aiohttp.TCPConnector(limit=CFG.concurrency, ssl=False)

    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        # Load robots.txt
        robots = None
        if CFG.respect_robots:
            robots = load_robots(f"https://{CFG.base_domain}", CFG.user_agent)

        # Discover URLs
        urls = await get_urls(session)
        urls = [u for u in urls if CFG.base_domain in u][: CFG.max_urls]
        log.info(f"Queued {len(urls)} URLs (max={CFG.max_urls})")

        progress = Progress(total=len(urls))
        semaphore = asyncio.Semaphore(CFG.concurrency)

        tasks = [
            asyncio.create_task(
                process_url(session, url, progress, robots, semaphore)
            )
            for url in urls
        ]

        # Run with graceful shutdown support
        for coro in asyncio.as_completed(tasks):
            if shutdown.is_set():
                for t in tasks:
                    t.cancel()
                break
            await coro
            await asyncio.sleep(CFG.delay_between_batches / CFG.concurrency)

    progress.log()
    log.info(f"✅ Done — {progress.saved} pages saved to {CFG.data_dir}")


if __name__ == "__main__":
    asyncio.run(main())

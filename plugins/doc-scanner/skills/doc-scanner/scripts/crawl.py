#!/usr/bin/env python3
"""Recursive documentation crawler using Playwright + playwright-stealth.

Discovers all documentation pages starting from a root URL via BFS traversal.
Outputs a sitemap.json with page metadata (URL, title, headings, status).

Why Playwright + playwright-stealth?
  Most modern documentation sites (Docusaurus, Nextra, GitBook, VitePress) are
  single-page applications that render content client-side with JavaScript.
  A simple HTTP GET only returns a shell <div id="root"></div>.  Playwright
  launches a real Chromium browser that executes JS and waits for content to
  render.  playwright-stealth patches dozens of browser fingerprint leaks
  (navigator.webdriver, chrome.runtime, WebGL vendor, etc.) so Cloudflare,
  Akamai, and similar WAFs see a normal residential browser session instead of
  a headless bot.

Why BFS (breadth-first search)?
  Documentation sites are typically shallow trees — sidebar links from the root
  reach most pages in 1-3 clicks.  BFS discovers this broad structure quickly,
  whereas DFS would tunnel deep into a single section before finding sibling
  pages.  The --max-depth flag caps traversal to avoid infinite crawls on
  sites with auto-generated paginated content.

Usage:
    python3 crawl.py <root-url> [--output sitemap.json] [--max-depth 10] [--delay 1.5] [--same-path-prefix]
"""

import argparse
import json
import logging
import random
import sys
import time
from collections import deque
from datetime import date
from urllib.parse import urljoin, urlparse, urldefrag

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# Configure structured logging so crawl progress is easy to follow in the terminal.
# Timestamps use HH:MM:SS (no date) since crawls are single-session operations.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("crawl")


def parse_args():
    """Define and parse CLI arguments.

    --same-path-prefix is important for versioned doc sites like
    https://docs.sqlc.dev/en/stable/ — it prevents the crawler from
    wandering into /en/latest/ or /en/v1.x/ which are separate doc trees.
    """
    p = argparse.ArgumentParser(description="Crawl documentation site and build sitemap")
    p.add_argument("root_url", help="Starting URL to crawl")
    p.add_argument("--output", "-o", default="sitemap.json", help="Output file path (default: sitemap.json)")
    p.add_argument("--max-depth", type=int, default=10, help="Maximum crawl depth (default: 10)")
    p.add_argument("--delay", type=float, default=1.5, help="Base delay between requests in seconds (default: 1.5)")
    p.add_argument("--same-path-prefix", action="store_true", help="Only follow links sharing the root URL path prefix")
    return p.parse_args()


def normalize_url(url):
    """Canonicalize a URL for deduplication.

    Two normalizations:
    1. Strip fragments (#section) — they point to the same page.
    2. Strip trailing slashes on non-root paths — /docs/install and /docs/install/
       are typically the same page, and doc sites link to both forms inconsistently.
       We keep the trailing slash on root paths (http://example.com/) since removing
       it would create an invalid URL.
    """
    url, _ = urldefrag(url)
    # url.count("/") > 3 means there's a path beyond the domain root
    # (e.g., "https://example.com/docs/" has 4 slashes)
    if url.endswith("/") and url.count("/") > 3:
        url = url.rstrip("/")
    return url


def is_doc_link(url):
    """Filter out URLs that are clearly not documentation pages.

    Heuristic-based: we skip binary assets (images, archives), non-doc site
    sections (blog, changelog, pricing), and data files (JSON, XML, RSS).
    This keeps the crawl focused on actual documentation content and avoids
    downloading large files or hitting non-doc endpoints.
    """
    parsed = urlparse(url)
    path = parsed.path.lower()

    # Binary/media files — downloading these wastes time and they contain no docs
    skip_extensions = (
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
        ".pdf", ".zip", ".tar", ".gz", ".whl",
        ".css", ".js", ".json", ".xml", ".rss", ".atom",
        ".mp4", ".webm", ".mp3", ".wav",
    )
    if any(path.endswith(ext) for ext in skip_extensions):
        return False

    # Non-documentation sections — these exist on the same domain but aren't docs
    skip_paths = ("/blog", "/changelog", "/releases", "/search", "/login", "/signup", "/pricing")
    if any(path.startswith(sp) for sp in skip_paths):
        return False

    return True


def should_follow(url, root_domain, root_path_prefix, same_path_prefix):
    """Gate function: decides whether a discovered link should be added to the crawl queue.

    Enforces three boundaries:
    1. Same domain — never follow external links (e.g., links to GitHub, npm)
    2. Same path prefix — when --same-path-prefix is set, restrict to the URL subtree
       (e.g., only /en/stable/* when starting from /en/stable/)
    3. Documentation link — skip non-doc resources (see is_doc_link)
    """
    parsed = urlparse(url)

    # Only follow http/https (skip mailto:, javascript:, tel:, etc.)
    if parsed.scheme not in ("http", "https"):
        return False

    # Stay on the same domain — cross-domain links are external references, not docs
    if parsed.hostname != root_domain:
        return False

    # When --same-path-prefix is active, only follow links under the root path.
    # This is crucial for versioned doc sites to avoid mixing documentation versions.
    if same_path_prefix and not parsed.path.startswith(root_path_prefix):
        return False

    # Final filter: skip non-documentation resources
    if not is_doc_link(url):
        return False

    return True


def extract_page_data(page):
    """Run JavaScript in the browser to extract structured data from the rendered page.

    We use page.evaluate() to execute JS directly in the page context because:
    - The DOM is already fully rendered (SPA content, lazy-loaded sections)
    - We get the *visible* text, not raw HTML source
    - Headings, links, and titles reflect the final rendered state

    Returns:
        title: The document.title (usually includes site name suffix)
        headings: List of {level, text, id} for H1-H3 elements
        links: List of absolute URLs from all <a href> elements
    """
    # document.title gives us the <title> tag content, which most doc sites set
    # to something like "Installing sqlc — sqlc documentation"
    title = page.evaluate("() => document.title || ''").strip()

    # Extract H1-H3 headings — these form the structural skeleton of each page.
    # We capture the id attribute for potential anchor link generation later.
    # .replace(/\\s+/g, ' ') collapses whitespace from multi-line heading text.
    headings = page.evaluate("""() => {
        const headings = [];
        document.querySelectorAll('h1, h2, h3').forEach(h => {
            headings.push({
                level: parseInt(h.tagName[1]),
                text: h.textContent.trim().replace(/\\s+/g, ' '),
                id: h.id || ''
            });
        });
        return headings;
    }""")

    # Collect all outbound links — these are our BFS edges.
    # Using a.href (the resolved absolute URL) rather than getAttribute('href')
    # so we don't have to deal with relative path resolution ourselves.
    # The try/catch handles rare edge cases like SVG <a> elements or malformed hrefs.
    links = page.evaluate("""() => {
        const links = [];
        document.querySelectorAll('a[href]').forEach(a => {
            try {
                links.push(a.href);
            } catch(e) {}
        });
        return links;
    }""")

    return title, headings, links


def humanized_delay(base_delay):
    """Add random jitter to the base delay to mimic human browsing patterns.

    A fixed delay between requests is a bot fingerprint — real users have variable
    reading times. We add ±0.5s of uniform random jitter. The max(0.2, ...) ensures
    we never go below 200ms even if base_delay is very small, preventing accidental
    request flooding.
    """
    jitter = random.uniform(-0.5, 0.5)
    return max(0.2, base_delay + jitter)


def crawl(args):
    """Main crawl loop: BFS traversal of documentation pages.

    Algorithm:
    1. Start with root_url in the queue at depth 0
    2. For each URL in the queue:
       a. Navigate to it with Playwright (renders JS, follows redirects)
       b. Record HTTP status — if >=400, log as failed and skip
       c. Handle redirects — if the final URL was already visited, skip
       d. Extract page data (title, headings, outgoing links)
       e. For each outgoing link, if it passes should_follow() and hasn't
          been visited, add it to the queue at depth+1
    3. Sleep between requests with humanized jitter
    4. Return the complete sitemap structure
    """
    root_url = normalize_url(args.root_url)
    parsed_root = urlparse(root_url)
    root_domain = parsed_root.hostname

    # Extract the path prefix for --same-path-prefix filtering.
    # For "https://docs.example.com/en/stable/intro", this gives "/en/stable/intro".
    # We strip the trailing slash so startswith() works correctly for both
    # "/en/stable" and "/en/stable/subpage".
    root_path_prefix = parsed_root.path.rstrip("/") or "/"

    # Special case: if the path is just "/", we want to match everything on the domain,
    # so we keep it as "/" (every path starts with "/").
    if root_path_prefix == "/":
        same_path_prefix_value = "/"
    else:
        same_path_prefix_value = root_path_prefix

    # BFS state: visited tracks all URLs we've seen (queued or fetched) to avoid cycles.
    # The queue holds (url, depth) tuples for pending visits.
    visited = set()
    queue = deque()
    queue.append((root_url, 0))
    visited.add(root_url)

    # Results: successfully crawled pages and failed attempts
    pages = []
    failed = []

    log.info(f"Starting crawl from {root_url}")
    log.info(f"Domain: {root_domain}, Path prefix: {same_path_prefix_value}")
    log.info(f"Max depth: {args.max_depth}, Delay: {args.delay}s, Same-path-prefix: {args.same_path_prefix}")

    # Launch a single browser instance for the entire crawl.
    # Reusing one browser context is faster than launching per-page and maintains
    # cookies/session state that some doc sites require (e.g., consent banners).
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            # Standard desktop viewport — some doc sites have responsive layouts
            # that hide content on small viewports
            viewport={"width": 1280, "height": 800},
            # Realistic Chrome user-agent string. playwright-stealth patches most
            # fingerprint vectors, but the UA string is the first thing WAFs check.
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        # Apply stealth patches — modifies navigator.webdriver, chrome.runtime,
        # WebGL renderer, and ~20 other fingerprint vectors to appear as a normal
        # Chrome browser. This is what lets us bypass Cloudflare's bot detection.
        # Apply stealth patches — modifies navigator.webdriver, chrome.runtime,
        # WebGL renderer, and ~20 other fingerprint vectors to appear as a normal
        # Chrome browser. This is what lets us bypass Cloudflare's bot detection.
        # playwright-stealth v2 uses Stealth().apply_stealth_sync() instead of stealth_sync().
        Stealth().apply_stealth_sync(page)

        while queue:
            url, depth = queue.popleft()

            # Depth guard: prevent runaway crawls on sites with deep auto-generated
            # hierarchies (e.g., API docs with one page per enum value)
            if depth > args.max_depth:
                log.warning(f"Max depth reached, skipping: {url}")
                continue

            log.info(f"[{len(pages)+1}/{len(visited)}] depth={depth} {url}")

            try:
                # Navigate to the page. wait_until="domcontentloaded" fires when the
                # HTML is parsed (faster than "networkidle" which waits for all assets).
                # 30s timeout handles slow-loading pages without hanging indefinitely.
                response = page.goto(url, wait_until="domcontentloaded", timeout=30000)

                # Extra 1s wait for JS frameworks to render content.
                # Docusaurus/Nextra/VitePress hydrate after DOMContentLoaded, so the
                # actual doc content may not be in the DOM yet when that event fires.
                page.wait_for_timeout(1000)

                status = response.status if response else 0

                # Record HTTP errors (404, 403, 500, etc.) as failures and skip.
                # These pages have no useful content to extract.
                if status >= 400:
                    failed.append({"url": url, "status": status, "reason": response.status_text if response else "Unknown"})
                    log.warning(f"HTTP {status} for {url}")
                    time.sleep(humanized_delay(args.delay))
                    continue

                # After navigation, the browser may have followed redirects.
                # page.url gives us the final URL. If it's a page we've already
                # visited (e.g., /docs redirects to /docs/intro which we crawled
                # via a sidebar link), skip it to avoid duplicates.
                final_url = normalize_url(page.url)
                if final_url != url and final_url in visited:
                    log.info(f"Redirected to already-visited: {final_url}")
                    time.sleep(humanized_delay(args.delay))
                    continue

                # Extract page metadata from the rendered DOM
                title, headings, links = extract_page_data(page)

                # Store the page in our results using the final (post-redirect) URL
                pages.append({
                    "url": final_url,
                    "title": title,
                    "headings": headings,
                    "status": status,
                })

                # Link discovery: scan all outgoing links for new pages to crawl.
                # Each link is normalized and checked against our crawl boundaries
                # before being added to the queue.
                new_links = 0
                for link in links:
                    normalized = normalize_url(link)
                    if normalized not in visited and should_follow(normalized, root_domain, same_path_prefix_value, args.same_path_prefix):
                        visited.add(normalized)
                        queue.append((normalized, depth + 1))
                        new_links += 1

                if new_links > 0:
                    log.info(f"  Found {new_links} new links")

            except Exception as e:
                # Catch-all for network errors, timeouts, and Playwright crashes.
                # We log the error and continue crawling — one broken page shouldn't
                # abort the entire crawl.
                failed.append({"url": url, "status": 0, "reason": str(e)})
                log.error(f"Error crawling {url}: {e}")

            # Rate limiting: sleep between requests to be polite to the server
            # and to avoid triggering rate-limit defenses.
            time.sleep(humanized_delay(args.delay))

        browser.close()

    # Build the sitemap output structure.
    # This JSON is the input for extract.py (the next pipeline step).
    return {
        "root_url": args.root_url,
        "crawl_date": str(date.today()),
        "domain": root_domain,
        "path_prefix": same_path_prefix_value,
        "pages": pages,
        "failed": failed,
        "stats": {
            "total_discovered": len(visited),   # URLs added to queue (including failed)
            "total_fetched": len(pages),         # Successfully crawled pages
            "total_failed": len(failed),         # Pages that returned errors
        },
    }


def main():
    args = parse_args()
    sitemap = crawl(args)

    # Write the sitemap to disk as pretty-printed JSON.
    # ensure_ascii=False preserves Unicode characters in page titles
    # (common in non-English documentation).
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(sitemap, f, indent=2, ensure_ascii=False)

    log.info(f"Sitemap written to {args.output}")
    log.info(f"Stats: {sitemap['stats']['total_fetched']} fetched, {sitemap['stats']['total_failed']} failed, {sitemap['stats']['total_discovered']} discovered")

    # Print failed URLs prominently so the operator can investigate.
    # Common causes: broken links in the docs, auth-protected pages, rate limiting.
    if sitemap["failed"]:
        log.warning(f"Failed URLs:")
        for entry in sitemap["failed"]:
            log.warning(f"  {entry['status']} {entry['url']}: {entry['reason']}")


if __name__ == "__main__":
    main()

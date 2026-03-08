#!/usr/bin/env python3
"""Recursive documentation crawler using Playwright + playwright-stealth.

Discovers all documentation pages starting from a root URL via BFS traversal.
Outputs a sitemap.json with page metadata (URL, title, headings, status).

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
from playwright_stealth import stealth_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("crawl")


def parse_args():
    p = argparse.ArgumentParser(description="Crawl documentation site and build sitemap")
    p.add_argument("root_url", help="Starting URL to crawl")
    p.add_argument("--output", "-o", default="sitemap.json", help="Output file path (default: sitemap.json)")
    p.add_argument("--max-depth", type=int, default=10, help="Maximum crawl depth (default: 10)")
    p.add_argument("--delay", type=float, default=1.5, help="Base delay between requests in seconds (default: 1.5)")
    p.add_argument("--same-path-prefix", action="store_true", help="Only follow links sharing the root URL path prefix")
    return p.parse_args()


def normalize_url(url):
    """Remove fragment and trailing slash for deduplication."""
    url, _ = urldefrag(url)
    if url.endswith("/") and url.count("/") > 3:
        url = url.rstrip("/")
    return url


def is_doc_link(url):
    """Filter out non-documentation links."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    # Skip common non-doc resources
    skip_extensions = (
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
        ".pdf", ".zip", ".tar", ".gz", ".whl",
        ".css", ".js", ".json", ".xml", ".rss", ".atom",
        ".mp4", ".webm", ".mp3", ".wav",
    )
    if any(path.endswith(ext) for ext in skip_extensions):
        return False
    # Skip common non-doc paths
    skip_paths = ("/blog", "/changelog", "/releases", "/search", "/login", "/signup", "/pricing")
    if any(path.startswith(sp) for sp in skip_paths):
        return False
    return True


def should_follow(url, root_domain, root_path_prefix, same_path_prefix):
    """Determine if a URL should be followed during crawling."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.hostname != root_domain:
        return False
    if same_path_prefix and not parsed.path.startswith(root_path_prefix):
        return False
    if not is_doc_link(url):
        return False
    return True


def extract_page_data(page):
    """Extract title, headings, and outgoing links from a rendered page."""
    # Extract title
    title = page.evaluate("() => document.title || ''").strip()

    # Extract headings (H1-H3)
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

    # Extract all links
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
    """Add random jitter to delay for human-like behavior."""
    jitter = random.uniform(-0.5, 0.5)
    return max(0.2, base_delay + jitter)


def crawl(args):
    root_url = normalize_url(args.root_url)
    parsed_root = urlparse(root_url)
    root_domain = parsed_root.hostname
    root_path_prefix = parsed_root.path.rstrip("/") or "/"

    # If path is just /, keep it as / to match everything on the domain
    if root_path_prefix == "/":
        same_path_prefix_value = "/"
    else:
        same_path_prefix_value = root_path_prefix

    visited = set()
    queue = deque()  # (url, depth)
    queue.append((root_url, 0))
    visited.add(root_url)

    pages = []
    failed = []

    log.info(f"Starting crawl from {root_url}")
    log.info(f"Domain: {root_domain}, Path prefix: {same_path_prefix_value}")
    log.info(f"Max depth: {args.max_depth}, Delay: {args.delay}s, Same-path-prefix: {args.same_path_prefix}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        stealth_sync(page)

        while queue:
            url, depth = queue.popleft()

            if depth > args.max_depth:
                log.warning(f"Max depth reached, skipping: {url}")
                continue

            log.info(f"[{len(pages)+1}/{len(visited)}] depth={depth} {url}")

            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Wait for content to render (handles JS-heavy sites)
                page.wait_for_timeout(1000)

                status = response.status if response else 0

                if status >= 400:
                    failed.append({"url": url, "status": status, "reason": response.status_text if response else "Unknown"})
                    log.warning(f"HTTP {status} for {url}")
                    time.sleep(humanized_delay(args.delay))
                    continue

                # Handle redirects — use final URL
                final_url = normalize_url(page.url)
                if final_url != url and final_url in visited:
                    log.info(f"Redirected to already-visited: {final_url}")
                    time.sleep(humanized_delay(args.delay))
                    continue

                title, headings, links = extract_page_data(page)

                pages.append({
                    "url": final_url,
                    "title": title,
                    "headings": headings,
                    "status": status,
                })

                # Discover new links
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
                failed.append({"url": url, "status": 0, "reason": str(e)})
                log.error(f"Error crawling {url}: {e}")

            time.sleep(humanized_delay(args.delay))

        browser.close()

    return {
        "root_url": args.root_url,
        "crawl_date": str(date.today()),
        "domain": root_domain,
        "path_prefix": same_path_prefix_value,
        "pages": pages,
        "failed": failed,
        "stats": {
            "total_discovered": len(visited),
            "total_fetched": len(pages),
            "total_failed": len(failed),
        },
    }


def main():
    args = parse_args()
    sitemap = crawl(args)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(sitemap, f, indent=2, ensure_ascii=False)

    log.info(f"Sitemap written to {args.output}")
    log.info(f"Stats: {sitemap['stats']['total_fetched']} fetched, {sitemap['stats']['total_failed']} failed, {sitemap['stats']['total_discovered']} discovered")

    if sitemap["failed"]:
        log.warning(f"Failed URLs:")
        for entry in sitemap["failed"]:
            log.warning(f"  {entry['status']} {entry['url']}: {entry['reason']}")


if __name__ == "__main__":
    main()

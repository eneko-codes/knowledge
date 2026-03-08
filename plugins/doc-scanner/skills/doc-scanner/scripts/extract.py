#!/usr/bin/env python3
"""Content extractor for crawled documentation pages.

Fetches full content of every page in a sitemap, detects the main content area,
converts HTML to markdown, classifies pages by category, and extracts code blocks
and function signatures.

Usage:
    python3 extract.py <sitemap.json> [--output extracted/] [--delay 1.0]
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from urllib.parse import urlparse

import html2text
from bs4 import BeautifulSoup, Comment
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("extract")


def parse_args():
    p = argparse.ArgumentParser(description="Extract content from crawled documentation pages")
    p.add_argument("sitemap", help="Path to sitemap.json from crawl.py")
    p.add_argument("--output", "-o", default="extracted", help="Output directory (default: extracted)")
    p.add_argument("--delay", type=float, default=1.0, help="Base delay between requests in seconds (default: 1.0)")
    return p.parse_args()


# Selectors for main content area, tried in order
CONTENT_SELECTORS = [
    "main",
    "article",
    "[role='main']",
    "#content",
    "#main-content",
    ".content",
    ".docs-content",
    ".doc-content",
    ".markdown-body",
    ".documentation",
    ".post-content",
    ".page-content",
    ".article-content",
    ".rst-content",
    ".md-content",
]

# Elements to strip from content
STRIP_SELECTORS = [
    "nav",
    "header",
    "footer",
    ".sidebar",
    ".toc",
    ".table-of-contents",
    ".nav-links",
    ".edit-this-page",
    ".page-nav",
    ".breadcrumb",
    ".breadcrumbs",
    ".header-anchor",
    ".copy-button",
    ".highlight-copy-btn",
    "script",
    "style",
    "noscript",
]


def find_main_content(soup):
    """Find the main content element using heuristic selectors."""
    for selector in CONTENT_SELECTORS:
        el = soup.select_one(selector)
        if el and len(el.get_text(strip=True)) > 100:
            return el
    # Fallback: use body
    return soup.body if soup.body else soup


def strip_noise(content_el):
    """Remove navigation, sidebar, and other non-content elements."""
    for selector in STRIP_SELECTORS:
        for el in content_el.select(selector):
            el.decompose()
    # Remove HTML comments
    for comment in content_el.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()
    return content_el


def extract_code_blocks(soup):
    """Extract code blocks with their language annotations."""
    blocks = []
    for pre in soup.find_all("pre"):
        code = pre.find("code")
        if code:
            # Detect language from class
            language = ""
            classes = code.get("class", [])
            for cls in classes:
                if cls.startswith("language-"):
                    language = cls[len("language-"):]
                    break
                elif cls.startswith("highlight-"):
                    language = cls[len("highlight-"):]
                    break
                elif cls.startswith("sourceCode"):
                    # Pandoc style
                    language = cls.replace("sourceCode", "").strip()
                    break
            # Also check parent pre classes
            if not language:
                pre_classes = pre.get("class", [])
                for cls in pre_classes:
                    if cls.startswith("language-"):
                        language = cls[len("language-"):]
                        break
            content = code.get_text()
            if content.strip():
                blocks.append({"language": language, "content": content})
        else:
            content = pre.get_text()
            if content.strip():
                blocks.append({"language": "", "content": content})
    return blocks


# Patterns for function signature extraction
SIGNATURE_PATTERNS = [
    # Go
    re.compile(r"func\s+(?:\([^)]*\)\s+)?\w+\s*\([^)]*\)(?:\s*(?:\([^)]*\)|[^{]+?))?(?:\s*\{)?"),
    # Python
    re.compile(r"(?:async\s+)?def\s+\w+\s*\([^)]*\)(?:\s*->\s*[^:]+)?:"),
    # TypeScript/JavaScript
    re.compile(r"(?:export\s+)?(?:async\s+)?function\s+\w+\s*(?:<[^>]*>)?\s*\([^)]*\)(?:\s*:\s*[^{]+)?"),
    # Rust
    re.compile(r"(?:pub\s+)?(?:async\s+)?fn\s+\w+\s*(?:<[^>]*>)?\s*\([^)]*\)(?:\s*->\s*[^{]+)?"),
    # Java/Kotlin
    re.compile(r"(?:public|private|protected)?\s*(?:static\s+)?(?:async\s+)?\w+(?:<[^>]*>)?\s+\w+\s*\([^)]*\)"),
]


def extract_signatures(code_blocks):
    """Extract function signatures from code blocks."""
    signatures = []
    for block in code_blocks:
        for pattern in SIGNATURE_PATTERNS:
            for match in pattern.finditer(block["content"]):
                sig = match.group(0).strip()
                # Clean up: remove trailing brace, limit length
                sig = sig.rstrip("{").strip()
                if len(sig) < 300 and sig not in signatures:
                    signatures.append(sig)
    return signatures


def classify_page(title, headings, code_blocks, markdown_text):
    """Classify a page into a documentation category."""
    title_lower = title.lower()
    text_lower = markdown_text.lower()

    # Count code blocks relative to text length
    text_len = len(markdown_text)
    code_len = sum(len(b["content"]) for b in code_blocks)
    code_ratio = code_len / max(text_len, 1)

    # Check for API reference indicators
    api_indicators = ["api reference", "api documentation", "function reference", "method reference",
                      "class reference", "type reference", "parameters", "returns", "arguments"]
    api_score = sum(1 for ind in api_indicators if ind in text_lower)

    # Check for tutorial indicators
    tutorial_indicators = ["step 1", "step 2", "getting started", "tutorial", "walkthrough",
                          "quickstart", "quick start", "how to", "guide"]
    tutorial_score = sum(1 for ind in tutorial_indicators if ind in text_lower)

    # Check for conceptual indicators
    concept_indicators = ["overview", "introduction", "concept", "architecture", "design",
                         "explanation", "understanding", "background"]
    concept_score = sum(1 for ind in concept_indicators if ind in text_lower)

    # Check for deprecation/warning content
    warning_indicators = ["deprecated", "breaking change", "migration", "upgrade", "removed in",
                         "no longer supported", "end of life"]
    warning_score = sum(1 for ind in warning_indicators if ind in text_lower)

    # Classify
    if warning_score >= 2:
        return "warning"
    if code_ratio > 0.6 and tutorial_score < 2:
        return "example"
    if api_score >= 2 or (code_ratio > 0.3 and any(extract_signatures([b]) for b in code_blocks)):
        return "api-reference"
    if tutorial_score >= 2:
        return "tutorial"
    if concept_score >= 1:
        return "conceptual"
    # Default: conceptual for text-heavy, example for code-heavy
    if code_ratio > 0.4:
        return "example"
    return "conceptual"


def extract_warnings(markdown_text):
    """Extract deprecation notices and warnings from text."""
    warnings = []
    lines = markdown_text.split("\n")
    warning_patterns = [
        re.compile(r"(?:deprecated|warning|caution|danger|important)\s*[:!]?\s*(.+)", re.IGNORECASE),
        re.compile(r"(?:removed|breaking change)\s+(?:in|since)\s+(.+)", re.IGNORECASE),
    ]
    for line in lines:
        for pattern in warning_patterns:
            match = pattern.search(line)
            if match:
                warning_text = line.strip().lstrip(">").strip().lstrip("*_").rstrip("*_").strip()
                if warning_text and len(warning_text) > 10 and warning_text not in warnings:
                    warnings.append(warning_text)
    return warnings


def url_to_filename(url):
    """Convert a URL to a safe filename."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        path = "index"
    # Replace path separators and special chars
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", path)
    # Collapse multiple underscores
    safe = re.sub(r"_+", "_", safe)
    # Limit length
    if len(safe) > 200:
        safe = safe[:200]
    return safe + ".json"


def humanized_delay(base_delay):
    """Add random jitter to delay for human-like behavior."""
    jitter = random.uniform(-0.3, 0.3)
    return max(0.2, base_delay + jitter)


def configure_html2text():
    """Create and configure an html2text converter."""
    h = html2text.HTML2Text()
    h.body_width = 0  # Don't wrap lines
    h.protect_links = True
    h.unicode_snob = True
    h.skip_internal_links = False
    h.ignore_images = False
    h.ignore_emphasis = False
    h.mark_code = True
    h.wrap_links = False
    h.wrap_list_items = False
    return h


def extract_page(page_obj, url, converter):
    """Extract structured content from a single rendered page."""
    html = page_obj.content()
    soup = BeautifulSoup(html, "lxml")

    # Extract code blocks before stripping (they're in the content)
    content_el = find_main_content(soup)
    code_blocks = extract_code_blocks(content_el)

    # Strip noise and convert to markdown
    content_el = strip_noise(content_el)
    content_html = str(content_el)
    markdown = converter.handle(content_html).strip()

    # Clean up markdown
    # Remove excessive blank lines
    markdown = re.sub(r"\n{4,}", "\n\n\n", markdown)

    # Extract title from first H1 or page title
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)

    # Extract headings
    headings = []
    for h in content_el.find_all(["h1", "h2", "h3"]):
        headings.append({
            "level": int(h.name[1]),
            "text": h.get_text(strip=True),
        })

    # Extract signatures and warnings
    signatures = extract_signatures(code_blocks)
    warnings = extract_warnings(markdown)

    # Classify the page
    category = classify_page(title, headings, code_blocks, markdown)

    return {
        "url": url,
        "title": title,
        "category": category,
        "markdown": markdown,
        "code_blocks": code_blocks,
        "signatures": signatures,
        "headings": headings,
        "warnings": warnings,
    }


def main():
    args = parse_args()

    # Load sitemap
    with open(args.sitemap, "r", encoding="utf-8") as f:
        sitemap = json.load(f)

    pages = sitemap.get("pages", [])
    if not pages:
        log.error("No pages found in sitemap")
        sys.exit(1)

    log.info(f"Extracting content from {len(pages)} pages")

    # Create output directory
    os.makedirs(args.output, exist_ok=True)

    converter = configure_html2text()
    category_counts = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        stealth_sync(page)

        for i, entry in enumerate(pages):
            url = entry["url"]
            log.info(f"[{i+1}/{len(pages)}] {url}")

            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)  # Wait for JS rendering

                if response and response.status >= 400:
                    log.warning(f"HTTP {response.status} for {url}, skipping")
                    continue

                data = extract_page(page, url, converter)

                # Track category counts
                cat = data["category"]
                category_counts[cat] = category_counts.get(cat, 0) + 1

                # Write output
                filename = url_to_filename(url)
                output_path = os.path.join(args.output, filename)
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

                log.info(f"  -> {cat} | {len(data['markdown'])} chars | {len(data['code_blocks'])} code blocks | {len(data['signatures'])} signatures")

            except Exception as e:
                log.error(f"Error extracting {url}: {e}")

            time.sleep(humanized_delay(args.delay))

        browser.close()

    # Summary
    log.info("=" * 60)
    log.info("Extraction complete")
    log.info(f"Output directory: {args.output}")
    log.info(f"Total pages extracted: {sum(category_counts.values())}")
    log.info("Category breakdown:")
    for cat, count in sorted(category_counts.items()):
        log.info(f"  {cat}: {count}")


if __name__ == "__main__":
    main()

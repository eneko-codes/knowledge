#!/usr/bin/env python3
"""Content extractor for crawled documentation pages.

Fetches full content of every page in a sitemap, detects the main content area,
converts HTML to markdown, classifies pages by category, and extracts code blocks
and function signatures.

Architecture:
  For each page URL in the sitemap (produced by crawl.py), this script:
  1. Navigates to the page with Playwright (same stealth setup as the crawler)
  2. Parses the rendered HTML with BeautifulSoup
  3. Locates the main content area using a prioritized list of CSS selectors
  4. Strips non-content elements (nav, sidebar, footer, etc.)
  5. Extracts code blocks with language annotations before HTML→markdown conversion
  6. Converts the cleaned HTML to markdown using html2text
  7. Classifies the page into a documentation category (api-reference, tutorial, etc.)
  8. Extracts function signatures using language-specific regex patterns
  9. Outputs one JSON file per page with all structured data

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
from playwright_stealth import Stealth

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


# ---------------------------------------------------------------------------
# Content area detection
# ---------------------------------------------------------------------------

# CSS selectors for the main content area, tried in priority order.
# Modern doc frameworks use semantic HTML (<main>, <article>) or ARIA roles,
# while older sites use class/id conventions. We try the most specific first.
#
# The 100-character minimum text check (in find_main_content) prevents matching
# an empty <main> wrapper that exists only for layout purposes.
CONTENT_SELECTORS = [
    "main",                # HTML5 semantic: Docusaurus, VitePress, MkDocs
    "article",             # HTML5 semantic: Hugo, Jekyll, some custom sites
    "[role='main']",       # ARIA role: accessibility-focused sites
    "#content",            # Common id: Sphinx (Read the Docs), GitBook
    "#main-content",       # Alternative id: some Confluence-derived sites
    ".content",            # Class-based: generic CMS themes
    ".docs-content",       # Class-based: Docusaurus v1, custom frameworks
    ".doc-content",        # Class-based: variant spelling
    ".markdown-body",      # GitHub-style: rendered markdown in GitHub Pages
    ".documentation",      # Class-based: some Ruby/Python doc generators
    ".post-content",       # Class-based: blog-style doc sites
    ".page-content",       # Class-based: generic CMS themes
    ".article-content",    # Class-based: article-focused layouts
    ".rst-content",        # Sphinx: reStructuredText content area
    ".md-content",         # MkDocs Material theme
]

# Elements that appear inside the content area but are not actual documentation.
# We remove these before converting to markdown to avoid polluting the output
# with navigation breadcrumbs, "Edit this page" links, copy-to-clipboard buttons, etc.
STRIP_SELECTORS = [
    "nav",                   # Nested navigation (e.g., prev/next page links)
    "header",                # Page headers that leak into <main>
    "footer",                # Page footers with copyright/links
    ".sidebar",              # Sidebar TOC that some themes put inside <main>
    ".toc",                  # Table of contents widget
    ".table-of-contents",    # Longer class name variant
    ".nav-links",            # Previous/next navigation links
    ".edit-this-page",       # "Edit on GitHub" button
    ".page-nav",             # Page-level navigation
    ".breadcrumb",           # Breadcrumb navigation trail
    ".breadcrumbs",          # Plural variant
    ".header-anchor",        # Clickable # anchor links on headings
    ".copy-button",          # Code block copy-to-clipboard button
    ".highlight-copy-btn",   # Alternative copy button class
    "script",                # Inline scripts (analytics, etc.)
    "style",                 # Inline stylesheets
    "noscript",              # Fallback content for no-JS browsers
]


def find_main_content(soup):
    """Locate the primary content element in the page DOM.

    Iterates through CONTENT_SELECTORS in priority order and returns the first
    match that contains more than 100 characters of visible text. The text length
    threshold avoids matching empty wrapper elements.

    Falls back to <body> if no selector matches — this handles minimal HTML pages
    (e.g., raw GitHub Pages with no semantic markup).
    """
    for selector in CONTENT_SELECTORS:
        el = soup.select_one(selector)
        # Require >100 chars to avoid matching empty structural elements
        if el and len(el.get_text(strip=True)) > 100:
            return el
    # Fallback: entire body (or root soup if no body tag)
    return soup.body if soup.body else soup


def strip_noise(content_el):
    """Remove non-content elements from the content area.

    Mutates the BeautifulSoup element in place by decomposing (removing from tree)
    all elements matching STRIP_SELECTORS, plus HTML comments.

    This must run AFTER extract_code_blocks() because some code blocks might be
    siblings of navigation elements — we want to capture the code first.
    """
    for selector in STRIP_SELECTORS:
        for el in content_el.select(selector):
            el.decompose()

    # HTML comments often contain build metadata, template markers, or editor hints
    # that would appear as visible text in the markdown output.
    for comment in content_el.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    return content_el


# ---------------------------------------------------------------------------
# Code block extraction
# ---------------------------------------------------------------------------

def extract_code_blocks(soup):
    """Extract all code blocks from the page with their programming language.

    Documentation sites render code in <pre><code>...</code></pre> elements.
    The programming language is typically annotated as a CSS class on the <code>
    or <pre> element, using one of several conventions:

    - class="language-python"    (Prism.js, highlight.js — most common)
    - class="highlight-python"   (Pygments, some Sphinx themes)
    - class="sourceCode python"  (Pandoc-generated HTML)

    We extract code blocks BEFORE stripping noise from the DOM, because some
    doc sites place code blocks adjacent to navigation elements that would
    be removed by strip_noise().

    Returns a list of {language: str, content: str} dicts.
    """
    blocks = []
    for pre in soup.find_all("pre"):
        code = pre.find("code")
        if code:
            # Try to detect the language from CSS classes on the <code> element.
            # Different syntax highlighting libraries use different class conventions.
            language = ""
            classes = code.get("class", [])
            for cls in classes:
                if cls.startswith("language-"):
                    # Prism.js / highlight.js convention: language-python, language-go
                    language = cls[len("language-"):]
                    break
                elif cls.startswith("highlight-"):
                    # Pygments convention: highlight-python
                    language = cls[len("highlight-"):]
                    break
                elif cls.startswith("sourceCode"):
                    # Pandoc convention: sourceCode python (space-separated)
                    language = cls.replace("sourceCode", "").strip()
                    break

            # Some themes put the language class on <pre> instead of <code>
            if not language:
                pre_classes = pre.get("class", [])
                for cls in pre_classes:
                    if cls.startswith("language-"):
                        language = cls[len("language-"):]
                        break

            # Get the raw text content (no HTML tags)
            content = code.get_text()
            if content.strip():
                blocks.append({"language": language, "content": content})
        else:
            # Bare <pre> without <code> — some older sites use this for code
            content = pre.get_text()
            if content.strip():
                blocks.append({"language": "", "content": content})

    return blocks


# ---------------------------------------------------------------------------
# Function signature extraction
# ---------------------------------------------------------------------------

# Regex patterns for extracting function/method signatures from code blocks.
# Each pattern targets a specific programming language's declaration syntax.
# These are intentionally broad — we'd rather capture a false positive
# (which is still useful context) than miss a real API signature.
SIGNATURE_PATTERNS = [
    # Go: func Name(args) returnType  or  func (receiver) Name(args) returnType
    re.compile(r"func\s+(?:\([^)]*\)\s+)?\w+\s*\([^)]*\)(?:\s*(?:\([^)]*\)|[^{]+?))?(?:\s*\{)?"),

    # Python: def name(args) -> ReturnType:  or  async def name(args):
    re.compile(r"(?:async\s+)?def\s+\w+\s*\([^)]*\)(?:\s*->\s*[^:]+)?:"),

    # TypeScript/JavaScript: function name(args): ReturnType  or  export async function
    re.compile(r"(?:export\s+)?(?:async\s+)?function\s+\w+\s*(?:<[^>]*>)?\s*\([^)]*\)(?:\s*:\s*[^{]+)?"),

    # Rust: fn name(args) -> ReturnType  or  pub async fn name<T>(args)
    re.compile(r"(?:pub\s+)?(?:async\s+)?fn\s+\w+\s*(?:<[^>]*>)?\s*\([^)]*\)(?:\s*->\s*[^{]+)?"),

    # Java/Kotlin: public static ReturnType name(args)
    re.compile(r"(?:public|private|protected)?\s*(?:static\s+)?(?:async\s+)?\w+(?:<[^>]*>)?\s+\w+\s*\([^)]*\)"),
]


def extract_signatures(code_blocks):
    """Extract function/method signatures from code blocks.

    Scans each code block against language-specific regex patterns to find
    function declarations. These signatures are surfaced in the generated
    SKILL.md as a quick-reference section for the most common API functions.

    Signatures are deduplicated and capped at 300 characters to exclude
    excessively long generic type signatures that would be noisy.
    """
    signatures = []
    for block in code_blocks:
        for pattern in SIGNATURE_PATTERNS:
            for match in pattern.finditer(block["content"]):
                sig = match.group(0).strip()
                # Remove trailing opening brace if captured
                sig = sig.rstrip("{").strip()
                # Skip excessively long signatures (complex generics, etc.)
                if len(sig) < 300 and sig not in signatures:
                    signatures.append(sig)
    return signatures


# ---------------------------------------------------------------------------
# Page classification
# ---------------------------------------------------------------------------

def classify_page(title, headings, code_blocks, markdown_text):
    """Classify a documentation page into one of five categories.

    Categories and their heuristics:

    - "warning":       Pages about deprecations, breaking changes, migrations.
                       Detected by keyword density (>= 2 warning indicators).

    - "example":       Pages dominated by code with minimal explanation.
                       Detected by code-to-text ratio > 0.6 (60% code).

    - "api-reference": API docs with function signatures, parameters, return types.
                       Detected by keyword density OR code ratio > 0.3 with signatures.

    - "tutorial":      Step-by-step guides ("Step 1", "Getting started", etc.).
                       Detected by sequential/procedural keyword density.

    - "conceptual":    Explanatory content (overviews, architecture, design docs).
                       Default for text-heavy pages that don't match other categories.

    The classification is heuristic and intentionally conservative — it's better
    to default to "conceptual" than to miscategorize an API reference as a tutorial.
    Claude reviews classifications during the workflow and can correct them.
    """
    title_lower = title.lower()
    text_lower = markdown_text.lower()

    # Calculate code density: ratio of code block content to total page text.
    # High code density suggests example/reference pages rather than prose.
    text_len = len(markdown_text)
    code_len = sum(len(b["content"]) for b in code_blocks)
    code_ratio = code_len / max(text_len, 1)  # max(_, 1) prevents division by zero

    # Score each category by counting how many indicator phrases appear in the text.
    # Each indicator is a lowercase phrase that's characteristic of that page type.

    api_indicators = ["api reference", "api documentation", "function reference", "method reference",
                      "class reference", "type reference", "parameters", "returns", "arguments"]
    api_score = sum(1 for ind in api_indicators if ind in text_lower)

    tutorial_indicators = ["step 1", "step 2", "getting started", "tutorial", "walkthrough",
                          "quickstart", "quick start", "how to", "guide"]
    tutorial_score = sum(1 for ind in tutorial_indicators if ind in text_lower)

    concept_indicators = ["overview", "introduction", "concept", "architecture", "design",
                         "explanation", "understanding", "background"]
    concept_score = sum(1 for ind in concept_indicators if ind in text_lower)

    warning_indicators = ["deprecated", "breaking change", "migration", "upgrade", "removed in",
                         "no longer supported", "end of life"]
    warning_score = sum(1 for ind in warning_indicators if ind in text_lower)

    # Classification priority: warnings > examples > api-reference > tutorial > conceptual.
    # Warnings come first because deprecation notices can appear on any page type.
    if warning_score >= 2:
        return "warning"
    # High code ratio without tutorial markers = example/sample code page
    if code_ratio > 0.6 and tutorial_score < 2:
        return "example"
    # API reference: either keyword-heavy or moderate code with actual signatures
    if api_score >= 2 or (code_ratio > 0.3 and any(extract_signatures([b]) for b in code_blocks)):
        return "api-reference"
    if tutorial_score >= 2:
        return "tutorial"
    if concept_score >= 1:
        return "conceptual"
    # Final fallback based on code density
    if code_ratio > 0.4:
        return "example"
    return "conceptual"


def extract_warnings(markdown_text):
    """Extract deprecation notices and warning callouts from markdown text.

    Scans line by line for patterns like "Deprecated: ...", "Warning: ...",
    "Removed in v2.0: ...", etc. These are surfaced separately in the generated
    plugin so Claude can proactively warn users about deprecated APIs.
    """
    warnings = []
    lines = markdown_text.split("\n")
    warning_patterns = [
        # Matches "Deprecated:", "Warning!", "Caution:", etc. followed by description
        re.compile(r"(?:deprecated|warning|caution|danger|important)\s*[:!]?\s*(.+)", re.IGNORECASE),
        # Matches "Removed in v2.0" or "Breaking change since 3.x" style notices
        re.compile(r"(?:removed|breaking change)\s+(?:in|since)\s+(.+)", re.IGNORECASE),
    ]
    for line in lines:
        for pattern in warning_patterns:
            match = pattern.search(line)
            if match:
                # Clean up: strip markdown blockquote markers (>) and emphasis (*_)
                warning_text = line.strip().lstrip(">").strip().lstrip("*_").rstrip("*_").strip()
                # Skip very short matches (likely false positives) and duplicates
                if warning_text and len(warning_text) > 10 and warning_text not in warnings:
                    warnings.append(warning_text)
    return warnings


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def url_to_filename(url):
    """Convert a URL to a filesystem-safe filename for the extracted JSON.

    Strategy:
    - Use the URL path as the base (strip domain, scheme, query)
    - Replace non-alphanumeric characters with underscores
    - Collapse consecutive underscores
    - Truncate to 200 chars to stay within filesystem limits
    - Append .json extension

    Example: https://docs.example.com/en/stable/api/config.html → en_stable_api_config.html.json
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        path = "index"
    # Replace anything that isn't alphanumeric, dot, dash, or underscore
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", path)
    safe = re.sub(r"_+", "_", safe)
    if len(safe) > 200:
        safe = safe[:200]
    return safe + ".json"


def humanized_delay(base_delay):
    """Add random jitter to delay for human-like request spacing.

    Slightly less jitter than the crawler (±0.3s vs ±0.5s) since we're
    re-visiting pages we already crawled — the server has seen us before.
    """
    jitter = random.uniform(-0.3, 0.3)
    return max(0.2, base_delay + jitter)


def configure_html2text():
    """Create and configure an html2text converter instance.

    html2text converts HTML to markdown. We configure it to:
    - body_width=0: disable line wrapping (doc content should preserve original formatting)
    - protect_links=True: don't mangle URLs in markdown link syntax
    - unicode_snob=True: use Unicode characters instead of ASCII approximations
    - mark_code=True: wrap inline code in backticks
    - wrap_links/wrap_list_items=False: prevent breaking long URLs or list items
    """
    h = html2text.HTML2Text()
    h.body_width = 0          # Don't wrap lines — preserves code indentation
    h.protect_links = True     # Keep URLs intact, don't shorten/mangle them
    h.unicode_snob = True      # Prefer Unicode chars (e.g., — instead of --)
    h.skip_internal_links = False  # Keep anchor links within the page
    h.ignore_images = False    # Keep image references (useful for diagrams)
    h.ignore_emphasis = False  # Preserve bold/italic markers
    h.mark_code = True         # Wrap inline <code> in backticks
    h.wrap_links = False       # Don't break long URLs across lines
    h.wrap_list_items = False  # Don't break list items across lines
    return h


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def extract_page(page_obj, url, converter):
    """Extract all structured content from a single rendered page.

    Orchestrates the full extraction pipeline:
    1. Get rendered HTML from Playwright
    2. Parse with BeautifulSoup (using lxml parser for speed)
    3. Find main content area
    4. Extract code blocks (before noise stripping, since code may be adjacent to nav)
    5. Strip non-content elements
    6. Convert cleaned HTML to markdown
    7. Extract title, headings, signatures, warnings
    8. Classify the page category

    Returns a dict with all extracted data, ready to be written as JSON.
    """
    html = page_obj.content()
    # lxml is faster than html.parser and more lenient with malformed HTML
    soup = BeautifulSoup(html, "lxml")

    # Step 1: Find the content area and extract code blocks FIRST.
    # Code blocks must be extracted before strip_noise() because some nav elements
    # (like "copy to clipboard" buttons) are siblings of code blocks.
    content_el = find_main_content(soup)
    code_blocks = extract_code_blocks(content_el)

    # Step 2: Remove navigation, sidebars, footers, etc. from the content area
    content_el = strip_noise(content_el)

    # Step 3: Convert the cleaned HTML to markdown
    content_html = str(content_el)
    markdown = converter.handle(content_html).strip()

    # Clean up: collapse runs of 4+ blank lines to 3 (keeps readability without waste)
    markdown = re.sub(r"\n{4,}", "\n\n\n", markdown)

    # Step 4: Extract the page title — prefer H1 over <title> since the latter
    # often includes the site name suffix ("Config - MyLib Docs")
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)

    # Step 5: Extract H1-H3 headings for structural metadata
    headings = []
    for h in content_el.find_all(["h1", "h2", "h3"]):
        headings.append({
            "level": int(h.name[1]),
            "text": h.get_text(strip=True),
        })

    # Step 6: Extract function signatures and deprecation warnings
    signatures = extract_signatures(code_blocks)
    warnings = extract_warnings(markdown)

    # Step 7: Classify into a documentation category
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    # Load the sitemap produced by crawl.py
    with open(args.sitemap, "r", encoding="utf-8") as f:
        sitemap = json.load(f)

    pages = sitemap.get("pages", [])
    if not pages:
        log.error("No pages found in sitemap")
        sys.exit(1)

    log.info(f"Extracting content from {len(pages)} pages")

    # Create output directory (no error if it already exists)
    os.makedirs(args.output, exist_ok=True)

    converter = configure_html2text()
    category_counts = {}  # Track how many pages fall into each category

    # Launch browser — same stealth configuration as the crawler.
    # We reuse one browser instance for all pages to avoid the ~2s startup
    # cost per page and to maintain session cookies.
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        for i, entry in enumerate(pages):
            url = entry["url"]
            log.info(f"[{i+1}/{len(pages)}] {url}")

            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Longer wait than crawler (1.5s vs 1s) because we need the full
                # content to be rendered, not just the link structure
                page.wait_for_timeout(1500)

                if response and response.status >= 400:
                    log.warning(f"HTTP {response.status} for {url}, skipping")
                    continue

                # Run the full extraction pipeline for this page
                data = extract_page(page, url, converter)

                # Accumulate category counts for the summary
                cat = data["category"]
                category_counts[cat] = category_counts.get(cat, 0) + 1

                # Write one JSON file per page — filename derived from URL path
                filename = url_to_filename(url)
                output_path = os.path.join(args.output, filename)
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

                log.info(f"  -> {cat} | {len(data['markdown'])} chars | {len(data['code_blocks'])} code blocks | {len(data['signatures'])} signatures")

            except Exception as e:
                log.error(f"Error extracting {url}: {e}")

            # Rate limiting between page fetches
            time.sleep(humanized_delay(args.delay))

        browser.close()

    # Print extraction summary
    log.info("=" * 60)
    log.info("Extraction complete")
    log.info(f"Output directory: {args.output}")
    log.info(f"Total pages extracted: {sum(category_counts.values())}")
    log.info("Category breakdown:")
    for cat, count in sorted(category_counts.items()):
        log.info(f"  {cat}: {count}")


if __name__ == "__main__":
    main()

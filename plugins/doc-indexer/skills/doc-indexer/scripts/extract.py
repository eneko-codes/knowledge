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
  5. Converts the cleaned HTML to markdown using markdownify (with inline
     language detection via code_language_callback — no placeholder system)
  6. Classifies the page into a documentation category (api-reference, tutorial, etc.)
  7. Extracts function signatures using language-specific regex patterns
  8. Outputs one JSON file per page with all structured data

Usage:
    python3 extract.py <sitemap.json> [--output extracted/] [--delay 1.0] [--guess-languages]
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

from bs4 import BeautifulSoup, Comment
from markdownify import markdownify as md
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
    p.add_argument("--delay", type=float, default=0.5, help="Base delay between requests in seconds (default: 0.5)")
    p.add_argument("--force", action="store_true", help="Re-extract pages even if output file already exists")
    p.add_argument("--guess-languages", action="store_true",
                   help="Use Pygments to guess language for unannotated code blocks")
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
    ".tabs",                 # Tab navigation bar (Pest/PHPUnit code tabs)
    ".tab-list",             # Alternative tab list class
    "[role='tablist']",      # ARIA role for tab navigation lists
]

# JavaScript injected into the live page to clean code blocks before HTML extraction.
# Uses computed styles (not class names) to generically catch noise from any syntax
# highlighting library — Torchlight, Prism, highlight.js, Shiki, Pygments, etc.
#
# Three cleaning passes:
# 1. Remove invisible/decorative elements inside <pre> (line numbers, copy targets,
#    annotation anchors) detected via computed CSS: display:none, visibility:hidden,
#    user-select:none, or aria-hidden="true".
# 2. Unwrap div-per-line wrappers (Torchlight, Docusaurus) that cause markdownify to
#    emit double blank lines between every line of code. Only triggers when ALL direct
#    children of <code> are <div> elements — a clear div-per-line structure.
# 3. Expand <details> elements so collapsed content is visible.
JS_CLEAN_CODE_BLOCKS = """
(() => {
    // Pass 1: Remove hidden/decorative elements inside <pre>
    document.querySelectorAll('pre').forEach(pre => {
        pre.querySelectorAll('*').forEach(el => {
            const s = window.getComputedStyle(el);
            if (s.display === 'none' ||
                s.visibility === 'hidden' ||
                s.userSelect === 'none' ||
                el.getAttribute('aria-hidden') === 'true') {
                el.remove();
            }
        });
    });
    // Pass 2: Unwrap div-per-line wrappers inside <code>
    document.querySelectorAll('pre code').forEach(code => {
        const ch = [...code.children];
        if (ch.length > 0 && ch.every(c => c.tagName === 'DIV')) {
            ch.forEach(div => {
                while (div.firstChild) code.insertBefore(div.firstChild, div);
                code.insertBefore(document.createTextNode('\\n'), div);
                div.remove();
            });
        }
    });
    // Pass 3: Expand <details> elements
    document.querySelectorAll('details').forEach(d => d.open = true);
})()
"""


def find_main_content(soup):
    """Locate the primary content element in the page DOM.

    Iterates through CONTENT_SELECTORS in priority order and returns the first
    match that contains more than 500 characters of visible text. The text length
    threshold (raised from 100 to 500) avoids matching small nav sections or
    empty wrapper elements.

    If the first match contains a <nav> or <aside> child, it's likely a layout
    wrapper rather than the actual content area. In that case, we try to find a
    more specific child element (an <article>, <section>, or <div> with enough
    text) before accepting the match.

    Falls back to <body> if no selector matches — this handles minimal HTML pages
    (e.g., raw GitHub Pages with no semantic markup). The fallback is flagged
    via the returned used_fallback boolean so downstream code can warn about
    potential noise from navigation/sidebar content leaking into the extraction.

    Returns:
        (element, used_fallback) tuple
    """
    for selector in CONTENT_SELECTORS:
        el = soup.select_one(selector)
        # Require >500 chars to avoid matching small nav sections or empty wrappers
        if el and len(el.get_text(strip=True)) > 500:
            # If the match contains <nav> or <aside>, it may be a broad layout
            # wrapper. Try to find a more specific child element first.
            if el.find("nav") or el.find("aside"):
                # Look for a child article, section, or div with substantial content
                for child_tag in ["article", "section", "div"]:
                    for child in el.find_all(child_tag, recursive=False):
                        child_text = child.get_text(strip=True)
                        # The child must have substantial content AND not itself
                        # be a nav/aside to be a better match
                        if (len(child_text) > 500
                                and not child.find("nav")
                                and child.name not in ("nav", "aside")):
                            return child, False
                # No better child found — use the original match, it's still
                # the best we have. strip_noise() will clean out the nav/aside.
            return el, False
    # Fallback: entire body (or root soup if no body tag).
    # This may capture navigation, sidebar, footer — flag it.
    log.warning("No content selector matched, falling back to <body>")
    return (soup.body if soup.body else soup), True


def strip_noise(content_el):
    """Remove non-content elements from the content area.

    Mutates the BeautifulSoup element in place by decomposing (removing from tree)
    all elements matching STRIP_SELECTORS, plus HTML comments.
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

def _detect_language_from_element(el):
    """Extract programming language from an HTML element's CSS classes and data attributes.

    Checks multiple conventions used by different syntax highlighting libraries
    and documentation generators. Returns empty string if no language is found.
    """
    classes = el.get("class", [])
    for cls in classes:
        if cls.startswith("language-"):
            return cls[len("language-"):]
        if cls.startswith("highlight-"):
            return cls[len("highlight-"):]
        if cls.startswith("brush:"):
            # SyntaxHighlighter convention: brush:python
            return cls[len("brush:"):].strip()
        if cls == "sourceCode":
            # Pandoc convention: class list ["sourceCode", "python"]
            for other_cls in classes:
                if other_cls != "sourceCode" and not other_cls.startswith("source"):
                    return other_cls
            continue
        if cls.startswith("sourceCode "):
            return cls[len("sourceCode "):].strip()

    # data-lang / data-language attributes (Docusaurus v2, Hugo, some React sites)
    for attr in ("data-lang", "data-language", "lang"):
        val = el.get(attr, "")
        if val:
            return val

    return ""


def _code_language_callback(pre_element):
    """Callback for markdownify to detect code block languages.

    Called by markdownify for each <pre> element during HTML→markdown conversion.
    Checks child <code>, then <pre>, then parent <div> for language annotations
    using _detect_language_from_element().

    Returns language string or empty string.
    """
    code = pre_element.find("code")
    if code:
        lang = _detect_language_from_element(code)
        if lang:
            return lang

    lang = _detect_language_from_element(pre_element)
    if lang:
        return lang

    if pre_element.parent and pre_element.parent.name in ("div", "td"):
        lang = _detect_language_from_element(pre_element.parent)
        if lang:
            return lang

    return ""


def _extract_code_blocks_from_soup(content_el):
    """Extract code block metadata from <pre> elements without modifying the DOM.

    Read-only traversal used to capture {language, content} for metadata
    (signatures, classify_page). Does NOT modify the DOM — markdownify handles
    the actual conversion.
    """
    blocks = []
    for pre in content_el.find_all("pre"):
        code = pre.find("code")
        language = ""
        content = ""

        if code:
            language = _detect_language_from_element(code)
            if not language:
                language = _detect_language_from_element(pre)
            if not language and pre.parent and pre.parent.name in ("div", "td"):
                language = _detect_language_from_element(pre.parent)
            content = code.get_text()
        else:
            language = _detect_language_from_element(pre)
            if not language and pre.parent and pre.parent.name in ("div", "td"):
                language = _detect_language_from_element(pre.parent)
            content = pre.get_text()

        if content.strip():
            blocks.append({"language": language, "content": content})

    return blocks


def _guess_code_block_languages(markdown_text):
    """Annotate bare ``` code blocks with Pygments-guessed languages.

    Only called when --guess-languages is set. Finds unannotated fenced code
    blocks, runs Pygments guess_lexer(), and annotates if confident.
    """
    from pygments.lexers import guess_lexer
    from pygments.util import ClassNotFound

    def replace_bare_fence(match):
        code = match.group(1)
        if not code.strip():
            return match.group(0)
        try:
            lexer = guess_lexer(code)
            lang = lexer.aliases[0] if lexer.aliases else lexer.name.lower()
            return f"```{lang}\n{code}```"
        except (ClassNotFound, Exception):
            return match.group(0)

    pattern = re.compile(r'```\n(.*?)```', re.DOTALL)
    return pattern.sub(replace_bare_fence, markdown_text)


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

def classify_page(title, headings, code_blocks, markdown_text, url=""):
    """Classify a documentation page into one of five categories.

    Categories and their heuristics:

    - "warning":       Pages about deprecations, breaking changes, migrations.
                       Detected by title keywords or body keyword density (>= 3).

    - "example":       Pages dominated by code with minimal explanation.
                       Detected by code-to-text ratio > 0.6 (60% code).

    - "api-reference": API docs with function signatures, parameters, return types.
                       Detected by keyword density OR code ratio > 0.3 with signatures.

    - "tutorial":      Step-by-step guides ("Step 1", "Getting started", etc.).
                       Detected by sequential/procedural keyword density.

    - "conceptual":    Explanatory content (overviews, architecture, design docs).
                       Default for text-heavy pages that don't match other categories.

    Title matches are weighted 3x vs body matches (the title is the strongest
    classification signal). URL path segments add +2 to the relevant category.
    Heading structure (H2/H3 that look like function signatures) boosts api_score.

    The classification is heuristic and intentionally conservative — it's better
    to default to "conceptual" than to miscategorize an API reference as a tutorial.
    Claude reviews classifications during the workflow and can correct them.
    """
    title_lower = title.lower()
    text_lower = markdown_text.lower()

    # Extract URL path for path-based classification signal
    url_path = urlparse(url).path.lower() if url else ""

    # Calculate code density: ratio of code block content to total page text.
    # High code density suggests example/reference pages rather than prose.
    text_len = len(markdown_text)
    code_len = sum(len(b["content"]) for b in code_blocks)
    code_ratio = code_len / max(text_len, 1)  # max(_, 1) prevents division by zero

    # --- Warning detection ---
    # Title match is an immediate classification. Body keywords need >= 3 matches
    # (threshold raised from 2 to avoid pages that incidentally mention "deprecated").
    warning_title_indicators = ["deprecat", "breaking change", "upgrade guide",
                                "migration guide", "end of life", "eol",
                                "sunset", "removed in"]
    warning_body_indicators = ["deprecated", "breaking change", "end of life", "eol",
                               "sunset", "removed in", "migration guide", "upgrade guide",
                               "no longer supported", "will be removed"]
    is_warning_title = any(ind in title_lower for ind in warning_title_indicators)
    if is_warning_title:
        return "warning"
    warning_body_score = sum(1 for ind in warning_body_indicators if ind in text_lower)
    if warning_body_score >= 3:
        return "warning"

    # --- URL path signal ---
    # URL path bonuses — add +2 to category scores for matching path segments
    url_api_bonus = 2 if any(seg in url_path for seg in ["/api/", "/reference/", "/ref/"]) else 0
    url_tutorial_bonus = 2 if any(seg in url_path for seg in ["/tutorial/", "/guide/", "/guides/", "/getting-started/"]) else 0
    url_cli_bonus = 2 if "/cli/" in url_path else 0
    url_troubleshoot_bonus = 2 if "/troubleshooting/" in url_path else 0

    # --- Heading structure signal ---
    # If most H2/H3 headings look like function/method signatures (contain
    # parentheses or start with a type keyword), boost api_score.
    h2h3_headings = [h["text"] for h in headings if h.get("level") in (2, 3)]
    sig_like_count = 0
    for ht in h2h3_headings:
        # Headings with parentheses like "create(options)" or "Response.json()"
        if "(" in ht and ")" in ht:
            sig_like_count += 1
        # Headings starting with common type prefixes: "string Name", "void Execute"
        elif re.match(r'^(?:string|int|bool|void|array|object|float|static|public|private)\s+\w+', ht, re.IGNORECASE):
            sig_like_count += 1
    heading_api_bonus = 2 if (h2h3_headings and sig_like_count > len(h2h3_headings) / 2) else 0

    # --- Tutorial detection ---
    # Title-weighted: "getting started", "tutorial", "installation" in the title
    # are strong signals. Body keywords are weaker.
    tutorial_title_indicators = ["getting started", "tutorial", "walkthrough",
                                "quickstart", "quick start", "installation", "how to"]
    tutorial_body_indicators = ["step 1", "step 2", "tutorial", "walkthrough",
                               "quickstart", "quick start", "how to", "guide",
                               "example", "recipe", "cookbook", "hands-on",
                               "follow along"]
    tutorial_title_score = sum(3 for ind in tutorial_title_indicators if ind in title_lower)
    tutorial_body_score = sum(1 for ind in tutorial_body_indicators if ind in text_lower)
    tutorial_score = tutorial_title_score + tutorial_body_score + url_tutorial_bonus
    if tutorial_score >= 3:
        return "tutorial"

    # --- API reference detection ---
    # Title-weighted: "reference", "api" in title are strong signals.
    # Also triggered by high function signature density.
    api_title_indicators = ["reference", "api", "helpers", "collections"]
    api_body_indicators = ["api reference", "api documentation", "function reference",
                          "method reference", "class reference", "type reference",
                          "parameters", "returns", "arguments", "endpoint",
                          "request", "response", "schema", "request body",
                          "response body", "throws", "interface", "enum",
                          "http method"]
    api_title_score = sum(3 for ind in api_title_indicators if ind in title_lower)
    api_body_score = sum(1 for ind in api_body_indicators if ind in text_lower)
    api_score = api_title_score + api_body_score + url_api_bonus + url_cli_bonus + heading_api_bonus
    if api_score >= 4 or (code_ratio > 0.3 and any(extract_signatures([b]) for b in code_blocks)):
        return "api-reference"

    # --- Example detection ---
    # Pages dominated by code with minimal prose.
    if code_ratio > 0.6 and tutorial_score < 3:
        return "example"

    # --- Conceptual detection ---
    concept_indicators = ["overview", "introduction", "concept", "architecture", "design",
                         "explanation", "understanding", "background"]
    concept_score = sum(1 for ind in concept_indicators if ind in text_lower)
    if concept_score >= 1:
        return "conceptual"

    # Final fallback based on code density
    if code_ratio > 0.4:
        return "example"
    return "conceptual"


def extract_warnings(markdown_text):
    """Extract deprecation notices and warning callouts from markdown text.

    Only matches structured admonition patterns — lines that start with a clear
    warning marker like "> **Warning:**", "> [!WARNING]", "**Deprecated:**", etc.
    This avoids false positives from normal prose that merely mentions the word
    "warning" or "deprecated" in a sentence (e.g., "this guide covers migration").

    Previously this function used loose regex that matched any line containing
    "deprecated" or "warning" anywhere, causing massive false positives (blog
    titles, tutorial descriptions, etc.). The stricter patterns below only match
    lines that are clearly formatted as admonitions or notices.
    """
    warnings = []
    lines = markdown_text.split("\n")
    warning_patterns = [
        # Markdown admonition: "> **Warning:**", "> **Deprecated:**", "> **Caution:**"
        re.compile(r"^>\s*\*\*(?:Warning|Deprecated|Caution|Danger|Important)\*\*\s*[:!]\s*(.+)", re.IGNORECASE),
        # GitHub-style alert: "> [!WARNING]", "> [!CAUTION]"
        re.compile(r"^>\s*\[!(?:WARNING|CAUTION|DANGER|IMPORTANT)\]\s*(.*)$", re.IGNORECASE),
        # Bold label at line start: "**Deprecated:** ...", "**Warning:** ..."
        re.compile(r"^\*\*(?:Deprecated|Warning|Caution|Breaking Change)\*\*\s*[:!]\s*(.+)", re.IGNORECASE),
        # Explicit deprecation notice: "Deprecated since v1.x" at line start
        re.compile(r"^(?:Deprecated|Removed)\s+(?:since|in|as of)\s+v?\d+", re.IGNORECASE),
    ]
    for line in lines:
        stripped = line.strip()
        for pattern in warning_patterns:
            match = pattern.search(stripped)
            if match:
                # Use the full line as the warning text, cleaned up
                warning_text = stripped.lstrip(">").strip().lstrip("*_").rstrip("*_").strip()
                if warning_text and len(warning_text) > 10 and warning_text not in warnings:
                    warnings.append(warning_text)
                break  # One match per line is enough
    return warnings


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

# Module-level set for tracking generated filenames across calls to url_to_filename.
# Prevents collisions when two different URLs produce the same filename
# (e.g., /docs/config and /api/config both become "config.json").
_used_filenames = set()


def url_to_filename(url):
    """Convert a URL to a filesystem-safe filename for the extracted JSON.

    Strategy:
    - Use the URL path as the base (strip domain, scheme, query)
    - Replace non-alphanumeric characters with underscores
    - Collapse consecutive underscores
    - Truncate to 200 chars to stay within filesystem limits
    - Append .json extension
    - Detect collisions and append -1, -2, etc. if needed

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

    candidate = safe + ".json"
    if candidate.lower() in _used_filenames:
        counter = 1
        while f"{safe}-{counter}.json".lower() in _used_filenames:
            counter += 1
        candidate = f"{safe}-{counter}.json"
        log.warning(f"  Filename collision for '{url}' → {candidate}")

    _used_filenames.add(candidate.lower())
    return candidate


def humanized_delay(base_delay):
    """Add random jitter to delay for human-like request spacing.

    Slightly less jitter than the crawler (±0.3s vs ±0.5s) since we're
    re-visiting pages we already crawled — the server has seen us before.
    """
    jitter = random.uniform(-0.3, 0.3)
    return max(0.2, base_delay + jitter)


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def extract_page(page_obj, url, guess_languages=False):
    """Extract all structured content from a single rendered page.

    Orchestrates the full extraction pipeline:
    1. Get rendered HTML from Playwright
    2. Parse with BeautifulSoup (using lxml parser for speed)
    3. Find main content area and extract code block metadata (read-only)
    4. Strip non-content elements
    5. Convert cleaned HTML to markdown using markdownify (with inline
       language detection via code_language_callback)
    6. Extract title, headings, signatures, warnings
    7. Classify the page category

    Returns a dict with all extracted data, ready to be written as JSON.
    """
    # Step 0: Clean the live DOM via JavaScript BEFORE capturing HTML.
    # This single injection handles three things:
    # 1. Removes invisible/decorative elements inside <pre> (line numbers, copy
    #    targets, annotation anchors) using computed styles — works generically
    #    across all syntax highlighting libraries without knowing class names.
    # 2. Unwraps div-per-line wrappers (Torchlight, Docusaurus) that cause
    #    markdownify to emit double blank lines between every code line.
    # 3. Expands <details> elements so collapsed content is visible.
    try:
        page_obj.evaluate(JS_CLEAN_CODE_BLOCKS)
    except Exception:
        pass  # Non-critical — BeautifulSoup fallback handles <details> below

    html = page_obj.content()
    # lxml is faster than html.parser and more lenient with malformed HTML
    soup = BeautifulSoup(html, "lxml")

    # Fallback: also expand <details> in the parsed DOM in case the JS injection
    # didn't cover dynamically inserted elements or the page blocked evaluate().
    for details in soup.find_all("details"):
        details["open"] = ""

    # Step 1: Find the content area and extract code block metadata (read-only).
    # _extract_code_blocks_from_soup does NOT modify the DOM — it just captures
    # {language, content} for metadata (signatures, classify_page).
    content_el, used_fallback = find_main_content(soup)
    code_blocks = _extract_code_blocks_from_soup(content_el)

    # Step 2: Remove navigation, sidebars, footers, etc. from the content area.
    content_el = strip_noise(content_el)

    # Step 3: Convert the cleaned HTML to markdown using markdownify.
    # Language annotations are detected inline via _code_language_callback —
    # no placeholder system needed.
    markdown = md(str(content_el), heading_style="ATX", wrap=False,
                  code_language_callback=_code_language_callback,
                  table_infer_header=True).strip()

    # Optional: guess languages for unannotated code blocks using Pygments
    if guess_languages:
        markdown = _guess_code_block_languages(markdown)

    # Clean internal documentation links.
    # Doc sites often have internal links like [Container](/docs/12.x/container) or
    # [Container](</docs/12.x/container>). These absolute paths are meaningless in
    # the generated plugin. Convert them to just the link text (strip the URL).
    markdown = re.sub(r'\[([^\]]+)\]\(<{0,1}/[^)>]+>{0,1}\)', r'\1', markdown)

    # Strip inline table of contents — anchor link lists at the top of pages.
    # These are navigation artifacts like "* [Section Name](<#anchor>)" that
    # are redundant with the actual headings in the body.
    markdown = re.sub(r'^\s*\*\s+\[([^\]]+)\]\(<#[^>]+>\)\s*$', '', markdown, flags=re.MULTILINE)

    # Strip tab switcher UI labels that leak from interactive doc elements.
    # Doc sites use tabbed code examples (e.g., Pest/PHPUnit, macOS/Windows/Linux)
    # and the tab labels appear as raw text lines in the extracted markdown.
    tab_patterns = [
        r'^\s*Pest PHPUnit\s*$',
        r'^\s*macOS Windows PowerShell Linux\s*$',
    ]
    for tp in tab_patterns:
        markdown = re.sub(tp, '', markdown, flags=re.MULTILINE)

    # Strip the leading H1 heading from the markdown content.
    # The section template in build_plugin.py adds its own "# {title}" heading,
    # so the H1 from markdownify conversion creates a duplicate.
    markdown = re.sub(r'^#\s+[^\n]+\n+', '', markdown, count=1)

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
    category = classify_page(title, headings, code_blocks, markdown, url)

    return {
        "url": url,
        "title": title,
        "category": category,
        "markdown": markdown,
        "code_blocks": code_blocks,
        "signatures": signatures,
        "headings": headings,
        "warnings": warnings,
        "used_fallback_selector": used_fallback,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    # Reset module-level state for clean runs (matters if imported as a module)
    _used_filenames.clear()

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

    category_counts = {}  # Track how many pages fall into each category

    # Launch browser — same stealth configuration as the crawler.
    # We reuse one browser instance for all pages to avoid the ~2s startup
    # cost per page and to maintain session cookies.
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        skipped = 0
        for i, entry in enumerate(pages):
            url = entry["url"]

            # Resumability: skip pages whose output file already exists.
            # This allows re-running extract.py after a crash without
            # re-fetching pages that were already successfully extracted.
            filename = url_to_filename(url)
            output_path = os.path.join(args.output, filename)
            if not args.force and os.path.exists(output_path):
                # Still need to count the category for the summary
                try:
                    with open(output_path, "r", encoding="utf-8") as f:
                        cached = json.load(f)
                    cat = cached.get("category", "conceptual")
                    category_counts[cat] = category_counts.get(cat, 0) + 1
                except Exception:
                    pass
                skipped += 1
                continue

            log.info(f"[{i+1}/{len(pages)}] {url}")

            try:
                # Navigate with retry logic for transient failures.
                # First attempt: standard timeout. On failure, retry once with
                # 5-second delay and doubled timeout before giving up.
                response = None
                nav_timeout = 30000
                for attempt in range(3):
                    try:
                        response = page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout)
                        try:
                            page.wait_for_load_state("networkidle", timeout=5000)
                        except Exception:
                            pass
                        break
                    except Exception as nav_err:
                        if attempt < 2:
                            log.warning(f"  Navigation attempt {attempt+1} failed: {nav_err}. Retrying...")
                            time.sleep(5)
                            nav_timeout *= 2  # Double timeout on retry
                        else:
                            raise

                if response and response.status >= 400:
                    log.warning(f"HTTP {response.status} for {url}, skipping")
                    continue

                # Run the full extraction pipeline with retry.
                # If extraction fails (e.g., page didn't fully render), retry
                # once after a 5-second delay with a fresh page load.
                data = None
                try:
                    data = extract_page(page, url, guess_languages=args.guess_languages)
                except Exception as extract_err:
                    log.warning(f"  Extraction failed: {extract_err}. Retrying after 5s...")
                    time.sleep(5)
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout * 2)
                        try:
                            page.wait_for_load_state("networkidle", timeout=10000)
                        except Exception:
                            pass
                        data = extract_page(page, url, guess_languages=args.guess_languages)
                    except Exception as retry_err:
                        log.error(f"  Extraction retry also failed: {retry_err}")
                        continue

                if data is None:
                    continue

                # Accumulate category counts for the summary
                cat = data["category"]
                category_counts[cat] = category_counts.get(cat, 0) + 1

                # Write one JSON file per page — filename already computed above
                # (url_to_filename was called before the skip check)
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

                fallback_note = " [FALLBACK]" if data.get("used_fallback_selector") else ""
                log.info(f"  -> {cat} | {len(data['markdown'])} chars | {len(data['code_blocks'])} code blocks | {len(data['signatures'])} signatures{fallback_note}")

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
    if skipped:
        log.info(f"Skipped (already extracted): {skipped}")
    log.info("Category breakdown:")
    for cat, count in sorted(category_counts.items()):
        log.info(f"  {cat}: {count}")


if __name__ == "__main__":
    main()

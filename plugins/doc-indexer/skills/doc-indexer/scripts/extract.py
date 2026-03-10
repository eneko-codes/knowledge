#!/usr/bin/env python3
"""Content extractor for crawled documentation pages.

Processes saved HTML files (from crawl.py) to extract structured content.
Uses a two-tier extraction strategy for maximum accuracy:

  Primary:  Defuddle (Node.js) — multi-pass content detection with code block
            standardization (language detection from 9+ patterns, line number
            removal, toolbar/header removal). Best for documentation sites.

  Fallback: trafilatura — best benchmarked content extraction (F1 0.958 on
            ScrapingHub benchmark). Internally ensembles its own algorithm +
            readability-lxml + jusText. HTML output fed to markdownify for
            code-block-safe markdown conversion.

Architecture:
  For each page in the sitemap (with saved HTML from crawl.py):
  1. Try Defuddle extraction (produces markdown directly)
  2. If Defuddle fails, fall back to trafilatura → markdownify
  3. Extract metadata: code blocks, headings, signatures, warnings
  4. Classify the page into a documentation category
  5. Output one JSON file per page with all structured data

Usage:
    python3 extract.py <sitemap.json> [--output extracted/] [--force] [--guess-languages]
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("extract")

# Resolve paths relative to this script's location so the script works
# regardless of the current working directory when invoked.
SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args():
    p = argparse.ArgumentParser(description="Extract content from crawled documentation pages")
    p.add_argument("sitemap", help="Path to sitemap.json from crawl.py")
    p.add_argument("--output", "-o", default="extracted", help="Output directory (default: extracted)")
    p.add_argument("--force", action="store_true", help="Re-extract pages even if output file already exists")
    p.add_argument("--guess-languages", action="store_true",
                   help="Use Pygments to guess language for unannotated code blocks")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Defuddle extraction (primary)
# ---------------------------------------------------------------------------

def extract_with_defuddle(html_path, url):
    """Extract content using Defuddle via Node.js subprocess.

    Defuddle (by the Obsidian CEO) uses multi-pass scoring with code block
    standardization:
    - Language detection from 9+ class/attribute patterns
    - Line number removal from multiple formats
    - Toolbar/header cleanup (copy buttons, filename labels)
    - Multi-pass with fallback recovery when initial pass returns empty

    Returns dict with {title, markdown} or None if extraction fails.
    """
    script = SCRIPT_DIR / "defuddle_extract.mjs"
    try:
        result = subprocess.run(
            ["node", str(script), str(html_path), url],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            log.warning(f"  Defuddle failed (exit {result.returncode}): {result.stderr.strip()[:200]}")
            return None
        data = json.loads(result.stdout)
        content = data.get("content", "")
        if len(content.strip()) < 200:
            log.warning(f"  Defuddle: too little content ({len(content.strip())} chars)")
            return None
        return {"title": data.get("title", ""), "markdown": content}
    except subprocess.TimeoutExpired:
        log.warning("  Defuddle: timed out after 120s")
        return None
    except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
        log.warning(f"  Defuddle error: {e}")
        return None


# ---------------------------------------------------------------------------
# Trafilatura extraction (fallback)
# ---------------------------------------------------------------------------

def extract_with_trafilatura(html, url):
    """Extract content using trafilatura (HTML output) then markdownify.

    Uses trafilatura's ensemble algorithm (own heuristics + readability-lxml
    + jusText fallbacks) for boilerplate removal, then markdownify for
    HTML-to-markdown conversion with code block language detection.

    Returns dict with {title, markdown, code_blocks} or None.
    """
    from trafilatura import extract as traf_extract, extract_metadata
    from bs4 import BeautifulSoup
    from markdownify import markdownify as md

    # Get clean HTML from trafilatura's ensemble extraction
    clean_html = traf_extract(
        html, output_format="html",
        include_formatting=True, include_tables=True,
        include_links=True, url=url,
    )
    if not clean_html or len(clean_html.strip()) < 200:
        log.warning("  Trafilatura: insufficient content")
        return None

    # Extract title via trafilatura's metadata extraction
    # (uses Open Graph, JSON-LD, <title>, <h1> in priority order)
    metadata = extract_metadata(html, default_url=url)
    title = metadata.title if metadata and metadata.title else ""

    # If trafilatura didn't find a title, try the original HTML directly
    if not title:
        soup = BeautifulSoup(html, "lxml")
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)
        if not title:
            t = soup.find("title")
            if t:
                title = t.get_text(strip=True)

    # Extract code blocks from the clean HTML for metadata
    clean_soup = BeautifulSoup(clean_html, "lxml")
    code_blocks = _extract_code_blocks_from_soup(clean_soup)

    # Convert clean HTML to markdown with code language detection
    markdown = md(clean_html, heading_style="ATX", wrap=False,
                  code_language_callback=_code_language_callback,
                  table_infer_header=True).strip()

    return {"title": title, "markdown": markdown, "code_blocks": code_blocks}


# ---------------------------------------------------------------------------
# Markdown parsing utilities
# ---------------------------------------------------------------------------

def extract_code_blocks_from_markdown(markdown):
    """Parse fenced code blocks from markdown text.

    Matches ```language\\n...``` patterns. Used for the Defuddle path where
    we only have markdown (no HTML soup to parse).
    """
    blocks = []
    for match in re.finditer(r'```(\w*)\n(.*?)```', markdown, re.DOTALL):
        lang = match.group(1) or ""
        content = match.group(2)
        if content.strip():
            blocks.append({"language": lang, "content": content})
    return blocks


def extract_headings_from_markdown(markdown):
    """Parse ATX headings (H1-H3) from markdown text."""
    headings = []
    for match in re.finditer(r'^(#{1,3})\s+(.+)$', markdown, re.MULTILINE):
        level = len(match.group(1))
        text = match.group(2).strip()
        # Strip trailing anchor links like {#section-id}
        text = re.sub(r'\s*\{#[^}]+\}\s*$', '', text)
        if text:
            headings.append({"level": level, "text": text})
    return headings


def clean_title(title):
    """Clean a page title by removing site name suffixes.

    Documentation sites often append the site name to the title tag:
    "Artisan Console | Laravel 11.x - The clean stack..."
    "Config - MyLib Docs"

    Splits on common delimiters and returns the shortest meaningful segment,
    which is usually the actual page title.
    """
    if not title:
        return title

    # Split on common title delimiters
    for sep in [" | ", " - ", " :: ", " — ", " · ", " – "]:
        if sep in title:
            parts = [p.strip() for p in title.split(sep) if p.strip()]
            if len(parts) > 1:
                # Return the shortest part that's at least 3 chars
                # (the page title is usually shorter than the site name)
                candidates = [p for p in parts if len(p) >= 3]
                if candidates:
                    return min(candidates, key=len)

    return title.strip()


def clean_markdown(markdown, source_url=""):
    """Post-process extracted markdown.

    Applies minimal cleanup that both extractors may need:
    - Strip leading H1 (build_plugin.py template adds its own)
    - Strip links pointing to the source documentation site
    - Strip internal documentation links (relative paths)
    - Collapse excessive blank lines
    """
    # Strip the leading H1 heading from the markdown content.
    # The section template in build_plugin.py adds its own "# {title}" heading.
    markdown = re.sub(r'^#\s+[^\n]+\n+', '', markdown, count=1)

    # Strip links pointing to the source documentation site.
    # Defuddle outputs absolute URLs like [Name](https://laravel.com/docs/12.x/routing#section)
    # which are useless in the generated skill. Keep just the link text.
    if source_url:
        domain = urlparse(source_url).netloc
        if domain:
            markdown = re.sub(
                rf'\[([^\]]+)\]\(https?://{re.escape(domain)}[^)]*\)',
                r'\1',
                markdown,
            )

    # Strip internal documentation links — relative paths like [Name](/docs/thing)
    markdown = re.sub(r'\[([^\]]+)\]\(<{0,1}/[^)>]+>{0,1}\)', r'\1', markdown)

    # Collapse runs of 4+ blank lines to 3
    markdown = re.sub(r"\n{4,}", "\n\n\n", markdown)

    return markdown.strip()


# ---------------------------------------------------------------------------
# Code block extraction from HTML (for trafilatura fallback path)
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
            return cls[len("brush:"):].strip()
        if cls == "sourceCode":
            for other_cls in classes:
                if other_cls != "sourceCode" and not other_cls.startswith("source"):
                    return other_cls
            continue
        if cls.startswith("sourceCode "):
            return cls[len("sourceCode "):].strip()

    for attr in ("data-lang", "data-language", "lang"):
        val = el.get(attr, "")
        if val:
            return val

    return ""


def _code_language_callback(pre_element):
    """Callback for markdownify to detect code block languages.

    Called by markdownify for each <pre> element during HTML→markdown conversion.
    Checks child <code>, then <pre>, then parent <div> for language annotations.
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
    (signatures, classify_page). Used in the trafilatura fallback path where
    we have clean HTML to parse.
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


# ---------------------------------------------------------------------------
# Pygments language guessing
# ---------------------------------------------------------------------------

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
SIGNATURE_PATTERNS = [
    # Go: func Name(args) returnType
    re.compile(r"func\s+(?:\([^)]*\)\s+)?\w+\s*\([^)]*\)(?:\s*(?:\([^)]*\)|[^{]+?))?(?:\s*\{)?"),
    # Python: def name(args) -> ReturnType:
    re.compile(r"(?:async\s+)?def\s+\w+\s*\([^)]*\)(?:\s*->\s*[^:]+)?:"),
    # TypeScript/JavaScript: function name(args): ReturnType
    re.compile(r"(?:export\s+)?(?:async\s+)?function\s+\w+\s*(?:<[^>]*>)?\s*\([^)]*\)(?:\s*:\s*[^{]+)?"),
    # Rust: fn name(args) -> ReturnType
    re.compile(r"(?:pub\s+)?(?:async\s+)?fn\s+\w+\s*(?:<[^>]*>)?\s*\([^)]*\)(?:\s*->\s*[^{]+)?"),
    # Java/Kotlin: public static ReturnType name(args)
    re.compile(r"(?:public|private|protected)?\s*(?:static\s+)?(?:async\s+)?\w+(?:<[^>]*>)?\s+\w+\s*\([^)]*\)"),
]


def extract_signatures(code_blocks):
    """Extract function/method signatures from code blocks."""
    signatures = []
    for block in code_blocks:
        for pattern in SIGNATURE_PATTERNS:
            for match in pattern.finditer(block["content"]):
                sig = match.group(0).strip().rstrip("{").strip()
                if len(sig) < 300 and sig not in signatures:
                    signatures.append(sig)
    return signatures


# ---------------------------------------------------------------------------
# Page classification
# ---------------------------------------------------------------------------

def classify_page(title, headings, code_blocks, markdown_text, url=""):
    """Classify a documentation page into one of five categories.

    Categories: warning, example, api-reference, tutorial, conceptual.
    """
    title_lower = title.lower()
    text_lower = markdown_text.lower()
    url_path = urlparse(url).path.lower() if url else ""

    text_len = len(markdown_text)
    code_len = sum(len(b["content"]) for b in code_blocks)
    code_ratio = code_len / max(text_len, 1)

    # --- Warning detection ---
    warning_title_indicators = ["deprecat", "breaking change", "upgrade guide",
                                "migration guide", "end of life", "eol",
                                "sunset", "removed in"]
    warning_body_indicators = ["deprecated", "breaking change", "end of life", "eol",
                               "sunset", "removed in", "migration guide", "upgrade guide",
                               "no longer supported", "will be removed"]
    if any(ind in title_lower for ind in warning_title_indicators):
        return "warning"
    if sum(1 for ind in warning_body_indicators if ind in text_lower) >= 3:
        return "warning"

    # --- URL path signals ---
    url_api_bonus = 2 if any(seg in url_path for seg in ["/api/", "/reference/", "/ref/"]) else 0
    url_tutorial_bonus = 2 if any(seg in url_path for seg in ["/tutorial/", "/guide/", "/guides/", "/getting-started/"]) else 0
    url_cli_bonus = 2 if "/cli/" in url_path else 0

    # --- Heading structure signal ---
    h2h3_headings = [h["text"] for h in headings if h.get("level") in (2, 3)]
    sig_like_count = 0
    for ht in h2h3_headings:
        if "(" in ht and ")" in ht:
            sig_like_count += 1
        elif re.match(r'^(?:string|int|bool|void|array|object|float|static|public|private)\s+\w+', ht, re.IGNORECASE):
            sig_like_count += 1
    heading_api_bonus = 2 if (h2h3_headings and sig_like_count > len(h2h3_headings) / 2) else 0

    # --- Tutorial detection ---
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
    if code_ratio > 0.6 and tutorial_score < 3:
        return "example"

    # --- Conceptual detection ---
    concept_indicators = ["overview", "introduction", "concept", "architecture", "design",
                         "explanation", "understanding", "background"]
    if sum(1 for ind in concept_indicators if ind in text_lower) >= 1:
        return "conceptual"

    if code_ratio > 0.4:
        return "example"
    return "conceptual"


# ---------------------------------------------------------------------------
# Warning extraction
# ---------------------------------------------------------------------------

def extract_warnings(markdown_text):
    """Extract deprecation notices and warning callouts from markdown text.

    Only matches structured admonition patterns to avoid false positives.
    """
    warnings = []
    warning_patterns = [
        re.compile(r"^>\s*\*\*(?:Warning|Deprecated|Caution|Danger|Important)\*\*\s*[:!]\s*(.+)", re.IGNORECASE),
        re.compile(r"^>\s*\[!(?:WARNING|CAUTION|DANGER|IMPORTANT)\]\s*(.*)$", re.IGNORECASE),
        re.compile(r"^\*\*(?:Deprecated|Warning|Caution|Breaking Change)\*\*\s*[:!]\s*(.+)", re.IGNORECASE),
        re.compile(r"^(?:Deprecated|Removed)\s+(?:since|in|as of)\s+v?\d+", re.IGNORECASE),
    ]
    for line in markdown_text.split("\n"):
        stripped = line.strip()
        for pattern in warning_patterns:
            if pattern.search(stripped):
                warning_text = stripped.lstrip(">").strip().lstrip("*_").rstrip("*_").strip()
                if warning_text and len(warning_text) > 10 and warning_text not in warnings:
                    warnings.append(warning_text)
                break
    return warnings


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

_used_filenames = set()


def url_to_filename(url):
    """Convert a URL to a filesystem-safe filename for the extracted JSON."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        path = "index"
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


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def extract_page(html, html_path, url, guess_languages=False):
    """Extract content from a saved HTML page.

    Pipeline:
    1. Try Defuddle (best code block handling, multi-pass recovery)
    2. Fall back to trafilatura (best benchmarked accuracy, internal ensemble)
    3. Extract metadata from the resulting markdown
    4. Classify the page
    """
    # Try Defuddle first (primary extractor)
    result = extract_with_defuddle(html_path, url)
    extractor = "defuddle"

    # Fall back to trafilatura if Defuddle fails
    if result is None:
        result = extract_with_trafilatura(html, url)
        extractor = "trafilatura"

    if result is None:
        log.error(f"  Both extractors failed for {url}")
        return None

    title = clean_title(result["title"])
    markdown = result["markdown"]

    # Post-process markdown
    markdown = clean_markdown(markdown, source_url=url)
    if guess_languages:
        markdown = _guess_code_block_languages(markdown)

    # Extract code blocks: use HTML-derived blocks from trafilatura path
    # (better language detection from class attributes), or parse from
    # markdown for the Defuddle path.
    code_blocks = result.get("code_blocks") or extract_code_blocks_from_markdown(markdown)

    # Extract headings from markdown
    headings = extract_headings_from_markdown(markdown)

    # Extract function signatures and deprecation warnings
    signatures = extract_signatures(code_blocks)
    warnings = extract_warnings(markdown)

    # Classify page category
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
        "extractor": extractor,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    _used_filenames.clear()

    with open(args.sitemap, "r", encoding="utf-8") as f:
        sitemap = json.load(f)

    pages = sitemap.get("pages", [])
    if not pages:
        log.error("No pages found in sitemap")
        sys.exit(1)

    log.info(f"Extracting content from {len(pages)} pages")

    os.makedirs(args.output, exist_ok=True)

    html_dir = sitemap.get("html_dir", "")
    if not html_dir or not os.path.isdir(html_dir):
        log.error(f"HTML directory not found: {html_dir}")
        log.error("Re-run crawl.py to generate saved HTML files")
        sys.exit(1)

    category_counts = {}
    extractor_counts = {"defuddle": 0, "trafilatura": 0, "failed": 0}
    skipped = 0

    for i, entry in enumerate(pages):
        url = entry["url"]

        filename = url_to_filename(url)
        output_path = os.path.join(args.output, filename)
        if not args.force and os.path.exists(output_path):
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

        html_file = entry.get("html_file", "")
        html_path = os.path.join(html_dir, html_file) if html_file else ""
        if not html_file or not os.path.exists(html_path):
            log.warning(f"  HTML file not found: {html_file}, skipping")
            continue

        try:
            with open(html_path, "r", encoding="utf-8") as f:
                html = f.read()

            data = extract_page(html, html_path, url, guess_languages=args.guess_languages)

            if data is None:
                extractor_counts["failed"] += 1
                continue

            cat = data["category"]
            category_counts[cat] = category_counts.get(cat, 0) + 1
            extractor_counts[data["extractor"]] += 1

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            ext = data["extractor"]
            log.info(f"  -> {cat} | {len(data['markdown'])} chars | "
                     f"{len(data['code_blocks'])} code blocks | "
                     f"{len(data['signatures'])} sigs | [{ext}]")

        except Exception as e:
            log.error(f"Error extracting {url}: {e}")
            extractor_counts["failed"] += 1

    # Summary
    log.info("=" * 60)
    log.info("Extraction complete")
    log.info(f"Output directory: {args.output}")
    log.info(f"Total pages extracted: {sum(category_counts.values())}")
    if skipped:
        log.info(f"Skipped (already extracted): {skipped}")
    log.info("Extractor usage:")
    for ext, count in sorted(extractor_counts.items()):
        if count > 0:
            log.info(f"  {ext}: {count}")
    log.info("Category breakdown:")
    for cat, count in sorted(category_counts.items()):
        log.info(f"  {cat}: {count}")


if __name__ == "__main__":
    main()

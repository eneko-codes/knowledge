#!/usr/bin/env python3
"""Reconnaissance probe for documentation sites — runs BEFORE crawl.py.

Analyzes a documentation site's rendering strategy, page discovery mechanisms,
and URL patterns to produce a structured JSON report.  This report guides crawl
parameter selection so crawl.py can be invoked with optimal flags
(--same-path-prefix, --max-depth, --exclude-pattern, etc.) without manual
trial-and-error.

Why three separate probes?
  1. Raw HTML fetch (no JS) — tells us what search engines and simple scrapers
     see.  Comparing this to the rendered version reveals how much content
     depends on JavaScript.
  2. Playwright rendered fetch — gives us the full DOM after JS execution,
     including SPA-rendered content and all navigation links.
  3. Page list probes (llms.txt, sitemap.xml, robots.txt) — discovers
     pre-built page inventories that can replace BFS crawling entirely,
     saving time and reducing load on the target server.

Usage:
    python3 recon.py <root-url> [--output /tmp/recon.json] [--timeout 30]
"""

import argparse
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen


# ---------------------------------------------------------------------------
# Logging — same format as crawl.py for visual consistency in pipelines.
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("recon")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    """Define and parse CLI arguments.

    --timeout caps the total wall-clock time across all probes so that recon
    never blocks a CI pipeline longer than expected.  Individual probes bail
    out early when the budget is exhausted.
    """
    p = argparse.ArgumentParser(
        description="Analyze a documentation site and produce a recon report for crawl.py",
    )
    p.add_argument("root_url", help="Root URL of the documentation site to analyze")
    p.add_argument("--output", "-o", default="/tmp/recon.json", help="Output JSON path (default: /tmp/recon.json)")
    p.add_argument("--timeout", type=int, default=30, help="Total timeout budget in seconds (default: 30)")
    return p.parse_args()


# ---------------------------------------------------------------------------
# HTML text extraction — strip tags, scripts, and styles to measure visible
# text length from a raw HTTP response.  This is intentionally minimal: we
# only need a character count, not a clean parse.
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """HTMLParser subclass that collects visible text, ignoring scripts and styles.

    We need a rough character count of the "useful" text in a raw HTML response
    to compare against the Playwright-rendered version.  The ratio tells us
    whether the site is static (ratio ~1.0) or client-rendered (ratio ~0.0).
    """

    _SKIP_TAGS = frozenset(("script", "style", "noscript"))

    def __init__(self):
        super().__init__()
        self._pieces = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._pieces.append(data)

    def get_text(self):
        return " ".join(self._pieces)


def _extract_visible_text(html):
    """Return the visible text from an HTML string with tags/scripts/styles removed."""
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def _detect_requires_js(html):
    """Check if a <noscript> tag mentions JavaScript, suggesting JS is required.

    Sites that render everything client-side often include a <noscript> fallback
    saying "enable JavaScript to view this page".
    """
    match = re.search(r"<noscript[^>]*>(.*?)</noscript>", html, re.IGNORECASE | re.DOTALL)
    if match and "javascript" in match.group(1).lower():
        return True
    return False


def _count_script_tags(html):
    """Count <script elements in the HTML source.

    A high script count (>10) combined with little visible text suggests
    heavy client-side rendering.
    """
    return len(re.findall(r"<script[\s>]", html, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Timeout budget helper — probes check this before starting so we don't
# exceed the overall --timeout wall-clock limit.
# ---------------------------------------------------------------------------

class _Budget:
    """Tracks remaining wall-clock time for the overall recon operation.

    Each probe calls .check() before starting.  If the budget is exhausted
    the probe is skipped and logged — we report partial results rather than
    timing out hard.
    """

    def __init__(self, total_seconds):
        self._start = time.monotonic()
        self._total = total_seconds

    def remaining(self):
        return max(0, self._total - (time.monotonic() - self._start))

    def exhausted(self):
        return self.remaining() <= 0

    def check(self, probe_name):
        """Return True if there is budget remaining, False otherwise."""
        if self.exhausted():
            log.warning(f"Timeout budget exhausted — skipping {probe_name}")
            return False
        return True


# ---------------------------------------------------------------------------
# Probe 1: Raw HTML fetch (no JavaScript)
# ---------------------------------------------------------------------------

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def probe_raw_html(url, budget):
    """Fetch the root URL with a plain HTTP GET — no JavaScript execution.

    This gives us the server-sent HTML that search engine crawlers (and
    simple scrapers) would see.  By comparing the visible text length here
    to the Playwright-rendered version, we can classify the site's rendering
    strategy.
    """
    if not budget.check("raw_html"):
        return None

    log.info("Probe 1: Raw HTML fetch (no JS)")

    req = Request(url, headers={"User-Agent": _USER_AGENT})
    timeout = min(10, budget.remaining())

    try:
        with urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        log.error(f"  Raw HTML fetch failed: {e}")
        return None

    visible_text = _extract_visible_text(html)
    raw_text_length = len(visible_text.strip())

    requires_js = _detect_requires_js(html)
    script_count = _count_script_tags(html)

    log.info(f"  Raw text length: {raw_text_length} chars, scripts: {script_count}")
    if requires_js:
        log.info("  Site indicates JavaScript is required")

    return {
        "html": html,
        "raw_text_length": raw_text_length,
        "requires_js": requires_js,
        "script_count": script_count,
    }


# ---------------------------------------------------------------------------
# Probe 2: Playwright rendered fetch
# ---------------------------------------------------------------------------

def probe_rendered(url, budget):
    """Launch a headless Chromium browser, render the page, and extract links.

    Same Playwright + stealth setup as crawl.py so we see exactly what the
    crawler will see.  The rendered text length compared to the raw fetch
    tells us the content_ratio — the core signal for rendering classification.
    """
    if not budget.check("rendered"):
        return None

    log.info("Probe 2: Playwright rendered fetch")

    # Import here so the script can still parse/run probe 1 and 3 even if
    # Playwright is not installed (graceful degradation).
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    rendered_text_length = 0
    links = []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=_USER_AGENT,
            )
            page = context.new_page()
            Stealth().apply_stealth_sync(page)

            # Navigate — same two-phase wait as crawl.py: domcontentloaded first,
            # then try networkidle with a short timeout.
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            # Extra wait for SPA rendering — frameworks like React/Vue may not
            # have finished hydration by networkidle.
            page.wait_for_timeout(2000)

            rendered_text_length = page.evaluate("() => document.body.innerText.length") or 0

            # Extract all <a href> links — same JS as crawl.py's extract_page_data.
            links = page.evaluate("""() => {
                const links = [];
                document.querySelectorAll('a[href]').forEach(a => {
                    try {
                        links.push(a.href);
                    } catch(e) {}
                });
                return links;
            }""")

            browser.close()

        log.info(f"  Rendered text length: {rendered_text_length} chars, links found: {len(links)}")

    except Exception as e:
        log.error(f"  Playwright render failed: {e}")
        return None

    return {
        "rendered_text_length": rendered_text_length,
        "links": links,
    }


# ---------------------------------------------------------------------------
# URL pattern analysis — examine the link corpus from Probe 2 to identify
# version tags, locale prefixes, and query param patterns that would bloat
# a naive BFS crawl.
# ---------------------------------------------------------------------------

_LOCALE_CODES = frozenset((
    "en", "es", "fr", "de", "ja", "ko", "zh", "zh-hans", "pt", "ru", "it",
))

_URL_PATTERNS = [
    # (label, compiled regex)
    ("version_tag", re.compile(r"@v?\d")),
    ("tab_query",   re.compile(r"\?tab=")),
    ("ref_query",   re.compile(r"\?ref=")),
]


def _detect_version_segments(path):
    """Check if any path segment looks like a version number (e.g., v2.1, 12.x)."""
    for segment in path.strip("/").split("/"):
        if re.match(r"v?\d+\.\d+", segment) or re.match(r"v?\d+\.x", segment):
            return segment
    return None


def _detect_locale_prefix(path):
    """Check if the first path segment is a common locale code."""
    segments = path.strip("/").split("/")
    if segments and segments[0].lower() in _LOCALE_CODES:
        return segments[0].lower()
    return None


def analyze_urls(links, root_domain):
    """Analyze same-domain links for recurring patterns that inform crawl exclusions.

    Patterns appearing in >30% of links are likely structural (version selectors,
    locale switchers) rather than content — suggesting --exclude-pattern flags.
    Patterns in >90% of links get elevated to warnings because they would cause
    the crawler to waste most of its budget on duplicates.
    """
    parsed_root = urlparse(f"https://{root_domain}")

    # Filter to same-domain links only
    same_domain_links = []
    for link in links:
        try:
            parsed = urlparse(link)
            if parsed.hostname == root_domain and parsed.scheme in ("http", "https"):
                same_domain_links.append(link)
        except Exception:
            continue

    total = len(same_domain_links)
    if total == 0:
        return {
            "total_links": len(links),
            "doc_links": 0,
            "patterns": [],
        }, [], []

    # Count matches for each predefined pattern
    pattern_counts = {}
    pattern_examples = {}
    for label, regex in _URL_PATTERNS:
        count = 0
        example = None
        for link in same_domain_links:
            m = regex.search(link)
            if m:
                count += 1
                if example is None:
                    example = m.group(0)
        if count > 0:
            pattern_counts[label] = count
            pattern_examples[label] = example

    # Detect version path segments across all links
    version_count = 0
    version_example = None
    for link in same_domain_links:
        parsed = urlparse(link)
        seg = _detect_version_segments(parsed.path)
        if seg:
            version_count += 1
            if version_example is None:
                version_example = seg
    if version_count > 0:
        pattern_counts["version_path"] = version_count
        pattern_examples["version_path"] = version_example

    # Detect locale prefixes across all links
    locale_count = 0
    locale_example = None
    for link in same_domain_links:
        parsed = urlparse(link)
        loc = _detect_locale_prefix(parsed.path)
        if loc:
            locale_count += 1
            if locale_example is None:
                locale_example = loc
    if locale_count > 0:
        pattern_counts["locale_prefix"] = locale_count
        pattern_examples["locale_prefix"] = locale_example

    # Build structured pattern list, suggested exclusions, and warnings
    patterns = []
    suggested_excludes = []
    warnings = []

    # Map labels to regex strings suitable for --exclude-pattern
    _EXCLUDE_REGEXES = {
        "version_tag": r"@v?\d",
        "tab_query": r"\?tab=",
        "ref_query": r"\?ref=",
        "version_path": r"v?\d+\.\d+",
        "locale_prefix": None,  # handled specially below
    }

    for label, count in pattern_counts.items():
        pct = round(count / total * 100, 1)
        regex_str = _EXCLUDE_REGEXES.get(label)

        # For locale_prefix, build a regex from the detected code
        if label == "locale_prefix" and locale_example:
            regex_str = f"/{locale_example}/"

        patterns.append({
            "pattern": regex_str or label,
            "count": count,
            "pct": pct,
            "example": pattern_examples.get(label, ""),
        })

        if pct > 30 and regex_str:
            suggested_excludes.append(regex_str)

        if pct > 90:
            warnings.append(
                f"{pct}% of links match {label} pattern {regex_str or label} — exclude recommended"
            )

    url_analysis = {
        "total_links": len(links),
        "doc_links": total,
        "patterns": patterns,
    }
    return url_analysis, suggested_excludes, warnings


# ---------------------------------------------------------------------------
# Probe 3: Page list probes (llms.txt, sitemap.xml, robots.txt)
# ---------------------------------------------------------------------------

def _fetch_text(url, timeout=5):
    """Fetch a URL and return the response body as text, or None on failure.

    Used for lightweight resource probes (llms.txt, sitemap.xml, robots.txt).
    Returns None for non-200 responses or if the Content-Type is HTML (which
    usually means a custom 404 page).
    """
    try:
        req = Request(url, headers={"User-Agent": _USER_AGENT})
        with urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read().decode("utf-8", errors="replace")
            return body, content_type
    except Exception:
        return None


def _parse_llms_txt_links(text):
    """Extract URLs from an llms.txt file.

    llms.txt files contain a mix of markdown links [text](url) and plain
    URLs on their own lines.  We extract both forms.
    """
    links = set()

    # Markdown-style links: [text](url)
    for match in re.finditer(r"\[.*?\]\((https?://[^\s)]+)\)", text):
        links.add(match.group(1))

    # Plain URLs on their own or inline
    for match in re.finditer(r"(?<!\()(https?://[^\s)]+)", text):
        links.add(match.group(0))

    return list(links)


_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def _parse_sitemap(url, timeout=5, max_sub=3):
    """Parse a sitemap.xml, following sitemap index files up to max_sub levels.

    Returns (total_url_count, doc_url_count) where doc_url_count excludes
    obvious non-doc resources (images, CSS, JS, blog posts).
    """
    result = _fetch_text(url, timeout=timeout)
    if result is None:
        return None

    body, content_type = result

    # Reject HTML responses — some servers return a custom 404 page as HTML
    if "html" in content_type.lower():
        return None

    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None

    # Check if this is a sitemap index (contains <sitemap> elements)
    sub_sitemaps = root.findall(f"{_SITEMAP_NS}sitemap")
    if not sub_sitemaps:
        # Also check without namespace for non-standard sitemaps
        sub_sitemaps = root.findall("sitemap")

    if sub_sitemaps:
        total = 0
        doc_total = 0
        for sub in sub_sitemaps[:max_sub]:
            loc_el = sub.find(f"{_SITEMAP_NS}loc")
            if loc_el is None:
                loc_el = sub.find("loc")
            if loc_el is not None and loc_el.text:
                sub_result = _parse_sitemap(loc_el.text.strip(), timeout=timeout, max_sub=0)
                if sub_result:
                    total += sub_result[0]
                    doc_total += sub_result[1]
        return (total, doc_total) if total > 0 else None

    # Regular sitemap — count <url> elements
    urls_els = root.findall(f"{_SITEMAP_NS}url")
    if not urls_els:
        urls_els = root.findall("url")

    total = 0
    doc_count = 0
    skip_extensions = (
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
        ".pdf", ".zip", ".css", ".js", ".json", ".xml",
    )
    skip_paths = ("/blog", "/changelog", "/releases")

    for url_el in urls_els:
        loc_el = url_el.find(f"{_SITEMAP_NS}loc")
        if loc_el is None:
            loc_el = url_el.find("loc")
        if loc_el is None or not loc_el.text:
            continue
        total += 1
        loc = loc_el.text.strip().lower()
        parsed = urlparse(loc)
        path = parsed.path

        if any(path.endswith(ext) for ext in skip_extensions):
            continue
        if any(path.startswith(sp) for sp in skip_paths):
            continue
        doc_count += 1

    return (total, doc_count)


def probe_page_lists(origin, budget):
    """Check for pre-built page inventories: llms.txt, sitemap.xml, robots.txt.

    These resources can short-circuit BFS crawling entirely — if a site
    provides an llms.txt with all doc URLs, we can skip the expensive
    Playwright-based crawl and just fetch those URLs directly.
    """
    if not budget.check("page_lists"):
        return None

    log.info("Probe 3: Page list probes")

    discovery = {
        "method": "bfs_crawl",
        "llms_txt": None,
        "llms_full_txt": False,
        "sitemap_xml": None,
        "robots_txt_sitemap": None,
    }

    # --- llms.txt ---
    try:
        llms_url = f"{origin}/llms.txt"
        result = _fetch_text(llms_url, timeout=5)
        if result is not None:
            body, content_type = result
            # Reject HTML responses — likely a custom 404
            if "html" not in content_type.lower():
                links = _parse_llms_txt_links(body)
                # Save parsed URLs to a file for --from-urls consumption
                urls_file = None
                if links:
                    domain_slug = re.sub(r"[^a-zA-Z0-9]", "-", urlparse(origin).hostname)
                    urls_file = f"/tmp/{domain_slug}-llms-urls.txt"
                    with open(urls_file, "w", encoding="utf-8") as uf:
                        uf.write("\n".join(links) + "\n")
                    log.info(f"  llms.txt URLs saved to {urls_file}")
                discovery["llms_txt"] = {"exists": True, "url_count": len(links), "urls_file": urls_file}
                log.info(f"  llms.txt: {len(links)} URLs found")
            else:
                log.info("  llms.txt: returned HTML (likely 404)")
        else:
            log.info("  llms.txt: not found")
    except Exception as e:
        log.warning(f"  llms.txt probe failed: {e}")

    # --- llms-full.txt ---
    try:
        llms_full_url = f"{origin}/llms-full.txt"
        result = _fetch_text(llms_full_url, timeout=5)
        if result is not None:
            _, content_type = result
            if "html" not in content_type.lower():
                discovery["llms_full_txt"] = True
                log.info("  llms-full.txt: exists")
            else:
                log.info("  llms-full.txt: returned HTML (likely 404)")
        else:
            log.info("  llms-full.txt: not found")
    except Exception as e:
        log.warning(f"  llms-full.txt probe failed: {e}")

    # --- sitemap.xml ---
    try:
        sitemap_url = f"{origin}/sitemap.xml"
        sitemap_result = _parse_sitemap(sitemap_url, timeout=5)
        if sitemap_result:
            total, doc_count = sitemap_result
            discovery["sitemap_xml"] = {
                "exists": True,
                "url_count": total,
                "doc_url_count": doc_count,
            }
            log.info(f"  sitemap.xml: {total} total URLs, {doc_count} doc URLs")
        else:
            log.info("  sitemap.xml: not found or unparseable")
    except Exception as e:
        log.warning(f"  sitemap.xml probe failed: {e}")

    # --- robots.txt ---
    try:
        robots_url = f"{origin}/robots.txt"
        result = _fetch_text(robots_url, timeout=5)
        if result is not None:
            body, _ = result
            for line in body.splitlines():
                if line.strip().lower().startswith("sitemap:"):
                    sitemap_directive = line.split(":", 1)[1].strip()
                    discovery["robots_txt_sitemap"] = sitemap_directive
                    log.info(f"  robots.txt Sitemap directive: {sitemap_directive}")
                    break
            if discovery["robots_txt_sitemap"] is None:
                log.info("  robots.txt: no Sitemap directive")
        else:
            log.info("  robots.txt: not found")
    except Exception as e:
        log.warning(f"  robots.txt probe failed: {e}")

    return discovery


# ---------------------------------------------------------------------------
# Classification — combine probe results into rendering strategy, discovery
# method, and suggested crawl flags.
# ---------------------------------------------------------------------------

def classify_rendering(content_ratio, script_count, requires_js):
    """Classify the site's rendering strategy from probe signals.

    Three categories:
    - static: Server returns nearly all content as HTML.  Playwright is
      optional but still useful for link extraction from hydrated nav menus.
    - ssr_hydration: Server renders a meaningful HTML shell, but JS enhances
      it significantly.  Playwright is recommended.
    - client_spa: Server returns a near-empty shell; all content is rendered
      by JavaScript.  Playwright is mandatory.
    """
    if content_ratio >= 0.7 and script_count <= 5:
        return "static"
    if content_ratio >= 0.3:
        return "ssr_hydration"
    return "client_spa"


def choose_discovery_method(discovery):
    """Pick the best page discovery method based on available inventories.

    llms.txt is preferred when it has enough entries because it was curated
    by the site maintainer specifically for LLM consumption.  sitemap.xml is
    the next best option.  BFS crawl is the fallback.
    """
    if discovery.get("llms_txt") and discovery["llms_txt"].get("url_count", 0) > 5:
        return "llms_txt"
    if discovery.get("sitemap_xml") and discovery["sitemap_xml"].get("doc_url_count", 0) > 5:
        return "sitemap_xml"
    return "bfs_crawl"


def suggest_flags(root_url, estimated_pages):
    """Generate suggested crawl.py flags based on site characteristics.

    These are conservative recommendations — the operator should review them
    before passing to crawl.py.
    """
    flags = []
    parsed = urlparse(root_url)
    path = parsed.path.rstrip("/")

    # Non-trivial path prefix suggests versioned or scoped docs
    if path and path != "/":
        flags.append("--same-path-prefix")

    if estimated_pages > 500:
        limit = int(estimated_pages * 1.5)
        flags.append(f"--max-pages {limit}")

    if estimated_pages < 50:
        flags.append("--max-depth 5")
    elif estimated_pages > 200:
        flags.append("--max-depth 3")

    return flags


def estimate_pages(discovery, url_analysis):
    """Estimate total documentation page count from available signals.

    Uses the most authoritative source available: llms.txt > sitemap doc
    count > link count from rendered page.
    """
    if discovery.get("llms_txt") and discovery["llms_txt"].get("url_count", 0) > 0:
        return discovery["llms_txt"]["url_count"]
    if discovery.get("sitemap_xml") and discovery["sitemap_xml"].get("doc_url_count", 0) > 0:
        return discovery["sitemap_xml"]["doc_url_count"]
    if url_analysis and url_analysis.get("doc_links", 0) > 0:
        return url_analysis["doc_links"]
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def recon(args):
    """Run all probes and assemble the final recon report.

    Probes run sequentially (raw_html → rendered → page_lists) with a shared
    timeout budget.  If the budget runs out mid-way, completed probe results
    are still included — partial data is better than no data.
    """
    root_url = args.root_url
    parsed = urlparse(root_url)
    domain = parsed.hostname
    origin = f"{parsed.scheme}://{domain}"

    budget = _Budget(args.timeout)
    probes_completed = []

    log.info(f"Recon target: {root_url}")
    log.info(f"Domain: {domain}, timeout: {args.timeout}s")

    # --- Probe 1: Raw HTML ---
    raw = probe_raw_html(root_url, budget)
    raw_text_length = 0
    requires_js = False
    script_count = 0

    if raw is not None:
        probes_completed.append("raw_html")
        raw_text_length = raw["raw_text_length"]
        requires_js = raw["requires_js"]
        script_count = raw["script_count"]

    # --- Probe 2: Rendered ---
    rendered = probe_rendered(root_url, budget)
    rendered_text_length = 0
    links = []

    if rendered is not None:
        probes_completed.append("rendered")
        rendered_text_length = rendered["rendered_text_length"]
        links = rendered["links"]

    # Content ratio: raw_text / rendered_text.  Measures how much content the
    # server delivers without JavaScript.
    #   ≈ 1.0  → static site (raw ≈ rendered)
    #   > 1.0  → SSR with hidden/collapsed content in raw HTML (e.g., pkg.go.dev
    #            has all packages in the HTML but Playwright only shows visible ones)
    #   < 0.3  → SPA — raw HTML has no content, JS renders everything
    #   ≈ 0.0  → pure client-side (DocC, empty shell)
    # Values > 1 are normal and still classify correctly (≥ 0.7 threshold).
    if rendered_text_length > 0:
        content_ratio = round(raw_text_length / rendered_text_length, 2)
    else:
        content_ratio = 0.0

    # --- URL analysis ---
    url_analysis, suggested_excludes, warnings = analyze_urls(links, domain)

    # --- Probe 3: Page lists ---
    discovery = probe_page_lists(origin, budget)
    if discovery is not None:
        probes_completed.append("page_lists")
        discovery["method"] = choose_discovery_method(discovery)
    else:
        discovery = {
            "method": "bfs_crawl",
            "llms_txt": None,
            "llms_full_txt": False,
            "sitemap_xml": None,
            "robots_txt_sitemap": None,
        }

    # --- Classification ---
    rendering = classify_rendering(content_ratio, script_count, requires_js)
    estimated = estimate_pages(discovery, url_analysis)
    flags = suggest_flags(root_url, estimated)

    log.info(f"Rendering: {rendering}, content ratio: {content_ratio}")
    log.info(f"Discovery method: {discovery['method']}, estimated pages: {estimated}")

    return {
        "url": root_url,
        "domain": domain,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "probes_completed": probes_completed,
        "rendering": rendering,
        "content_ratio": content_ratio,
        "requires_js": requires_js,
        "script_count": script_count,
        "raw_text_length": raw_text_length,
        "rendered_text_length": rendered_text_length,
        "discovery": discovery,
        "url_analysis": url_analysis,
        "suggested_exclude_patterns": suggested_excludes,
        "suggested_flags": flags,
        "warnings": warnings,
        "estimated_page_count": estimated,
    }


def main():
    args = parse_args()
    report = recon(args)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    log.info(f"Report written to {args.output}")
    log.info(f"Probes completed: {report['probes_completed']}")
    if report["warnings"]:
        for w in report["warnings"]:
            log.warning(f"  {w}")


if __name__ == "__main__":
    main()

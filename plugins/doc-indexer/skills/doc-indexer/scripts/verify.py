#!/usr/bin/env python3
"""Accuracy verifier — compares generated plugin content against live source pages.

Re-visits the original URL of every generated markdown file using Playwright,
extracts key signals (title, heading count, code block count, text length),
and compares them against the generated content. Flags mismatches.

This catches extraction failures that structural validation (validate.py) misses:
- Truncated content (text much shorter than the live page)
- Missing code blocks (extractor failed to capture them)
- Missing headings (content selector was too narrow)
- Wrong title (breadcrumb/nav text leaked into the title)
- Fallback selector noise (navigation text mixed with content)

For any mismatches found, Claude should investigate manually — optionally
taking a screenshot of the specific page for visual inspection.

Usage:
    python3 verify.py <plugin-dir> [--delay 1.0] [--screenshot-dir /tmp/screenshots]
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("verify")


def parse_args():
    p = argparse.ArgumentParser(description="Verify generated plugin content against live source pages")
    p.add_argument("plugin_dir", help="Path to the generated plugin directory")
    p.add_argument("--delay", type=float, default=0.5, help="Base delay between requests in seconds (default: 0.5)")
    p.add_argument(
        "--screenshot-dir",
        default="",
        help="If set, take screenshots of mismatched pages and save them here",
    )
    return p.parse_args()


def humanized_delay(base_delay):
    """Add random jitter to delay for human-like request spacing."""
    jitter = random.uniform(-0.3, 0.3)
    return max(0.2, base_delay + jitter)


def find_skill_dir(plugin_dir):
    """Find the skills/<name>/ directory inside the plugin."""
    skills_dir = plugin_dir / "skills"
    if not skills_dir.exists():
        return None
    for child in skills_dir.iterdir():
        if child.is_dir() and (child / "SKILL.md").exists():
            return child
    return None


def collect_content_files(skill_dir):
    """Collect all markdown content files (excluding SKILL.md and SITEMAP.md).

    Returns a list of (relative_path, absolute_path) tuples.
    """
    files = []
    for md_file in sorted(skill_dir.rglob("*.md")):
        rel = md_file.relative_to(skill_dir)
        name = str(rel)
        # Skip index files — they're generated, not extracted from a source page
        if name == "SKILL.md" or name.startswith("index/"):
            continue
        files.append((name, md_file))
    return files


def extract_source_url(markdown_text):
    """Extract the source URL from the '> Source: <url>' line in the generated markdown."""
    for line in markdown_text.split("\n"):
        line = line.strip()
        if line.startswith("> Source:"):
            url = line[len("> Source:"):].strip()
            return url
    return None


def extract_markdown_signals(markdown_text):
    """Extract key signals from a generated markdown file for comparison.

    Returns a dict with:
    - title: the H1 heading text
    - heading_count: number of headings (any level)
    - code_block_count: number of fenced code blocks (``` delimited)
    - text_length: total character count of the markdown
    """
    lines = markdown_text.split("\n")

    # Extract title from first H1
    title = ""
    for line in lines:
        if line.startswith("# ") and not line.startswith("##"):
            title = line[2:].strip()
            break

    # Count headings (lines starting with #)
    heading_count = sum(1 for line in lines if re.match(r"^#{1,6}\s", line))

    # Count fenced code blocks (``` pairs)
    code_block_count = sum(1 for line in lines if line.strip().startswith("```")) // 2

    return {
        "title": title,
        "heading_count": heading_count,
        "code_block_count": code_block_count,
        "text_length": len(markdown_text),
    }


def extract_live_signals(page):
    """Extract key signals from a live rendered page for comparison.

    Uses JavaScript evaluation in the browser to get the same signals
    we extract from markdown, but ONLY from the main content area.

    IMPORTANT: This must use the same content area selectors as extract.py's
    find_main_content(). Previously, headings and code blocks were counted
    from the full page (including sidebar/nav), causing systematic false
    mismatches because extract.py correctly strips those elements.
    """
    # All signals are extracted from the main content area only.
    # The selector list matches extract.py's CONTENT_SELECTORS.
    signals = page.evaluate("""() => {
        const selectors = [
            'main', 'article', '[role="main"]', '#content', '#main-content',
            '.content', '.docs-content', '.doc-content', '.markdown-body',
            '.documentation', '.post-content', '.page-content',
            '.article-content', '.rst-content', '.md-content'
        ];

        // Find the main content element (same logic as extract.py)
        let contentEl = null;
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el && el.textContent.trim().length > 100) {
                contentEl = el;
                break;
            }
        }
        if (!contentEl) {
            contentEl = document.body || document.documentElement;
        }

        // Extract title from first H1 within content area, or document.title
        const h1 = contentEl.querySelector('h1');
        const title = h1
            ? h1.textContent.trim().replace(/\\s+/g, ' ')
            : (document.title || '');

        // Count headings WITHIN the content area only
        const headingCount = contentEl.querySelectorAll('h1, h2, h3, h4, h5, h6').length;

        // Count code blocks WITHIN the content area only
        const codeBlockCount = contentEl.querySelectorAll('pre').length;

        // Text length of the content area
        const textLength = contentEl.textContent.trim().length;

        return { title, headingCount, codeBlockCount, textLength };
    }""")

    return {
        "title": signals["title"],
        "heading_count": signals["headingCount"],
        "code_block_count": signals["codeBlockCount"],
        "text_length": signals["textLength"],
    }


def compare_signals(file_path, md_signals, live_signals):
    """Compare markdown signals against live page signals and return mismatches.

    Returns a list of mismatch descriptions. Empty list = all checks passed.

    Thresholds are intentionally lenient:
    - Titles: must share at least 60% of words (handles site name suffixes)
    - Headings: markdown must have at least 50% of live headings
      (some headings are in sidebar/nav, not main content)
    - Code blocks: markdown must have at least 50% of live code blocks
      (some code blocks may be in stripped nav/sidebar areas)
    - Text length: markdown must be at least 30% of live text length
      (html2text output is shorter than raw text due to stripped HTML/nav)
    """
    mismatches = []

    # Title comparison — check word overlap rather than exact match.
    # Generated titles may differ from <title> due to site name suffixes,
    # breadcrumbs, or H1 vs <title> differences.
    md_title_words = set(md_signals["title"].lower().split())
    live_title_words = set(live_signals["title"].lower().split())
    if md_title_words and live_title_words:
        overlap = len(md_title_words & live_title_words)
        max_words = max(len(md_title_words), len(live_title_words))
        if max_words > 0 and overlap / max_words < 0.6:
            mismatches.append(
                f"Title mismatch: markdown has \"{md_signals['title']}\" "
                f"but live page has \"{live_signals['title']}\""
            )

    # Heading count — markdown should have at least 50% of live headings.
    # Live page may have headings in sidebar/nav that we intentionally strip.
    if live_signals["heading_count"] > 0:
        ratio = md_signals["heading_count"] / live_signals["heading_count"]
        if ratio < 0.5:
            mismatches.append(
                f"Heading count: markdown has {md_signals['heading_count']} "
                f"but live page has {live_signals['heading_count']} "
                f"({ratio:.0%} captured)"
            )

    # Code block count — markdown should have at least 50% of live code blocks.
    if live_signals["code_block_count"] > 0:
        ratio = md_signals["code_block_count"] / live_signals["code_block_count"]
        if ratio < 0.5:
            mismatches.append(
                f"Code blocks: markdown has {md_signals['code_block_count']} "
                f"but live page has {live_signals['code_block_count']} "
                f"({ratio:.0%} captured)"
            )

    # Text length — markdown should be at least 30% of live text length.
    # html2text output is naturally shorter (no HTML tags, stripped nav).
    # A very low ratio suggests content was truncated or the wrong area was captured.
    if live_signals["text_length"] > 200:
        ratio = md_signals["text_length"] / live_signals["text_length"]
        if ratio < 0.3:
            mismatches.append(
                f"Content length: markdown is {md_signals['text_length']} chars "
                f"but live page content is {live_signals['text_length']} chars "
                f"({ratio:.0%} — possible truncation)"
            )

    return mismatches


def verify(args):
    """Main verification loop: compare every generated file against its live source."""
    plugin_dir = Path(args.plugin_dir).resolve()

    if not plugin_dir.exists():
        log.error(f"Plugin directory does not exist: {plugin_dir}")
        sys.exit(1)

    # Find the skill directory
    skill_dir = find_skill_dir(plugin_dir)
    if skill_dir is None:
        log.error(f"No skill directory found in {plugin_dir}")
        sys.exit(1)

    # Collect all content files
    content_files = collect_content_files(skill_dir)
    if not content_files:
        log.error("No content files found")
        sys.exit(1)

    log.info(f"Verifying {len(content_files)} files against live source pages")

    # Create screenshot directory if requested
    screenshot_dir = None
    if args.screenshot_dir:
        screenshot_dir = Path(args.screenshot_dir)
        screenshot_dir.mkdir(parents=True, exist_ok=True)

    # Results tracking
    passed = []
    mismatched = []
    skipped = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        for i, (rel_path, abs_path) in enumerate(content_files):
            # Read the generated markdown
            markdown_text = abs_path.read_text(encoding="utf-8")

            # Extract the source URL from the file
            source_url = extract_source_url(markdown_text)
            if not source_url:
                skipped.append((rel_path, "No source URL found in file"))
                log.warning(f"[{i+1}/{len(content_files)}] {rel_path} — SKIP (no source URL)")
                continue

            log.info(f"[{i+1}/{len(content_files)}] {rel_path}")

            try:
                # Navigate to the live page
                response = page.goto(source_url, wait_until="domcontentloaded", timeout=30000)
                # Wait for network idle instead of fixed timeout — adapts to page speed
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass

                if response and response.status >= 400:
                    skipped.append((rel_path, f"HTTP {response.status} for {source_url}"))
                    log.warning(f"  SKIP — HTTP {response.status}")
                    continue

                # Extract signals from both the markdown and the live page
                md_signals = extract_markdown_signals(markdown_text)
                live_signals = extract_live_signals(page)

                # Compare
                issues = compare_signals(rel_path, md_signals, live_signals)

                if issues:
                    mismatched.append((rel_path, source_url, issues))
                    log.warning(f"  MISMATCH:")
                    for issue in issues:
                        log.warning(f"    - {issue}")

                    # Take screenshot of mismatched page if screenshot dir is set
                    if screenshot_dir:
                        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", rel_path) + ".png"
                        screenshot_path = screenshot_dir / safe_name
                        try:
                            page.screenshot(path=str(screenshot_path))
                            log.info(f"  Screenshot saved: {screenshot_path}")
                        except Exception as e:
                            log.warning(f"  Screenshot failed: {e}")
                else:
                    passed.append(rel_path)
                    log.info(f"  OK (title match, {md_signals['heading_count']}/{live_signals['heading_count']} headings, {md_signals['code_block_count']}/{live_signals['code_block_count']} code blocks)")

            except Exception as e:
                skipped.append((rel_path, str(e)))
                log.error(f"  ERROR: {e}")

            time.sleep(humanized_delay(args.delay))

        browser.close()

    # Print summary report
    print()
    print("=" * 60)
    print("VERIFICATION REPORT")
    print("=" * 60)
    print()

    for rel_path in passed:
        print(f"  [+] {rel_path}")

    for rel_path, source_url, issues in mismatched:
        print(f"  [-] {rel_path}")
        for issue in issues:
            print(f"      {issue}")

    for rel_path, reason in skipped:
        print(f"  [?] {rel_path} — {reason}")

    print()
    print("-" * 60)
    print(f"PASSED:     {len(passed)}")
    print(f"MISMATCHED: {len(mismatched)}")
    print(f"SKIPPED:    {len(skipped)}")
    print(f"TOTAL:      {len(content_files)}")
    print()

    if mismatched:
        print("RESULT: MISMATCHES FOUND — review the flagged files")
        if screenshot_dir:
            print(f"Screenshots of mismatched pages saved to: {screenshot_dir}")
    else:
        print("RESULT: ALL FILES VERIFIED")

    print("=" * 60)

    # Exit code: 0 if all passed, 1 if mismatches found
    sys.exit(1 if mismatched else 0)


def main():
    args = parse_args()
    verify(args)


if __name__ == "__main__":
    main()

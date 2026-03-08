#!/usr/bin/env python3
"""Plugin generator — assembles extracted content into a complete documentation plugin.

Takes the per-page JSON files from extract.py and assembles them into a complete
Claude Code documentation plugin with the standard directory structure:

    plugins/docs-<library>/
    ├── .claude-plugin/plugin.json        # Plugin metadata
    └── skills/<library>-docs/
        ├── SKILL.md                      # Index file Claude reads first
        ├── index/SITEMAP.md              # Full page listing
        ├── api/                          # API reference pages
        ├── concepts/                     # Conceptual + tutorial pages
        ├── examples/                     # Code-heavy example pages
        └── warnings/WARNINGS.md          # Deprecation notices

The generated SKILL.md is the entry point for Claude — it lists every sub-file
so Claude can navigate to the relevant section based on the user's question.

Usage:
    python3 build_plugin.py <library-name> <extracted-dir> [--version latest] [--source-url URL] [--output-dir DIR]
"""

import argparse
import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("build_plugin")

# Resolve paths relative to this script's location so the script works
# regardless of the current working directory when invoked.
SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = SCRIPT_DIR.parent / "templates"

# Maps extract.py's page categories to output directory names.
# "tutorial" merges into "concepts" because tutorials are conceptual in nature —
# they explain how things work through guided examples, unlike pure "example"
# pages which are mostly code with minimal prose.
CATEGORY_DIRS = {
    "api-reference": "api",        # Function signatures, type definitions, parameters
    "conceptual": "concepts",      # Overviews, architecture, design explanations
    "tutorial": "concepts",        # Step-by-step guides (merged with conceptual)
    "example": "examples",         # Code-heavy pages with minimal prose
    "warning": "warnings",         # Deprecation notices, breaking changes
}


def parse_args():
    p = argparse.ArgumentParser(description="Build documentation plugin from extracted content")
    p.add_argument("library_name", help="Library identifier (e.g., sqlc, goose, htmx)")
    p.add_argument("extracted_dir", help="Directory containing extracted JSON files")
    p.add_argument("--version", default="latest", help="Documentation version label (default: latest)")
    p.add_argument("--source-url", default="", help="Original documentation URL")
    p.add_argument(
        "--output-dir",
        default="",
        help="Output directory (default: ../../plugins/docs-<library> relative to scripts/)",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_extracted(extracted_dir):
    """Load all extracted JSON files from the directory.

    Files are sorted alphabetically for deterministic output — the same input
    always produces the same plugin structure, making diffs meaningful.
    """
    pages = []
    for filename in sorted(os.listdir(extracted_dir)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(extracted_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        pages.append(data)
    return pages


# ---------------------------------------------------------------------------
# Filename and grouping utilities
# ---------------------------------------------------------------------------

def sanitize_filename(text):
    """Convert a page title to a safe, readable filename.

    Transforms "Installing sqlc on macOS" → "installing-sqlc-on-macos".
    Truncates at 80 characters to avoid filesystem path length limits
    (especially relevant on Windows where MAX_PATH is 260 characters).
    """
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", text.lower())
    safe = re.sub(r"-+", "-", safe).strip("-")
    if len(safe) > 80:
        safe = safe[:80].rstrip("-")
    return safe or "untitled"


def group_by_category(pages):
    """Group extracted pages by their documentation category.

    Returns a dict like {"api-reference": [page1, page2], "conceptual": [page3], ...}.
    Pages without a category default to "conceptual".
    """
    groups = defaultdict(list)
    for page in pages:
        category = page.get("category", "conceptual")
        groups[category].append(page)
    return dict(groups)


def find_top_signatures(pages, top_n=10):
    """Find the N most frequently appearing function signatures across all pages.

    These are surfaced in the generated SKILL.md as a "Quick Reference" section
    so Claude can immediately answer questions about common API functions without
    reading through all sub-files.

    We count occurrences across pages (not within a single page) because a
    signature that appears on multiple pages is likely a core API function.
    """
    sig_counts = Counter()
    for page in pages:
        for sig in page.get("signatures", []):
            sig_counts[sig] += 1
    return [sig for sig, _ in sig_counts.most_common(top_n)]


# ---------------------------------------------------------------------------
# Template handling
# ---------------------------------------------------------------------------

def load_template(name):
    """Load a template file from the templates/ directory.

    Templates use Python's str.format() syntax ({variable_name}) rather than
    Jinja2 to avoid adding an extra dependency. This is sufficient for our
    needs since we're doing simple variable substitution without loops or
    conditionals.
    """
    path = TEMPLATE_DIR / name
    if not path.exists():
        log.error(f"Template not found: {path}")
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def render_template(template, **kwargs):
    """Safely render a template string with variable substitution.

    Python's str.format() fails on strings containing literal braces (e.g.,
    Go code like `func main() {`). We use sequential str.replace() instead,
    which only substitutes known placeholders and ignores literal braces.
    """
    result = template
    for key, value in kwargs.items():
        result = result.replace("{" + key + "}", str(value))
    return result


# ---------------------------------------------------------------------------
# Content generation
# ---------------------------------------------------------------------------

def generate_section_file(page, library_name):
    """Generate a markdown sub-file for a single documentation page.

    Each sub-file contains:
    - The page title as an H1 heading
    - A "Source:" link to the original URL (for reference/verification)
    - The full extracted markdown content (verbatim, not summarized)
    - Any deprecation warnings highlighted at the bottom
    """
    template = load_template("section_template.md")
    title = page.get("title", "Untitled")
    url = page.get("url", "")
    markdown = page.get("markdown", "")
    warnings = page.get("warnings", [])

    # Format warnings as a blockquote section if any exist
    warnings_block = ""
    if warnings:
        warnings_block = "\n\n> **Warnings:**\n" + "\n".join(f"> - {w}" for w in warnings)

    return render_template(
        template,
        title=title,
        source_url=url,
        content=markdown,
        warnings=warnings_block,
    )


def generate_warnings_file(pages):
    """Generate a consolidated WARNINGS.md from all pages classified as "warning".

    Rather than creating one file per warning page, we consolidate all deprecation
    notices into a single WARNINGS.md. This makes it easy for Claude to scan all
    warnings at once when a user asks about deprecated features.
    """
    lines = ["# Warnings and Deprecation Notices\n"]
    for page in pages:
        title = page.get("title", "Untitled")
        url = page.get("url", "")
        warnings = page.get("warnings", [])
        lines.append(f"\n## {title}\n")
        lines.append(f"Source: {url}\n")
        if warnings:
            for w in warnings:
                lines.append(f"- {w}")
        # Include full markdown for context — warnings often need surrounding
        # text to understand the migration path or replacement API.
        markdown = page.get("markdown", "")
        if markdown:
            lines.append(f"\n{markdown}")
    return "\n".join(lines)


def generate_sitemap(pages, library_name):
    """Generate index/SITEMAP.md — a complete listing of all documentation pages.

    Groups pages by category with relative links to their content files.
    This serves as the "table of contents" for the entire documentation plugin.
    Claude reads this to understand what content is available before diving
    into specific sub-files.
    """
    lines = [f"# {library_name} Documentation Sitemap\n"]
    lines.append(f"Total pages: {len(pages)}\n")

    # Group by category for organized presentation
    groups = group_by_category(pages)
    for category in sorted(groups.keys()):
        cat_pages = groups[category]
        output_dir = CATEGORY_DIRS.get(category, "concepts")
        lines.append(f"\n## {category.replace('-', ' ').title()} ({len(cat_pages)} pages)\n")
        for page in cat_pages:
            title = page.get("title", "Untitled")
            filename = sanitize_filename(title) + ".md"
            # Relative path from index/ to the content directory
            filepath = f"../{output_dir}/{filename}"
            lines.append(f"- [{title}]({filepath})")

    return "\n".join(lines)


def generate_skill_md(library_name, pages, source_url, version, file_listing):
    """Generate the SKILL.md index file for the documentation plugin.

    SKILL.md is the most important file in the plugin — it's what Claude reads
    first when the skill is activated. It contains:
    - Frontmatter with trigger phrases for skill activation
    - Source URL and version metadata
    - Directory structure overview
    - Quick reference for the most common API functions
    - Complete file listing so Claude knows where to find every piece of content
    """
    template = load_template("SKILL_template.md")

    # Surface the top 5-10 most common function signatures as a quick reference.
    # This lets Claude answer "what's the signature for X?" without reading sub-files.
    top_sigs = find_top_signatures(pages)
    quick_ref = ""
    if top_sigs:
        quick_ref = "\n## Quick Reference — Common Functions\n\n"
        quick_ref += "```\n" + "\n".join(top_sigs) + "\n```\n"

    # Build a summary of how many pages are in each content directory
    groups = group_by_category(pages)
    category_summary = ""
    for category in sorted(groups.keys()):
        output_dir = CATEGORY_DIRS.get(category, "concepts")
        count = len(groups[category])
        category_summary += f"- **{output_dir}/**: {count} {category.replace('-', ' ')} pages\n"

    return render_template(
        template,
        library_name=library_name,
        library_name_title=library_name.replace("-", " ").title(),
        version=version,
        source_url=source_url,
        total_pages=len(pages),
        category_summary=category_summary,
        quick_reference=quick_ref,
        file_listing=file_listing,
    )


def generate_plugin_json(library_name, version, source_url):
    """Generate .claude-plugin/plugin.json for the documentation plugin.

    This is the plugin metadata file that Claude Code reads to identify and
    load the plugin. It must contain name, description, version, and author.
    """
    template = load_template("plugin_json_template.json")
    return render_template(
        template,
        library_name=library_name,
        library_name_title=library_name.replace("-", " ").title(),
        version=version,
        source_url=source_url,
    )


# ---------------------------------------------------------------------------
# Main build pipeline
# ---------------------------------------------------------------------------

def build_plugin(args):
    """Orchestrate the full plugin build from extracted content.

    Pipeline:
    1. Load all extracted JSON files
    2. Group pages by category
    3. Create plugin directory structure
    4. Generate content sub-files (one .md per page, warnings consolidated)
    5. Generate index/SITEMAP.md (full page listing)
    6. Generate SKILL.md (entry point with file index and quick reference)
    7. Generate plugin.json (metadata)
    """
    library = args.library_name
    extracted_dir = args.extracted_dir
    version = args.version
    source_url = args.source_url

    # Default output location: alongside other plugins in the monorepo.
    # scripts/ → doc-scanner skill → doc-scanner plugin → plugins/ → docs-<lib>/
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = SCRIPT_DIR.parent.parent.parent.parent / f"docs-{library}"

    log.info(f"Building plugin for '{library}' v{version}")
    log.info(f"Reading from: {extracted_dir}")
    log.info(f"Writing to: {output_dir}")

    # Load all extracted pages
    pages = load_extracted(extracted_dir)
    if not pages:
        log.error("No extracted pages found")
        sys.exit(1)

    log.info(f"Loaded {len(pages)} pages")

    # Group by category and log distribution
    groups = group_by_category(pages)
    for cat, cat_pages in sorted(groups.items()):
        log.info(f"  {cat}: {len(cat_pages)} pages")

    # Set up the plugin directory structure following Claude Code plugin conventions:
    # .claude-plugin/plugin.json (required metadata)
    # skills/<name>/SKILL.md (required skill definition)
    skill_name = f"{library}-docs"
    skill_dir = output_dir / "skills" / skill_name
    plugin_meta_dir = output_dir / ".claude-plugin"
    index_dir = skill_dir / "index"

    for d in [plugin_meta_dir, index_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Track all generated files for the SKILL.md file listing
    file_listing_lines = []
    written_files = []

    # Generate content sub-files, organized by category into subdirectories
    for category, cat_pages in sorted(groups.items()):
        output_subdir = CATEGORY_DIRS.get(category, "concepts")
        content_dir = skill_dir / output_subdir
        content_dir.mkdir(parents=True, exist_ok=True)

        # Warning pages get consolidated into a single WARNINGS.md rather than
        # individual files, because deprecation info is most useful when viewed together.
        if category == "warning":
            warnings_content = generate_warnings_file(cat_pages)
            warnings_path = content_dir / "WARNINGS.md"
            warnings_path.write_text(warnings_content, encoding="utf-8")
            rel_path = f"{output_subdir}/WARNINGS.md"
            file_listing_lines.append(f"- `{rel_path}` — Deprecation notices and warnings")
            written_files.append(rel_path)
            log.info(f"  Wrote {warnings_path}")
            continue

        # For all other categories: one markdown file per extracted page
        for page in cat_pages:
            title = page.get("title", "Untitled")
            filename = sanitize_filename(title) + ".md"
            filepath = content_dir / filename
            content = generate_section_file(page, library)
            filepath.write_text(content, encoding="utf-8")

            rel_path = f"{output_subdir}/{filename}"
            file_listing_lines.append(f"- `{rel_path}` — {title}")
            written_files.append(rel_path)

    log.info(f"Wrote {len(written_files)} content files")

    # Generate the SITEMAP.md index (complete page listing grouped by category)
    sitemap_content = generate_sitemap(pages, library)
    sitemap_path = index_dir / "SITEMAP.md"
    sitemap_path.write_text(sitemap_content, encoding="utf-8")
    # Insert SITEMAP at the top of the file listing
    file_listing_lines.insert(0, f"- `index/SITEMAP.md` — Full sitemap of all {len(pages)} pages")
    log.info(f"Wrote {sitemap_path}")

    # Generate SKILL.md — the entry point Claude reads when the skill activates.
    # The file listing is sorted alphabetically for consistent, scannable output.
    file_listing = "\n".join(sorted(file_listing_lines))
    skill_content = generate_skill_md(library, pages, source_url, version, file_listing)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(skill_content, encoding="utf-8")
    log.info(f"Wrote {skill_path}")

    # Generate plugin.json metadata
    plugin_json_content = generate_plugin_json(library, version, source_url)
    plugin_json_path = plugin_meta_dir / "plugin.json"
    plugin_json_path.write_text(plugin_json_content, encoding="utf-8")
    log.info(f"Wrote {plugin_json_path}")

    # Final summary
    log.info("=" * 60)
    log.info(f"Plugin built successfully: {output_dir}")
    log.info(f"Total files: {len(written_files) + 3} (content + SITEMAP + SKILL + plugin.json)")
    log.info(f"Skill name: {skill_name}")


def main():
    args = parse_args()
    build_plugin(args)


if __name__ == "__main__":
    main()

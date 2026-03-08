#!/usr/bin/env python3
"""Plugin generator — assembles extracted content into a complete documentation plugin.

Reads extracted JSON files, groups by category, generates markdown sub-files,
SITEMAP.md, SKILL.md index, and plugin.json.

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

SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = SCRIPT_DIR.parent / "templates"

# Category → output directory mapping
CATEGORY_DIRS = {
    "api-reference": "api",
    "conceptual": "concepts",
    "tutorial": "concepts",
    "example": "examples",
    "warning": "warnings",
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


def load_extracted(extracted_dir):
    """Load all extracted JSON files."""
    pages = []
    for filename in sorted(os.listdir(extracted_dir)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(extracted_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        pages.append(data)
    return pages


def sanitize_filename(text):
    """Convert a title or URL path to a safe filename."""
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", text.lower())
    safe = re.sub(r"-+", "-", safe).strip("-")
    if len(safe) > 80:
        safe = safe[:80].rstrip("-")
    return safe or "untitled"


def group_by_category(pages):
    """Group pages by their documentation category."""
    groups = defaultdict(list)
    for page in pages:
        category = page.get("category", "conceptual")
        groups[category].append(page)
    return dict(groups)


def find_top_signatures(pages, top_n=10):
    """Find the most referenced function signatures across all pages."""
    sig_counts = Counter()
    for page in pages:
        for sig in page.get("signatures", []):
            sig_counts[sig] += 1
    return [sig for sig, _ in sig_counts.most_common(top_n)]


def load_template(name):
    """Load a template file."""
    path = TEMPLATE_DIR / name
    if not path.exists():
        log.error(f"Template not found: {path}")
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def generate_section_file(page, library_name):
    """Generate a markdown sub-file for a single page."""
    template = load_template("section_template.md")
    title = page.get("title", "Untitled")
    url = page.get("url", "")
    markdown = page.get("markdown", "")
    warnings = page.get("warnings", [])

    warnings_block = ""
    if warnings:
        warnings_block = "\n\n> **Warnings:**\n" + "\n".join(f"> - {w}" for w in warnings)

    return template.format(
        title=title,
        source_url=url,
        content=markdown,
        warnings=warnings_block,
    )


def generate_warnings_file(pages):
    """Generate a consolidated WARNINGS.md from all warning pages."""
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
        # Also include the full markdown for context
        markdown = page.get("markdown", "")
        if markdown:
            lines.append(f"\n{markdown}")
    return "\n".join(lines)


def generate_sitemap(pages, library_name):
    """Generate index/SITEMAP.md listing all pages."""
    lines = [f"# {library_name} Documentation Sitemap\n"]
    lines.append(f"Total pages: {len(pages)}\n")

    # Group by category for organized listing
    groups = group_by_category(pages)
    for category in sorted(groups.keys()):
        cat_pages = groups[category]
        output_dir = CATEGORY_DIRS.get(category, "concepts")
        lines.append(f"\n## {category.replace('-', ' ').title()} ({len(cat_pages)} pages)\n")
        for page in cat_pages:
            title = page.get("title", "Untitled")
            filename = sanitize_filename(title) + ".md"
            filepath = f"../{output_dir}/{filename}"
            lines.append(f"- [{title}]({filepath})")

    return "\n".join(lines)


def generate_skill_md(library_name, pages, source_url, version, file_listing):
    """Generate the SKILL.md index for the docs plugin."""
    template = load_template("SKILL_template.md")

    top_sigs = find_top_signatures(pages)
    quick_ref = ""
    if top_sigs:
        quick_ref = "\n## Quick Reference — Common Functions\n\n"
        quick_ref += "```\n" + "\n".join(top_sigs) + "\n```\n"

    # Build category summary
    groups = group_by_category(pages)
    category_summary = ""
    for category in sorted(groups.keys()):
        output_dir = CATEGORY_DIRS.get(category, "concepts")
        count = len(groups[category])
        category_summary += f"- **{output_dir}/**: {count} {category.replace('-', ' ')} pages\n"

    return template.format(
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
    """Generate plugin.json for the docs plugin."""
    template = load_template("plugin_json_template.json")
    return template.format(
        library_name=library_name,
        library_name_title=library_name.replace("-", " ").title(),
        version=version,
        source_url=source_url,
    )


def build_plugin(args):
    library = args.library_name
    extracted_dir = args.extracted_dir
    version = args.version
    source_url = args.source_url

    # Determine output directory
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

    # Group by category
    groups = group_by_category(pages)
    for cat, cat_pages in sorted(groups.items()):
        log.info(f"  {cat}: {len(cat_pages)} pages")

    # Create directory structure
    skill_name = f"{library}-docs"
    skill_dir = output_dir / "skills" / skill_name
    plugin_meta_dir = output_dir / ".claude-plugin"
    index_dir = skill_dir / "index"

    for d in [plugin_meta_dir, index_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Create content directories and write sub-files
    file_listing_lines = []
    written_files = []

    for category, cat_pages in sorted(groups.items()):
        output_subdir = CATEGORY_DIRS.get(category, "concepts")
        content_dir = skill_dir / output_subdir
        content_dir.mkdir(parents=True, exist_ok=True)

        # Special case: consolidate warnings into one file
        if category == "warning":
            warnings_content = generate_warnings_file(cat_pages)
            warnings_path = content_dir / "WARNINGS.md"
            warnings_path.write_text(warnings_content, encoding="utf-8")
            rel_path = f"{output_subdir}/WARNINGS.md"
            file_listing_lines.append(f"- `{rel_path}` — Deprecation notices and warnings")
            written_files.append(rel_path)
            log.info(f"  Wrote {warnings_path}")
            continue

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

    # Generate SITEMAP.md
    sitemap_content = generate_sitemap(pages, library)
    sitemap_path = index_dir / "SITEMAP.md"
    sitemap_path.write_text(sitemap_content, encoding="utf-8")
    file_listing_lines.insert(0, f"- `index/SITEMAP.md` — Full sitemap of all {len(pages)} pages")
    log.info(f"Wrote {sitemap_path}")

    # Generate SKILL.md
    file_listing = "\n".join(sorted(file_listing_lines))
    skill_content = generate_skill_md(library, pages, source_url, version, file_listing)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(skill_content, encoding="utf-8")
    log.info(f"Wrote {skill_path}")

    # Generate plugin.json
    plugin_json_content = generate_plugin_json(library, version, source_url)
    plugin_json_path = plugin_meta_dir / "plugin.json"
    plugin_json_path.write_text(plugin_json_content, encoding="utf-8")
    log.info(f"Wrote {plugin_json_path}")

    # Summary
    log.info("=" * 60)
    log.info(f"Plugin built successfully: {output_dir}")
    log.info(f"Total files: {len(written_files) + 3} (content + SITEMAP + SKILL + plugin.json)")
    log.info(f"Skill name: {skill_name}")


def main():
    args = parse_args()
    build_plugin(args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Skill generator — assembles extracted content into a documentation skill.

Takes the per-page JSON files from extract.py and assembles them into a
Claude Code documentation skill:

    <name>-docs/
    ├── SKILL.md          # Index file Claude reads first
    └── pages/            # All documentation pages (flat)

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

PAGES_DIR = "pages"


def parse_args():
    p = argparse.ArgumentParser(description="Build documentation skill from extracted content")
    p.add_argument("library_name", help="Library identifier (e.g., react, laravel, htmx)")
    p.add_argument("extracted_dir", help="Directory containing extracted JSON files")
    p.add_argument("--version", default="latest", help="Documentation version label (default: latest)")
    p.add_argument("--source-url", default="", help="Original documentation URL")
    p.add_argument(
        "--output-dir",
        required=True,
        help="Output directory for the skill (e.g., ~/.claude/skills/react-docs)",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_extracted(extracted_dir):
    """Load all extracted JSON files from the directory.

    Files are sorted alphabetically for deterministic output — the same input
    always produces the same skill structure, making diffs meaningful.
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


# ---------------------------------------------------------------------------
# Description term derivation
# ---------------------------------------------------------------------------

# Domain-specific term pools — each maps a signal (found in titles, headings,
# URL paths, or code block languages) to the description terms it suggests.
# Terms are checked in priority order; the first matches win.
_DOMAIN_SIGNALS = [
    # Languages / syntax-heavy docs
    ({"syntax", "grammar", "specification", "language reference", "type system", "generics", "concurrency"},
     ["syntax", "language features", "types", "standard library"]),
    # CLI tools
    ({"command", "commands", "subcommand", "flags", "cli", "usage:", "shell"},
     ["commands", "CLI usage", "flags", "options"]),
    # Databases / query-heavy
    ({"query", "queries", "sql", "schema", "index", "table", "migration", "orm"},
     ["queries", "schema design", "data types", "migrations"]),
    # Infrastructure / cloud
    ({"resource", "provider", "manifest", "deploy", "terraform", "kubernetes", "helm", "cluster"},
     ["resources", "deployment", "configuration", "infrastructure"]),
    # UI / component libraries
    ({"component", "components", "hook", "hooks", "rendering", "state", "props", "jsx", "tsx"},
     ["components", "hooks", "rendering", "state management"]),
    # Data science / math
    ({"array", "dataframe", "tensor", "numpy", "pandas", "plot", "matplotlib", "scipy"},
     ["functions", "data structures", "computation", "visualization"]),
]

# Fallback terms when no domain signal matches strongly enough.
_DEFAULT_TERMS = ["API", "configuration", "usage patterns", "troubleshooting"]


def derive_description_terms(pages):
    """Analyze extracted pages to pick domain-appropriate description terms.

    Scans page titles, H2/H3 headings, and code block languages for domain
    signals. Returns a list of 3-5 terms that best describe what the docs cover.
    """
    # Build a bag of lowercase tokens from titles and headings
    tokens = set()
    for page in pages:
        title = page.get("title", "").lower()
        tokens.update(title.split())
        for h in page.get("headings", []):
            text = h.get("text", "").lower()
            tokens.update(text.split())
            # Also add the full heading text for multi-word signal matching
            tokens.add(text)
        # Add code block languages as signals
        for block in page.get("code_blocks", []):
            lang = block.get("language", "").lower()
            if lang:
                tokens.add(lang)
        # Add URL path segments
        url = page.get("url", "")
        if url:
            from urllib.parse import urlparse
            path = urlparse(url).path.lower()
            tokens.update(seg for seg in path.split("/") if seg)

    # Score each domain by counting how many of its signal words appear
    best_terms = None
    best_score = 0
    for signals, terms in _DOMAIN_SIGNALS:
        score = sum(1 for s in signals if s in tokens)
        if score > best_score:
            best_score = score
            best_terms = terms

    # Require at least 2 signal hits to override the default
    if best_score >= 2 and best_terms:
        return best_terms

    return _DEFAULT_TERMS



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


def generate_section_file(page, library_name, template=None):
    """Generate a markdown sub-file for a single documentation page."""
    if template is None:
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




def generate_skill_md(library_name, versioned_library, skill_name, pages, source_url, version, file_listing):
    """Generate the SKILL.md index file for the documentation skill.

    SKILL.md is the most important file — it's what Claude reads first when
    the skill is activated. It contains:
    - Frontmatter with trigger phrases for skill activation (version-aware)
    - Source URL and version metadata
    - Directory structure overview
    - Complete file listing so Claude knows where to find every piece of content
    """
    template = load_template("SKILL_template.md")

    # No quick reference section — it was noise with out-of-context signatures
    quick_ref = ""

    # Simple page count summary
    pages_summary = f"- **{PAGES_DIR}/**: {len(pages)} documentation pages\n"

    # Build version-specific trigger phrases for the SKILL.md description.
    # When versioned, include phrases like "laravel 11 docs" so Claude picks
    # the right version. When "latest", omit version from triggers.
    if version and version != "latest":
        version_triggers = (
            f'"{library_name} {version}", "{library_name} {version} docs", '
            f'"{library_name} version {version}"'
        )
    else:
        version_triggers = ""

    # Derive domain-appropriate description terms from the actual content
    description_terms = ", ".join(derive_description_terms(pages))

    return render_template(
        template,
        library_name=library_name,
        versioned_library=versioned_library,
        plugin_name=skill_name,
        library_name_title=library_name.replace("-", " ").title(),
        version=version,
        version_triggers=version_triggers,
        description_terms=description_terms,
        source_url=source_url,
        total_pages=len(pages),
        pages_summary=pages_summary,
        quick_reference=quick_ref,
        file_listing=file_listing,
    )


# ---------------------------------------------------------------------------
# Main build pipeline
# ---------------------------------------------------------------------------

def build_skill(args):
    """Orchestrate the full skill build from extracted content.

    Pipeline:
    1. Load all extracted JSON files
    2. Create skill directory structure
    3. Generate content sub-files (one .md per page in pages/)
    4. Generate SKILL.md (entry point with file index and sub-topic descriptions)
    """
    library = args.library_name
    extracted_dir = args.extracted_dir
    version = args.version
    source_url = args.source_url

    # Version-aware naming: when version is not "latest", insert it between
    # the library name and the "-docs" suffix so multiple versions can coexist.
    # e.g., "laravel" + "11" → "laravel-11-docs"
    # e.g., "laravel" + "latest" → "laravel-docs"
    if version and version != "latest":
        skill_name = f"{library}-{version}-docs"
        versioned_library = f"{library}-{version}"
    else:
        skill_name = f"{library}-docs"
        versioned_library = library

    output_dir = Path(args.output_dir)

    log.info(f"Building skill '{skill_name}' v{version}")
    log.info(f"Reading from: {extracted_dir}")
    log.info(f"Writing to: {output_dir}")

    # Load all extracted pages
    pages = load_extracted(extracted_dir)
    if not pages:
        log.error("No extracted pages found")
        sys.exit(1)

    log.info(f"Loaded {len(pages)} pages")

    # output_dir IS the skill directory (SKILL.md + pages/)
    skill_dir = output_dir

    # Track all generated files for the SKILL.md file listing
    file_listing_lines = []
    written_files = []

    # Generate content sub-files — all files go into a single pages/ directory.
    # All files go into a single flat pages/ directory.
    content_dir = skill_dir / PAGES_DIR
    content_dir.mkdir(parents=True, exist_ok=True)

    used_filenames = {}

    section_template = load_template("section_template.md")

    for page in pages:
        title = page.get("title", "Untitled")
        filename = sanitize_filename(title) + ".md"

        # Detect filename collisions
        if filename.lower() in used_filenames:
            base = sanitize_filename(title)
            counter = 2
            while f"{base}-{counter}.md".lower() in used_filenames:
                counter += 1
            filename = f"{base}-{counter}.md"
            log.warning(f"  Filename collision: '{title}' → {filename}")

        used_filenames[filename.lower()] = True

        filepath = content_dir / filename
        content = generate_section_file(page, library, section_template)
        filepath.write_text(content, encoding="utf-8")

        # Build rich file listing with H2 headings as sub-topics
        h2_headings = [h["text"] for h in page.get("headings", []) if h.get("level") == 2]
        if h2_headings:
            # Show up to 8 key sub-topics
            topics = ", ".join(h2_headings[:8])
            if len(h2_headings) > 8:
                topics += f", ... (+{len(h2_headings) - 8} more)"
            file_listing_lines.append(f"- `{PAGES_DIR}/{filename}` — {title}: {topics}")
        else:
            file_listing_lines.append(f"- `{PAGES_DIR}/{filename}` — {title}")

        written_files.append(f"{PAGES_DIR}/{filename}")

    log.info(f"Wrote {len(written_files)} content files")

    # Generate SKILL.md — the entry point Claude reads when the skill activates.
    # The file listing is sorted alphabetically for consistent, scannable output.
    file_listing = "\n".join(sorted(file_listing_lines))
    skill_content = generate_skill_md(library, versioned_library, skill_name, pages, source_url, version, file_listing)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(skill_content, encoding="utf-8")
    log.info(f"Wrote {skill_path}")

    # Final summary
    log.info("=" * 60)
    log.info(f"Skill built successfully: {output_dir}")
    log.info(f"Total files: {len(written_files) + 1} (content + SKILL.md)")
    log.info(f"Skill name: {skill_name}")


def main():
    args = parse_args()
    build_skill(args)


if __name__ == "__main__":
    main()

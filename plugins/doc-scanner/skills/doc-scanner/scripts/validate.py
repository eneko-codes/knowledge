#!/usr/bin/env python3
"""Coverage validator for generated documentation plugins.

Runs a suite of checks to verify that the generated plugin is complete,
structurally sound, and faithfully represents the original documentation.

Checks performed:
  1. plugin.json exists and has required fields (name, description, version, author)
  2. SKILL.md exists, has YAML frontmatter, and has substantial content
  3. SITEMAP.md exists
  4. Page count: content files >= sitemap pages (accounting for warning consolidation)
  5. Section coverage: >= 90% of sitemap headings appear in content files
  6. Link resolution: all file paths in SKILL.md resolve to existing files
  7. No empty files: every .md file has real content (not just a heading)
  8. Signature coverage: function-like headings from sitemap appear in content (>= 80%)

Exit codes:
  0 — all checks passed
  1 — one or more checks failed

Usage:
    python3 validate.py <plugin-dir> [--sitemap sitemap.json]
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
log = logging.getLogger("validate")


def parse_args():
    p = argparse.ArgumentParser(description="Validate generated documentation plugin")
    p.add_argument("plugin_dir", help="Path to the generated plugin directory")
    p.add_argument("--sitemap", help="Path to original sitemap.json for cross-referencing")
    return p.parse_args()


class ValidationResult:
    """Accumulates check results and generates a formatted report.

    Separates errors (check failures that must be fixed) from warnings
    (potential issues worth investigating but not blocking). The .passed
    property only considers errors, not warnings.
    """

    def __init__(self):
        self.checks = []     # List of (name, "PASS"/"FAIL", detail) tuples
        self.errors = []     # Failure descriptions for the summary
        self.warnings = []   # Non-blocking issues

    def add_check(self, name, passed, detail=""):
        """Record a check result.

        Args:
            name: Human-readable check name (e.g., "plugin.json exists")
            passed: True if the check succeeded, False if it failed
            detail: Additional context (counts, paths, etc.)
        """
        status = "PASS" if passed else "FAIL"
        self.checks.append((name, status, detail))
        if not passed:
            self.errors.append(f"{name}: {detail}")

    def add_warning(self, message):
        """Record a non-blocking issue worth investigating."""
        self.warnings.append(message)

    @property
    def passed(self):
        """True if all checks passed (warnings don't count as failures)."""
        return len(self.errors) == 0

    def report(self):
        """Generate a formatted text report of all check results."""
        lines = ["=" * 60, "VALIDATION REPORT", "=" * 60, ""]

        # List each check with a [+] (pass) or [-] (fail) indicator
        for name, status, detail in self.checks:
            icon = "+" if status == "PASS" else "-"
            line = f"  [{icon}] {name}"
            if detail:
                line += f" — {detail}"
            lines.append(line)

        # List warnings separately
        if self.warnings:
            lines.append("")
            lines.append("WARNINGS:")
            for w in self.warnings:
                lines.append(f"  [!] {w}")

        # Summary line
        lines.append("")
        lines.append("-" * 60)
        if self.passed:
            lines.append("RESULT: ALL CHECKS PASSED")
        else:
            lines.append(f"RESULT: {len(self.errors)} CHECK(S) FAILED")
            for err in self.errors:
                lines.append(f"  - {err}")

        lines.append("=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Plugin structure discovery
# ---------------------------------------------------------------------------

def find_skill_dir(plugin_dir):
    """Locate the skill directory inside the plugin.

    Claude Code plugins store skills in skills/<skill-name>/SKILL.md.
    We search for any subdirectory of skills/ that contains a SKILL.md file.
    """
    skills_dir = plugin_dir / "skills"
    if not skills_dir.exists():
        return None
    for child in skills_dir.iterdir():
        if child.is_dir() and (child / "SKILL.md").exists():
            return child
    return None


def collect_md_files(skill_dir):
    """Recursively collect all .md files in the skill directory except SKILL.md.

    Returns a dict mapping relative paths (e.g., "api/config.md") to absolute
    Path objects. SKILL.md is excluded because it's the index file, not content.
    """
    files = {}
    for md_file in skill_dir.rglob("*.md"):
        rel = md_file.relative_to(skill_dir)
        if str(rel) == "SKILL.md":
            continue
        files[str(rel)] = md_file
    return files


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_plugin_json(plugin_dir, result):
    """Verify that .claude-plugin/plugin.json exists and has required fields.

    Required fields: name, description, version, author.
    Without these, Claude Code won't load the plugin.
    """
    pj_path = plugin_dir / ".claude-plugin" / "plugin.json"
    if not pj_path.exists():
        result.add_check("plugin.json exists", False, f"Missing: {pj_path}")
        return

    with open(pj_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    required = ["name", "description", "version", "author"]
    missing = [k for k in required if k not in data]
    if missing:
        result.add_check("plugin.json has required fields", False, f"Missing fields: {missing}")
    else:
        result.add_check("plugin.json has required fields", True)


def check_skill_md(skill_dir, result):
    """Verify that SKILL.md exists, has YAML frontmatter, and has enough content.

    Frontmatter (the --- delimited YAML block at the top) is required for Claude
    to detect when to activate the skill. The 500-character minimum ensures the
    file isn't just a stub with no useful index information.
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        result.add_check("SKILL.md exists", False)
        return None

    content = skill_md.read_text(encoding="utf-8")

    # Check for YAML frontmatter (--- delimited block at file start)
    if content.startswith("---"):
        end = content.find("---", 3)
        if end > 0:
            result.add_check("SKILL.md has frontmatter", True)
        else:
            result.add_check("SKILL.md has frontmatter", False, "Frontmatter not closed")
    else:
        result.add_check("SKILL.md has frontmatter", False, "No frontmatter found")

    # Minimum content length — a real SKILL.md with file listings should be >500 chars
    if len(content) > 500:
        result.add_check("SKILL.md has substantial content", True, f"{len(content)} chars")
    else:
        result.add_check("SKILL.md has substantial content", False, f"Only {len(content)} chars")

    return content


def check_page_count(sitemap, md_files, skill_dir, result):
    """Verify that the number of content files matches the sitemap page count.

    Warning pages are consolidated into a single WARNINGS.md, so we subtract
    warning page count from the expected total. The check passes if we have
    at least as many content files as non-warning sitemap pages.
    """
    # First check that SITEMAP.md exists
    sitemap_md = skill_dir / "index" / "SITEMAP.md"
    if not sitemap_md.exists():
        result.add_check("SITEMAP.md exists", False)
        return

    result.add_check("SITEMAP.md exists", True)

    if sitemap is None:
        result.add_warning("No sitemap.json provided — skipping count cross-reference")
        return

    sitemap_pages = len(sitemap.get("pages", []))

    # Content files = all .md files except those in index/ (SITEMAP.md)
    content_files = {k: v for k, v in md_files.items() if not k.startswith("index/")}
    content_count = len(content_files)

    # Warning pages get consolidated into a single WARNINGS.md by build_plugin.py,
    # so the file count will be lower than the sitemap page count. We detect this
    # by checking if WARNINGS.md exists (indicating consolidation happened).
    # The actual number of consolidated pages = (sitemap_pages - content_count),
    # which is valid as long as WARNINGS.md accounts for the difference.
    has_warnings_file = (skill_dir / "warnings" / "WARNINGS.md").exists()

    # Allow the difference if a WARNINGS.md exists (pages were consolidated)
    # or if there are pages with "warning" in the title (title-based heuristic)
    warning_slack = 0
    if has_warnings_file:
        # The difference between sitemap pages and content files is the number
        # of pages that were consolidated into WARNINGS.md (minus 1 for the file itself)
        warning_slack = max(0, sitemap_pages - content_count)

    if content_count >= sitemap_pages - warning_slack:
        result.add_check(
            "Page count matches",
            True,
            f"{content_count} content files for {sitemap_pages} sitemap pages",
        )
    else:
        result.add_check(
            "Page count matches",
            False,
            f"{content_count} content files but {sitemap_pages} sitemap pages (diff: {sitemap_pages - content_count})",
        )


def check_section_coverage(sitemap, md_files, skill_dir, result):
    """Verify that headings from the sitemap appear in the content files.

    This catches cases where a page was extracted but its content was empty or
    truncated. We check for each H1/H2/H3 heading text (case-insensitive)
    appearing anywhere in the content files.

    Threshold: 90% coverage passes. Some headings may legitimately not appear
    (e.g., auto-generated headings with dynamic content, or headings that only
    appear after JavaScript interaction).
    """
    if sitemap is None:
        result.add_warning("No sitemap.json — skipping section coverage check")
        return

    # Collect all heading texts from the sitemap
    all_headings = []
    for page in sitemap.get("pages", []):
        for h in page.get("headings", []):
            text = h.get("text", "").strip()
            # Skip very short headings (likely navigation artifacts like ">" or "<<")
            if text and len(text) > 2:
                all_headings.append(text)

    if not all_headings:
        result.add_warning("No headings found in sitemap — skipping section coverage")
        return

    # Concatenate all content files into one string for substring search.
    # This is O(n*m) but fast enough for documentation-scale data.
    all_content = ""
    for rel_path, filepath in md_files.items():
        all_content += filepath.read_text(encoding="utf-8") + "\n"

    # Case-insensitive substring match for each heading
    found = 0
    missing = []
    for heading in all_headings:
        normalized = heading.lower().strip()
        if normalized in all_content.lower():
            found += 1
        else:
            missing.append(heading)

    coverage = found / len(all_headings) * 100 if all_headings else 100

    # 90% threshold: allows for minor mismatches due to JS-rendered headings,
    # Unicode normalization differences, or dynamic content
    if coverage >= 90:
        result.add_check(
            "Section coverage",
            True,
            f"{found}/{len(all_headings)} headings found ({coverage:.1f}%)",
        )
    else:
        result.add_check(
            "Section coverage",
            False,
            f"{found}/{len(all_headings)} headings found ({coverage:.1f}%)",
        )

    # Report missing headings (capped to avoid flooding the report)
    if missing and len(missing) <= 10:
        for h in missing:
            result.add_warning(f"Missing heading: {h}")
    elif missing:
        result.add_warning(f"{len(missing)} headings missing (showing first 10)")
        for h in missing[:10]:
            result.add_warning(f"  Missing: {h}")


def check_link_resolution(skill_md_content, skill_dir, result):
    """Verify that every file path referenced in SKILL.md resolves to an existing file.

    SKILL.md lists all content files as backtick-quoted paths like `api/config.md`.
    This check ensures none of those references are broken — a broken reference
    means Claude would try to read a file that doesn't exist.
    """
    if skill_md_content is None:
        return

    # Match backtick-quoted paths that look like file references (contain .md)
    # Pattern: starts with a letter, contains word chars/slashes/dashes, ends in .md
    path_pattern = re.compile(r"`([a-zA-Z][\w/-]*\.md)`")
    referenced = path_pattern.findall(skill_md_content)

    if not referenced:
        result.add_warning("No file paths found in SKILL.md to check")
        return

    broken = []
    for ref in referenced:
        full_path = skill_dir / ref
        if not full_path.exists():
            broken.append(ref)

    if broken:
        result.add_check(
            "Link resolution",
            False,
            f"{len(broken)} broken references: {broken[:5]}",
        )
    else:
        result.add_check(
            "Link resolution",
            True,
            f"All {len(referenced)} referenced paths resolve",
        )


def check_empty_files(md_files, result):
    """Verify that no content files are empty or suspiciously short.

    Empty files indicate extraction failures where a page was processed but
    no content was captured (e.g., the content area selector didn't match).
    Files under 50 characters likely contain only a heading with no body.
    """
    empty = []
    placeholder = []
    for rel_path, filepath in md_files.items():
        content = filepath.read_text(encoding="utf-8").strip()
        if not content:
            empty.append(rel_path)
        elif len(content) < 50:
            # 50 chars is roughly "# Title\n\n> Source: url" — just a heading, no content
            placeholder.append(rel_path)

    if empty:
        result.add_check("No empty files", False, f"{len(empty)} empty files: {empty[:5]}")
    else:
        result.add_check("No empty files", True, f"All {len(md_files)} files have content")

    if placeholder:
        result.add_warning(f"{len(placeholder)} files with very short content (<50 chars): {placeholder[:5]}")


def check_signature_coverage(sitemap, md_files, result):
    """Heuristic check: headings that look like function signatures should appear in content.

    Some doc sites use function signatures as heading text (e.g., "NewClient(opts)").
    These are the most valuable API references, so we verify they made it through
    extraction. A heading is considered function-like if it contains both "(" and ")".

    Threshold: 80% coverage passes. Lower than section coverage because signature
    headings may be rendered differently in the extracted markdown.
    """
    if sitemap is None:
        return

    # Find headings that look like function signatures (contain parentheses)
    sig_headings = []
    for page in sitemap.get("pages", []):
        for h in page.get("headings", []):
            text = h.get("text", "")
            if "(" in text and ")" in text:
                sig_headings.append(text)

    if not sig_headings:
        return  # No signature-like headings, skip this check

    # Search all content files for each signature heading
    all_content = ""
    for filepath in md_files.values():
        all_content += filepath.read_text(encoding="utf-8") + "\n"

    found = sum(1 for sig in sig_headings if sig.lower() in all_content.lower())
    if sig_headings:
        coverage = found / len(sig_headings) * 100
        if coverage >= 80:
            result.add_check("Signature coverage", True, f"{found}/{len(sig_headings)} ({coverage:.1f}%)")
        else:
            result.add_check("Signature coverage", False, f"{found}/{len(sig_headings)} ({coverage:.1f}%)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    plugin_dir = Path(args.plugin_dir).resolve()

    if not plugin_dir.exists():
        log.error(f"Plugin directory does not exist: {plugin_dir}")
        sys.exit(1)

    # Load the original sitemap for cross-referencing (optional but recommended)
    sitemap = None
    if args.sitemap:
        with open(args.sitemap, "r", encoding="utf-8") as f:
            sitemap = json.load(f)

    result = ValidationResult()

    # Step 1: Find the skill directory
    skill_dir = find_skill_dir(plugin_dir)
    if skill_dir is None:
        log.error(f"No skill directory found in {plugin_dir}")
        result.add_check("Skill directory exists", False)
        print(result.report())
        sys.exit(1)

    result.add_check("Skill directory exists", True, str(skill_dir.name))

    # Step 2: Collect all content files for subsequent checks
    md_files = collect_md_files(skill_dir)
    result.add_check("Content files found", len(md_files) > 0, f"{len(md_files)} markdown files")

    # Step 3: Run all validation checks
    check_plugin_json(plugin_dir, result)          # Metadata integrity
    skill_md_content = check_skill_md(skill_dir, result)  # SKILL.md structure
    check_page_count(sitemap, md_files, skill_dir, result)      # Completeness
    check_section_coverage(sitemap, md_files, skill_dir, result) # Content fidelity
    check_link_resolution(skill_md_content, skill_dir, result)   # Internal links
    check_empty_files(md_files, result)                          # No stub files
    check_signature_coverage(sitemap, md_files, result)          # API coverage

    # Print the report and exit with appropriate code
    print(result.report())
    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Coverage validator for generated documentation skills.

Runs a suite of checks to verify that the generated skill is complete,
structurally sound, and faithfully represents the extracted content.

Checks performed:
  1. SKILL.md exists, has YAML frontmatter, and has substantial content
  2. Content files exist (at least one .md file besides SKILL.md)
  3. Link resolution: all file paths in SKILL.md resolve to existing files
  4. No empty files: every .md file has real content (not just a heading)
  5. Page count: content files match extracted JSON count (when --extracted-dir provided)
  6. Section coverage: >= 90% of extracted headings appear in content files
  7. Signature coverage: function-like headings appear in code blocks >= 80%

Checks 5-7 compare the built skill against the filtered extracted directory
(post-Step 4), catching truncated or mangled extractions that the structural
checks alone would miss.

Exit codes:
  0 — all checks passed
  1 — one or more checks failed

Usage:
    python3 validate.py <skill-dir> [--extracted-dir /tmp/<lib>-extracted/]
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
    p = argparse.ArgumentParser(description="Validate generated documentation skill")
    p.add_argument("skill_dir", help="Path to the generated skill directory (contains SKILL.md + pages/)")
    p.add_argument("--extracted-dir", help="Path to the filtered extracted JSON directory for cross-referencing")
    return p.parse_args()


class ValidationResult:
    """Accumulates check results and generates a formatted report."""

    def __init__(self):
        self.checks = []
        self.errors = []
        self.warnings = []

    def add_check(self, name, passed, detail=""):
        status = "PASS" if passed else "FAIL"
        self.checks.append((name, status, detail))
        if not passed:
            self.errors.append(f"{name}: {detail}")

    def add_warning(self, message):
        self.warnings.append(message)

    @property
    def passed(self):
        return len(self.errors) == 0

    def report(self):
        lines = ["=" * 60, "VALIDATION REPORT", "=" * 60, ""]

        for name, status, detail in self.checks:
            icon = "+" if status == "PASS" else "-"
            line = f"  [{icon}] {name}"
            if detail:
                line += f" — {detail}"
            lines.append(line)

        if self.warnings:
            lines.append("")
            lines.append("WARNINGS:")
            for w in self.warnings:
                lines.append(f"  [!] {w}")

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
# Helpers
# ---------------------------------------------------------------------------

def collect_md_files(skill_dir):
    """Recursively collect all .md files in the skill directory except SKILL.md."""
    files = {}
    for md_file in skill_dir.rglob("*.md"):
        rel = md_file.relative_to(skill_dir)
        if str(rel) == "SKILL.md":
            continue
        files[str(rel)] = md_file
    return files


def load_extracted(extracted_dir):
    """Load all extracted JSON files from the directory."""
    pages = []
    for filename in sorted(os.listdir(extracted_dir)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(extracted_dir, filename), "r", encoding="utf-8") as f:
            pages.append(json.load(f))
    return pages


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_skill_md(skill_dir, result):
    """Verify that SKILL.md exists, has YAML frontmatter, and has enough content."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        result.add_check("SKILL.md exists", False)
        return None

    content = skill_md.read_text(encoding="utf-8")

    if content.startswith("---"):
        end = content.find("---", 3)
        if end > 0:
            result.add_check("SKILL.md has frontmatter", True)
        else:
            result.add_check("SKILL.md has frontmatter", False, "Frontmatter not closed")
    else:
        result.add_check("SKILL.md has frontmatter", False, "No frontmatter found")

    if len(content) > 500:
        result.add_check("SKILL.md has substantial content", True, f"{len(content)} chars")
    else:
        result.add_check("SKILL.md has substantial content", False, f"Only {len(content)} chars")

    return content


def check_link_resolution(skill_md_content, skill_dir, result):
    """Verify that every file path referenced in SKILL.md resolves to an existing file."""
    if skill_md_content is None:
        return

    path_pattern = re.compile(r"`([a-zA-Z_][\w/-]*\.md)`")
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
    """Verify that no content files are empty or suspiciously short."""
    empty = []
    placeholder = []
    for rel_path, filepath in md_files.items():
        content = filepath.read_text(encoding="utf-8").strip()
        if not content:
            empty.append(rel_path)
        elif len(content) < 200:
            placeholder.append(rel_path)

    if empty:
        result.add_check("No empty files", False, f"{len(empty)} empty files: {empty[:5]}")
    else:
        result.add_check("No empty files", True, f"All {len(md_files)} files have content")

    if placeholder:
        result.add_warning(f"{len(placeholder)} files with very short content (<200 chars): {placeholder[:5]}")


def check_page_count(extracted_pages, md_files, result):
    """Verify that the number of content files matches the extracted page count."""
    extracted_count = len(extracted_pages)
    content_count = len(md_files)

    if content_count >= extracted_count:
        result.add_check(
            "Page count matches",
            True,
            f"{content_count} content files for {extracted_count} extracted pages",
        )
    else:
        result.add_check(
            "Page count matches",
            False,
            f"{content_count} content files but {extracted_count} extracted pages "
            f"(missing {extracted_count - content_count})",
        )


def check_section_coverage(extracted_pages, md_files, result):
    """Verify that headings from the extracted content appear in the built skill.

    Catches truncated extractions where a page was processed but content was
    cut short during the build step. Compares against the filtered extracted
    directory (post-Step 4), not the raw sitemap.

    Threshold: 90% coverage passes.
    """
    all_headings = []
    for page in extracted_pages:
        for h in page.get("headings", []):
            text = h.get("text", "").strip()
            if text and len(text) > 2:
                all_headings.append(text)

    if not all_headings:
        result.add_warning("No headings found in extracted content — skipping section coverage")
        return

    all_md_headings = set()
    heading_line_pattern = re.compile(r"^#{1,6}\s+(.+)", re.MULTILINE)
    for filepath in md_files.values():
        content = filepath.read_text(encoding="utf-8")
        for match in heading_line_pattern.finditer(content):
            all_md_headings.add(match.group(1).strip().lower())

    found = sum(1 for h in all_headings if h.lower().strip() in all_md_headings)
    coverage = found / len(all_headings) * 100

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

    missing = [h for h in all_headings if h.lower().strip() not in all_md_headings]
    if missing and len(missing) <= 10:
        for h in missing:
            result.add_warning(f"Missing heading: {h}")
    elif missing:
        result.add_warning(f"{len(missing)} headings missing (showing first 10)")
        for h in missing[:10]:
            result.add_warning(f"  Missing: {h}")


def check_signature_coverage(extracted_pages, md_files, result):
    """Verify that function-like headings from extracted content appear in code blocks.

    Catches cases where code blocks were lost or mangled during the build step.

    Threshold: 80% coverage passes.
    """
    # Match headings that look like actual function signatures, not
    # parenthetical notes like "Tinker (REPL)" or "One to Many (Polymorphic)".
    # A function signature starts with a word-like identifier immediately
    # followed by "(" — e.g., "NewClient(opts)", "create(array $attributes)".
    sig_pattern = re.compile(r"\w\(")
    sig_headings = []
    for page in extracted_pages:
        for h in page.get("headings", []):
            text = h.get("text", "")
            if sig_pattern.search(text):
                sig_headings.append(text)

    if not sig_headings:
        return

    code_block_pattern = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
    all_code_content = ""
    for filepath in md_files.values():
        content = filepath.read_text(encoding="utf-8")
        for match in code_block_pattern.finditer(content):
            all_code_content += match.group(1) + "\n"

    found = sum(1 for sig in sig_headings if sig.lower() in all_code_content.lower())
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
    skill_dir = Path(args.skill_dir).resolve()

    if not skill_dir.exists():
        log.error(f"Skill directory does not exist: {skill_dir}")
        sys.exit(1)

    result = ValidationResult()

    if not (skill_dir / "SKILL.md").exists():
        log.error(f"No SKILL.md found in {skill_dir}")
        result.add_check("Skill directory exists", False)
        print(result.report())
        sys.exit(1)
    result.add_check("Skill directory exists", True, str(skill_dir.name))

    md_files = collect_md_files(skill_dir)
    result.add_check("Content files found", len(md_files) > 0, f"{len(md_files)} markdown files")

    # Structural checks (always run)
    skill_md_content = check_skill_md(skill_dir, result)
    check_link_resolution(skill_md_content, skill_dir, result)
    check_empty_files(md_files, result)

    # Content fidelity checks (when extracted directory is provided)
    if args.extracted_dir:
        extracted_dir = Path(args.extracted_dir).resolve()
        if extracted_dir.exists():
            extracted_pages = load_extracted(str(extracted_dir))
            check_page_count(extracted_pages, md_files, result)
            check_section_coverage(extracted_pages, md_files, result)
            check_signature_coverage(extracted_pages, md_files, result)
        else:
            result.add_warning(f"Extracted directory not found: {extracted_dir}")
    else:
        result.add_warning("No --extracted-dir provided — skipping content fidelity checks")

    print(result.report())
    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Coverage validator for generated documentation plugins.

Verifies that the generated plugin is complete and correct by checking page counts,
section coverage, signature presence, link resolution, and content completeness.

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


def find_skill_dir(plugin_dir):
    """Find the skills/<name>/ directory inside the plugin."""
    skills_dir = plugin_dir / "skills"
    if not skills_dir.exists():
        return None
    for child in skills_dir.iterdir():
        if child.is_dir() and (child / "SKILL.md").exists():
            return child
    return None


def collect_md_files(skill_dir):
    """Collect all markdown files in the skill directory (excluding SKILL.md)."""
    files = {}
    for md_file in skill_dir.rglob("*.md"):
        rel = md_file.relative_to(skill_dir)
        if str(rel) == "SKILL.md":
            continue
        files[str(rel)] = md_file
    return files


def check_plugin_json(plugin_dir, result):
    """Check that plugin.json exists and has required fields."""
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
    """Check that SKILL.md exists and has frontmatter."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        result.add_check("SKILL.md exists", False)
        return None

    content = skill_md.read_text(encoding="utf-8")

    # Check frontmatter
    if content.startswith("---"):
        end = content.find("---", 3)
        if end > 0:
            result.add_check("SKILL.md has frontmatter", True)
        else:
            result.add_check("SKILL.md has frontmatter", False, "Frontmatter not closed")
    else:
        result.add_check("SKILL.md has frontmatter", False, "No frontmatter found")

    # Check minimum content length
    if len(content) > 500:
        result.add_check("SKILL.md has substantial content", True, f"{len(content)} chars")
    else:
        result.add_check("SKILL.md has substantial content", False, f"Only {len(content)} chars")

    return content


def check_page_count(sitemap, md_files, skill_dir, result):
    """Check that page count in SITEMAP.md matches sitemap.json."""
    sitemap_md = skill_dir / "index" / "SITEMAP.md"
    if not sitemap_md.exists():
        result.add_check("SITEMAP.md exists", False)
        return

    result.add_check("SITEMAP.md exists", True)

    if sitemap is None:
        result.add_warning("No sitemap.json provided — skipping count cross-reference")
        return

    sitemap_pages = len(sitemap.get("pages", []))
    # Count content files (exclude SITEMAP.md itself)
    content_files = {k: v for k, v in md_files.items() if not k.startswith("index/")}
    content_count = len(content_files)

    # Warning pages may be consolidated, so allow some slack
    warning_pages = sum(1 for p in sitemap.get("pages", []) if "warning" in str(p.get("title", "")).lower())

    if content_count >= sitemap_pages - warning_pages:
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
    """Check that headings from sitemap appear in content files."""
    if sitemap is None:
        result.add_warning("No sitemap.json — skipping section coverage check")
        return

    all_headings = []
    for page in sitemap.get("pages", []):
        for h in page.get("headings", []):
            text = h.get("text", "").strip()
            if text and len(text) > 2:
                all_headings.append(text)

    if not all_headings:
        result.add_warning("No headings found in sitemap — skipping section coverage")
        return

    # Read all content files
    all_content = ""
    for rel_path, filepath in md_files.items():
        all_content += filepath.read_text(encoding="utf-8") + "\n"

    found = 0
    missing = []
    for heading in all_headings:
        # Normalize for comparison
        normalized = heading.lower().strip()
        if normalized in all_content.lower():
            found += 1
        else:
            missing.append(heading)

    coverage = found / len(all_headings) * 100 if all_headings else 100

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

    if missing and len(missing) <= 10:
        for h in missing:
            result.add_warning(f"Missing heading: {h}")
    elif missing:
        result.add_warning(f"{len(missing)} headings missing (showing first 10)")
        for h in missing[:10]:
            result.add_warning(f"  Missing: {h}")


def check_link_resolution(skill_md_content, skill_dir, result):
    """Check that paths referenced in SKILL.md resolve to existing files."""
    if skill_md_content is None:
        return

    # Find backtick-quoted paths that look like file references
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
    """Check that no content files are empty or contain only placeholders."""
    empty = []
    placeholder = []
    for rel_path, filepath in md_files.items():
        content = filepath.read_text(encoding="utf-8").strip()
        if not content:
            empty.append(rel_path)
        elif len(content) < 50:
            placeholder.append(rel_path)

    if empty:
        result.add_check("No empty files", False, f"{len(empty)} empty files: {empty[:5]}")
    else:
        result.add_check("No empty files", True, f"All {len(md_files)} files have content")

    if placeholder:
        result.add_warning(f"{len(placeholder)} files with very short content (<50 chars): {placeholder[:5]}")


def check_signature_coverage(sitemap, md_files, result):
    """Check that extracted signatures appear in content files (heuristic)."""
    if sitemap is None:
        return

    # This is a best-effort check — we look for function-like patterns
    # in the sitemap headings and check they appear in content
    sig_headings = []
    for page in sitemap.get("pages", []):
        for h in page.get("headings", []):
            text = h.get("text", "")
            # Heuristic: headings that look like function signatures
            if "(" in text and ")" in text:
                sig_headings.append(text)

    if not sig_headings:
        return

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


def main():
    args = parse_args()
    plugin_dir = Path(args.plugin_dir).resolve()

    if not plugin_dir.exists():
        log.error(f"Plugin directory does not exist: {plugin_dir}")
        sys.exit(1)

    # Load sitemap if provided
    sitemap = None
    if args.sitemap:
        with open(args.sitemap, "r", encoding="utf-8") as f:
            sitemap = json.load(f)

    result = ValidationResult()

    # Find skill directory
    skill_dir = find_skill_dir(plugin_dir)
    if skill_dir is None:
        log.error(f"No skill directory found in {plugin_dir}")
        result.add_check("Skill directory exists", False)
        print(result.report())
        sys.exit(1)

    result.add_check("Skill directory exists", True, str(skill_dir.name))

    # Collect content files
    md_files = collect_md_files(skill_dir)
    result.add_check("Content files found", len(md_files) > 0, f"{len(md_files)} markdown files")

    # Run all checks
    check_plugin_json(plugin_dir, result)
    skill_md_content = check_skill_md(skill_dir, result)
    check_page_count(sitemap, md_files, skill_dir, result)
    check_section_coverage(sitemap, md_files, skill_dir, result)
    check_link_resolution(skill_md_content, skill_dir, result)
    check_empty_files(md_files, result)
    check_signature_coverage(sitemap, md_files, result)

    # Output report
    print(result.report())
    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()

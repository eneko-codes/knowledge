---
name: doc-indexer
description: >
  Use when asked to index documentation, generate a docs plugin, crawl documentation,
  index library docs, create a documentation plugin, or build docs for a library.
  Trigger phrases: "index documentation", "generate docs plugin", "crawl documentation",
  "index library docs", "create docs plugin", "build docs for".
---

# Doc Indexer

Generate a complete hierarchical documentation plugin by crawling an external documentation site.

## Prerequisites

Before first use, run the setup script to create the Python virtual environment:

```bash
cd {PLUGIN_ROOT}/scripts
bash setup.sh
```

This installs Playwright, playwright-stealth, BeautifulSoup4, html2text, and downloads Chromium (~200MB one-time download). All subsequent commands assume the venv is activated.

## Workflow

Follow these steps in order. Do not skip steps. Run each script and verify its output before proceeding.

### Step 1: Gather Parameters

Ask the user for:
- **Library name** — short identifier (e.g., `sqlc`, `goose`, `laravel`)
- **Documentation root URL** — the starting page to crawl (e.g., `https://docs.sqlc.dev/en/stable/`)
- **Path prefix restriction** — whether to restrict crawling to the URL path prefix (default: yes)
- **Version label** — documentation version if applicable (default: `latest`)
- **Scope** — where to install the plugin (default: `user`)

**Versioning:** When the user specifies a version other than `latest`, the generated plugin includes the version in its name. For example, `laravel` version `11` produces plugin `laravel-11-docs` with skill `laravel-11-docs`. This allows multiple versions to coexist — the user can have `laravel-11-docs` and `laravel-12-docs` installed simultaneously. Always ask about version when the documentation URL contains a version indicator (e.g., `/v2/`, `/11.x/`, `/en/stable/`).

**Scope:** The plugin can be installed at two scopes:

| Scope | Output directory | Who can use it | Committed to git? |
|-------|-----------------|----------------|:--:|
| **project** | `<project-root>/.claude/plugins/<name>-docs/` | Whole team | Yes — everyone on the project gets the docs |
| **user** | `~/.claude/plugins/<name>-docs/` | Just you | No — available in all your projects |

Recommend **project** scope when the docs are relevant to the current project (e.g., the framework the project uses). This way the whole team benefits. Recommend **user** scope for general-purpose libraries the user works with across multiple projects.

### Step 2: Crawl Documentation Pages

Run the crawler to discover all documentation pages:

```bash
cd {PLUGIN_ROOT}/scripts
source .venv/bin/activate
python3 crawl.py <root-url> \
  --output /tmp/<library>-sitemap.json \
  --same-path-prefix \
  --delay 1.5
```

**Verify output:**
- Open `/tmp/<library>-sitemap.json`
- Check `stats.total_fetched` — confirm the page count is reasonable
- Check `failed` array — investigate any failures
- Report the crawl summary to the user: total pages discovered, fetched, failed

If too many pages failed or the count seems wrong, adjust parameters and re-crawl.

### Step 3: Extract Page Content

Run the extractor on the sitemap:

```bash
python3 extract.py /tmp/<library>-sitemap.json \
  --output /tmp/<library>-extracted/ \
  --delay 1.0
```

**Verify output:**
- Check `/tmp/<library>-extracted/` contains one JSON file per crawled page
- Report extraction summary to the user: file count, category breakdown

### Step 4: Review and Filter Content

This is the most important step. Read the extracted JSON files and curate the content before building the plugin.

**4a. Summarize what was found.**

Read the title, category, and first ~200 characters of each extracted JSON file. Present a summary to the user:

```
Extracted 287 pages from Laravel 12 documentation.

Topics detected (by page count):
 1. Eloquent ORM (42 pages)
 2. Routing (18 pages)
 3. Authentication (24 pages)
 4. Blade Templates (15 pages)
 5. Validation (12 pages)
 6. Queues & Jobs (16 pages)
 7. Mail (11 pages)
 8. Broadcasting (9 pages)
 9. Testing (21 pages)
10. Cashier / Billing (14 pages)
11. Other / General (75 pages)
12. Blog posts (20 pages)
13. Archive/listing pages (10 pages)

Which topics do you want to include? (e.g., "1, 2, 3, 5, 9" or "all")
```

Group pages by topic/module by analyzing their URL paths and titles. Present as a numbered list so the user can pick by number.

**4b. Wait for the user's response.** Do not proceed until the user confirms which topics to include.

**4c. Apply quality filter.**

After the user selects topics (or for small sites), review each remaining page and decide KEEP or SKIP.

**KEEP** pages that contain:
- API reference (function signatures, parameters, return types)
- Configuration reference (settings, options, formats)
- Code examples showing how to use the library
- Installation or setup instructions
- Migration guides or upgrade paths
- Conceptual explanations of library-specific features

**SKIP** pages that contain:
- Blog posts or news articles
- Archive or category listing pages (just lists of links to other pages)
- Contributor or community guidelines
- Release notes or changelogs
- "About the project" or team pages
- Pages with less than 100 words of actual content
- Duplicate content (same information already in a KEEP page)

**4d. Present the filter results to the user.**

```
After filtering: keeping 193 of 287 pages.

Skipped 94 pages:
- 20 blog posts
- 10 archive/listing pages
- 14 billing pages (user excluded)
- 50 other low-value pages

Proceed with building the plugin? (yes / show skipped pages / adjust)
```

The user can review skipped pages and override if needed. Only proceed when the user confirms.

**4e. Delete skipped JSON files** from `/tmp/<library>-extracted/` so `build_plugin.py` only processes the kept pages.

### Step 5: Build the Plugin

Generate the complete plugin from the filtered content. The `--output-dir` depends on the scope chosen in Step 1:

**Project scope:**
```bash
python3 build_plugin.py <library-name> /tmp/<library>-extracted/ \
  --source-url <root-url> \
  --version <version-label> \
  --output-dir <project-root>/.claude/plugins/<name>-docs
```

**User scope:**
```bash
python3 build_plugin.py <library-name> /tmp/<library>-extracted/ \
  --source-url <root-url> \
  --version <version-label> \
  --output-dir ~/.claude/plugins/<name>-docs
```

Replace `<name>-docs` with the versioned plugin name (e.g., `laravel-11-docs` or `goose-docs`).

**Verify output:**
- Check the generated directory structure has: `.claude-plugin/plugin.json`, `skills/<name>-docs/SKILL.md`, subdirectories for content
- Open the generated `SKILL.md` — confirm it lists every sub-file
- Spot-check a few sub-files for content completeness

### Step 6: Validate Coverage

Run the validator to ensure nothing was lost:

```bash
python3 validate.py <output-dir> \
  --sitemap /tmp/<library>-sitemap.json
```

**Interpret results:**
- Exit code 0 = all checks pass
- Exit code 1 = gaps found — read the report and fix issues
- Common issues: missing pages, empty files, broken internal links

If validation fails, fix the identified gaps and re-validate.

### Step 7: Install and Finalize

After building and validating, install the plugin at the chosen scope.

**Project scope** (shared with team via git):
```bash
claude /plugin install <name>-docs --scope project
```
The plugin directory at `<project-root>/.claude/plugins/<name>-docs/` should be committed to git so teammates get it automatically.

**User scope** (available across all your projects):
```bash
claude /plugin install <name>-docs --scope user
```

Report the final results to the user:
- Total pages indexed (after filtering)
- Pages skipped and why
- Plugin name (including version if applicable)
- Plugin directory location
- Scope and what that means for visibility

## Script Reference

All scripts are in `{PLUGIN_ROOT}/scripts/`:

| Script | Purpose | Key Arguments |
|--------|---------|---------------|
| `crawl.py` | Discover all doc pages via BFS crawl | `<root-url>` `--output` `--max-depth` `--delay` `--same-path-prefix` |
| `extract.py` | Fetch and convert page content to markdown | `<sitemap.json>` `--output` `--delay` |
| `build_plugin.py` | Assemble plugin from extracted content | `<library-name>` `<extracted-dir>` `--version` `--source-url` `--output-dir` |
| `validate.py` | Verify plugin completeness | `<plugin-dir>` `--sitemap` |
| `setup.sh` | Create venv and install dependencies | (none) |

Templates are in `{PLUGIN_ROOT}/templates/`:

| Template | Used By | Purpose |
|----------|---------|---------|
| `SKILL_template.md` | `build_plugin.py` | Generated SKILL.md for the docs plugin |
| `plugin_json_template.json` | `build_plugin.py` | Generated plugin.json |
| `section_template.md` | `build_plugin.py` | Individual content sub-files |

## Critical Rules

1. **Verbatim extraction.** Never paraphrase, summarize, or rewrite documentation content. Copy it exactly as it appears on the source site. Code blocks must be preserved character-for-character.

2. **Filter before building.** Always run the review and filter step (Step 4) before building. Never build from unfiltered extracted content — noise degrades the plugin's usefulness.

3. **User decides what to include.** Present the topic list and filter results to the user. Do not silently skip pages — the user might want content you would have filtered out.

4. **Validate before declaring done.** Always run `validate.py` after `build_plugin.py`. Do not skip this step. Fix all reported gaps.

5. **Respect rate limits.** Use the default delay (1.5s) unless the user explicitly asks for faster crawling. Do not reduce delay below 0.5s.

6. **Report, don't assume.** After each step, report results to the user. Do not silently skip failed pages or empty extractions. The user decides how to handle issues.

7. **One browser instance.** Both `crawl.py` and `extract.py` use Playwright with stealth patches. They manage their own browser lifecycle — do not run them concurrently.

---
name: doc-scanner
description: >
  Use when asked to scan documentation, generate a docs plugin, crawl documentation,
  index library docs, create a documentation plugin, or build docs for a library.
  Trigger phrases: "scan documentation", "generate docs plugin", "crawl documentation",
  "index library docs", "create docs plugin", "build docs for".
---

# Doc Scanner

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
- **Library name** — short identifier (e.g., `sqlc`, `goose`, `htmx`)
- **Documentation root URL** — the starting page to crawl (e.g., `https://docs.sqlc.dev/en/stable/`)
- **Path prefix restriction** — whether to restrict crawling to the URL path prefix (default: yes)
- **Version label** — documentation version if applicable (default: `latest`)

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
- Spot-check 3-5 files: confirm markdown content is complete, code blocks are preserved
- Check category assignments make sense (api-reference, conceptual, tutorial, example)
- Report extraction summary to the user: file count, category breakdown

If content looks incomplete or categories are wrong, the user may ask you to manually adjust individual JSON files before proceeding.

### Step 4: Build the Plugin

Generate the complete plugin from extracted content:

```bash
python3 build_plugin.py <library-name> /tmp/<library>-extracted/ \
  --source-url <root-url> \
  --version <version-label> \
  --output-dir <monorepo-root>/plugins/docs-<library>
```

The output directory defaults to `../../plugins/docs-<library>` relative to the scripts directory, which places it alongside other plugins in the monorepo.

**Verify output:**
- Check the generated directory structure has: `.claude-plugin/plugin.json`, `skills/<library>-docs/SKILL.md`, subdirectories for content
- Open the generated `SKILL.md` — confirm it lists every sub-file
- Spot-check a few sub-files for content completeness

### Step 5: Validate Coverage

Run the validator to ensure nothing was lost:

```bash
python3 validate.py <monorepo-root>/plugins/docs-<library>/ \
  --sitemap /tmp/<library>-sitemap.json
```

**Interpret results:**
- Exit code 0 = all checks pass
- Exit code 1 = gaps found — read the report and fix issues
- Common issues: missing pages, empty files, broken internal links

If validation fails, fix the identified gaps (re-run extract for missing pages, manually add missing sections) and re-validate.

### Step 6: Register and Finalize

Add the new plugin to the root `marketplace.json`:

```json
{
  "name": "docs-<library>",
  "description": "<Library> documentation reference",
  "version": "1.0.0",
  "author": { "name": "Eneko" },
  "source": "./plugins/docs-<library>",
  "category": "development",
  "keywords": ["documentation", "<library>"]
}
```

Report the final results to the user:
- Total pages indexed
- Plugin directory location
- Any warnings or manual fixes applied
- Suggest testing with: `claude /plugin install docs-<library>@supercharge`

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

2. **Completeness over brevity.** Every page in the sitemap must appear in the generated plugin. Every heading, every code example, every function signature. Missing content defeats the purpose.

3. **Validate before declaring done.** Always run `validate.py` after `build_plugin.py`. Do not skip this step. Fix all reported gaps.

4. **Respect rate limits.** Use the default delay (1.5s) unless the user explicitly asks for faster crawling. Do not reduce delay below 0.5s.

5. **Report, don't assume.** After each step, report results to the user. Do not silently skip failed pages or empty extractions. The user decides how to handle issues.

6. **One browser instance.** Both `crawl.py` and `extract.py` use Playwright with stealth patches. They manage their own browser lifecycle — do not run them concurrently.

---
name: doc-indexer
description: >
  Use when asked to index documentation, generate a docs plugin, crawl documentation,
  index library docs, create a documentation plugin, or build docs for a library.
  Trigger phrases: "index documentation", "generate docs plugin", "crawl documentation",
  "index library docs", "create docs plugin", "build docs for".
---

# Doc Indexer

Generate a complete documentation plugin by crawling an external documentation site.

## Prerequisites

Before first use, run the setup script to create the Python virtual environment:

```bash
cd {PLUGIN_ROOT}/scripts
bash setup.sh
```

This installs Playwright, playwright-stealth, BeautifulSoup4, markdownify, Pygments, and downloads Chromium (~200MB one-time download). All subsequent commands assume the venv is activated.

## Workflow

Follow these steps in order. Do not skip steps. Run each script and verify its output before proceeding.

### Step 1: Gather Parameters

Collect the following. The user may provide all of them upfront, some, or none — fill in what's missing.

- **Library name** — short identifier (e.g., `react`, `java`, `laravel`)
- **Documentation root URL** — the starting page to crawl (e.g., `https://docs.sqlc.dev/en/stable/`)
- **Path prefix restriction** — whether to restrict crawling to the URL path prefix (default: yes)
- **Version label** — documentation version if applicable (default: `latest`)
- **Scope** — where to install the plugin (default: `user`)

**If the user doesn't provide a URL** (e.g., "index go docs", "index laravel docs"), use web search to find the official documentation site. Search for `<library> official documentation site` and pick the official docs URL. Confirm with the user before proceeding:

```
I found the official Go documentation at https://go.dev/doc/
Is this the right URL? Should I restrict crawling to this path?
```

Do not guess or fabricate URLs. Always search and confirm.

**Versioning:** When the user specifies a version other than `latest`, the generated plugin includes the version in its name. For example, `laravel` version `11` produces plugin `laravel-11-docs` with skill `laravel-11-docs`. This allows multiple versions to coexist — the user can have `laravel-11-docs` and `laravel-12-docs` installed simultaneously. Always ask about version when the documentation URL contains a version indicator (e.g., `/v2/`, `/11.x/`, `/en/stable/`).

**Scope:** The plugin can be installed at two scopes:

| Scope       | Output directory                              | Who can use it |              Committed to git?              |
| ----------- | --------------------------------------------- | -------------- | :-----------------------------------------: |
| **project** | `<project-root>/.claude/plugins/<name>-docs/` | Whole team     | Yes — everyone on the project gets the docs |
| **user**    | `~/.claude/plugins/<name>-docs/`              | Just you       |     No — available in all your projects     |

Recommend **project** scope when the docs are relevant to the current project (e.g., the framework the project uses). This way the whole team benefits. Recommend **user** scope for general-purpose libraries the user works with across multiple projects.

### Step 2: Crawl Documentation Pages

Run the crawler to discover all documentation pages:

```bash
cd {PLUGIN_ROOT}/scripts
source .venv/bin/activate
python3 crawl.py <root-url> \
  --output /tmp/<library>-sitemap.json \
  --same-path-prefix
```

**Verify output:**

- Open `/tmp/<library>-sitemap.json`
- Check `stats.total_fetched` — confirm the page count is reasonable
- Check `failed` array — investigate any failures
- Check `/tmp/<library>-html/` — confirm HTML files were saved (one per page)
- Report the crawl summary to the user: total pages discovered, fetched, failed

If too many pages failed or the count seems wrong, adjust parameters and re-crawl.

### Step 3: Extract Page Content

Run the extractor on the saved HTML:

```bash
python3 extract.py /tmp/<library>-sitemap.json \
  --output /tmp/<library>-extracted/
```

This reads the HTML files saved by crawl.py — no browser or network needed.

Add `--guess-languages` if the site has many unannotated code blocks — this uses Pygments to guess languages for bare ``` blocks. Only use when needed, as it may misclassify some blocks.

**Verify output:**

- Check `/tmp/<library>-extracted/` contains one JSON file per crawled page
- Report extraction summary to the user: file count

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

After the user selects topics, review each remaining page and decide KEEP or SKIP.

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

**4c-extra. Flag extraction problems.**

Check each page's extracted JSON for these issues:

- `"used_fallback_selector": true` — the extractor couldn't find the content area and fell back to `<body>`. The markdown likely contains navigation/sidebar noise. Tell the user: _"This page may not have extracted cleanly — it used a fallback selector. Keep, skip, or re-extract?"_
- Markdown looks garbled (broken tables, truncated code blocks, navigation text mixed with content) — tell the user: _"This page's markdown looks malformed. Here's an excerpt: [first 200 chars]. Keep, skip, or flag for manual review?"_
- The `category` field in the extracted JSON is metadata only — it does not affect directory placement. All files go into a flat `pages/` directory.

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

Replace `<name>-docs` with the versioned plugin name (e.g., `laravel-11-docs` or `react-docs`).

**Verify output:**

- Check the generated directory structure has: `.claude-plugin/plugin.json`, `skills/<name>-docs/SKILL.md`, `skills/<name>-docs/pages/` with content files
- Open the generated `SKILL.md` — confirm it lists every sub-file with H2 sub-topic descriptions
- If re-running after a partial extraction, extract.py automatically skips already-extracted pages (use `--force` to re-extract all)
- Spot-check a few sub-files for content completeness

### Step 6: Validate Structure

Run the validator to check the plugin's structural integrity:

```bash
python3 validate.py <output-dir>
```

Do NOT pass `--sitemap` here. The original sitemap contains all crawled pages, but we intentionally filtered pages in Step 4. Passing the sitemap would cause the page count check to fail.

Without `--sitemap`, the validator checks:

- plugin.json exists with required fields
- SKILL.md has frontmatter and substantial content
- All file paths in SKILL.md resolve to existing files
- No empty content files

**Interpret results:**

- Exit code 0 = all checks pass
- Exit code 1 = gaps found — read the report and fix issues

If validation fails, fix the identified gaps and re-validate.

### Step 6b: Verify Accuracy Against Live Pages

Run the accuracy verifier to compare EVERY generated file against its live source page:

```bash
python3 verify.py <output-dir> --screenshot-dir /tmp/<library>-screenshots
```

This re-visits the original URL of every content file and compares key signals:

- **Title match** — does the markdown title match the live page's H1?
- **Heading count** — does the markdown have at least 40% of the live page's headings?
- **Code block count** — does the markdown have at least 70% of the live page's code blocks?
- **Content length** — is the markdown at least 40% the length of the live page content?

When `--screenshot-dir` is provided, mismatched pages get a screenshot saved automatically. Use the Read tool to view screenshots of mismatched pages — this shows what the page actually looks like versus what was extracted.

**Interpret results:**

- Exit code 0 = all files verified
- Exit code 1 = mismatches found — review the report

For each mismatch, present it to the user:

```
Mismatch in pages/configuration.md:
- Code blocks: markdown has 1 but live page has 3 (33% captured)
- Screenshot saved at /tmp/sqlc-screenshots/api_configuration.md.png

Options:
1. Keep as-is (partial content is still useful)
2. Skip this page (remove from plugin)
3. Re-extract this specific page
```

Do not proceed to Step 7 until all mismatches are resolved or accepted by the user.

### Step 7: Install and Finalize

After building and validating, register the plugin by adding it to the appropriate settings.json file. You cannot use `claude /plugin install` from inside a Claude Code session (nested sessions are not allowed), so you must edit the settings file directly.

**User scope** — add to `~/.claude/settings.json`:

Read the file, then add `"<name>-docs": true` to the `enabledPlugins` object. If `enabledPlugins` doesn't exist, create it.

**Project scope** — add to `<project-root>/.claude/settings.json`:

Read the file (create it if it doesn't exist), then add `"<name>-docs": true` to the `enabledPlugins` object. The plugin directory at `<project-root>/.claude/plugins/<name>-docs/` should be committed to git so teammates get it automatically.

**Important:** If the project has a project-level settings.json that sets other plugins to `false`, the new plugin must be explicitly set to `true` there as well, or it will be implicitly disabled.

Report the final results to the user:

- Total pages indexed (after filtering)
- Pages skipped and why
- Plugin name (including version if applicable)
- Plugin directory location
- Scope and what that means for visibility

**Clean up temporary files** after the user confirms everything looks good:

```bash
rm -f /tmp/<library>-sitemap.json
rm -rf /tmp/<library>-html/
rm -rf /tmp/<library>-extracted/
rm -rf /tmp/<library>-screenshots/
```

Do not clean up until the user has confirmed the plugin is working. They may want to re-extract or re-verify.

After cleaning temp files, ask the user if they also want to reclaim disk space by removing the Python virtual environment (~50MB) and the Chromium browser binary (~200MB). Explain that these are only needed by doc-indexer, and if deleted, `setup.sh` must be re-run before indexing docs again:

```
The doc-indexer environment takes ~250MB of disk space:
- Python venv: {PLUGIN_ROOT}/scripts/.venv/ (~50MB)
- Chromium browser: ~/.cache/ms-playwright/ (~200MB)

These are only used when indexing new documentation. Want me to delete them
to reclaim disk space? You'll need to re-run setup.sh if you index docs again
in the future. (yes/no)
```

If yes:

```bash
rm -rf {PLUGIN_ROOT}/scripts/.venv/
rm -rf ~/.cache/ms-playwright/
```

## Script Reference

All scripts are in `{PLUGIN_ROOT}/scripts/`:

| Script            | Purpose                                      | Key Arguments                                                                |
| ----------------- | -------------------------------------------- | ---------------------------------------------------------------------------- |
| `crawl.py`        | Discover all doc pages via BFS crawl         | `<root-url>` `--output` `--max-depth` `--max-pages` `--delay` `--same-path-prefix` |
| `extract.py`      | Convert saved HTML to structured markdown    | `<sitemap.json>` `--output` `--force` `--guess-languages`                    |
| `build_plugin.py` | Assemble plugin from extracted content       | `<library-name>` `<extracted-dir>` `--version` `--source-url` `--output-dir` |
| `validate.py`     | Verify plugin structural integrity           | `<plugin-dir>`                                                               |
| `verify.py`       | Compare generated content against live pages | `<plugin-dir>` `--delay` `--screenshot-dir`                                  |
| `setup.sh`        | Create venv and install dependencies         | (none)                                                                       |

Templates are in `{PLUGIN_ROOT}/templates/`:

| Template                    | Used By           | Purpose                                |
| --------------------------- | ----------------- | -------------------------------------- |
| `SKILL_template.md`         | `build_plugin.py` | Generated SKILL.md for the docs plugin |
| `plugin_json_template.json` | `build_plugin.py` | Generated plugin.json                  |
| `section_template.md`       | `build_plugin.py` | Individual content sub-files           |

## Critical Rules

1. **Verbatim extraction.** Never paraphrase, summarize, or rewrite documentation content. Copy it exactly as it appears on the source site. Code blocks must be preserved character-for-character.

2. **Never edit extracted content.** During the review step (Step 4), you may DELETE pages (skip them) or RECLASSIFY pages (change category), but never modify the markdown content itself. The content must be exactly what the extractor produced from the original page. If content looks wrong, flag it to the user — do not attempt to fix or improve it.

3. **Flag extraction problems.** If a page's markdown looks garbled (broken tables, navigation text mixed with content, truncated code blocks), tell the user: "This page may not have extracted cleanly — here's what it looks like: [excerpt]. Keep, skip, or re-extract?" Never silently include garbled content.

4. **Filter before building.** Always run the review and filter step (Step 4) before building. Never build from unfiltered extracted content — noise degrades the plugin's usefulness.

5. **User decides what to include.** Present the topic list and filter results to the user. Do not silently skip pages — the user might want content you would have filtered out.

6. **Validate and spot-check.** Always run `validate.py` after `build_plugin.py`, then spot-check 3-5 files for accuracy. Do not skip these steps.

7. **Respect rate limits.** The default delay is 0.5s between requests. If a script starts getting HTTP 429 (Too Many Requests) or 403 errors, re-run with a higher delay: `--delay 2.0`. If errors persist, try `--delay 5.0`. Tell the user what's happening and why you're increasing the delay.

8. **Report, don't assume.** After each step, report results to the user. Do not silently skip failed pages or empty extractions. The user decides how to handle issues.

9. **One browser instance.** Both `crawl.py` and `extract.py` use Playwright with stealth patches. They manage their own browser lifecycle — do not run them concurrently.

---
name: doc-indexer
description: >
  Use when asked to index documentation, generate a docs skill, crawl documentation,
  index library docs, create a documentation skill, or build docs for a library.
  Trigger phrases: "index documentation", "generate docs skill", "crawl documentation",
  "index library docs", "create docs skill", "build docs for", "index docs".
---

# Doc Indexer

Generate a documentation skill by crawling an external documentation site. The generated skill is placed in a `.claude/skills/` directory where Claude Code auto-discovers it — no plugin registration needed.

## Prerequisites

Before first use, ensure the Python virtual environment exists:

```bash
cd {PLUGIN_ROOT}/scripts
```

- **IF** `.venv/` directory exists AND `node_modules/` directory exists → skip setup, activate with `source .venv/bin/activate`
- **IF** either is missing → run `bash setup.sh` (installs Python deps, Chromium ~200MB, Node.js deps). Requires Node.js 18+.

All subsequent commands assume the venv is activated.

## Workflow

Follow these steps in order. Do not skip steps. Run each script and verify its output before proceeding.

### Step 1: Gather Parameters

Collect the following. The user may provide all of them upfront, some, or none — fill in what's missing.

- **Library name** — short identifier (e.g., `react`, `java`, `laravel`)
- **Documentation root URL** — the starting page to crawl (e.g., `https://docs.sqlc.dev/en/stable/`)
- **Path prefix restriction** — whether to restrict crawling to the URL path prefix (default: yes)
- **Version label** — documentation version if applicable (default: `latest`)
- **Scope** — where to save the generated skill (default: `user`)

**Resolving the URL:**

- **IF the user provides a URL** → use it directly.
- **IF the user doesn't provide a URL** (e.g., "index go docs") → use web search to find the official documentation site. Search for `<library> official documentation site`. Do not guess or fabricate URLs. Confirm with the user before proceeding:
  ```
  I found the official Go documentation at https://go.dev/doc/
  Is this the right URL? Should I restrict crawling to this path?
  ```

**Versioning:**

- **IF the URL contains a version indicator** (e.g., `/v2/`, `/11.x/`, `/en/stable/`) → always ask the user which version to label it as.
- **IF the user specifies a version** other than `latest` → include the version in the skill name (e.g., `laravel` version `11` → skill name `laravel-11-docs`). This allows multiple versions to coexist side by side.
- **IF no version indicator** → default to `latest`.

**Scope:**

| Scope       | Output directory                             | Who can use it |              Committed to git?              |
| ----------- | -------------------------------------------- | -------------- | :-----------------------------------------: |
| **project** | `<project-root>/.claude/skills/<name>-docs/` | Whole team     | Yes — everyone on the project gets the docs |
| **user**    | `~/.claude/skills/<name>-docs/`              | Just you       |     No — available in all your projects     |

- **IF the docs are for a framework/library the current project uses** → recommend **project** scope.
- **IF the docs are general-purpose** (used across multiple projects) → recommend **user** scope.

**Gate:** Confirm the output directory with the user before proceeding. Show the resolved path and wait for explicit confirmation. Do not proceed until confirmed.

### Step 1b: Reconnaissance

Run the reconnaissance script to analyze the site before crawling:

```bash
python3 recon.py <root-url> --output /tmp/<library>-recon.json
```

This probes the site with raw HTTP and Playwright to determine:
- Whether the site requires JavaScript rendering (static vs SPA)
- Whether machine-readable page lists exist (llms.txt, sitemap.xml)
- What URL patterns would flood a BFS crawl (versioned pages, tab params)
- Recommended crawl parameters

**After recon completes, present the report to the user:**

```
Recon complete for https://react.dev/reference/react:
- Rendering: SSR hydration (content ratio 1.71)
- Discovery: llms.txt found with 177 pages (no BFS crawl needed)
- No URL noise patterns detected
- Suggested flags: --same-path-prefix

Proceed with these settings?
```

**Decision tree:**

1. **IF `discovery.method == "llms_txt"`** → report to user that BFS can be skipped. Use the saved URL file directly:
   ```bash
   python3 crawl.py --from-urls <urls_file from recon report> --output /tmp/<library>-sitemap.json
   ```
   This fetches only the curated URLs from llms.txt — no BFS crawl needed.

2. **IF `discovery.method == "sitemap_xml"`** → report sitemap URL count. Use `doc_url_count` as `--max-pages` hint.

3. **IF `discovery.method == "bfs_crawl"`** → use `suggested_exclude_patterns` and `suggested_flags` from the recon report as defaults for Step 2.

4. **IF `suggested_exclude_patterns` is non-empty** → pass each as `--exclude-pattern` to crawl.py.

5. **IF `warnings` is non-empty** → report warnings to user before crawling.

### Step 2: Crawl Documentation Pages

Run the crawler to discover all documentation pages:

```bash
cd {PLUGIN_ROOT}/scripts
source .venv/bin/activate
python3 crawl.py <root-url> \
  --output /tmp/<library>-sitemap.json \
  --same-path-prefix
```

**Choosing crawl parameters:**

| Parameter | When to use |
|-----------|-------------|
| `--same-path-prefix` | Default. Keeps crawl under the root URL's path tree. |
| Remove `--same-path-prefix` | When the root URL is an index page that links to pages outside its path (e.g., `pkg.go.dev/std` links to `/fmt`, `/net/http`). |
| `--exclude-pattern <regex>` | When the site has versioned URLs, tab views, or locale duplicates that would flood the crawl. Repeatable. |
| `--max-depth N` | Lower (2-3) for index pages that link to flat package lists. Higher (5-10) for deeply nested doc trees. Default: 10. |
| `--max-pages N` | Safety cap. Set to 2-3x the expected page count for the first crawl attempt. |
| `--delay N` | Increase to 2.0-5.0 if getting HTTP 429/403 errors. Default: 0.5. |

Common `--exclude-pattern` values:

| Pattern | Skips | Example sites |
|---------|-------|---------------|
| `@v?\d` | Versioned package pages (`pkg@v2`, `std@go1.26`) | pkg.go.dev |
| `\?tab=` | Tab views (`?tab=versions`, `?tab=licenses`) | pkg.go.dev |
| `/\d+\.x/` | Versioned doc trees (`/11.x/`, `/12.x/`) | Laravel, many frameworks |
| `/(en\|es\|fr\|de)/` | Locale duplicates | Translated doc sites |
| `/api/` | Auto-generated API pages | Sites with large API refs |

#### After the crawl completes: Evaluate results

Open `/tmp/<library>-sitemap.json` and check `stats`.

**Decision tree:**

1. **IF `total_fetched` is within expected range (e.g., 50-500 for a typical library) AND `total_failed` < 10% of fetched** → crawl is healthy. Report summary to user and proceed to Step 2b.

2. **IF `total_fetched` is much higher than expected (e.g., 5x+)** → likely noise flooding the crawl. Analyze URLs:
   - Sample 20 URLs from the sitemap pages.
   - **IF >50% share a repeating pattern** (versioned URLs like `@v1.2`, query params like `?tab=`, locale prefixes) → identify the pattern, report to user, and re-crawl with `--exclude-pattern`. Example:
     ```
     Crawl found 1100 pages but most are versioned duplicates (e.g., std@go1.26.1,
     std@go1.25.0). I'll re-crawl with --exclude-pattern '@go\d' to filter these.
     ```
   - **IF no clear pattern** → pages may be legitimate. Proceed to Step 2b and let Step 4 filter.

3. **IF `total_fetched` < 10 AND the site is known to have more content** → crawl is too restrictive.
   - Try removing `--same-path-prefix`.
   - **IF still too few** → try increasing `--max-depth`.
   - **IF still too few after 2 attempts** → report to user:
     ```
     The crawler only found N pages after 2 attempts with different parameters.
     This site's structure may not work well with BFS crawling. Options:
     1. Try a different root URL (e.g., the sidebar/index page)
     2. Proceed with what we have
     3. Abort
     ```

4. **IF `total_failed` > 30% of discovered** → site may be blocking the crawler.
   - Re-crawl with `--delay 2.0`.
   - **IF still failing** → try `--delay 5.0`.
   - **IF still failing after 2 delay increases** → report to user that the site appears to be blocking automated access.

**Retry limit:** Maximum 2 re-crawl attempts per issue. After 2 failed attempts, report the problem to the user and ask how to proceed.

### Step 2b: Crawl Sanity Check

Before spending time on extraction, do a quick quality check on the crawl results.

Read 10-15 page entries from the sitemap (spread across the list, not just the first few). For each, check the URL and title.

**Decision tree:**

1. **IF >50% of sampled pages look like duplicates, version variants, or non-doc pages** → the crawl has too much noise. Go back to Step 2 with `--exclude-pattern` or adjusted parameters. Do NOT proceed to extraction.

2. **IF the pages look like legitimate documentation** → proceed to Step 3.

3. **IF unsure** → report the sample to the user and ask:
   ```
   Here's a sample of crawled pages:
   - https://example.com/docs/getting-started (200 OK)
   - https://example.com/docs/api/users (200 OK)
   - https://example.com/docs/v2/getting-started (200 OK) ← possible version duplicate?

   Do these look right, or should I re-crawl with adjusted parameters?
   ```

### Step 3: Extract Page Content

Run the extractor on the saved HTML:

```bash
python3 extract.py /tmp/<library>-sitemap.json \
  --output /tmp/<library>-extracted/
```

This reads the HTML files saved by crawl.py and extracts content using Defuddle — a multi-pass content detection engine with code block standardization. It detects languages from 9+ class/attribute patterns, removes line numbers, strips toolbar/button chrome, and outputs clean markdown directly.

#### After extraction completes: Evaluate results

Check the log output and the `/tmp/<library>-extracted/` directory.

**Decision tree:**

1. **IF extraction succeeded for >90% of pages** → healthy. Report summary (file count, any failures) and proceed to Step 4.

2. **IF 10-50% of pages failed extraction** → partial success. Report failures to user:
   ```
   Extracted 180/200 pages. 20 pages failed (Defuddle timeout or empty result).
   Failed pages: [list first 5 URLs]
   Options:
   1. Proceed with the 180 successful pages
   2. Re-extract failed pages with --force
   3. Investigate specific failures
   ```

3. **IF >50% of pages failed extraction** → fundamental problem. BAIL:
   ```
   Extraction failed on N/M pages. Defuddle can't extract content from this
   site's HTML structure (possibly heavy JS rendering, unusual DOM layout, or
   anti-scraping measures). This site may not be indexable with doc-indexer.
   ```

### Step 4: Review and Filter Content

This is the most important step. Read the extracted JSON files and curate the content before building the skill.

**4a. Summarize what was found.**

Read the title and first ~200 characters of each extracted JSON file. Group pages by topic/module by analyzing URL paths and titles. Present a summary:

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

**4b. Gate:** Wait for the user's response. Do not proceed until the user confirms which topics to include.

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

Check each page's extracted JSON for quality:

- **IF markdown looks garbled** (broken tables, truncated code blocks, navigation text mixed with content) → tell the user: _"This page's markdown looks malformed. Here's an excerpt: [first 200 chars]. Keep, skip, or flag for manual review?"_

**4d. Gate:** Present the filter results to the user.

```
After filtering: keeping 193 of 287 pages.

Skipped 94 pages:
- 20 blog posts
- 10 archive/listing pages
- 14 billing pages (user excluded)
- 50 other low-value pages

Proceed with building the skill? (yes / show skipped pages / adjust)
```

The user can review skipped pages and override if needed. Only proceed when the user confirms.

**4e. Delete skipped JSON files** from `/tmp/<library>-extracted/` so `build_plugin.py` only processes the kept pages.

### Step 5: Build the Skill

Generate the documentation skill from the filtered content. The `--output-dir` depends on the scope chosen in Step 1.

**Project scope:**

```bash
python3 build_plugin.py <library-name> /tmp/<library>-extracted/ \
  --source-url <root-url> \
  --version <version-label> \
  --output-dir <project-root>/.claude/skills/<name>-docs
```

**User scope:**

```bash
python3 build_plugin.py <library-name> /tmp/<library>-extracted/ \
  --source-url <root-url> \
  --version <version-label> \
  --output-dir ~/.claude/skills/<name>-docs
```

Replace `<name>-docs` with the versioned name (e.g., `laravel-11-docs` or `react-docs`).

**Verify output:**

- Check the generated directory structure has: `SKILL.md` and `pages/` with content files.
- Open the generated `SKILL.md` — confirm it lists every sub-file with H2 sub-topic descriptions.
- Spot-check a few sub-files for content completeness.

**IF build fails or output is empty** → check that `/tmp/<library>-extracted/` has files (Step 4e may have deleted too many). If so, go back to Step 4d and restore some files.

### Step 6: Validate Structure

Run the validator to check the skill's structural integrity:

```bash
python3 validate.py <output-dir> --extracted-dir /tmp/<library>-extracted/
```

Pass `--extracted-dir` pointing to the filtered extracted directory (after Step 4e deleted skipped files). This enables content fidelity checks that catch truncated or mangled extractions.

The validator checks:

- SKILL.md has frontmatter and substantial content
- All file paths in SKILL.md resolve to existing files
- No empty content files
- Page count matches extracted files (with `--extracted-dir`)
- Section coverage: >= 90% of extracted headings appear in the built skill
- Signature coverage: function-like headings appear in code blocks >= 80%

**Decision tree:**

- **IF exit code 0** → all checks pass. Proceed to Step 6b.
- **IF exit code 1** → read the report and identify the failure type:
  - **Missing files** (paths in SKILL.md don't resolve) → go back to Step 5 and rebuild.
  - **Low section coverage** (<90% headings) → go back to Step 3 and re-extract with `--force`, then rebuild (Step 5).
  - **Low signature coverage** (<80%) → this is often acceptable for non-API docs. Report to user and ask whether to proceed or re-extract.
  - **Empty content files** → delete the empty files, rebuild (Step 5), re-validate.
  - **After fix** → re-run `validate.py` to confirm. Maximum 2 fix-validate cycles. If still failing, report to user.

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

**Decision tree:**

- **IF exit code 0** → all files verified. Proceed to Step 7.
- **IF exit code 1 with <20% mismatches** → handle each mismatch individually:

  For each mismatch, present it to the user:
  ```
  Mismatch in pages/configuration.md:
  - Code blocks: markdown has 1 but live page has 3 (33% captured)
  - Screenshot saved at /tmp/<library>-screenshots/configuration.md.png

  Options:
  1. Keep as-is (partial content is still useful)
  2. Skip this page (remove from skill)
  3. Re-extract this specific page
  ```

  **IF user chooses option 3 (re-extract):**
  1. Delete the specific JSON file from `/tmp/<library>-extracted/`.
  2. Re-run `extract.py /tmp/<library>-sitemap.json --output /tmp/<library>-extracted/ --force` (--force re-extracts even if output exists).
  3. Rebuild: re-run Step 5.
  4. Re-validate the specific page: re-run Step 6b.

- **IF exit code 1 with >50% mismatches** → systemic extraction problem. BAIL:
  ```
  Over 50% of pages have significant content mismatches compared to the live site.
  This suggests the extraction quality is too low for a reliable skill. The site's
  HTML structure may not work well with Defuddle.
  Options:
  1. Proceed anyway (skill will have partial/incomplete content for many pages)
  2. Abort and clean up
  ```

- **IF exit code 1 with 20-50% mismatches** → mixed results. Report summary to user and let them decide:
  ```
  N of M pages have content mismatches. Here's the breakdown:
  - X pages: missing code blocks
  - Y pages: low content length
  - Z pages: title mismatch

  Options:
  1. Review each mismatch individually
  2. Keep all as-is (accept partial content)
  3. Drop all mismatched pages
  4. Abort
  ```

Do not proceed to Step 7 until all mismatches are resolved or accepted by the user.

### Step 7: Finalize

The generated skill is auto-discovered by Claude Code from its `.claude/skills/` directory — no registration or installation is needed. The user just needs to restart their Claude Code session.

Report the final results to the user:

- Total pages indexed (after filtering)
- Pages skipped and why
- Skill name (including version if applicable)
- Skill directory location
- Scope and what that means for visibility
- Remind the user to restart Claude Code for the skill to be available

**Gate:** Wait for user to confirm the skill is working before cleaning up.

**Clean up temporary files:**

```bash
bash cleanup.sh <library-name>
```

After cleaning temp files, ask the user if they also want to reclaim disk space (~300MB: venv, node_modules, Chromium). These are only needed by doc-indexer — if deleted, `setup.sh` must be re-run before indexing again.

If yes:

```bash
bash teardown.sh
```

## Script Reference

All scripts are in `{PLUGIN_ROOT}/scripts/`:

| Script                 | Purpose                                      | Key Arguments                                                                                          |
| ---------------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `recon.py`             | Analyze site before crawling                 | `<root-url>` `--output` `--timeout`                                                                    |
| `crawl.py`             | Discover all doc pages via BFS crawl         | `<root-url>` `--output` `--max-depth` `--max-pages` `--delay` `--same-path-prefix` `--exclude-pattern` `--from-urls` |
| `extract.py`           | Extract content via Defuddle                 | `<sitemap.json>` `--output` `--force`                                                                  |
| `defuddle_extract.mjs` | Node.js wrapper for Defuddle (called by extract.py) | `<html-file>` `[url]`                                                                           |
| `build_plugin.py`      | Assemble skill from extracted content        | `<library-name>` `<extracted-dir>` `--version` `--source-url` `--output-dir`                           |
| `validate.py`          | Verify skill structural integrity            | `<skill-dir>` `--extracted-dir`                                                                        |
| `verify.py`            | Compare generated content against live pages | `<skill-dir>` `--delay` `--screenshot-dir`                                                             |
| `setup.sh`             | Create venv, install Python + Node.js deps   | (none)                                                                                                 |
| `cleanup.sh`           | Remove temp files after indexing             | `<library-name>`                                                                                       |
| `teardown.sh`          | Remove venv, node_modules, Chromium (~300MB) | (none)                                                                                                 |

Templates are in `{PLUGIN_ROOT}/templates/`:

| Template                    | Used By           | Purpose                                |
| --------------------------- | ----------------- | -------------------------------------- |
| `SKILL_template.md`         | `build_plugin.py` | Generated SKILL.md for the docs skill |
| `section_template.md`       | `build_plugin.py` | Individual content sub-files          |

## Critical Rules

1. **Verbatim extraction.** Never paraphrase, summarize, or rewrite documentation content. Copy it exactly as it appears on the source site. Code blocks must be preserved character-for-character.

2. **Never edit extracted content.** During the review step (Step 4), you may DELETE pages (skip them) but never modify the markdown content itself. The content must be exactly what the extractor produced from the original page. If content looks wrong, flag it to the user — do not attempt to fix or improve it.

3. **Flag extraction problems.** If a page's markdown looks garbled (broken tables, navigation text mixed with content, truncated code blocks), tell the user: "This page may not have extracted cleanly — here's what it looks like: [excerpt]. Keep, skip, or re-extract?" Never silently include garbled content.

4. **Filter before building.** Always run the review and filter step (Step 4) before building. Never build from unfiltered extracted content — noise degrades the skill's usefulness.

5. **User decides what to include.** Present the topic list and filter results to the user. Do not silently skip pages — the user might want content you would have filtered out.

6. **Validate and spot-check.** Always run `validate.py` after `build_plugin.py`, then spot-check 3-5 files for accuracy. Do not skip these steps.

7. **Respect rate limits.** The default delay is 0.5s between requests. If a script starts getting HTTP 429 (Too Many Requests) or 403 errors, re-run with a higher delay: `--delay 2.0`. If errors persist, try `--delay 5.0`. Tell the user what's happening and why you're increasing the delay.

8. **Report, don't assume.** After each step, report results to the user. Do not silently skip failed pages or empty extractions. The user decides how to handle issues.

9. **One browser instance.** `crawl.py` and `verify.py` use Playwright with stealth patches. They manage their own browser lifecycle — do not run them concurrently. `extract.py` does not use a browser — it processes saved HTML files via Defuddle (Node.js).

10. **Never write custom scripts or modify existing scripts.** The provided scripts (`crawl.py`, `extract.py`, `build_plugin.py`, `validate.py`, `verify.py`) are the only tools you use. If a crawl produces bad results, adjust the parameters (`--exclude-pattern`, `--same-path-prefix`, `--max-depth`, `--max-pages`, `--delay`) and re-crawl. If adjusting parameters doesn't work after 2 attempts, report the problem to the user and ask how to proceed — do not write wrapper scripts, custom fetchers, or any other code to work around the issue.

11. **Maximum 2 retries per step.** If a step fails twice with different parameters, stop retrying and escalate to the user. Explain what was tried, what failed, and present options. Do not enter retry loops.

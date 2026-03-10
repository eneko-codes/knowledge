<div align="center">

# knowledge

**Index any documentation locally and use it as a Claude Code skill.**

Crawl a docs site, pick the topics you want, and get a local skill
that Claude navigates directly — no searching, no guessing.

No extra API calls. No latency. Index your own docs in minutes.

[Benefits](#benefits-of-documentation-skills) ·
[Install](#installation) ·
[Index Your Own](#index-your-own-docs)

</div>

---

## Benefits of Documentation Skills

Claude Code can access docs three ways: **WebFetch** fetches pages directly from the web, **MCP servers** (like [Context7](https://github.com/upstash/context7) or [docs-mcp-server](https://github.com/arabold/docs-mcp-server)) expose a search API over pre-indexed docs, and **skills** (this project) give Claude a local file-based index it can navigate directly.

<table>
<tr><th width="33%">WebFetch</th><th width="33%">MCP Doc Servers</th><th width="33%">Skills (this project)</th></tr>
<tr>
<td>

**Direct fetch** — Claude fetches a documentation URL and reads the page content.

- Must know or find the correct URL first
- Gets full page content including navigation and UI noise
- One network request per page
- No setup required

</td>
<td>

**Search API** — Claude sends a query to the MCP server, which returns matching results from pre-indexed docs.

- Results depend on query and indexing quality
- May need multiple search-refine cycles
- Requires running an MCP server
- Token overhead per tool call (schema + protocol)

</td>
<td>

**Local index** — Claude reads SKILL.md which lists every available page, then reads the target file directly.

- Sees all available pages upfront via the index
- Picks the right file from the table of contents
- Two file reads: index + target page
- No network requests, no server to run

</td>
</tr>
</table>

> **Trade-off:** One-time crawl (5-30 min) to generate the skill. Re-crawl when docs update — monthly is usually enough.

---

## Installation

**Add the marketplace** *(one-time)*

```bash
claude /plugin marketplace add https://github.com/eneko-codes/knowledge
```

Then install the doc-indexer plugin:

```bash
claude /plugin install doc-indexer@knowledge
```

That's it. You can now index any documentation site.

---

## Index Your Own Docs

Tell Claude:

```
Index the React docs
```

or with a specific URL:

```
Index the documentation at https://docs.sqlc.dev/en/stable/ for sqlc
```

If you don't provide a URL, Claude searches for the official docs and confirms with you before crawling.

### What happens

Claude runs a 7-step pipeline:

1. **Crawl** — visits every page on the docs site using a stealth Chromium browser
2. **Extract** — converts each page to structured markdown with code blocks preserved
3. **Summarize** — shows you what was found, grouped by topic
4. **You choose** — you pick which topics to include from a numbered list
5. **Filter** — Claude reviews each page and removes noise (blog posts, archive listings, empty pages). You approve the final list before proceeding
6. **Build** — assembles the filtered content into a skill with a flat `pages/` directory and a rich SKILL.md index listing sub-topics per file
7. **Validate** — checks structural integrity, then re-visits every source page and compares against the generated markdown (title, headings, code blocks, content length). Mismatches are flagged with screenshots

Example interaction for a large library:

```
Extracted 287 pages from Laravel 12 documentation.

Topics detected:
 1. Eloquent ORM (42 pages)
 2. Routing (18 pages)
 3. Authentication (24 pages)
 4. Blade Templates (15 pages)
 5. Validation (12 pages)
 6. Queues & Jobs (16 pages)
 ...

Which topics do you want to include? (e.g., "1, 2, 3, 5" or "all")
```

You type `1, 2, 3, 5` and Claude builds a focused skill with just those topics — no bloat.

### Scope

Choose where to save the generated skill:

| Scope | Output directory | Who gets the docs | Use when |
|:------|:-----------------|:------------------|:---------|
| **project** | `<project>/.claude/skills/<name>-docs/` | Whole team (committed to git) | The library is used by the project |
| **user** | `~/.claude/skills/<name>-docs/` | Just you, all projects | General-purpose library you use everywhere |

Skills placed in `.claude/skills/` directories are auto-discovered by Claude Code — no registration or installation is needed. Just restart your session.

### Versioned documentation

Multiple versions of the same library coexist side by side. For example, indexing Laravel 11 and Laravel 12 produces separate skills: `laravel-11-docs` and `laravel-12-docs`. Claude picks the right version based on context, or you can ask about a specific one.

> [!TIP]
> **Add a CLAUDE.md instruction so Claude always uses the docs skill.**
>
> Whether you index docs at user scope or project scope, add a line to your project's `CLAUDE.md` telling Claude to use it:
>
> ```markdown
> When working with React, use the react-docs skill to look up documentation.
> ```
>
> Without this, Claude may rely on training data instead of the indexed docs. The instruction ensures Claude reaches for the skill first — giving you accurate, version-specific answers every time.
>
> We also recommend disabling other documentation MCP servers you might be using, as they can compete with the docs skill and add unnecessary tool call overhead.

<details>
<summary><strong>Prerequisites</strong></summary>

<br>

doc-indexer requires **Python 3.8+**, **Node.js 18+**, and downloads a Chromium browser (~200MB) for crawling.

**macOS** — Python comes pre-installed on macOS 12.3+.

```bash
brew install python@3.12          # Homebrew
```

**Linux**

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install python3 python3-venv python3-pip

# Fedora / RHEL
sudo dnf install python3 python3-pip

# Arch
sudo pacman -S python python-pip
```

**Windows**

```powershell
winget install Python.Python.3.12       # winget (recommended)
choco install python --version=3.12     # Chocolatey
scoop install python                    # Scoop
```

**Playwright system libraries** *(Linux only)*

```bash
sudo npx playwright install-deps chromium
```

</details>

<details>
<summary><strong>First-time setup</strong></summary>

<br>

Creates a Python venv, installs Node.js dependencies, and downloads Chromium:

**macOS / Linux**

```bash
cd ~/.claude/plugins/cache/knowledge/*/plugins/doc-indexer/skills/doc-indexer/scripts
bash setup.sh
```

**Windows (PowerShell)**

```powershell
cd $env:USERPROFILE\.claude\plugins\cache\knowledge\*\plugins\doc-indexer\skills\doc-indexer\scripts
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
npm install
```

</details>

<details>
<summary><strong>How the pipeline works</strong></summary>

<br>

```
┌─────────────────────────────────────────────────────────────────────┐
│                      DOC-INDEXER PIPELINE                          │
└─────────────────────────────────────────────────────────────────────┘

    ┌──────────┐
    │ setup.sh │  One-time: create .venv, install Python deps,
    └────┬─────┘  download Chromium, npm install Defuddle
         │
         ▼
┌─────────────────┐     Pre-crawl site analysis
│   recon.py      │     Inputs:  root URL
│   (Step 1b)     │     Process: raw HTTP fetch → Playwright render → compare
│                 │              → check llms.txt, sitemap.xml → classify site
│                 │     Outputs: /tmp/<lib>-recon.json (rendering, discovery
│                 │              method, suggested flags, URL patterns)
└────────┬────────┘
         │  recon report informs crawl parameters
         ▼
┌─────────────────┐     BFS traversal with Playwright+stealth
│   crawl.py      │     Inputs:  root URL, --same-path-prefix, --max-depth,
│   (Step 2)      │              --exclude-pattern
│                 │     Process: launch Chromium → visit pages → extract links
│                 │              → save rendered HTML → checkpoint every 20 pages
│                 │     Outputs: /tmp/<lib>-sitemap.json (metadata)
│                 │              /tmp/<lib>-html/*.html  (rendered pages)
└────────┬────────┘
         │  sitemap.json + saved HTML files
         ▼
┌─────────────────┐     Per-page content extraction
│  extract.py     │     Inputs:  sitemap.json, /tmp/<lib>-html/
│  (Step 3)       │     Process: for each HTML file:
│        │        │       ┌──────────────────────────┐
│        ├───────►│───────│ defuddle_extract.mjs     │ Node.js subprocess
│        │        │       │ (Defuddle → markdown)    │ per HTML file
│        │        │       └──────────────────────────┘
│                 │              → parse markdown: code blocks, headings, sigs
│                 │              → classify page category
│                 │              → Pygments language guess (optional)
│                 │     Outputs: /tmp/<lib>-extracted/*.json (one per page)
└────────┬────────┘
         │  extracted JSON files
         ▼
┌─────────────────┐     Human-in-the-loop curation
│  Claude Agent   │     Process: read extracted JSONs → group by topic
│  (Step 4)       │              → present to user → user picks topics
│                 │              → quality filter (KEEP/SKIP) → user confirms
│                 │              → delete skipped JSON files
│                 │     Output:  filtered /tmp/<lib>-extracted/ (only kept pages)
└────────┬────────┘
         │  filtered extracted JSONs
         ▼
┌─────────────────┐     Assemble skill from filtered content
│ build_plugin.py │     Inputs:  library name, extracted dir, version, source URL
│   (Step 5)      │     Process: load JSONs → generate pages/*.md from template
│                 │              → generate SKILL.md (index + file listing)
│                 │     Outputs: <output-dir>/SKILL.md
│                 │              <output-dir>/pages/*.md
│                 │     Templates used:
│                 │       ├── SKILL_template.md
│                 │       └── section_template.md
└────────┬────────┘
         │  built skill directory
         ▼
┌─────────────────┐     Structural integrity checks
│  validate.py    │     Inputs:  skill dir, --extracted-dir
│   (Step 6)      │     Checks:  SKILL.md frontmatter ✓
│                 │              link resolution (all paths exist) ✓
│                 │              no empty files ✓
│                 │              page count matches extracted ✓
│                 │              section coverage ≥ 90% ✓
│                 │              signature coverage ≥ 80% ✓
│                 │     Output:  exit 0 (pass) or exit 1 (fail) + report
└────────┬────────┘
         │
         ▼
┌─────────────────┐     Live accuracy verification
│   verify.py     │     Inputs:  skill dir, --screenshot-dir
│   (Step 6b)     │     Process: for each pages/*.md file:
│                 │              → extract source URL from "> Source:" line
│                 │              → re-visit live page with Playwright+stealth
│                 │              → re-extract via Defuddle for baseline
│                 │              → compare signals (title, headings, code, length)
│                 │              → screenshot mismatched pages
│                 │     Output:  exit 0 (pass) or exit 1 (mismatches) + report
└────────┬────────┘
         │
         ▼
    ┌──────────┐
    │ FINALIZE │  Skill is auto-discovered from .claude/skills/
    │ (Step 7) │  Clean up /tmp/ files, optionally delete .venv + Chromium
    └──────────┘
```

**`crawl.py`** — Stealth Chromium browser with anti-fingerprint patches. BFS-crawls from the root URL and saves the HTML to disk. Each page is visited only once — extract.py reuses the saved HTML.

**`extract.py`** — Extracts main content from saved HTML using [Defuddle](https://github.com/kepano/defuddle) for algorithmic content detection with code block standardization (language detection, line number removal, toolbar cleanup). No browser needed — works fully offline. Resumable — skips already-extracted pages on re-run.

**Claude review** — Reads extracted content, groups by topic, asks user which topics to keep. Then filters out noise: blog posts, archive listings, empty pages, duplicates. User approves the final list.

**`build_plugin.py`** — Writes all pages into a flat `pages/` directory. Generates SKILL.md index with H2 sub-topic descriptions per file. Outputs the skill directory (SKILL.md + pages/) directly to the specified `--output-dir`.

**`validate.py`** — Structural checks: SKILL.md frontmatter, file paths resolve, no empty files.

**`verify.py`** — Accuracy check: re-visits every source URL with Playwright, compares title, heading count, code block count, and content length against the generated markdown. Full-page screenshots of mismatched pages.

</details>

<details>
<summary><strong>CLI Reference</strong></summary>

<br>

**recon.py** — Analyze a documentation site before crawling

```
python3 recon.py <root-url> [options]

  --output FILE            Output report path (default: /tmp/recon.json)
  --timeout SECS           Max total runtime in seconds (default: 30)
```

**crawl.py** — Discover documentation pages via BFS crawl

```
python3 crawl.py <root-url> [options]

  --output FILE            Output sitemap path (default: sitemap.json)
  --max-depth N            Max link-follow depth from root (default: 10)
  --max-pages N            Stop after N pages, 0 = unlimited (default: 0)
  --delay SECS             Base delay between requests (default: 0.5)
  --same-path-prefix       Only follow links under the root URL's path
  --exclude-pattern REGEX  Skip URLs matching regex (repeatable)
```

**extract.py** — Convert saved HTML to structured markdown

```
python3 extract.py <sitemap.json> [options]

  --output DIR             Output directory for JSON files (default: extracted/)
  --force                  Re-extract even if output file already exists
  --guess-languages        Use Pygments to guess language for unannotated code blocks
```

**build_plugin.py** — Assemble extracted content into a documentation skill

```
python3 build_plugin.py <library-name> <extracted-dir> [options]

  --version LABEL          Documentation version label (default: latest)
  --source-url URL         Original documentation URL
  --output-dir DIR         Skill output directory (required)
```

**validate.py** — Check skill structural integrity

```
python3 validate.py <skill-dir> [options]

  --extracted-dir DIR      Cross-reference against filtered extracted JSON files
```

**verify.py** — Compare generated content against live source pages

```
python3 verify.py <skill-dir> [options]

  --delay SECS             Base delay between requests (default: 0.5)
  --screenshot-dir DIR     Save full-page screenshots of mismatched pages
```

</details>

<details>
<summary><strong>Troubleshooting</strong></summary>

<br>

**Playwright fails to install Chromium** — Ensure internet access and ~200MB disk space.

**Crawl gets blocked (403/429)** — Increase the delay: `python3 crawl.py <url> --delay 3.0`

**Empty markdown extraction** — Defuddle failed to extract content. This is rare but can happen with very unusual HTML structures. Open an issue with the URL.

</details>

---

<div align="center">

**MIT License**

</div>

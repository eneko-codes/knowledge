<div align="center">

# knowledge

**A Claude Code plugin marketplace for turning any documentation site into a local, instant-access plugin.**

Crawl once. Query forever. No MCP servers. No API calls. No latency.

[Installation](#installation) ·
[Usage](#usage) ·
[How It Works](#how-it-works) ·
[Troubleshooting](#troubleshooting)

</div>

---

## Why Skills Instead of MCP?

Claude Code can access documentation two ways: **MCP servers** fetch pages on-the-fly via API calls, and **skills** read pre-indexed local files. This project takes the skills approach.

<table>
<tr><th width="50%">MCP Servers (real-time fetching)</th><th width="50%">Skills (local pre-indexed files)</th></tr>
<tr>
<td>

- 200–2000ms latency per lookup
- Breaks when APIs change or rate-limit
- ~60% token overhead from protocol wrapping
- One page at a time, no cross-referencing
- Blocked by Cloudflare and bot detection
- Requires internet at query time

</td>
<td>

- **<1ms** reads from local disk
- **100% reliable** — no external dependencies
- **Zero protocol overhead** — direct file reads
- **Full documentation map** via SKILL.md index
- **Hierarchical navigation** — `api/`, `concepts/`, `examples/`
- **Works offline** — plane, train, corporate firewall

</td>
</tr>
</table>

> **The trade-off:** A one-time crawl (5–30 min) generates the plugin. Re-run the crawler when docs update — for most libraries, monthly is enough.

<details>
<summary><strong>Research and evidence</strong></summary>

<br>

1. **Anthropic uses the same pattern.** The official `claude-plugins-official` marketplace distributes documentation as local skill files (e.g., the Stripe plugin uses local markdown, not MCP calls).

2. **Better context window utilization.** A pre-indexed SITEMAP.md gives Claude a complete map of all docs in ~2K tokens. An MCP server would need a tool call just to discover what pages exist.

3. **Deterministic answers.** Local files always return the same content. MCP servers vary due to A/B testing, geo-routing, CDN caching, or page updates between calls.

4. **Community convergence.** Multiple Claude Code plugin developers have independently converged on the "crawl once, read locally" pattern, suggesting it's the natural optimum.

</details>

---

## Available Plugins

| Plugin | Description |
|:-------|:------------|
| `doc-scanner` | Crawls any documentation site and generates a complete, hierarchical documentation plugin |

---

## Prerequisites

<details>
<summary><strong>Python 3.8+</strong> — Required for doc-scanner scripts</summary>

<br>

**macOS** — Pre-installed on macOS 12.3+. Verify: `python3 --version`

```bash
brew install python@3.12          # Homebrew
sudo port install python312       # MacPorts
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

Or download from [python.org](https://www.python.org/downloads/windows/). Check **"Add Python to PATH"** during install.

</details>

<details>
<summary><strong>Claude Code</strong> — The CLI this plugin extends</summary>

<br>

**macOS / Linux**

```bash
npm install -g @anthropic-ai/claude-code     # npm (Node.js 18+)
brew install claude-code                      # Homebrew
```

**Windows**

```powershell
npm install -g @anthropic-ai/claude-code     # npm (Node.js 18+)
```

</details>

<details>
<summary><strong>Playwright system libraries</strong> — Linux only</summary>

<br>

macOS and Windows need nothing extra. On Linux:

```bash
# Automatic (recommended)
sudo npx playwright install-deps chromium

# Manual — Ubuntu / Debian
sudo apt install libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
  libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2

# Manual — Fedora / RHEL
sudo dnf install nss nspr atk at-spi2-atk cups-libs libdrm \
  libxkbcommon libXcomposite libXdamage libXfixes libXrandr mesa-libgbm \
  pango cairo alsa-lib
```

</details>

---

## Installation

**1. Add the marketplace**

```bash
claude /plugin marketplace add https://github.com/eneko-codes/claude-knowledge
```

**2. Install the plugin**

```bash
claude /plugin install doc-scanner@knowledge
```

**3. Run setup** *(one-time — installs Python deps + Chromium ~200MB)*

<details>
<summary>macOS / Linux</summary>

```bash
cd ~/.claude/plugins/cache/knowledge/*/plugins/doc-scanner/skills/doc-scanner/scripts
bash setup.sh
```

</details>

<details>
<summary>Windows (PowerShell)</summary>

```powershell
cd $env:USERPROFILE\.claude\plugins\cache\knowledge\*\plugins\doc-scanner\skills\doc-scanner\scripts
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

> On Windows, use `.venv\Scripts\Activate.ps1` instead of `source .venv/bin/activate`.

</details>

---

## Usage

Tell Claude to scan any documentation site:

```
Scan the documentation at https://docs.sqlc.dev/en/stable/ and generate a docs plugin for sqlc
```

```
Crawl the htmx documentation at https://htmx.org/docs/ and create a plugin
```

```
Index the Goose library docs at https://pressly.github.io/goose/
```

Claude handles the full workflow automatically:

1. Asks for any missing parameters (library name, version)
2. Crawls all documentation pages
3. Extracts and classifies content
4. Builds a complete documentation plugin
5. Validates coverage
6. Registers it in the marketplace

### Generated plugin structure

For a library called `sqlc`:

```
plugins/docs-sqlc/
├── .claude-plugin/
│   └── plugin.json                  # Plugin metadata
└── skills/sqlc-docs/
    ├── SKILL.md                     # Entry point — full file index
    ├── index/
    │   └── SITEMAP.md               # Complete page listing
    ├── api/                         # API reference pages
    │   ├── configuration.md
    │   └── query-annotations.md
    ├── concepts/                    # Conceptual docs + tutorials
    │   ├── overview.md
    │   └── getting-started.md
    ├── examples/                    # Code-heavy example pages
    │   └── using-sqlc-with-postgresql.md
    └── warnings/                    # Deprecation notices
        └── WARNINGS.md
```

### Using a generated plugin

```bash
claude /plugin install docs-sqlc@knowledge
```

Then just ask Claude — it automatically uses the documentation:

```
What's the configuration format for sqlc.yaml?
How do I use sqlc with PostgreSQL arrays?
What functions does sqlc generate for a query?
```

---

## How It Works

The doc-scanner skill orchestrates four scripts in a pipeline:

```
crawl.py  ──>  extract.py  ──>  build_plugin.py  ──>  validate.py
 (URLs)        (markdown)       (plugin files)        (coverage report)
```

### `crawl.py` — Discover pages

Launches a headless Chromium browser with [playwright-stealth](https://github.com/nickmilo/playwright-stealth) anti-fingerprint patches. Performs BFS traversal from the root URL, following same-domain links. Outputs `sitemap.json` with URL, title, H1–H3 headings, and HTTP status for every page.

Key features:
- `--same-path-prefix` restricts crawling to a URL subtree (critical for versioned docs like `/en/stable/`)
- Randomized delay (1.5s ± 0.5s) mimics human browsing patterns
- Handles redirects, HTTP errors, and JavaScript-rendered pages

### `extract.py` — Convert to markdown

Re-visits each page with the same stealth browser. Locates the main content area via 15 CSS selector heuristics (`<main>`, `<article>`, `[role="main"]`, `.docs-content`, etc.). Strips navigation, sidebars, footers, and UI widgets. Converts to markdown via [html2text](https://github.com/Alir3z4/html2text).

Classifies each page as: `api-reference` · `conceptual` · `tutorial` · `example` · `warning`

Extracts function signatures using language-specific regex (Go, Python, TypeScript, Rust, Java).

### `build_plugin.py` — Assemble the plugin

Groups pages by category into directories. Generates one markdown file per page. Consolidates warnings into a single `WARNINGS.md`. Builds the `SKILL.md` index with trigger phrases, quick reference for top API functions, and a complete file listing.

### `validate.py` — Verify coverage

Runs 7 checks:

| # | Check | Threshold |
|:-:|:------|:----------|
| 1 | `plugin.json` exists with required fields | required |
| 2 | `SKILL.md` has YAML frontmatter + substantial content | > 500 chars |
| 3 | `SITEMAP.md` exists | required |
| 4 | Page count matches sitemap (accounting for warning consolidation) | exact |
| 5 | Section coverage — sitemap headings found in content files | >= 90% |
| 6 | Link resolution — all SKILL.md file paths resolve | 100% |
| 7 | No empty content files | 0 empty |

### Manual usage

<details>
<summary>macOS / Linux</summary>

```bash
cd plugins/doc-scanner/skills/doc-scanner/scripts
source .venv/bin/activate

python3 crawl.py https://pressly.github.io/goose/ \
  --output /tmp/goose-sitemap.json \
  --same-path-prefix

python3 extract.py /tmp/goose-sitemap.json \
  --output /tmp/goose-extracted/

python3 build_plugin.py goose /tmp/goose-extracted/ \
  --source-url https://pressly.github.io/goose/ \
  --output-dir ../../../../../../plugins/docs-goose

python3 validate.py ../../../../../../plugins/docs-goose/ \
  --sitemap /tmp/goose-sitemap.json
```

</details>

<details>
<summary>Windows (PowerShell)</summary>

```powershell
cd plugins\doc-scanner\skills\doc-scanner\scripts
.\.venv\Scripts\Activate.ps1

python crawl.py https://pressly.github.io/goose/ `
  --output $env:TEMP\goose-sitemap.json `
  --same-path-prefix

python extract.py $env:TEMP\goose-sitemap.json `
  --output $env:TEMP\goose-extracted\

python build_plugin.py goose $env:TEMP\goose-extracted\ `
  --source-url https://pressly.github.io/goose/ `
  --output-dir ..\..\..\..\..\..\plugins\docs-goose

python validate.py ..\..\..\..\..\..\plugins\docs-goose\ `
  --sitemap $env:TEMP\goose-sitemap.json
```

</details>

---

## Troubleshooting

<details>
<summary><strong>Playwright fails to install Chromium</strong></summary>

<br>

Ensure internet access and ~200MB disk space. On Linux, install system deps first:

```bash
sudo npx playwright install-deps chromium
```

</details>

<details>
<summary><strong>Crawl gets blocked (403/429 errors)</strong></summary>

<br>

Increase the delay:

```bash
python3 crawl.py <url> --delay 3.0
```

Some sites may require even longer delays or block automated access entirely.

</details>

<details>
<summary><strong>Extraction produces empty markdown</strong></summary>

<br>

The content area heuristic may not match the site's HTML structure. Inspect the page's HTML to find the correct content selector and open an issue with the site URL.

</details>

<details>
<summary><strong>Windows: <code>source .venv/bin/activate</code> fails</strong></summary>

<br>

Use PowerShell, not Command Prompt:

```powershell
.\.venv\Scripts\Activate.ps1
```

If execution policy blocks it:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

</details>

---

<div align="center">

**MIT License**

</div>

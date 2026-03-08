<div align="center">

# knowledge

**Pre-built documentation plugins for Claude Code.**

Install a plugin, get instant access to any library's docs. No API calls, no latency, works offline.

[Available Docs](#available-documentation) ·
[Installation](#installation) ·
[Crawl Your Own](#crawl-your-own-docs) ·
[Why Skills?](#why-skills-instead-of-mcp)

</div>

---

## Available Documentation

| Plugin | Library | Install |
|:-------|:--------|:--------|
| `docs-goose` | [Goose](https://pressly.github.io/goose/) — Go database migrations | `claude /plugin install docs-goose@knowledge` |

> More libraries coming soon. [Request one](https://github.com/eneko-codes/claude-knowledge/issues) or [crawl your own](#crawl-your-own-docs).

---

## Installation

**1. Add the marketplace** *(one-time)*

```bash
claude /plugin marketplace add https://github.com/eneko-codes/claude-knowledge
```

**2. Install any docs plugin**

```bash
claude /plugin install docs-goose@knowledge
```

**3. Just ask Claude**

```
How do I use goose migrations with PostgreSQL?
What CLI commands does goose support?
Show me how to embed SQL migrations in Go
```

That's it. Claude reads the docs locally — instant answers, no setup.

### Versioned documentation

Multiple versions of the same library can coexist:

```bash
claude /plugin install docs-laravel-11@knowledge
claude /plugin install docs-laravel-12@knowledge
```

Claude picks the right version based on context, or you can ask about a specific one.

---

## Crawl Your Own Docs

The `doc-scanner` plugin lets you generate documentation plugins for **any** site — useful for niche libraries, private docs, or libraries not yet in the marketplace.

```bash
claude /plugin install doc-scanner@knowledge
```

Then tell Claude:

```
Scan the documentation at https://docs.sqlc.dev/en/stable/ and generate a docs plugin for sqlc
```

Claude crawls the site, extracts content, builds the plugin, and validates coverage — all automatically.

<details>
<summary><strong>Prerequisites for doc-scanner</strong></summary>

<br>

doc-scanner requires **Python 3.8+** and downloads a Chromium browser (~200MB) for crawling. Pre-built docs plugins have no prerequisites.

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
<summary><strong>Setup</strong></summary>

<br>

First-time setup creates a Python venv and downloads Chromium:

**macOS / Linux**

```bash
cd ~/.claude/plugins/cache/knowledge/*/plugins/doc-scanner/skills/doc-scanner/scripts
bash setup.sh
```

**Windows (PowerShell)**

```powershell
cd $env:USERPROFILE\.claude\plugins\cache\knowledge\*\plugins\doc-scanner\skills\doc-scanner\scripts
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

</details>

<details>
<summary><strong>How the pipeline works</strong></summary>

<br>

doc-scanner runs four scripts in sequence:

```
crawl.py  ──>  extract.py  ──>  build_plugin.py  ──>  validate.py
 (URLs)        (markdown)       (plugin files)        (coverage report)
```

**`crawl.py`** — Launches a stealth Chromium browser with anti-fingerprint patches. BFS-crawls from the root URL. Outputs `sitemap.json` with titles, headings, and status for every page.

**`extract.py`** — Re-visits each page, finds the main content area via 15 CSS selector heuristics, strips navigation/UI, converts to markdown. Classifies pages as `api-reference` · `conceptual` · `tutorial` · `example` · `warning`.

**`build_plugin.py`** — Groups pages into `api/`, `concepts/`, `examples/`, `warnings/` directories. Generates SKILL.md index with quick reference for top API functions.

**`validate.py`** — Runs 7 checks: plugin.json fields, SKILL.md frontmatter, page count, section coverage (>= 90%), link resolution (100%), no empty files.

</details>

<details>
<summary><strong>Manual usage (without Claude)</strong></summary>

<br>

**macOS / Linux**

```bash
cd plugins/doc-scanner/skills/doc-scanner/scripts
source .venv/bin/activate

python3 crawl.py https://pressly.github.io/goose/ \
  --output /tmp/goose-sitemap.json --same-path-prefix

python3 extract.py /tmp/goose-sitemap.json \
  --output /tmp/goose-extracted/

python3 build_plugin.py goose /tmp/goose-extracted/ \
  --source-url https://pressly.github.io/goose/

python3 validate.py ../../../../../../plugins/docs-goose/ \
  --sitemap /tmp/goose-sitemap.json
```

**Windows (PowerShell)**

```powershell
cd plugins\doc-scanner\skills\doc-scanner\scripts
.\.venv\Scripts\Activate.ps1

python crawl.py https://pressly.github.io/goose/ `
  --output $env:TEMP\goose-sitemap.json --same-path-prefix

python extract.py $env:TEMP\goose-sitemap.json `
  --output $env:TEMP\goose-extracted\

python build_plugin.py goose $env:TEMP\goose-extracted\ `
  --source-url https://pressly.github.io/goose/

python validate.py ..\..\..\..\..\..\plugins\docs-goose\ `
  --sitemap $env:TEMP\goose-sitemap.json
```

</details>

---

## Why Skills Instead of MCP?

Claude Code can access documentation two ways: **MCP servers** fetch pages in real-time via API calls, and **skills** read pre-indexed local files.

<table>
<tr><th width="50%">MCP Servers (real-time fetching)</th><th width="50%">Skills (pre-indexed local files)</th></tr>
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

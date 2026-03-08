<div align="center">

# knowledge

**Pre-built documentation plugins for Claude Code.**

Install a plugin. Get instant, offline access to any library's docs.

No API calls. No latency. No setup.

[Available Docs](#available-documentation) ·
[Install](#installation) ·
[Request Docs](#request-a-library) ·
[Index Your Own](#index-your-own-docs) ·
[Why Skills?](#why-skills-instead-of-mcp)

</div>

---

## Available Documentation

| Plugin | Library | Pages |
|:-------|:--------|------:|
| `goose-docs` | [Goose](https://pressly.github.io/goose/) — Go database migrations | 29 |

```bash
claude /plugin install goose-docs@knowledge
```

> **Don't see your library?** [Request it](https://github.com/eneko-codes/knowledge/issues/new?template=doc-request.yml) — no setup needed, just fill out the form.

---

## Installation

**1. Add the marketplace** *(one-time)*

```bash
claude /plugin marketplace add https://github.com/eneko-codes/knowledge
```

**2. Install a docs plugin**

```bash
claude /plugin install goose-docs@knowledge
```

**3. Ask Claude**

```
How do I use goose migrations with PostgreSQL?
What CLI commands does goose support?
Show me how to embed SQL migrations in Go
```

That's it. Claude reads the docs from local files — instant answers, works offline.

### Versioned documentation

Multiple versions of the same library coexist side by side:

```bash
claude /plugin install laravel-11-docs@knowledge
claude /plugin install laravel-12-docs@knowledge
```

Claude picks the right version based on context, or you can ask about a specific one.

---

## Request a Library

Want docs for a library that isn't listed? **[Open a request](https://github.com/eneko-codes/knowledge/issues/new?template=doc-request.yml)** with the library name and documentation URL. No tooling needed on your end — we'll index it and add it to the marketplace.

---

## Index Your Own Docs

The `doc-indexer` plugin lets you generate documentation plugins for **any** site — useful for private docs, niche libraries, or libraries not yet in the marketplace.

```bash
claude /plugin install doc-indexer@knowledge
```

Then tell Claude:

```
Index the documentation at https://docs.sqlc.dev/en/stable/ for sqlc
```

Claude handles the full pipeline: crawl, extract, build, validate. It will ask you which **scope** to install at:

| Scope | Who gets the docs | Use when |
|:------|:------------------|:---------|
| **project** | Whole team (committed to git) | The library is used by the project |
| **user** | Just you, all projects | General-purpose library you use everywhere |

<details>
<summary><strong>Prerequisites</strong></summary>

<br>

doc-indexer requires **Python 3.8+** and downloads a Chromium browser (~200MB) for crawling. Pre-built docs plugins have **no prerequisites**.

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

Creates a Python venv and downloads Chromium:

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
```

</details>

<details>
<summary><strong>How the pipeline works</strong></summary>

<br>

```
crawl.py  ──>  extract.py  ──>  build_plugin.py  ──>  validate.py
 (URLs)        (markdown)       (plugin files)        (coverage report)
```

**`crawl.py`** — Stealth Chromium browser with anti-fingerprint patches. BFS-crawls from the root URL. Outputs `sitemap.json` with titles, headings, and status for every page.

**`extract.py`** — Finds the main content area via 15 CSS selector heuristics, strips navigation/UI, converts to markdown. Classifies pages as `api-reference` · `conceptual` · `tutorial` · `example` · `warning`.

**`build_plugin.py`** — Groups pages into `api/`, `concepts/`, `examples/`, `warnings/`. Generates SKILL.md index with quick reference for top API functions.

**`validate.py`** — 7 checks: plugin.json fields, SKILL.md frontmatter, page count, section coverage (>= 90%), link resolution (100%), no empty files.

</details>

<details>
<summary><strong>Manual usage (without Claude)</strong></summary>

<br>

**macOS / Linux**

```bash
cd plugins/doc-indexer/skills/doc-indexer/scripts
source .venv/bin/activate

python3 crawl.py https://pressly.github.io/goose/ \
  --output /tmp/goose-sitemap.json --same-path-prefix

python3 extract.py /tmp/goose-sitemap.json \
  --output /tmp/goose-extracted/

python3 build_plugin.py goose /tmp/goose-extracted/ \
  --source-url https://pressly.github.io/goose/

python3 validate.py ../../../../../../plugins/goose-docs/ \
  --sitemap /tmp/goose-sitemap.json
```

**Windows (PowerShell)**

```powershell
cd plugins\doc-indexer\skills\doc-indexer\scripts
.\.venv\Scripts\Activate.ps1

python crawl.py https://pressly.github.io/goose/ `
  --output $env:TEMP\goose-sitemap.json --same-path-prefix

python extract.py $env:TEMP\goose-sitemap.json `
  --output $env:TEMP\goose-extracted\

python build_plugin.py goose $env:TEMP\goose-extracted\ `
  --source-url https://pressly.github.io/goose/

python validate.py ..\..\..\..\..\..\plugins\goose-docs\ `
  --sitemap $env:TEMP\goose-sitemap.json
```

</details>

---

## Why Skills Instead of MCP?

Claude Code can access docs two ways: **MCP servers** fetch pages in real-time, **skills** read pre-indexed local files.

<table>
<tr><th width="50%">MCP Servers</th><th width="50%">Skills (this project)</th></tr>
<tr>
<td>

- 200–2000ms per lookup
- Breaks when APIs change or rate-limit
- ~60% token overhead from protocol
- One page at a time
- Blocked by Cloudflare / bot detection
- Requires internet

</td>
<td>

- **<1ms** from local disk
- **100% reliable** — no external deps
- **Zero overhead** — direct file reads
- **Full docs map** via SKILL.md index
- **Hierarchical** — `api/`, `concepts/`, `examples/`
- **Works offline**

</td>
</tr>
</table>

> **Trade-off:** One-time crawl (5–30 min) to generate. Re-crawl when docs update — monthly is usually enough.

<details>
<summary><strong>Research and evidence</strong></summary>

<br>

1. **Anthropic uses the same pattern.** The official `claude-plugins-official` marketplace ships documentation as local skill files.

2. **Better context utilization.** A SITEMAP.md gives Claude a complete docs map in ~2K tokens. MCP needs a tool call just to discover what pages exist.

3. **Deterministic answers.** Local files return the same content every time. MCP varies due to CDN caching, A/B testing, and page updates.

4. **Community convergence.** Multiple plugin developers independently converged on "crawl once, read locally."

</details>

---

## Troubleshooting

<details>
<summary><strong>Playwright fails to install Chromium</strong></summary>

<br>

Ensure internet access and ~200MB disk space. On Linux:

```bash
sudo npx playwright install-deps chromium
```

</details>

<details>
<summary><strong>Crawl gets blocked (403/429)</strong></summary>

<br>

Increase the delay:

```bash
python3 crawl.py <url> --delay 3.0
```

</details>

<details>
<summary><strong>Empty markdown extraction</strong></summary>

<br>

The content area heuristic may not match the site's HTML. Open an issue with the URL.

</details>

<details>
<summary><strong>Windows: <code>source</code> not found</strong></summary>

<br>

Use PowerShell: `.\.venv\Scripts\Activate.ps1`

If blocked: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

</details>

---

<div align="center">

**MIT License**

</div>

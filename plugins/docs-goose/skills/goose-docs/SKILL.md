---
name: goose-docs
description: >
  Goose (latest) documentation reference. Use when asked about goose,
  its API, configuration, usage patterns, or troubleshooting.
  
---

# Goose Documentation (latest)

Complete reference for Goose, extracted from the official documentation.

- **Source:** https://pressly.github.io/goose/
- **Version:** latest
- **Plugin name:** docs-goose
- **Total pages:** 29

## Directory Structure

- **api/**: 4 api reference pages
- **concepts/**: 17 conceptual pages
- **examples/**: 1 example pages
- **concepts/**: 1 tutorial pages
- **warnings/**: 6 warning pages


## Quick Reference — Common Functions

```
FUNCTION histories_partition_creation( DATE, DATE )
FROM generate_series( $1, $2, '1 month' )
TABLE users (
    id int NOT NULL PRIMARY KEY,
    username text,
    name text,
    surname text
)
ON users (user_id)
func main()
main

import (
    "database/sql"
    "embed"
    "log"

    _ "github.com/mattn/go-sqlite3"
    "github.com/pressly/goose/v3"
)
func (p *Provider) Up(ctx context.Context) ([]*MigrationResult, error)
TABLE users (id INTEGER)
TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username text NOT NULL
)
func (q *Queries) ListUsers(ctx context.Context) ([]User, error)
```

## File Index

- `api/custom-store.md` — Custom store
- `api/embedding-migrations.md` — Embedding migrations
- `api/sql-file-annotations.md` — SQL file annotations
- `api/sql-migration-files-and-goose-annotations.md` — SQL migration files and goose annotations
- `concepts/2021-pressly-goose.md` — 2021 - pressly/goose
- `concepts/2023-pressly-goose.md` — 2023 - pressly/goose
- `concepts/2024-pressly-goose.md` — 2024 - pressly/goose
- `concepts/a-tour-of-goose-up-and-down-commands.md` — A tour of goose up and down commands
- `concepts/ad-hoc-migrations-with-no-versioning.md` — Ad-hoc migrations with no versioning
- `concepts/adding-a-goose-provider.md` — Adding a goose provider
- `concepts/adding-support-for-out-of-order-migrations.md` — Adding support for out-of-order migrations
- `concepts/environment-variables.md` — Environment variables
- `concepts/general-pressly-goose.md` — General - pressly/goose
- `concepts/go-migrations-pressly-goose.md` — Go migrations - pressly/goose
- `concepts/goose-provider.md` — Goose provider
- `concepts/hello-docs.md` — Hello, docs!
- `concepts/installing-goose.md` — Installing goose
- `concepts/overview.md` — Overview
- `concepts/package-pressly-goose.md` — Package - pressly/goose
- `concepts/sql-migrations-pressly-goose.md` — SQL migrations - pressly/goose
- `concepts/testing-pressly-goose.md` — Testing - pressly/goose
- `concepts/usingsqlcandgoose.md` — Usingsqlcandgoose
- `examples/better-tests-with-containers.md` — Better tests with containers
- `index/SITEMAP.md` — Full sitemap of all 29 pages
- `warnings/WARNINGS.md` — Deprecation notices and warnings

## How to Use

1. Start with `index/SITEMAP.md` for an overview of all available pages.
2. Navigate to the relevant directory based on what you need:
   - `api/` for function signatures, type definitions, and parameter details
   - `concepts/` for explanations, guides, and tutorials
   - `examples/` for code examples and sample usage
   - `warnings/` for deprecation notices and breaking changes
3. Read the specific sub-file for detailed content.

## Important

- All content is extracted verbatim from the official documentation.
- Code blocks are preserved exactly as they appear in the source.
- If content seems outdated, re-run the doc-scanner to refresh.

---
name: {versioned_library}-docs
description: >
  {library_name_title} ({version}) documentation reference. Use when asked about {library_name},
  its {description_terms}.
  {version_triggers}
---

# {library_name_title} Documentation ({version})

Complete reference for {library_name_title}, extracted from the official documentation.

- **Source:** {source_url}
- **Version:** {version}
- **Plugin name:** {plugin_name}
- **Total pages:** {total_pages}

## Contents

{pages_summary}
{quick_reference}
## File Index

Each entry shows the file path, page title, and key sub-topics (H2 headings).
Scan this index to find the right file for your question.

{file_listing}

## How to Use

1. Scan the File Index above to find relevant pages by title and sub-topics.
2. Read the specific `pages/*.md` file for detailed content.
3. Each file includes a `> Source:` link to the original documentation URL.

## Important

- All content is extracted verbatim from the official documentation.
- Code blocks are preserved exactly as they appear in the source.
- If content seems outdated, re-run the doc-indexer to refresh.

# Wiki Agent Instructions

You are the agent managing this wiki. This wiki is a knowledge base for an AI Scientist — it stores up-to-date articles from different sources all from the web.

You can read and write any file in this directory. When answering queries, always ground your answers in the actual files here. Never fabricate article content, metadata, or citations.

## Directory Structure

```
wiki/
├── articles.md     # Content catalog — every page listed with a one-line summary
├── topic.md        # Content catalog — every page listed with a one-line summary
├── log.md          # Chronological action log (append-only)
├── sources/        # Information about the sources where we can get the latest articles, each item shows how info from this resource is organized, and how to get info from this source efficiently
│   ├── arxiv.md
│   ├── x.md
│   ├── anthropic.md
│   └── ...
├── articles/      # raw articles
│   ├── arxiv/
│   │   ├── Attention is All Your Need
│   │   │   ├── metadata.json
│   │   │   └── info.md
│   │   └── ...
│   ├── x/
│   │   └── ...
│   ├── anthropic/
│   │   └── ...
│   └── ...
├── topics/         # Gather materials by topics, to provide cross-article analysis
└── CLAUDE.md       # This file
```

**Immutable layer:** `articles/` holds raw fetched content. Once an article is saved, do not edit `metadata.json` or `info.md` — re-fetch and create a new entry if the upstream changed. This keeps the source of truth intact and traceable.

**Wiki layer:** `articles.md`, `topic.md`, `topics/`, `sources/`, and `log.md` are agent-maintained. Create, update, and cross-reference freely.

## Orient First

At the start of every session, before doing anything else:

1. Read `articles.md` — learn what articles have been collected.
2. Read `topic.md` — learn what cross-article topic pages exist.
3. Read the last ~20 lines of `log.md` — understand recent activity.

This prevents duplicate fetches, missed cross-references, and repeated work.

## Core Operations

### Query

When the user asks a question:

1. Check `articles.md` and `topic.md` to find relevant pages.
2. Search with grep/glob across `articles/` and `topics/` if the catalogs don't cover it.
3. Read the relevant files and synthesize an answer. Cite specific files (e.g., "per articles/arxiv/Attention is All You Need/info.md").
4. If the answer is a substantial synthesis worth keeping, file it into `topics/` as a new or updated topic page. This is how the wiki compounds — good answers become permanent knowledge.
5. Append to `log.md`.

### Add Article

When the user asks to ingest a new article:

1. Check `sources/{source}.md` for how that source is organized and how to fetch from it efficiently. If the source isn't documented yet, see "Add Source" below.
2. Fetch the article. Create `articles/{source}/{article-title}/` with:
   - `metadata.json` — at minimum: title, authors, source, url, published date, fetched date.
   - `info.md` — the article's content or a faithful extract, plus a short summary at the top.
3. Add an entry to `articles.md`.
4. If the article belongs to an existing topic in `topics/`, update that topic page with the new reference.
5. Append to `log.md`.

Do not overwrite an existing article directory. If a newer version is needed, create a sibling directory with a version suffix and note the relation in both `info.md` files.

### Build / Update Topic

When the user asks to gather materials by topic, or when a query produces a synthesis worth keeping:

1. Read every article you intend to draw from.
2. Write or update `topics/{topic-name}.md`. Reference each article by relative path (e.g., `articles/arxiv/Attention is All You Need/info.md`).
3. Note contradictions across articles explicitly — don't silently pick a side.
4. Update `topic.md` and append to `log.md`.

### Add Source

When the user asks to track a new information source:

1. Create `sources/{source}.md` describing: what the source is, how content is organized there, the access method (API, RSS, scraping notes, auth), rate limits, and a recommended fetch recipe.
2. Append to `log.md`. (Source pages are not listed in `articles.md` or `topic.md`.)

### Lint

When asked to health-check the wiki:

- Article directories not listed in `articles.md`.
- Topic pages not listed in `topic.md`.
- Topic pages that don't reference any article.
- Articles missing `metadata.json` or `info.md`.
- `sources/` entries referenced by articles but not present (or vice versa).
- Stale or contradictory claims across topic pages.
- Report findings and fix what you can without inventing data.

## Writing to Each Directory

### Articles (`articles/{source}/{article-title}/`)
- `metadata.json` is structured; keep keys consistent across articles from the same source.
- `info.md` starts with a 1–3 line summary, then the content. Preserve the original wording when quoting; mark any agent-added commentary clearly.
- Directory name should match the article title closely (lowercase, hyphens preferred, but readable titles are acceptable since this is human-facing).

### Topics (`topics/`)
- One file per topic: `attention-mechanisms.md`, `agentic-rag.md`.
- Always reference the articles that support it (relative paths into `articles/`).
- Update existing topic files when new articles arrive. Note contradictions explicitly — don't silently overwrite.

### Sources (`sources/`)
- One file per source. Keep it operational: the next agent should be able to fetch from this source by following the page.

## articles.md and topic.md

Flat catalogs. Each entry is one line: path + one-line summary.

`articles.md`:

```markdown
# Articles
Last updated: YYYY-MM-DD | Total: N

## arxiv
- articles/arxiv/Attention is All You Need/info.md — [one-line summary]

## anthropic
- articles/anthropic/<title>/info.md — [one-line summary]

## x
- articles/x/<title>/info.md — [one-line summary]
```

`topic.md`:

```markdown
# Topics
Last updated: YYYY-MM-DD | Total: N

- topics/attention-mechanisms.md — [one-line summary]
- topics/agentic-rag.md — [one-line summary]
```

Update both catalogs every time you create or significantly update a page they index.

## log.md

Append-only chronological record. Format:

```markdown
## [YYYY-MM-DD] action | subject
- Details of what changed
```

Actions: `query`, `add-article`, `update-article`, `build-topic`, `update-topic`, `add-source`, `lint`.

When `log.md` exceeds 300 entries, rotate: rename to `log-YYYY-MM-DD.md` and start fresh.

## Conventions

- Filenames: lowercase, hyphens, no spaces — except article directory names, which may preserve the human-readable title.
- Cross-reference between directories using relative paths.
- When updating a file, note the date if the content is time-sensitive.
- Prefer updating existing files over creating new ones when the topic or article already has a page.

## Constraints

- Stay within this wiki directory.
- Never invent article content, authors, dates, URLs, or citations. If a fetch fails or a field is unknown, leave it empty and say so.
- Never modify files inside an existing `articles/{source}/{title}/` directory after creation. Add a new versioned sibling instead.
- When synthesizing across articles, always cite the specific article paths.
- If asked to plan a fetch or a topic build, write the plan to the relevant topic or source page — don't just answer in chat.

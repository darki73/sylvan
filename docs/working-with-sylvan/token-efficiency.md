# Token Efficiency

Every tool response includes measurements of how many tokens it returned versus
how many tokens a naive approach (reading entire files) would have consumed. This
is not an estimate -- it is calculated for every call and tracked across sessions.


## Per-response efficiency

Every response from the server includes a `_meta.token_efficiency` block:

```json
"_meta": {
  "token_efficiency": {
    "returned": 244,
    "equivalent_file_read": 9817,
    "reduction_percent": 97.5,
    "method": "byte_estimate"
  }
}
```

| Field | Meaning |
|---|---|
| `returned` | Tokens in this response |
| `equivalent_file_read` | Tokens if you had read the full file(s) instead |
| `reduction_percent` | How much was saved: `(1 - returned/equivalent) * 100` |
| `method` | How tokens were counted (see below) |

When `read_symbol` returns a 30-line function from a 500-line file, `returned` is
the token count of those 30 lines and `equivalent_file_read` is the token count
of the entire file. The difference is what your agent did not have to process.


## Measurement methods

The `method` field tells you how tokens were counted:

| Method | When used | Accuracy |
|---|---|---|
| `tiktoken_cl100k` | Both sides can use tiktoken (Python) | Exact |
| `byte_estimate` | Tiktoken unavailable or cross-language | Approximate (bytes / 4) |

When the server and your agent both use tiktoken's `cl100k_base` encoding, the
counts are exact. When that is not possible (e.g., the file content is only
available as bytes), a byte-based estimate is used. The method is always reported
so you know the precision of the numbers.


## Session tracking

Token efficiency accumulates across all tool calls in a session. Use
`usage_stats` to see the running totals:

```
usage_stats()
```

```json
{
  "session": {
    "duration_seconds": 2366.2,
    "tool_calls": 35,
    "symbols_retrieved": 14,
    "tokens_returned": 28373,
    "tokens_avoided": 131090,
    "token_efficiency": {
      "total_returned": 25543,
      "total_equivalent": 104555,
      "reduction_percent": 75.6,
      "by_category": {
        "search": {
          "calls": 2,
          "returned": 17359,
          "equivalent": 40557
        },
        "retrieval": {
          "calls": 16,
          "returned": 8184,
          "equivalent": 63998
        },
        "analysis": {
          "calls": 0,
          "returned": 0,
          "equivalent": 0
        }
      }
    }
  }
}
```

The `by_category` breakdown shows efficiency by tool type:

| Category | Tools included |
|---|---|
| `search` | `find_code`, `find_text`, `find_docs`, `search_all_repos` |
| `retrieval` | `read_symbol`, `read_doc_section`, `whats_in_file`, `understand_symbol` |
| `analysis` | `what_breaks_if_i_change`, `who_calls_this`, `inheritance_chain` |
| `indexing` | `index_project`, `reindex_file`, `index_multi_repo` |
| `meta` | `usage_stats`, `open_dashboard`, `indexed_repos` |

Retrieval tools typically have the highest reduction percentages because they
return small slices of large files. Search tools return compact result lists
that replace what would otherwise be multiple file reads.


## All-time tracking

Efficiency data persists across server restarts. The `overall` section of
`usage_stats` shows lifetime totals:

```json
"overall": {
  "repos_used": 2,
  "days_active": 14,
  "total_tool_calls": 1847,
  "total_tokens_returned": 482000,
  "total_tokens_avoided": 3210000,
  "total_symbols_retrieved": 920,
  "first_used": "2025-01-10",
  "last_used": "2025-01-24"
}
```

This gives you a long-term picture of how much the server is saving. If
`total_tokens_avoided` is in the millions, the server is doing significant work
to keep your agent's context window focused.


## The efficiency ring

The dashboard (covered in the previous chapter) displays an efficiency ring -- a
visual gauge showing the current session's reduction percentage. A 75% ring means
three-quarters of the tokens your agent would have consumed were avoided.

The ring updates in real-time as tool calls are made. It is the quickest way to
see whether the server is earning its keep during an active session.


## Filtering by repo

To see efficiency for a specific repository:

```
usage_stats(repo="my-project")
```

This filters the session and overall statistics to only include tool calls that
touched that repository. Useful for comparing how different projects benefit
from indexing.


## The input cost

Sylvan registers 65 tools with descriptions and parameter schemas. This adds
approximately 9,200 tokens to your agent's context at session start. On a 200K
context model that is 4.6%, on a 1M model under 1%. The cost is fixed and does
not grow during the conversation.

See [TRANSPARENCY.md](https://github.com/darki73/sylvan/blob/main/TRANSPARENCY.md)
in the repository root for the full breakdown, including what data sylvan does
and does not access.


## What the numbers mean in practice

- **90%+ reduction** is typical for `read_symbol` calls, where a single function
  is returned from a large file.
- **70-85% reduction** is typical for search calls, where a ranked result list
  replaces reading multiple files.
- **50-70% reduction** is typical for `whats_in_file`, where signatures replace
  full source.
- **Negative reduction** can happen with `find_text` on small files, where the
  context lines plus metadata exceed the file size. This is rare and the absolute
  token count is small when it happens.

The overall session reduction percentage is the number that matters most. If it
stays above 70%, the server is consistently returning focused results instead of
dumping entire files into your agent's context.

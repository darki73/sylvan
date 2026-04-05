# Token cost transparency

Sylvan registers MCP tools that your agent sees in its context window. This page
documents exactly what that costs.

## Tool descriptions: the input cost

When your agent connects to sylvan, it receives the full list of tools with their
descriptions and parameter schemas. This is the fixed cost per session.

| Metric | Value |
|--------|-------|
| Tools registered | 65 |
| Description text | ~16,600 characters |
| Parameter schemas | ~20,400 characters |
| **Total context cost** | **~9,200 tokens** |

On a 200K context model, that is 4.6% of the window. On a 1M context model, under 1%.

This cost is paid once at session start and does not grow during the conversation.

## Tool responses: the output cost

Every tool response includes a `_meta.token_efficiency` block measuring what it
returned versus what a naive file read would have cost. These numbers are not
estimates. They are calculated per call and tracked across sessions.

Typical reduction rates:

| Tool type | Typical reduction |
|-----------|------------------|
| `read_symbol` (retrieval) | 90%+ |
| `find_code` (search) | 70-85% |
| `whats_in_file` (browsing) | 50-70% |
| `what_breaks_if_i_change` (analysis) | varies by graph size |
| Memory/preference tools | ~200-500 tokens per call |

Memory and preference tools (`remember_this`, `load_user_rules`, etc.) are meta
operations. They add a small fixed cost per call with no file-read equivalent to
measure against.

## The math

Real numbers from a production installation over 10 active days:

| Metric | Value |
|--------|-------|
| Tool calls | 6,766 |
| Tokens returned | 3,701,586 |
| Equivalent file reads | 25,648,611 |
| **Tokens avoided** | **21,947,025** |
| **Reduction** | **85.6%** |

The 9,200 tokens of tool descriptions avoided 21.9 million tokens of file reads.
That is a 2,385x return.

## What we do not do

- We do not send data to external servers. Everything runs locally.
- We do not log conversation content. The memory system stores only what the
  agent explicitly saves via `save_memory`.
- We do not run background inference. Embeddings are generated locally via
  sentence-transformers (ONNX, no GPU required) or an optional local Ollama
  instance.
- We do not access files outside indexed repositories.

## Verifying these numbers yourself

Run `get_session_stats()` through any MCP client to see live token efficiency
for your session. The dashboard at `get_dashboard_url()` shows the same data
visually, including per-session history and all-time totals.

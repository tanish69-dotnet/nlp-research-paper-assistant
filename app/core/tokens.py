"""Conservative prompt-size budgeting for small-context model calls.

Local models are served by Ollama whose *default* context window is
``num_ctx=4096``.  A request whose prompt is larger than that window is
rejected with HTTP 400 before any generation happens::

    request (5027 tokens) exceeds the available context size (4096 tokens)

Vision requests cannot even raise ``num_ctx`` (Ollama rejects per-request
``options`` when the payload carries images), so prompt size has to be
bounded *before* the call for every path.

No tokenizer is available for every provider, so sizing uses a deliberately
conservative characters-per-token ratio plus a per-message chat-template
overhead.  The estimator over-counts ordinary English prose (real ratio is
roughly 4 chars/token) so that identifier-, table- and caption-heavy evidence
— which tokenizes far denser — still fits inside the real window.
"""

from __future__ import annotations

import math

#: Real English prose tokenizes at ~4 chars/token while ids, numbers and table
#: cells can land near 2.  Over-estimating only costs a little evidence
#: context; under-estimating fails the entire request.
CHARS_PER_TOKEN = 3.0

#: Every message is wrapped by the model's chat template with a small,
#: roughly constant control-token frame.
MESSAGE_OVERHEAD_TOKENS = 10


def estimate_tokens(text: str) -> int:
    """Conservative token estimate for one text blob."""
    if not text:
        return 0
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def estimate_message_tokens(text: str) -> int:
    """Conservative token estimate for one chat message, template frame included."""
    return estimate_tokens(text) + MESSAGE_OVERHEAD_TOKENS


def estimate_messages_tokens(contents: list[str]) -> int:
    """Conservative token estimate for a whole request built from ``contents``."""
    return sum(estimate_message_tokens(content) for content in contents)

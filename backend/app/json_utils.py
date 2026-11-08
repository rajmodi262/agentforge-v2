"""Tolerant JSON parsing for LLM output.

LLMs in JSON mode occasionally truncate at the token limit, leaving an
unterminated string or unclosed brackets. `loads_tolerant` recovers a valid
object from such output by (a) extracting the JSON span, (b) closing open
strings/brackets, and (c) if needed, dropping the incomplete trailing element
and retrying. It never invents data — it only salvages what parsed cleanly.
"""

import json
from typing import Any


def _extract_span(s: str) -> str:
    """Strip markdown fences and isolate the outermost JSON object/array."""
    s = s.strip()
    if "```json" in s:
        s = s.split("```json", 1)[1]
        s = s.split("```", 1)[0]
    elif "```" in s:
        s = s.split("```", 1)[1]
        s = s.split("```", 1)[0]
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        return s[start:end + 1]
    return s.strip()


def _close_open_structures(s: str) -> str:
    """Close any unterminated string and unclosed brackets at the truncation point."""
    stack = []
    in_string = False
    escape = False
    for ch in s:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]":
                if stack:
                    stack.pop()
    out = s
    if in_string:
        out += '"'
    out = out.rstrip().rstrip(",")
    for closer in reversed(stack):
        out += closer
    return out


def loads_tolerant(content: str) -> Any:
    """Parse JSON from LLM output, repairing truncation when possible.

    Raises ValueError if nothing parseable can be recovered.
    """
    if content is None:
        raise ValueError("no content to parse")
    if not isinstance(content, str):
        return content  # already-decoded (e.g. tool_use input dict)

    # 1) direct
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    span = _extract_span(content)

    # 2) extracted span as-is
    try:
        return json.loads(span)
    except json.JSONDecodeError:
        pass

    # 3) close open structures
    try:
        return json.loads(_close_open_structures(span))
    except json.JSONDecodeError:
        pass

    # 4) progressively drop the incomplete trailing element, then close + retry
    cur = span
    for _ in range(4000):
        idx = cur.rfind(",")
        if idx < 0:
            break
        cur = cur[:idx]
        try:
            return json.loads(_close_open_structures(cur))
        except json.JSONDecodeError:
            continue

    raise ValueError("could not recover JSON from content")

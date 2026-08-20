"""Print the actual shape of a JSON endpoint, from a machine that can reach it.

Written the day a feature shipped against a provider retired two weeks
earlier, and then against a model name that no longer existed. Both were
"known" facts. CLAUDE.md now carries the rule -- never trust a name you did
not verify against the live API -- and this is the tool that makes obeying
it a two-minute job instead of a guessing loop.

Two reasons it runs on a GitHub runner rather than locally: the dev session
often cannot reach the internet, and several of these publishers (ESPN
especially) refuse datacenter IPs but accept a runner.

    Actions -> Probe endpoint -> Run workflow -> paste a URL

Prints structure and a redacted sample, never the whole body: these
responses run to megabytes and the point is the shape.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

MAX_SAMPLE_KEYS = 25
MAX_VALUE_CHARS = 90


def describe(value: object, depth: int = 0) -> str:
    pad = "  " * depth
    if isinstance(value, dict):
        keys = list(value)
        head = f"dict({len(keys)} keys)"
        if depth >= 2:
            return head
        # A big id-keyed map repeats one shape thousands of times. Expanding
        # a sample of them is noise -- name a few ids and let the sample
        # entry printed below carry the actual structure.
        if len(keys) > MAX_SAMPLE_KEYS:
            preview = ", ".join(str(k) for k in keys[:5])
            return f"{head} keyed like: {preview}, ..."
        lines = [head]
        for key in keys:
            lines.append(f"{pad}  {key}: {describe(value[key], depth + 1)}")
        return "\n".join(lines)
    if isinstance(value, list):
        head = f"list({len(value)})"
        if not value or depth >= 2:
            return head
        return f"{head} of {describe(value[0], depth + 1)}"
    text = repr(value)
    return text if len(text) <= MAX_VALUE_CHARS else text[:MAX_VALUE_CHARS] + "..."


def main() -> int:
    url = os.environ.get("PROBE_URL", "").strip()
    if not url:
        print("::error::PROBE_URL is required")
        return 2
    if not url.startswith("https://"):
        print("::error::PROBE_URL must be https")
        return 2

    headers = {"User-Agent": "FBBible/1.0 (personal draft tool, shape probe)"}
    # Opt-in bearer auth for the AI provider's endpoints (the model list
    # needs it). The key rides in from the workflow's secret env and is
    # never echoed -- a key pasted into the URL input would land in the
    # workflow log, which is the never-log-a-token rule broken.
    if os.environ.get("PROBE_AUTH") == "ai-key":
        api_key = os.environ.get("AI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            print("::error::PROBE_AUTH=ai-key but no AI_API_KEY secret is set")
            return 2
        headers["Authorization"] = f"Bearer {api_key}"
        print("(authorized with the AI key)")

    print(f"probing {url}\n")
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status = response.status
            raw = response.read()
    except Exception as exc:  # noqa: BLE001 - the failure IS the finding
        print(f"::error::{type(exc).__name__}: {exc}")
        return 1

    print(f"HTTP {status} · {len(raw):,} bytes\n")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print("not JSON. First 300 bytes:")
        print(raw[:300].decode("utf-8", errors="replace"))
        return 0

    # Field census: every field name across a big id-keyed map, with holder
    # counts. The shape view below shows ONE entry; this mode answers "which
    # fields exist at all, and how many entries carry each" -- what you need
    # before building an extractor against sparse per-entry coverage (the
    # IDP stats question, and the same trap the offense stats hit).
    if os.environ.get("PROBE_MODE") == "fields" and isinstance(payload, dict):
        counts: dict[str, int] = {}
        entries = 0
        for value in payload.values():
            if isinstance(value, dict):
                entries += 1
                for field in value:
                    counts[field] = counts.get(field, 0) + 1
        print(f"field census across {entries} dict entries ({len(counts)} distinct fields):")
        for field, n in sorted(counts.items()):
            print(f"  {field}: {n}")
        return 0

    print(describe(payload))

    # For a big id-keyed map, one real entry says more than the schema does
    # -- but it has to be the RIGHT entry. The first key is arbitrary, and on
    # a stats endpoint it is usually a player with no production, whose
    # sparse record hides every field that matters. Show the fullest entry
    # instead: that is the one that reveals what the payload can carry.
    if isinstance(payload, dict) and len(payload) > 50:
        dict_entries = [(k, v) for k, v in payload.items() if isinstance(v, dict)]
        if dict_entries:
            key, richest = max(dict_entries, key=lambda kv: len(kv[1]))
            widths = sorted((len(v) for _, v in dict_entries), reverse=True)
            median = widths[len(widths) // 2]
            print(f"\nfield counts: max {widths[0]}, median {median}")
            print(f"\nrichest entry [{key}] ({len(richest)} fields):")
            print(json.dumps(richest, indent=1, sort_keys=True)[:2000])
        else:
            key = next(iter(payload))
            print(f"\nsample entry [{key}]:")
            print(json.dumps(payload[key], indent=1)[:900])
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
import urllib.error
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

    # Opt-in sync-token auth for the app's own gated endpoints -- the same
    # X-Sync-Token the runner and watchdog hold. Needed to probe
    # /app/data/feeds.json, which is behind the login gate. The token rides
    # in from the workflow secret env and is never echoed.
    if os.environ.get("PROBE_SYNC") == "1":
        sync_token = os.environ.get("SYNC_TOKEN", "")
        if not sync_token:
            print("::error::PROBE_SYNC=1 but no SYNC_TOKEN secret is set")
            return 2
        headers["X-Sync-Token"] = sync_token
        print("(authorized with the sync token)")

    print(f"probing {url}\n")
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status = response.status
            resp_headers = response.headers
            raw = response.read()
    except urllib.error.HTTPError as exc:
        # An error status is still an answer, and its headers are often the
        # whole finding: a 401's cf-cache-status says whether Cloudflare is
        # caching a gated page, which no green watchdog run can reveal.
        status = exc.code
        resp_headers = exc.headers
        raw = exc.read()
    except Exception as exc:  # noqa: BLE001 - the failure IS the finding
        print(f"::error::{type(exc).__name__}: {exc}")
        return 1

    print(f"HTTP {status} · {len(raw):,} bytes\n")
    # A fixed allowlist rather than "print them all": headers carry cookies
    # and tokens, and never-log-a-token binds this script too. These name
    # who served the response and whether anything in the path cached it.
    caching = (
        "content-type",
        "cache-control",
        "age",
        "etag",
        "last-modified",
        "cf-cache-status",
        "cf-ray",
        "x-vercel-cache",
        "x-vercel-id",
        "server",
        "via",
    )
    for name in caching:
        value = resp_headers.get(name)
        if value:
            print(f"  {name}: {value}")
    print()
    print(f"  body bytes: {len(raw):,}")
    # Strict, browser-equivalent parse. Python's json.loads accepts the
    # literals NaN, Infinity and -Infinity (via parse_constant); a browser's
    # JSON.parse rejects all three and throws. So a response Python calls
    # "valid JSON" can be one the app's fetch(...).then(r => r.json())
    # silently rejects into its .catch, leaving the page on its seed data
    # while a raw NAVIGATION to the same URL (which never parses) looks
    # fine. This is the one check that tells them apart.
    def _reject(tok: str) -> None:
        raise ValueError(f"non-standard JSON literal: {tok}")

    try:
        json.loads(raw, parse_constant=_reject)
        print("  strict JSON (browser JSON.parse): OK")
    except ValueError as exc:
        print(f"  ::error::strict JSON (browser JSON.parse) FAILS: {exc}")
        print("  -> a browser's fetch().json() rejects this; the page keeps its seed data")
    print()
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
    # A LIST of dicts gets the same census, one level down into whichever
    # sub-dict PROBE_KEY names. Sleeper's projections arrive that way --
    # 3,113 rows each carrying a `stats` object -- and the field names in
    # that object are the whole question: they decide whether the existing
    # league scorer can read a projection line at all, and a name that is
    # merely close scores a silent zero.
    if os.environ.get("PROBE_MODE") == "fields" and isinstance(payload, list):
        inner = os.environ.get("PROBE_KEY") or ""
        counts: dict[str, int] = {}
        entries = 0
        for item in payload:
            if not isinstance(item, dict):
                continue
            target = item.get(inner) if inner else item
            if isinstance(target, dict):
                entries += 1
                for field in target:
                    counts[field] = counts.get(field, 0) + 1
        label = f"{inner}." if inner else ""
        print(f"field census across {entries} list entries ({len(counts)} distinct {label}fields):")
        for field, n in sorted(counts.items()):
            print(f"  {label}{field}: {n}")
        return 0

    if os.environ.get("PROBE_MODE") == "fields" and isinstance(payload, dict):
        counts = {}
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

    # One named entry, in full. The shape view below picks the *richest*
    # entry, which on a mixed payload is whichever population happens to
    # carry the most fields -- no help when the question is about a
    # smaller population sharing the same dict. Sleeper's season stats are
    # exactly that: 8,179 numeric player keys, 32 "TEAM_XXX" offense keys
    # and 32 bare team codes carrying team DEFENSE/special-teams
    # aggregates. Asking for "DET" is the only way to see the third.
    wanted = os.environ.get("PROBE_KEY") or ""
    if wanted and isinstance(payload, dict):
        entry = payload.get(wanted)
        if entry is None:
            near = [k for k in payload if wanted.lower() in str(k).lower()][:10]
            print(f"::error::no key {wanted!r}. Similar keys: {near}")
            return 1
        if isinstance(entry, dict):
            print(f"entry [{wanted}] ({len(entry)} fields):")
            for field in sorted(entry):
                print(f"  {field}: {entry[field]}")
        else:
            print(f"entry [{wanted}]: {str(entry)[:MAX_VALUE_CHARS]}")
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

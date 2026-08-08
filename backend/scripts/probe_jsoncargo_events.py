"""Does JSONCargo expose the full event history anywhere? Probe, do not guess.

Prints the HTTP status and whether the body carries a list of movements, for each candidate
path. A handful of quota calls, reported honestly.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import jsoncargo  # noqa: E402

BOX = os.environ.get("BOX", "MRKU3210827")
BOL = os.environ.get("BOL", "272520178")
LINE = "MAERSK"

CANDIDATES = [
    (f"/containers/{BOX}/events/", {"shipping_line": LINE}),
    (f"/containers/{BOX}/movements/", {"shipping_line": LINE}),
    (f"/containers/{BOX}/history/", {"shipping_line": LINE}),
    (f"/containers/{BOX}/tracking/", {"shipping_line": LINE}),
    (f"/containers/{BOX}/", {"shipping_line": LINE, "include": "events"}),
    (f"/containers/{BOX}/", {"shipping_line": LINE, "detail": "full"}),
    (f"/bol/{BOL}/", {"shipping_line": LINE}),
    (f"/bills-of-lading/{BOL}/", {"shipping_line": LINE}),
    ("/", None),
]


def shape(body):
    """Where, if anywhere, a list of events is hiding."""
    if not isinstance(body, dict):
        return f"{type(body).__name__}"
    hits = []
    for k, v in body.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            hits.append(f"{k}[{len(v)}] keys={sorted(v[0])[:6]}")
    return "; ".join(hits) or f"keys={list(body)[:10]}"


async def main():
    c = jsoncargo.config()
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as x:
        for path, params in CANDIDATES:
            try:
                r = await x.get(f"{c['base']}{path}", params=params or {},
                                headers={"x-api-key": c["key"], "Accept": "application/json"})
                body = r.json() if r.headers.get("content-type", "").startswith(
                    "application/json") else {}
            except Exception as e:
                print(f"{path:52} -> ERROR {type(e).__name__}")
                continue
            note = shape(body.get("data", body)) if r.status_code < 400 else str(
                body.get("message") or body.get("detail") or "")[:70]
            print(f"{path:52} {str(params.get('include') or params.get('detail') or '') if params else '':6} "
                  f"-> HTTP {r.status_code}  {note[:150]}")


if __name__ == "__main__":
    asyncio.run(main())

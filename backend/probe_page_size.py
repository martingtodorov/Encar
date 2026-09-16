"""Does Encar's list endpoint honour a page bigger than 500?

Every leaf of the crawl is one request for up to 500 rows. If 1000 come back WHOLE, the
whole crawl costs half as many requests — but a silently truncated page looks exactly like
a short leaf, which loses cars quietly, so this is measured before anything is turned up.

Run it on a host Encar answers (production, not the preview pod):

    cd /app/backend && python probe_page_size.py            # tries 1000
    cd /app/backend && python probe_page_size.py 750 1000 1500

It makes at most a handful of requests, paced by the client's own floor, and writes nothing.
"""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from encar import encar                      # noqa: E402
import sync                                  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s",
                    stream=sys.stdout)


async def ids(offset, limit):
    data = await encar.search(offset=offset, limit=limit)
    rows = (data or {}).get("SearchResults") or []
    return [str(r.get("Id")) for r in rows if r.get("Id")]


async def main(sizes):
    total = await encar.count()
    if total is None:
        print("Encar did not answer the count request — run this where Encar answers.")
        return 2
    print(f"catalogue upstream: {total} cars\n")

    base = await ids(0, sync.LEAF_MAX)
    print(f"limit={sync.LEAF_MAX:>5}: {len(base):>5} rows, {len(set(base)):>5} distinct  "
          f"(the page size in use today)")
    if len(base) < sync.LEAF_MAX:
        print("  the baseline page came back short — upstream is unwell, try again later")
        return 2

    verdict = {}
    for n in sizes:
        got = await ids(0, n)
        whole = len(got) >= n and len(set(got)) == len(got)
        # The bigger page must also CONTAIN the smaller one: a page that returns the right
        # number of rows from a different sort window is not a bigger page, it is a
        # different query.
        overlap = len(set(base) & set(got))
        verdict[n] = whole and overlap >= len(base) * 0.9
        print(f"limit={n:>5}: {len(got):>5} rows, {len(set(got)):>5} distinct, "
              f"{overlap}/{len(base)} of the first page present  -> "
              f"{'HONOURED' if verdict[n] else 'ignored/truncated'}")

    good = [n for n, ok in verdict.items() if ok]
    print()
    if good:
        best = max(good)
        print(f"Encar honours pages up to {best}. To use it, set in backend/.env:\n"
              f"    ENCAR_LEAF_MAX={best}\n"
              f"and restart the backend. The crawl then needs roughly "
              f"{best // sync.LEAF_MAX}x fewer leaf requests.")
    else:
        print("No size above the current one came back whole — leave ENCAR_LEAF_MAX unset.")
    return 0


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:]] or [1000]
    sys.exit(asyncio.run(main(args)))

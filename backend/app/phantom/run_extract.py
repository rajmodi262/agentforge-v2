"""Batch extraction over every relevant, not-yet-extracted article.

usage: python -m app.phantom.run_extract [limit]
Writes progress to stdout; safe to stop and resume (articles are marked as they finish).
"""

import asyncio
import sys
import time

from app.database import init_db
from app.phantom.extract import extract_article
from app.phantom.llm import model_for
from app.phantom.store import pending_articles, save_mentions


async def main(limit: int) -> None:
    init_db()
    todo = pending_articles(limit)
    t0 = time.time()
    total_mentions = 0
    print(f"extracting {len(todo)} articles with {model_for('fast')}", flush=True)
    for i, a in enumerate(todo, 1):
        t = time.time()
        try:
            r = await extract_article(a["title"], a["text"], str(a["published"]) if a["published"] else None)
            n = await asyncio.to_thread(save_mentions, a["id"], r["mentions"], r["meta"].get("model") or "")
            total_mentions += n
            status = f"{n} mention(s)" + (f", dropped {len(r['dropped'])}" if r["dropped"] else "")
        except Exception as e:  # keep going — one bad article must not stop the batch
            status = f"ERROR {e!r}"[:120]
        el = time.time() - t0
        eta = el / i * (len(todo) - i)
        print(f"[{i}/{len(todo)}] {time.time() - t:5.1f}s  {status:40}  | {a['kind']:7} | {a['title'][:70]}  (eta {eta / 60:.0f} min)", flush=True)
    print(f"DONE {len(todo)} articles, {total_mentions} mentions, {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 1000))

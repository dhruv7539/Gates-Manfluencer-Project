"""Apply content analysis coding-unit schema to scraped scope-relevant tweets.

Takes each *_scope_relevant.xlsx from Scraped Tweets - Nigeria/ and produces a
coding-unit xlsx matching the Kibe_Jagero reference schema:
  Segment ID | Influencer | Platform | Content Type | Theme(s) |
  Context (NOT CODED - comprehension only) | Verbatim Text (CODE THIS)

Uses gpt-4o with batched classification for context + theme generation.
Cached per-creator to avoid re-spending on reruns.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm as atqdm


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY missing"

INPUT_DIR = ROOT / "Scraped Tweets - Nigeria"
OUTPUT_DIR = ROOT / "Content Analysis - Nigeria"
CACHE_DIR = ROOT / "temp" / "content_analysis_scraped"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

LLM_MODEL = "gpt-4o"
BATCH_SIZE = 15
CONCURRENCY = 10

CREATORS = {
    "Deyemi Okanlawon": {"orientation": "Progressive", "platform": "X (Twitter)", "content_type": "Social Post / Tweet"},
    "Agba John Doe":    {"orientation": "Regressive",  "platform": "X (Twitter)", "content_type": "Social Post / Tweet"},
    "Shola":            {"orientation": "Regressive",  "platform": "X (Twitter)", "content_type": "Social Post / Tweet"},
    "Wizarab":          {"orientation": "Regressive",  "platform": "X (Twitter)", "content_type": "Social Post / Tweet"},
}

SYSTEM_PROMPT = """You are a qualitative research assistant preparing coding units from Nigerian creator tweets for a masculinity and gender study.

You will receive a batch of N short social posts (tweets) by one creator. For each post, return metadata to support human content coders — context for comprehension, and themes for aggregate analysis.

## Rules
- Do NOT change the text. The verbatim text is already fixed in the downstream file; you only produce metadata.
- Provide `context`: ONE sentence (max 25 words), neutral third person, wrapped in square brackets. Example: "[Wizarab argues that women, not men, are the root cause of extramarital affairs.]"
- Provide `themes`: list of 2–4 short multi-word tags relevant to masculinity / gender studies (e.g., "Marriage endurance", "Provider anxiety", "Female sexuality framing", "Male accountability", "Rape discourse", "Faith-framed masculinity"). Not single words.
- Themes should be analytically specific — describe the mechanism or claim, not just the topic.

Return ONLY a JSON object: {"results": [{"id": <int>, "context": "[...]", "themes": ["...", "..."]}]}. Output nothing else."""


def _cache_key(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


async def annotate_batch(batch, creator, orientation, sem, async_client):
    async with sem:
        lines = [f"Creator: {creator}  |  Orientation: {orientation}", "", "Tweets:"]
        for i, text in batch:
            lines.append(f"[{i}] {str(text)[:400]}")
        user = "\n".join(lines)
        for attempt in range(3):
            try:
                resp = await async_client.chat.completions.create(
                    model=LLM_MODEL,
                    temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user},
                    ],
                )
                data = json.loads(resp.choices[0].message.content)
                out = {}
                for r in data.get("results", []):
                    lid = r.get("id")
                    if lid is not None:
                        out[lid] = {
                            "context": r.get("context", ""),
                            "themes": r.get("themes", []),
                        }
                return out
            except Exception:
                await asyncio.sleep(2 ** attempt)
        return {i: {"context": "", "themes": []} for i, _ in batch}


async def annotate_all(texts, creator, orientation):
    async_client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = []
    for start in range(0, len(texts), BATCH_SIZE):
        chunk = list(enumerate(texts[start:start + BATCH_SIZE], start=start))
        tasks.append(asyncio.create_task(annotate_batch(chunk, creator, orientation, sem, async_client)))
    merged = {}
    for fut in atqdm.as_completed(tasks, total=len(tasks), desc=f"{creator[:20]:<20}"):
        merged.update(await fut)
    return merged


def _safe(name):
    return re.sub(r"[^\w\- ]+", "", name).strip()


def process_creator(creator, meta):
    in_path = INPUT_DIR / f"{creator}_scope_relevant.xlsx"
    if not in_path.exists():
        print(f"  skip {creator}: no input file")
        return None

    df = pd.read_excel(in_path)
    texts = df["text"].astype(str).tolist()

    # Check cache
    cache_path = CACHE_DIR / f"{_safe(creator)}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if len(cached) == len(texts):
            annotations = {int(k): v for k, v in cached.items()}
            print(f"  [{creator}] loaded {len(annotations)} cached annotations")
        else:
            annotations = None
    else:
        annotations = None

    if annotations is None:
        print(f"  [{creator}] annotating {len(texts)} tweets with gpt-4o...")
        annotations = asyncio.run(annotate_all(texts, creator, meta["orientation"]))
        cache_path.write_text(json.dumps({str(k): v for k, v in annotations.items()}))

    # Build coding units df
    rows = []
    for i, text in enumerate(texts):
        a = annotations.get(i, {"context": "", "themes": []})
        rows.append({
            "Segment ID": i + 1,
            "Influencer": creator,
            "Platform": meta["platform"],
            "Content Type": meta["content_type"],
            "Theme(s)": "; ".join(a.get("themes", [])),
            "Context (NOT CODED - comprehension only)": a.get("context", ""),
            "Verbatim Text (CODE THIS)": text,
        })
    out_df = pd.DataFrame(rows)

    out_dir = OUTPUT_DIR / _safe(creator)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_safe(creator)}_Coding_Units_Scraped.xlsx"
    out_df.to_excel(out_path, index=False)
    print(f"  [{creator}] wrote {len(out_df)} coding units to {out_path.relative_to(ROOT)}")
    return {"creator": creator, "units": len(out_df), "path": str(out_path.relative_to(ROOT))}


def main():
    rows = []
    for creator, meta in CREATORS.items():
        r = process_creator(creator, meta)
        if r:
            rows.append(r)

    summary = pd.DataFrame(rows)
    (OUTPUT_DIR / "_summary_scraped.xlsx").write_bytes(b"")
    summary.to_excel(OUTPUT_DIR / "_summary_scraped.xlsx", index=False)
    print("\n=== SCRAPED CONTENT CODING SUMMARY ===")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()

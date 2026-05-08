"""Backfill the 3 regressive creators (Shola/Wizarab/Agba) from their raw scrapes.

Target: push the project total ≥ 400 snippets while preserving the regressive
character of each file.

Per tweet:
  - Accept if it is on-scope masculinity content AND matches at least one
    regressive masculinity pattern (or is neutral observation about gender).
  - Reject if it is clearly progressive content (would contaminate the file).
  - Reject if off-scope (motivational, business promo, generic politics).
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm as atqdm


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
RAW   = ROOT / "Nigeria" / "Content Analysis" / "Content - Raw"
FINAL = ROOT / "Nigeria" / "Content Analysis" / "Content - Final"
LLM_MODEL   = "gpt-4o"
CONCURRENCY = 6

CREATORS = [
    {"name": "Agba John Doe", "raw": "Agba John Doe/Agba John Doe_Twitter_Raw.xlsx",
     "final": "Agba John Doe_Twitter.xlsx", "prefix": "AGB",
     "platform": "X", "ctype": "Tweet"},
    {"name": "Shola", "raw": "Shola/Shola_Twitter_Raw.xlsx",
     "final": "Shola_Twitter.xlsx", "prefix": "SHO",
     "platform": "X", "ctype": "Tweet"},
    {"name": "Wizarab", "raw": "Wizarab/Wizarab_Twitter_Raw.xlsx",
     "final": "Wizarab_Twitter.xlsx", "prefix": "WIZ",
     "platform": "X", "ctype": "Tweet"},
]

PROMPT = """You are filtering tweets for {name}, a REGRESSIVE Nigerian masculinity creator (soft patriarchy / scarcity narrative / manosphere-adjacent).

ACCEPT if the tweet is:
  - on-scope masculinity / gender content (marriage, dating, women, sex, fatherhood, money/provider, female sexuality, female submission, gender debate, hypergamy, simping, body count, infidelity, polygamy, sexual ethics, male grievance, women-as-transactional, anti-feminism)
  - AND the stance is either REGRESSIVE (typical for this creator) or NEUTRAL observation
  - AND it stands alone enough to be coded (does not require a missing parent tweet)

HARD REJECT if the tweet is CLEARLY PROGRESSIVE in stance — e.g.:
  - explicitly anti-rape culture / pro-consent (in a way that contradicts the creator's usual frame)
  - male accountability for misogyny that calls out fellow regressive men
  - pro-female-agency / pro-equality
  - destigmatising men seeking therapy in a non-victimhood way
  - critiquing patriarchy

ALSO REJECT (out of scope):
  - hustle / motivational without gender frame
  - business / book / event promo, link-only intros, "Read!" thread teasers
  - generic Nigerian politics / japa / fuel / election (unless gender angle)
  - food, sports, weather, birthday, condolence, RIP
  - replies whose meaning depends on missing parent tweet
  - religious-only with no gender frame
  - vague one-liners (< 8 substantive words)
  - mid-thread fragments starting in the middle of a sentence

TWEET:
\"\"\"{text}\"\"\"

JSON only:
{{"on_scope": true | false,
  "stance": "regressive" | "progressive" | "neutral" | "n/a",
  "accept": true | false,
  "theme": "<short label if accepted>",
  "reason": "<one short sentence>"}}"""

CTX_PROMPT = """One concise sentence (max 25 words) describing what this tweet is about, for a research coder unfamiliar with Nigerian context. Note any Pidgin / Yoruba / Nigerian references the coder might miss.

TWEET:
\"\"\"{text}\"\"\"

JSON only: {{"context": "..."}}"""


async def call_llm(client, sem, prompt):
    async with sem:
        for attempt in range(5):
            try:
                resp = await client.chat.completions.create(
                    model=LLM_MODEL, temperature=0,
                    response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": prompt}],
                )
                return json.loads(resp.choices[0].message.content)
            except Exception as e:
                err = str(e)
                if "429" in err or "rate" in err.lower():
                    await asyncio.sleep(5 * (2 ** attempt))
                    continue
                if attempt == 4:
                    return {}
                await asyncio.sleep(2 ** attempt)


async def process_creator(creator, client, sem):
    raw   = pd.read_excel(RAW / creator['raw'])
    final = pd.read_excel(FINAL / creator['final'])
    raw['t'] = raw['text'].astype(str).str.strip()
    final_texts = set(final['Verbatim Text (CODE THIS)'].astype(str).str.strip())
    cands = raw[~raw['t'].isin(final_texts)].copy()
    cands = cands[cands['t'].str.split().apply(len) >= 8].reset_index(drop=True)
    print(f"\n=== {creator['name']} ===  raw={len(raw)}  final={len(final)}  candidates={len(cands)}", flush=True)

    coros = [call_llm(client, sem, PROMPT.format(name=creator['name'], text=str(t)[:1500]))
             for t in cands['t']]
    results = await atqdm.gather(*coros, desc=creator['name'][:15])

    accepted = []
    drop_progressive = drop_offscope = 0
    for i, r in enumerate(results):
        if r.get("accept") is True:
            accepted.append({"text": str(cands.iloc[i]['t']),
                             "theme": r.get("theme", ""),
                             "reason": r.get("reason", "")})
        elif r.get("stance") == "progressive":
            drop_progressive += 1
        else:
            drop_offscope += 1
    print(f"  accept={len(accepted)}  drop_progressive={drop_progressive}  drop_offscope={drop_offscope}", flush=True)

    if not accepted:
        return 0

    ctx_coros = [call_llm(client, sem, CTX_PROMPT.format(text=a['text'][:1500])) for a in accepted]
    ctx_results = await atqdm.gather(*ctx_coros, desc=f"{creator['name'][:10]}-ctx")

    new_rows = [{
        "Segment ID": "PENDING",
        "Influencer": creator['name'],
        "Platform":   creator['platform'],
        "Content Type": creator['ctype'],
        "Context (NOT CODED - comprehension only)": c.get("context", a.get("reason", "")),
        "Verbatim Text (CODE THIS)": a['text'],
    } for a, c in zip(accepted, ctx_results)]
    new_df = pd.DataFrame(new_rows)

    combined = pd.concat([final, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["Verbatim Text (CODE THIS)"], keep="first").reset_index(drop=True)
    combined['Segment ID'] = [f"{creator['prefix']}_{i+1:03d}" for i in range(len(combined))]
    combined.to_excel(FINAL / creator['final'], index=False)
    added = len(combined) - len(final)
    print(f"  → {creator['final']}: {len(final)} → {len(combined)} (+{added})", flush=True)
    return added


async def main():
    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)
    total_added = 0
    for c in CREATORS:
        total_added += await process_creator(c, client, sem)
    print(f"\n=== TOTAL ADDED: {total_added} ===", flush=True)
    grand = sum(len(pd.read_excel(p)) for p in sorted(FINAL.glob('*.xlsx')))
    print(f"=== PROJECT TOTAL: {grand} ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

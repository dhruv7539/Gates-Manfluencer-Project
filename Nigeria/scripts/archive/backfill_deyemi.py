"""Backfill Deyemi_Twitter.xlsx with scope-relevant tweets from the raw scrape.

After ChatGPT's review the Final file is down to 18 rows — too thin for content
analysis. The raw scrape has 135 tweets; 117 are not yet in Final. This script
sends each candidate to gpt-4o with Deyemi's specific progressive-masculinity
scope (male accountability, rape culture, victim stigma, consent, false-
accusation debate, male trauma, fatherhood, provider pressure, male emotional
life, mental health, masculinity-Christianity intersection) and keeps the ones
that are clearly in scope.

Output: appends accepted candidates to Final, re-issues contiguous Segment IDs.
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
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY missing"

RAW_PATH   = ROOT / "Nigeria" / "Content Analysis" / "Content - Raw" / "Deyemi Okanlawon" / "Deyemi Okanlawon_Twitter_Raw.xlsx"
FINAL_PATH = ROOT / "Nigeria" / "Content Analysis" / "Content - Final" / "Deyemi Okanlawon_Twitter.xlsx"

LLM_MODEL = "gpt-4o"
CONCURRENCY = 4

SCOPE_PROMPT = """You are filtering tweets from Deyemi Okanlawon — a Nigerian PROGRESSIVE male voice (actor, dad of three, vocal on rape culture, male accountability, male emotional life, victim protection).

A tweet is IN-SCOPE for the Norman Lear Center / Gates Foundation Nigeria masculinity content analysis if it directly engages ANY of:
- male accountability / men holding men accountable
- rape culture, consent, sexual violence, victim-blaming, victim protection
- false accusation discourse / due process for men
- male emotional life, vulnerability, mental health, therapy, trauma
- fatherhood, raising boys, parenting, father absence
- marriage, partnership, domestic dynamics, divorce
- provider pressure, men + money, financial expectations on men
- gender debate / feminism / "men vs women" online discourse
- masculinity + faith / Christian framing of manhood
- sexual ethics, dating standards, double standards
- protection of women / children / vulnerable men
- defending or critiquing male behaviour as a category

A tweet is OUT-OF-SCOPE if:
- pure joke / meme with no gender content
- generic motivational / hustle / self-improvement (no gender frame)
- general Nigerian politics, japa, economy (unless gender angle)
- entertainment promo, movie/show plug, birthday wish
- pure logistics, replies that need a missing parent tweet to make sense
- religious-only content with no gender frame

TWEET:
\"\"\"{text}\"\"\"

JSON only:
{{"in_scope": true | false,
  "theme": "<one short label e.g. 'male accountability', 'rape culture', 'fatherhood', 'mental health' — leave blank if out of scope>",
  "reason": "<one short sentence>"}}"""

CTX_PROMPT = """One concise sentence (max 25 words) describing what this Deyemi Okanlawon tweet is about, for a research coder unfamiliar with Nigerian context. Note any Pidgin / Yoruba / Nigerian references the coder might miss.

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


async def main():
    raw = pd.read_excel(RAW_PATH)
    final = pd.read_excel(FINAL_PATH)
    final_texts = set(final["Verbatim Text (CODE THIS)"].astype(str).str.strip())
    raw["text_strip"] = raw["text"].astype(str).str.strip()
    candidates = raw[~raw["text_strip"].isin(final_texts)].reset_index(drop=True)
    print(f"=== Deyemi backfill ===", flush=True)
    print(f"  raw={len(raw)}  final={len(final)}  candidates={len(candidates)}", flush=True)

    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    # Pass 1: scope filter
    print(f"\n  pass 1: scope filter ({len(candidates)} gpt-4o calls)…", flush=True)
    scope_coros = [call_llm(client, sem, SCOPE_PROMPT.format(text=str(t)[:1500]))
                   for t in candidates["text"]]
    scope_results = await atqdm.gather(*scope_coros, desc="scope")

    accepted = []
    for i, r in enumerate(scope_results):
        if r.get("in_scope") is True:
            row = candidates.iloc[i]
            accepted.append({
                "text": str(row["text"]),
                "theme": r.get("theme", ""),
                "reason": r.get("reason", ""),
                "tweet_link": row.get("tweet_link"),
            })
    print(f"  accepted: {len(accepted)} / {len(candidates)}", flush=True)

    if not accepted:
        print("  nothing to add.", flush=True)
        return

    # Pass 2: generate context per accepted
    print(f"\n  pass 2: generating context notes ({len(accepted)} gpt-4o calls)…", flush=True)
    ctx_coros = [call_llm(client, sem, CTX_PROMPT.format(text=a["text"][:1500])) for a in accepted]
    ctx_results = await atqdm.gather(*ctx_coros, desc="context")

    # Build new rows
    new_rows = []
    for a, c in zip(accepted, ctx_results):
        new_rows.append({
            "Segment ID": "PENDING",
            "Influencer": "Deyemi Okanlawon",
            "Platform": "X",
            "Content Type": "Tweet",
            "Context (NOT CODED - comprehension only)": c.get("context", a.get("reason", "")),
            "Verbatim Text (CODE THIS)": a["text"],
        })
    new_df = pd.DataFrame(new_rows)

    # Combine + re-issue IDs
    combined = pd.concat([final, new_df], ignore_index=True)
    # Drop exact-duplicate verbatim text (defensive)
    combined = combined.drop_duplicates(subset=["Verbatim Text (CODE THIS)"], keep="first").reset_index(drop=True)
    combined["Segment ID"] = [f"DEY_{i+1:03d}" for i in range(len(combined))]
    combined.to_excel(FINAL_PATH, index=False)
    print(f"\n  → {FINAL_PATH.relative_to(ROOT)}: {len(final)} → {len(combined)} rows (+{len(combined)-len(final)})", flush=True)

    # Print themes summary
    from collections import Counter
    theme_counts = Counter(a["theme"] for a in accepted)
    print(f"\n  theme breakdown of additions:", flush=True)
    for theme, count in theme_counts.most_common():
        print(f"    {count:>3}  {theme}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

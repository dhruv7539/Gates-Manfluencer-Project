"""Backfill Deyemi from the 6,311-tweet Apify scrape (Jan 2020 → Nov 2025).

Pipeline:
  1. Read Apify export, dedup, dedup against current Final.
  2. Drop pure-RTs, URL-only, ultra-short.
  3. Broad keyword pre-filter → ~485 candidates.
  4. gpt-4o scope filter on each candidate (in_scope: true/false + theme).
  5. gpt-4o context note for each accepted.
  6. Append to Final, re-issue contiguous Segment IDs.

Strict scope per ChatGPT's review of Deyemi: progressive masculinity, male
accountability, rape culture/consent/victim protection, false-accusation
discourse, male trauma/mental health, fatherhood, marriage/relationships,
provider pressure, gender debate.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm as atqdm


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY missing"

APIFY_PATH = Path("/Users/sushildalavi/Downloads/dataset_advanced-x-twitter-profile-scraper_2026-04-30_06-33-28-572.xlsx")
FINAL_PATH = ROOT / "Nigeria" / "Content Analysis" / "Content - Final" / "Deyemi Okanlawon_Twitter.xlsx"

LLM_MODEL = "gpt-4o"
CONCURRENCY = 5

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
- Nollywood / movie / show / music / business promo
- generic motivational / hustle / self-improvement (no gender frame)
- general Nigerian politics, japa, economy, fuel, election (UNLESS gender angle)
- food, sports, weather, birthday wish, condolence, RIP
- pure logistics / replies that need a missing parent tweet to make sense
- religious-only content with no gender frame
- celebrity gossip without gender frame
- vague one-liners

Be STRICT. The tweet must contain a clear masculinity / gender claim or argument by itself. If you would have to guess at the parent tweet to interpret it, mark out-of-scope.

TWEET:
\"\"\"{text}\"\"\"

JSON only:
{{"in_scope": true | false,
  "theme": "<one short label e.g. 'male accountability', 'rape culture', 'fatherhood', 'mental health', 'marriage', 'gender debate' — leave blank if out of scope>",
  "reason": "<one short sentence>"}}"""

CTX_PROMPT = """One concise sentence (max 25 words) describing what this Deyemi Okanlawon tweet is about, for a research coder unfamiliar with Nigerian context. Note any Pidgin / Yoruba / Nigerian references the coder might miss.

TWEET:
\"\"\"{text}\"\"\"

JSON only: {{"context": "..."}}"""


KW = re.compile(
    r"\b("
    r"man|men|woman|women|wife|wives|husband|husbands|girl|boy|girls|boys|"
    r"father|fatherhood|dad|daddy|mom|mama|mother|son|sons|daughter|"
    r"marriage|marry|married|divorce|relationship|relationships|partner|spouse|"
    r"rape|rapist|consent|victim|survivor|abuse|abuser|abused|assault|"
    r"accountability|accountable|toxic|patriarchy|feminism|feminist|misogyny|"
    r"masculin|manhood|womanhood|gender|sexism|sexist|"
    r"therapy|trauma|depress|suicide|suicidal|cry|tears|vulnerab|emotion|"
    r"provider|provide|breadwinner|hustle|"
    r"dating|date|hookup|knack|knacking|"
    r"defamat|stigma|shame|shaming|"
    r"sex|sexual|sexuality|infidelity|cheat|cheating|cheater|"
    r"virgin|virginity|"
    r"male|female|"
    r"polygam|polyandr|monogam|"
    r"adesua|"
    r"bro|guy|guys|sis|sister|"
    r"responsibility|protect|leader|"
    r"abeg|na|wahala"
    r")\b",
    re.IGNORECASE,
)


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
    print("=== Deyemi backfill v2 (Apify 6311-tweet scrape) ===", flush=True)
    df = pd.read_excel(APIFY_PATH)
    final = pd.read_excel(FINAL_PATH)

    df = df.dropna(subset=['fullText']).copy()
    df['text'] = df['fullText'].astype(str).str.strip()
    df = df[df['text'] != '']
    df = df.drop_duplicates(subset='text').reset_index(drop=True)

    final_texts = set(final['Verbatim Text (CODE THIS)'].astype(str).str.strip())
    df = df[~df['text'].isin(final_texts)].reset_index(drop=True)

    df['n_words'] = df['text'].str.split().apply(len)
    df = df[df['n_words'] >= 8].reset_index(drop=True)
    df = df[~df['text'].str.startswith('RT @')].reset_index(drop=True)
    df = df[~df['text'].str.match(r'^https?://\S+\s*$')].reset_index(drop=True)

    df['has_kw'] = df['text'].str.contains(KW, regex=True, na=False)
    candidates = df[df['has_kw']].reset_index(drop=True)
    print(f"  apify rows after dedup/clean: {len(df)}", flush=True)
    print(f"  keyword-matching candidates:  {len(candidates)}", flush=True)

    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    print(f"\n  pass 1: scope filter ({len(candidates)} gpt-4o calls)…", flush=True)
    scope_coros = [call_llm(client, sem, SCOPE_PROMPT.format(text=str(t)[:1500]))
                   for t in candidates['text']]
    scope_results = await atqdm.gather(*scope_coros, desc="scope")

    accepted = []
    for i, r in enumerate(scope_results):
        if r.get("in_scope") is True:
            row = candidates.iloc[i]
            accepted.append({
                "text": str(row['text']),
                "theme": r.get("theme", ""),
                "reason": r.get("reason", ""),
                "tweetUrl": row.get('tweetUrl'),
                "createdAt": row.get('createdAt'),
            })
    print(f"  accepted: {len(accepted)} / {len(candidates)}", flush=True)

    if not accepted:
        return

    print(f"\n  pass 2: context notes ({len(accepted)} gpt-4o calls)…", flush=True)
    ctx_coros = [call_llm(client, sem, CTX_PROMPT.format(text=a['text'][:1500])) for a in accepted]
    ctx_results = await atqdm.gather(*ctx_coros, desc="context")

    new_rows = [{
        "Segment ID": "PENDING",
        "Influencer": "Deyemi Okanlawon",
        "Platform":   "X",
        "Content Type": "Tweet",
        "Context (NOT CODED - comprehension only)": c.get("context", a.get("reason", "")),
        "Verbatim Text (CODE THIS)": a['text'],
    } for a, c in zip(accepted, ctx_results)]
    new_df = pd.DataFrame(new_rows)

    combined = pd.concat([final, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["Verbatim Text (CODE THIS)"], keep="first").reset_index(drop=True)
    combined['Segment ID'] = [f"DEY_{i+1:03d}" for i in range(len(combined))]
    combined.to_excel(FINAL_PATH, index=False)

    print(f"\n  → {FINAL_PATH.relative_to(ROOT)}: {len(final)} → {len(combined)} (+{len(combined)-len(final)})", flush=True)

    from collections import Counter
    counts = Counter(a['theme'] for a in accepted)
    print(f"\n  theme breakdown of additions:", flush=True)
    for theme, count in counts.most_common():
        print(f"    {count:>3}  {theme}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

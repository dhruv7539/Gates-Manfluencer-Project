"""Deyemi v3 — broader on-scope acceptance with hard regressive-pattern rejection.

v1 strict progressive: 0 accepts. v2 strict 2-stage: 5 accepts. v3 widens the
gate: accept any on-scope masculinity content (fatherhood, marriage, men's
emotional life, gender debate, consent, accountability), but HARD REJECT if
the tweet matches any of the regressive patterns we caught in the orientation
audit. This produces content suitable for content analysis without
re-introducing the contradictions.
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
APIFY_PATH = Path("/Users/sushildalavi/Downloads/dataset_advanced-x-twitter-profile-scraper_2026-04-30_06-33-28-572.xlsx")
FINAL_PATH = ROOT / "Nigeria" / "Content Analysis" / "Content - Final" / "Deyemi Okanlawon_Twitter.xlsx"
LLM_MODEL   = "gpt-4o"
CONCURRENCY = 6

PROMPT = """You are filtering tweets from Deyemi Okanlawon for a Nigerian masculinity content analysis (Norman Lear Center / Gates Foundation).

ACCEPT if the tweet is ON-SCOPE for masculinity / gender content. On-scope themes:
  - fatherhood, raising boys, parenting decisions
  - marriage, partnership, household dynamics
  - men's mental health, vulnerability, therapy, emotional life
  - male accountability, calling out men's behaviour
  - rape culture, consent, sexual violence, victim protection
  - gender debate, feminism, equality, "men vs women" online
  - provider role, financial expectations on men
  - male friendship, brotherhood, male caregiving
  - sexual ethics, dating, double standards
  - critique of toxic masculinity OR critique of patriarchy

HARD REJECT if the tweet matches any REGRESSIVE pattern (these contaminate a progressive dataset):
  - "men are tired", "men suffer too", "the world kills men", "men are dying" (male-victimhood framing)
  - divorce-alimony complaints, "what about my money/assets/half"
  - "men are scum" sarcastic deflection or whataboutism
  - mocking male DV victims (e.g. "his roadside slap is waiting")
  - mocking male emotional expression (e.g. "small tap you dey cry")
  - provider-supremacy framings (even tongue-in-cheek)
  - "if she does it too" / "but when women do it" gotchas
  - feminist-mocking, "modern women" complaints
  - "high-value man / man-child" hierarchies
  - hypergamy resentment, women-as-transactional

ALSO REJECT (out of scope):
  - Nollywood/movie/show/music/business promo
  - generic motivational without gender frame
  - Nigerian politics / japa / fuel / election (unless gender angle)
  - food, sports, weather, birthday, condolence, RIP
  - replies whose meaning depends on missing parent tweet
  - religious-only with no gender frame
  - vague one-liners

TWEET:
\"\"\"{text}\"\"\"

JSON only:
{{"on_scope": true | false,
  "regressive_pattern": true | false,
  "accept": true | false,
  "theme": "<short label if accepted; blank otherwise>",
  "reason": "<one short sentence>"}}"""

CTX_PROMPT = """One concise sentence (max 25 words) describing what this Deyemi Okanlawon tweet is about, for a research coder unfamiliar with Nigerian context. Note Pidgin / Yoruba.

TWEET:
\"\"\"{text}\"\"\"

JSON only: {{"context": "..."}}"""


KW = re.compile(
    r"\b("
    r"man|men|woman|women|wife|wives|husband|husbands|girl|boy|girls|boys|"
    r"father|fatherhood|dad|daddy|mom|mama|mother|son|sons|daughter|daughters|"
    r"marriage|marry|married|divorce|relationship|partner|spouse|"
    r"rape|rapist|consent|victim|survivor|abuse|abuser|abused|assault|"
    r"accountab|toxic|patriarchy|feminism|feminist|misogyny|"
    r"masculin|manhood|womanhood|gender|sexism|sexist|"
    r"therapy|trauma|depress|suicid|cry|tears|vulnerab|emotion|"
    r"provider|breadwinner|"
    r"defamat|stigma|shame|"
    r"sex|sexual|infidelity|cheat|"
    r"male|female|"
    r"adesua|"
    r"protect|leader|"
    r"speak\s+up|silent|silenc|listen|hear|believe|"
    r"brother|brotherhood|friendship"
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
    print("=== Deyemi v3 broad on-scope, hard regressive-reject ===", flush=True)
    final = pd.read_excel(FINAL_PATH)
    print(f"  current rows: {len(final)}", flush=True)

    df = pd.read_excel(APIFY_PATH).dropna(subset=['fullText']).copy()
    df['text'] = df['fullText'].astype(str).str.strip()
    df = df[df['text'] != ''].drop_duplicates(subset='text').reset_index(drop=True)

    final_texts = set(final['Verbatim Text (CODE THIS)'].astype(str).str.strip())
    df = df[~df['text'].isin(final_texts)].reset_index(drop=True)

    df['n_words'] = df['text'].str.split().apply(len)
    df = df[df['n_words'] >= 8].reset_index(drop=True)
    df = df[~df['text'].str.startswith('RT @')].reset_index(drop=True)
    df = df[~df['text'].str.match(r'^https?://\S+\s*$')].reset_index(drop=True)
    df['has_kw'] = df['text'].str.contains(KW, regex=True, na=False)
    candidates = df[df['has_kw']].reset_index(drop=True)
    print(f"  candidates: {len(candidates)}", flush=True)

    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    print(f"\n  pass 1: on-scope + reject-regressive ({len(candidates)} gpt-4o calls)…", flush=True)
    coros = [call_llm(client, sem, PROMPT.format(text=str(t)[:1500])) for t in candidates['text']]
    results = await atqdm.gather(*coros, desc="filter")

    accepted = []
    rej_offscope = rej_regressive = 0
    for i, r in enumerate(results):
        on_s = r.get("on_scope")
        regr = r.get("regressive_pattern")
        if on_s and not regr:
            accepted.append({
                "text":  str(candidates.iloc[i]['text']),
                "theme": r.get("theme", ""),
                "reason": r.get("reason", ""),
            })
        elif on_s and regr:
            rej_regressive += 1
        else:
            rej_offscope += 1
    print(f"  on_scope+not_regressive (accepted): {len(accepted)}", flush=True)
    print(f"  rejected as regressive:             {rej_regressive}", flush=True)
    print(f"  rejected as off-scope:              {rej_offscope}", flush=True)

    if not accepted:
        return

    print(f"\n  pass 2: context notes ({len(accepted)} gpt-4o calls)…", flush=True)
    ctx_coros = [call_llm(client, sem, CTX_PROMPT.format(text=a['text'][:1500])) for a in accepted]
    ctx_results = await atqdm.gather(*ctx_coros, desc="context")

    new_rows = [{
        "Segment ID": "PENDING",
        "Influencer": "Deyemi Okanlawon",
        "Platform": "X",
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
    print(f"\n  theme breakdown:", flush=True)
    for theme, count in counts.most_common(15):
        print(f"    {count:>3}  {theme}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

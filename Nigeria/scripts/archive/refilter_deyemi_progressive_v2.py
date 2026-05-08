"""Re-filter Deyemi v2 — looser progressive accept + strict regressive reject.

The strict v1 rejected all 200 candidates (over-strict on "stand alone").
v2: accept any tweet that LEANS progressive (even if it needs slight context),
but explicitly reject ANY tweet matching the regressive patterns identified
in the orientation audit.

Two-stage decision per tweet:
  Stage A: does it have ANY progressive masculinity content?
  Stage B: does it match a regressive pattern (male victimhood, alimony
           grievance, mocking male DV/tears, men-are-scum deflection,
           provider-supremacy, hypergamy resentment, manosphere hierarchy)?
  Accept iff (A=yes) AND (B=no).
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

PROMPT = """You are filtering tweets from Deyemi Okanlawon for a PROGRESSIVE Nigerian masculinity content analysis.

Two-stage decision:

STAGE A — Does this tweet have any PROGRESSIVE masculinity content?
Examples of progressive content:
  - male accountability for misogyny / abuse / harm
  - anti-rape culture, consent, victim protection (women, children, vulnerable men)
  - male vulnerability, mental health, therapy, breaking emotional silence
  - fatherhood as presence, raising boys to be emotionally healthy
  - calling out other men's bad behaviour
  - critique of toxic masculinity, male privilege, patriarchal expectations
  - pro-equality, supporting women's voices, defending women publicly
  - male caregiving, household labour, emotional labour
  - destigmatising men seeking help

STAGE B — Does this tweet contain ANY of these REGRESSIVE patterns?
  - "men are tired", "men suffer too", "world kills men" (male-victimhood framing without acknowledging female suffering)
  - divorce-alimony complaints, "what about my money/assets"
  - "men are scum" sarcastic deflection or whataboutism
  - mocking male DV victims (e.g. "his roadside slap is waiting")
  - mocking male emotional expression (e.g. "small tap you dey cry")
  - provider-supremacy framings (even tongue-in-cheek, e.g. "may we have more money than our wives")
  - "if she does the same…" / double-standards-cut-both-ways gotchas
  - feminist-mocking, "modern women" complaints
  - "high-value man / man-child" hierarchies
  - hypergamy resentment, women-as-transactional framing

ACCEPT only if (Stage A = yes) AND (Stage B = no).

Out-of-scope (reject regardless):
  - Nollywood/movie/show/music/business promo
  - generic motivational without gender frame
  - Nigerian politics/japa/fuel/election (unless gender angle)
  - food, sports, weather, birthday, condolence, RIP
  - replies whose meaning depends on missing parent tweet
  - religious-only with no gender frame
  - vague one-liners

TWEET:
\"\"\"{text}\"\"\"

JSON only:
{{"stage_a_progressive": true | false,
  "stage_b_regressive_pattern": true | false,
  "accept": true | false,
  "theme": "<short label if accepted; blank otherwise>",
  "reason": "<one short sentence>"}}"""

CTX_PROMPT = """One concise sentence (max 25 words) describing what this Deyemi Okanlawon tweet is about, for a research coder unfamiliar with Nigerian context.

TWEET:
\"\"\"{text}\"\"\"

JSON only: {{"context": "..."}}"""


# Broader keyword pre-filter (semantic-leaning)
KW = re.compile(
    r"\b("
    r"man|men|woman|women|wife|wives|husband|husbands|girl|boy|girls|boys|"
    r"father|fatherhood|dad|daddy|mom|mama|mother|son|sons|daughter|"
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
    r"abeg|na\s+|wahala|"
    r"speak\s+up|silent|silenc|listen|hear|believe"
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
    print("=== Deyemi v2 progressive re-pass ===", flush=True)
    final = pd.read_excel(FINAL_PATH)
    print(f"  current rows: {len(final)}", flush=True)

    df = pd.read_excel(APIFY_PATH).dropna(subset=['fullText']).copy()
    df['text'] = df['fullText'].astype(str).str.strip()
    df = df[df['text'] != ''].drop_duplicates(subset='text').reset_index(drop=True)

    final_texts = set(final['Verbatim Text (CODE THIS)'].astype(str).str.strip())
    df = df[~df['text'].isin(final_texts)].reset_index(drop=True)

    df['n_words'] = df['text'].str.split().apply(len)
    df = df[df['n_words'] >= 10].reset_index(drop=True)
    df = df[~df['text'].str.startswith('RT @')].reset_index(drop=True)
    df = df[~df['text'].str.match(r'^https?://\S+\s*$')].reset_index(drop=True)
    df['has_kw'] = df['text'].str.contains(KW, regex=True, na=False)
    candidates = df[df['has_kw']].reset_index(drop=True)
    print(f"  candidates: {len(candidates)}", flush=True)

    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    print(f"\n  pass 1: 2-stage progressive filter ({len(candidates)} gpt-4o calls)…", flush=True)
    coros = [call_llm(client, sem, PROMPT.format(text=str(t)[:1500])) for t in candidates['text']]
    results = await atqdm.gather(*coros, desc="filter")

    accepted = []
    stats = {"prog_yes_regr_no": 0, "prog_yes_regr_yes": 0, "prog_no": 0}
    for i, r in enumerate(results):
        a = r.get("stage_a_progressive")
        b = r.get("stage_b_regressive_pattern")
        if a and not b:
            stats["prog_yes_regr_no"] += 1
            row = candidates.iloc[i]
            accepted.append({"text": str(row['text']), "theme": r.get("theme", ""), "reason": r.get("reason", "")})
        elif a and b:
            stats["prog_yes_regr_yes"] += 1
        else:
            stats["prog_no"] += 1
    print(f"  stage stats: {stats}", flush=True)
    print(f"  accepted (progressive AND not regressive): {len(accepted)}", flush=True)

    if not accepted:
        return

    # Print samples before saving
    print(f"\n  sample of accepts:", flush=True)
    for a in accepted[:8]:
        print(f"    [{a['theme']}] {a['text'][:160]}", flush=True)

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


if __name__ == "__main__":
    asyncio.run(main())

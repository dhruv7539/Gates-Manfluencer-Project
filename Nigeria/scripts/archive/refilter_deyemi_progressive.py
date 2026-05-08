"""Re-pass Deyemi's full 6,311-tweet Apify scrape with a STRICT progressive-only filter.

Problem: orientation audit flagged 11 Deyemi rows as regressive — male-victimhood
narratives ("this world is designed to kill men"), divorce-alimony complaints,
"men are scum" deflection, mocking male DV victims / male tears. His feed is
genuinely centrist/heterodox.

Goal:
  1. Drop the 11 confirmed regressive contradictions.
  2. Re-filter the 6311-tweet scrape with a STRICTER prompt that ONLY accepts
     clearly progressive content (not "men are tired" framings).
  3. Backfill enough new progressive tweets to push the project total ≥ 400.

Strict progressive criteria:
  - male accountability for misogyny / harm
  - anti-rape culture, consent, victim protection (women + children + men)
  - male vulnerability / mental health WITHOUT male-victimhood framing
  - fatherhood as presence, raising boys to be emotionally healthy
  - critique of toxic masculinity / male privilege
  - pro-equality / pro-female-agency

Reject:
  - "men are tired", "men suffer too" without acknowledging female suffering
  - divorce-alimony / "what about my money" complaints
  - "men are scum" sarcastic deflection
  - mocking male DV victims or male emotional expression
  - provider-supremacy framings even if tongue-in-cheek
  - generic Nigeria politics / Nollywood / japa / off-topic
  - religious-only with no gender frame

Output: appends accepted candidates to Deyemi Final, re-issues IDs.
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

LLM_MODEL   = "gpt-4o"
CONCURRENCY = 6

# 11 contradictions found by orientation audit
CONTRADICTIONS = ['DEY_002','DEY_006','DEY_009','DEY_010','DEY_027','DEY_035',
                  'DEY_037','DEY_040','DEY_043','DEY_047','DEY_048']

PROMPT = """You are filtering tweets from Deyemi Okanlawon for a PROGRESSIVE Nigerian masculinity content analysis (Norman Lear Center / Gates Foundation).

A tweet is ACCEPTED only if it CLEARLY advances PROGRESSIVE masculinity. That means:
  - male accountability for misogyny, abuse, or harm
  - anti-rape culture, consent education, victim protection (women / children / vulnerable men)
  - male vulnerability, mental health, therapy WITHOUT framing men as victims of women/society
  - fatherhood as presence, raising emotionally healthy boys, breaking generational father absence
  - critique of toxic masculinity, male privilege, patriarchal expectations on men
  - pro-equality, pro-female-agency, supporting women's voices
  - calling out other men's bad behaviour
  - destigmatising household labour for men, emotional labour, caregiving

REJECT (these all read regressive even when framed sympathetically toward men):
  - "men are tired", "men suffer too", "this world kills men" without acknowledging female suffering
  - divorce-alimony complaints, "what about my money", anti-divorce-court
  - "men are scum" sarcastic deflection or whataboutism
  - mocking male DV victims, mocking male emotional expression
  - provider-supremacy framings (even tongue-in-cheek)
  - "if she does it too" / double-standards-cut-both-ways gotchas
  - feminist-mocking, "modern women" complaints
  - "high-value man / man-child" hierarchies (manosphere framing)
  - hypergamy resentment

ALSO REJECT (out of scope):
  - Nollywood / movie / show / music / business promo
  - generic motivational / hustle without gender frame
  - Nigerian politics / japa / fuel / election (unless gender angle)
  - food, sports, weather, birthday, condolence
  - replies that need parent-tweet context to interpret
  - religious-only with no gender frame
  - vague one-liners

Be STRICT. The tweet must STAND ALONE as a clearly progressive masculinity statement. If you'd need to argue for it, reject.

TWEET:
\"\"\"{text}\"\"\"

JSON only:
{{"accept": true | false,
  "theme": "<short label e.g. 'male accountability', 'rape culture', 'fatherhood', 'male vulnerability', 'anti-toxic-masculinity'; blank if rejected>",
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
    r"provider|provide|breadwinner|"
    r"defamat|stigma|shame|"
    r"sex|sexual|sexuality|infidelity|cheat|"
    r"male|female|"
    r"adesua|"
    r"responsibility|protect|leader"
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
    print("=== Deyemi STRICT progressive re-pass ===", flush=True)

    final = pd.read_excel(FINAL_PATH)
    print(f"  current rows: {len(final)}", flush=True)

    # Drop the 11 contradictions first
    final_clean = final[~final['Segment ID'].isin(CONTRADICTIONS)].reset_index(drop=True)
    dropped = len(final) - len(final_clean)
    print(f"  dropped {dropped} regressive contradictions → {len(final_clean)}", flush=True)

    # Load full Apify scrape, dedup against current Final
    df = pd.read_excel(APIFY_PATH).dropna(subset=['fullText']).copy()
    df['text'] = df['fullText'].astype(str).str.strip()
    df = df[df['text'] != '']
    df = df.drop_duplicates(subset='text').reset_index(drop=True)

    final_texts = set(final_clean['Verbatim Text (CODE THIS)'].astype(str).str.strip())
    df = df[~df['text'].isin(final_texts)].reset_index(drop=True)

    df['n_words'] = df['text'].str.split().apply(len)
    df = df[df['n_words'] >= 10].reset_index(drop=True)
    df = df[~df['text'].str.startswith('RT @')].reset_index(drop=True)
    df = df[~df['text'].str.match(r'^https?://\S+\s*$')].reset_index(drop=True)
    df['has_kw'] = df['text'].str.contains(KW, regex=True, na=False)
    candidates = df[df['has_kw']].reset_index(drop=True)
    print(f"  apify pool after dedup/clean: {len(df)}", flush=True)
    print(f"  keyword-matching candidates:  {len(candidates)}", flush=True)

    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    print(f"\n  pass 1: STRICT progressive scope ({len(candidates)} gpt-4o calls)…", flush=True)
    coros = [call_llm(client, sem, PROMPT.format(text=str(t)[:1500])) for t in candidates['text']]
    results = await atqdm.gather(*coros, desc="strict")

    accepted = []
    for i, r in enumerate(results):
        if r.get("accept") is True:
            row = candidates.iloc[i]
            accepted.append({
                "text":  str(row['text']),
                "theme": r.get("theme", ""),
                "reason": r.get("reason", ""),
            })
    print(f"  STRICTLY progressive accepts: {len(accepted)} / {len(candidates)}", flush=True)

    if not accepted:
        # Even after dropping contradictions, save cleaned file
        final_clean['Segment ID'] = [f"DEY_{i+1:03d}" for i in range(len(final_clean))]
        final_clean.to_excel(FINAL_PATH, index=False)
        print(f"  no new accepts. wrote cleaned final: {len(final_clean)} rows", flush=True)
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

    combined = pd.concat([final_clean, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["Verbatim Text (CODE THIS)"], keep="first").reset_index(drop=True)
    combined['Segment ID'] = [f"DEY_{i+1:03d}" for i in range(len(combined))]
    combined.to_excel(FINAL_PATH, index=False)
    print(f"\n  → {FINAL_PATH.relative_to(ROOT)}: {len(final)} (was) → {len(final_clean)} (after drop) → {len(combined)} (after backfill)", flush=True)

    from collections import Counter
    counts = Counter(a['theme'] for a in accepted)
    print(f"\n  theme breakdown of new additions:", flush=True)
    for theme, count in counts.most_common():
        print(f"    {count:>3}  {theme}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

"""Finalize Ebuka Obi-Uchendu MENtality content for Content Analysis Final.

Two filtering layers (union of rejections — strictest possible):
  1. My LLM filter+critique pipeline (filter pass + critique pass, both must accept)
  2. ChatGPT's specific drop list from manual review (30 rows + 1 duplicate pair)

A row is ACCEPTED only if BOTH layers accept it.

Then generate context notes and save to:
  Nigeria/Content Analysis/Content - Final/Ebuka Obi-Uchendu_Podcast.xlsx
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY missing"

SRC = ROOT / "temp" / "Ebuka_Obi-Uchendu_RAW_unfiltered_for_review.xlsx"
OUT = ROOT / "Nigeria" / "Content Analysis" / "Content - Final" / "Ebuka Obi-Uchendu_Podcast.xlsx"

LLM_MODEL = "gpt-4o"
CONCURRENCY = 6
BATCH = 24


# ChatGPT's specific drops from manual review
CHATGPT_DROPS = {
    "EBK_012", "EBK_034", "EBK_035", "EBK_038", "EBK_039", "EBK_040", "EBK_041",
    "EBK_042", "EBK_049", "EBK_050", "EBK_052", "EBK_054", "EBK_066", "EBK_067",
    "EBK_072", "EBK_073", "EBK_074", "EBK_075", "EBK_088", "EBK_105", "EBK_106",
    "EBK_116", "EBK_142", "EBK_148", "EBK_149", "EBK_151", "EBK_160", "EBK_161",
    "EBK_167", "EBK_178",
}


SCOPE_PROMPT = """You are filtering a paragraph by Ebuka Obi-Uchendu — host of the MENtality Nigerian podcast about masculinity. Ebuka frames episodes with declarative monologues, raises pointed questions, and takes progressive stances on gender / fatherhood / men's emotional life.

ACCEPT only if the paragraph clearly engages a masculinity / gender theme:
  - male accountability, fatherhood, raising boys, role-modelling
  - marriage as partnership, household dynamics, divorce
  - men's emotional life, vulnerability, mental health
  - provider pressure, men + money expectations
  - gender debate, feminism, equality, "men vs women"
  - sexual ethics, dating, double standards, incel discourse
  - critique of toxic masculinity, "real man" tropes, alpha discourse
  - generational father-son trauma, male role models
  - rape culture, consent, male perpetrators

REJECT if:
  - pure interview transitions / "let's hear from X"
  - thanking guests / podcast logistics / intros / outros
  - pure questions to other panelists with no Ebuka stance
  - off-topic anecdotes (TV shows, celebrities) without gender claim
  - generic motivational without gender frame
  - mid-thought fragments needing prior turn for sense

PARAGRAPH:
\"\"\"{text}\"\"\"

JSON only:
{{"accept": true | false,
  "theme": "<short label if accepted>",
  "reason": "<one short sentence>"}}"""


CRITIQUE_PROMPT = """A first-pass scope filter said this Ebuka Obi-Uchendu paragraph is in-scope for a Nigerian masculinity content analysis.

CHALLENGE that decision. Re-read carefully. Is it 100% scope-relevant — does it make a clear, codable claim or observation about masculinity / men / fatherhood / male emotional life / marriage partnership / gender roles?

REJECT if:
  - the gender claim is implicit / requires inference
  - it's mostly an interview transition, intro, outro, panelist introduction
  - it's mostly a question to a panelist with no Ebuka stance
  - a research coder would have to argue for its scope-relevance
  - it's mostly an anecdote without a clear gender claim

ACCEPT only if the paragraph would obviously code as masculinity content to any researcher.

PARAGRAPH:
\"\"\"{text}\"\"\"

JSON only:
{{"accept": true | false, "reason": "<one short sentence>"}}"""


CTX_PROMPT = """One concise sentence (max 25 words) describing this Ebuka Obi-Uchendu (MENtality podcast host) paragraph for a research coder. Note any Pidgin / Yoruba / Nigerian references.

PARAGRAPH:
\"\"\"{text}\"\"\"

JSON only: {{"context": "..."}}"""


async def call(client, sem, prompt):
    async with sem:
        for attempt in range(6):
            try:
                resp = await client.chat.completions.create(
                    model=LLM_MODEL, temperature=0,
                    response_format={"type":"json_object"},
                    messages=[{"role":"user","content":prompt}],
                )
                return json.loads(resp.choices[0].message.content)
            except Exception as e:
                err = str(e)
                if "429" in err or "rate" in err.lower():
                    await asyncio.sleep(5 * (2 ** attempt))
                    continue
                if attempt == 5:
                    return {}
                await asyncio.sleep(1 + attempt)
        return {}


async def batched_filter(client, sem, items, prompt_fn, label):
    results = []
    for i in range(0, len(items), BATCH):
        batch = items[i:i+BATCH]
        coros = [call(client, sem, prompt_fn(it)) for it in batch]
        batch_res = await asyncio.gather(*coros)
        results.extend(batch_res)
        n_acc = sum(1 for r in results if r and r.get("accept") is True)
        print(f"    [{label}] [{i+len(batch)}/{len(items)}] cumulative accepts: {n_acc}", flush=True)
    return results


async def main():
    print("=== Finalize Ebuka Obi-Uchendu (filter + critique + ChatGPT drops) ===", flush=True)
    df = pd.read_excel(SRC)
    print(f"  loaded {len(df)} unfiltered paragraphs", flush=True)
    print(f"  ChatGPT drop list: {len(CHATGPT_DROPS)} rows to drop", flush=True)

    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    # Pass 1: scope filter (only on rows ChatGPT did NOT already drop — save API calls)
    rows = df.to_dict("records")
    pre_dropped = [r for r in rows if r["Candidate ID"] in CHATGPT_DROPS]
    candidates = [r for r in rows if r["Candidate ID"] not in CHATGPT_DROPS]
    print(f"  ChatGPT pre-drops removed: {len(pre_dropped)}", flush=True)
    print(f"  Candidates entering my filter: {len(candidates)}\n", flush=True)

    # PASS 1: scope filter
    print(f"  Pass 1: scope filter ({len(candidates)} gpt-4o calls)…", flush=True)
    pass1_results = await batched_filter(
        client, sem, candidates,
        lambda r: SCOPE_PROMPT.format(text=r["Verbatim Text (CODE THIS)"]),
        "scope"
    )
    pass1_accepts = [(r, res.get("theme",""), res.get("reason","")) for r, res in zip(candidates, pass1_results) if res and res.get("accept") is True]
    print(f"  Pass 1 accepts: {len(pass1_accepts)} / {len(candidates)}\n", flush=True)

    if not pass1_accepts:
        return

    # PASS 2: critique pass
    print(f"  Pass 2: critique pass ({len(pass1_accepts)} gpt-4o calls)…", flush=True)
    crit_results = await batched_filter(
        client, sem, pass1_accepts,
        lambda a: CRITIQUE_PROMPT.format(text=a[0]["Verbatim Text (CODE THIS)"]),
        "crit"
    )
    accepted = [a for a, c in zip(pass1_accepts, crit_results) if c and c.get("accept") is True]
    print(f"  Pass 2 unanimous accepts: {len(accepted)} / {len(pass1_accepts)}\n", flush=True)

    if not accepted:
        return

    # PASS 3: context notes
    print(f"  Pass 3: context notes ({len(accepted)} gpt-4o calls)…", flush=True)
    ctx_coros = []
    for i in range(0, len(accepted), BATCH):
        batch = accepted[i:i+BATCH]
        coros = [call(client, sem, CTX_PROMPT.format(text=a[0]["Verbatim Text (CODE THIS)"])) for a in batch]
        batch_res = await asyncio.gather(*coros)
        ctx_coros.extend(batch_res)
        print(f"    [ctx] [{i+len(batch)}/{len(accepted)}] done", flush=True)

    # Build final dataframe
    out_rows = []
    for i, ((row, theme, reason), ctx) in enumerate(zip(accepted, ctx_coros)):
        out_rows.append({
            "Segment ID":   f"EBK_{i+1:03d}",
            "Influencer":   "Ebuka Obi-Uchendu",
            "Platform":     row["Platform"],
            "Content Type": row["Content Type"],
            "Source File":  row["Source File"],
            "Source URL":   row["Source URL"],
            "Theme(s)":     theme,
            "Context (NOT CODED - comprehension only)": (ctx or {}).get("context", reason),
            "Verbatim Text (CODE THIS)": row["Verbatim Text (CODE THIS)"],
        })
    out_df = pd.DataFrame(out_rows)
    out_df.to_excel(OUT, index=False)
    print(f"\n  → {OUT.relative_to(ROOT)}: {len(out_df)} rows", flush=True)

    # Per-source + theme summary
    from collections import Counter
    print(f"\n  per-episode yield:", flush=True)
    src_counts = Counter(a[0]["Source File"] for a in accepted)
    for src, n in sorted(src_counts.items(), key=lambda x: -x[1]):
        print(f"    {n:>3}  {src}", flush=True)
    print(f"\n  theme breakdown:", flush=True)
    tm = Counter(a[1] for a in accepted)
    for theme, n in tm.most_common(15):
        print(f"    {n:>3}  {theme}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

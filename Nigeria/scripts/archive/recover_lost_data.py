"""Maximum-effort recovery of rows lost during the cap-to-50 mistake.

Strategy:
  1. Load the orientation_audit checkpoint (380-row snapshot from a prior Final state).
  2. For each creator, find rows in the checkpoint that are NOT in the current Final.
  3. Run gpt-4o lenient scope filter on each (must be on-scope masculinity content).
  4. For Deyemi only, additional regressive-pattern check (since prior cleanup
     identified regressive contaminations in the audit checkpoint that we
     don't want back).
  5. APPEND new rows to the END of each Final file (preserves pinned IDs:
     DEY_021, BNK_003, AGB_054, SHO_049, WIZ_014).
  6. Re-issue Segment IDs sequentially (existing rows keep their order/IDs;
     new rows get IDs after the existing list).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import html
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm as atqdm


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY missing"

FINAL = ROOT / "Nigeria" / "Content Analysis" / "Content - Final"
AUDIT = ROOT / "temp" / "orientation_audit.xlsx"
LLM_MODEL = "gpt-4o"
CONCURRENCY = 6


def deep_decode(s):
    s = str(s)
    for _ in range(4):
        n = html.unescape(s)
        if n == s: break
        s = n
    return s


def norm(s):
    s = deep_decode(s)
    s = re.sub(r'[\U00010000-\U0010ffff]', '', s)
    s = re.sub(r'\s+', ' ', s).strip().lower()
    return s


# Per-creator scope prompts
SCOPE_PROMPTS = {
    "Banky Wellington": """The MENtality podcast is about masculinity. Banky W is a panelist with progressive views (marriage partnership, fatherhood, vulnerability, men's emotional life, provider pressure).

ACCEPT this paragraph if it makes ANY observation, claim, or reflection about masculinity, marriage, fatherhood, men's roles, provider pressure, mental health, or gender. Be reasonable — every Banky utterance about gender even if short counts.

REJECT only if pure conversational filler, logistical question, or completely off-topic.

PARAGRAPH: \"\"\"{text}\"\"\"
JSON: {{"accept":true|false,"theme":"<short>","reason":"<sentence>"}}""",
    "Shola": """Filter this Shola tweet. Shola is a Nigerian REGRESSIVE masculinity creator (manosphere-adjacent, scarcity narrative, "finished men", men as prize, women as transactional).

ACCEPT if on-scope masculinity / gender content (marriage, dating, women, sex, female sexuality, gender debate, hypergamy, simping, sexual ethics, male grievance, anti-feminism). Stand-alone clear meaning.

REJECT if pure motivational without gender frame, off-topic, link-only, vague reply.

TEXT: \"\"\"{text}\"\"\"
JSON: {{"accept":true|false,"theme":"<short>","reason":"<sentence>"}}""",
    "Agba John Doe": """Filter this Agba John Doe tweet. He is a Nigerian REGRESSIVE masculinity creator (soft patriarchy, wife submission, marriage advice, male provision, sexual double standards). Many tweets are part of long threads.

ACCEPT if regressive masculinity claim (marriage, women, men's roles, fatherhood, sex, provision, submission, female sexuality), even mid-sentence thread fragments.

REJECT if pure URL/link, "Read!" intro, completely off-topic.

TEXT: \"\"\"{text}\"\"\"
JSON: {{"accept":true|false,"theme":"<short>","reason":"<sentence>"}}""",
    "Wizarab": """Filter this Wizarab tweet. He is a Nigerian REGRESSIVE masculinity creator (anti-women cynicism, anti-feminism, sexual entitlement, but mixed with some progressive consent content).

ACCEPT if on-scope masculinity / gender content. We accept both regressive and progressive content from him as long as it's clearly about masculinity / gender / sexual ethics / relationships.

REJECT if off-topic, pure reply needing parent context, short vague banter.

TEXT: \"\"\"{text}\"\"\"
JSON: {{"accept":true|false,"theme":"<short>","reason":"<sentence>"}}""",
    "Deyemi Okanlawon": """Filter this Deyemi Okanlawon tweet for a PROGRESSIVE Nigerian masculinity content analysis.

ACCEPT only if (A) on-scope masculinity content AND (B) NOT a regressive pattern.

ON-SCOPE: male accountability, vulnerability, fatherhood, marriage, mental health, anti-rape, gender debate.

HARD REJECT if regressive pattern present:
  - "men are tired", male-victimhood without acknowledging women
  - alimony/divorce-court grievances
  - mocking male DV victims or male tears
  - "men are scum" sarcastic deflection
  - hypergamy resentment
  - manosphere hierarchies (alpha/beta, high-value man)
  - polygamy advocacy
  - provider-supremacy framings

TEXT: \"\"\"{text}\"\"\"
JSON: {{"accept":true|false,"theme":"<short>","reason":"<sentence>"}}""",
}


CTX_PROMPT = """One sentence (max 25 words) describing this for a research coder unfamiliar with Nigerian context.
TEXT: \"\"\"{text}\"\"\"
JSON: {{"context":"..."}}"""


CREATORS = [
    ("Banky Wellington_Podcast.xlsx", "BNK", "Banky Wellington",       "YouTube (MENtality podcast)", "Podcast snippet"),
    ("Shola_Twitter.xlsx",            "SHO", "Shola",                  "X", "Tweet"),
    ("Agba John Doe_Twitter.xlsx",    "AGB", "Agba John Doe",          "X", "Tweet"),
    ("Wizarab_Twitter.xlsx",          "WIZ", "Wizarab",                "X", "Tweet"),
    ("Deyemi Okanlawon_Twitter.xlsx", "DEY", "Deyemi Okanlawon",       "X", "Tweet"),
]


async def call(client, sem, prompt):
    async with sem:
        for attempt in range(5):
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
                if attempt == 4:
                    return {}
                await asyncio.sleep(1 + attempt)
        return {}


async def main():
    print("=== Maximum-effort recovery from orientation_audit checkpoint ===\n")
    audit = pd.read_excel(AUDIT)
    audit['text_norm'] = audit['text'].apply(norm)

    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    grand_added = 0
    for fname, prefix, creator, platform, ctype in CREATORS:
        fp = FINAL / fname
        fin = pd.read_excel(fp)
        fin['text_norm'] = fin['Verbatim Text (CODE THIS)'].apply(norm)
        fin_set = set(fin['text_norm'])
        audit_sub = audit[audit['file'] == fname]
        missing = audit_sub[~audit_sub['text_norm'].isin(fin_set)].copy()

        print(f"\n--- {fname} ---  current={len(fin)}  candidates_in_audit={len(missing)}")
        if len(missing) == 0:
            continue

        prompt_tmpl = SCOPE_PROMPTS.get(creator)
        coros = [call(client, sem, prompt_tmpl.format(text=str(t)[:1500])) for t in missing['text']]
        res = await atqdm.gather(*coros, desc=f"{prefix}-validate")
        accepted = []
        for (_, row), r in zip(missing.iterrows(), res):
            if r and r.get("accept") is True:
                accepted.append({"text": str(row['text']), "theme": r.get("theme",""), "reason": r.get("reason","")})
        print(f"  passed scope re-validation: {len(accepted)}")
        if not accepted:
            continue

        # Generate context notes
        ctx_coros = [call(client, sem, CTX_PROMPT.format(text=a['text'][:1500])) for a in accepted]
        ctx_res = await atqdm.gather(*ctx_coros, desc=f"{prefix}-ctx")

        new_rows = [{
            "Segment ID": "PENDING",
            "Influencer": creator,
            "Platform": platform,
            "Content Type": ctype,
            "Context (NOT CODED - comprehension only)": x.get("context", a.get("reason","")),
            "Verbatim Text (CODE THIS)": a["text"],
        } for a, x in zip(accepted, ctx_res)]
        new_df = pd.DataFrame(new_rows)

        # APPEND to end (preserves pinned IDs)
        fin_clean = fin.drop(columns="text_norm")
        comb = pd.concat([fin_clean, new_df], ignore_index=True)
        # Dedup defensively
        comb = comb.drop_duplicates(subset=["Verbatim Text (CODE THIS)"], keep="first").reset_index(drop=True)
        # Re-issue IDs sequentially (existing keep order, new go after)
        comb['Segment ID'] = [f"{prefix}_{i+1:03d}" for i in range(len(comb))]
        comb.to_excel(fp, index=False)
        added = len(comb) - len(fin)
        grand_added += added
        print(f"  → {fname}: {len(fin)} → {len(comb)} (+{added})")

    print(f"\n=== TOTAL ADDED: {grand_added} ===")


if __name__ == "__main__":
    asyncio.run(main())

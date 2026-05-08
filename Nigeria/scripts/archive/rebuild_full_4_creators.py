"""Rebuild full content for the 4 kept creators after the cap-to-50 pivot.

The user originally had Banky 98 / Shola 105 / Agba 96 / Deyemi 50, then asked
to cap all 4 at 50 for balance, then changed their mind and wants ALL content
back. The pre-cap files were not backed up.

Strategy: ADD additional scope-relevant rows from each raw source on top of
the current 50, until we approximate the original counts.

  - Banky: re-mine MENtality transcripts (217 Banky turns total, 50 currently
    in Final). Score remaining ~167 with gpt-4o scope filter, take any that
    pass.
  - Shola: raw scrape has 143 tweets, 50 in Final. Score remaining ~93,
    take any that pass scope filter.
  - Agba: raw scrape has 120 tweets, 50 in Final. Score remaining ~70.
  - Deyemi: keep at 50, no change.
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
RAW   = ROOT / "Nigeria" / "Content Analysis" / "Content - Raw"
TRANS = RAW / "Banky Wellington" / "Transcripts"

LLM_MODEL   = "gpt-4o"
CONCURRENCY = 6


def deep_decode(s):
    s = str(s)
    for _ in range(4):
        n = html.unescape(s)
        if n == s: break
        s = n
    return s


# ===== Banky transcript parsing =====
BP = re.compile(r"^banky( wellington)?( w)?$|^bankole( wellington)?$", re.I)
BIO_BAD = [re.compile(r"\b(our|my) daughter\b(?! is a doctor)", re.I),
           re.compile(r"\bthe girls I have\b", re.I),
           re.compile(r"\bI don['’]t have (a |any )?(son|sons|kids|children)\b", re.I),
           re.compile(r"\b(coming off of|after|post[- ]?)covid.{0,40}(get|got|had to get) married\b", re.I)]


def parse_turns(path):
    text = path.read_text()
    turns = []
    cur_sp, cur_buf = None, []
    for line in text.split("\n"):
        line = line.rstrip()
        if not line: continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9 .\-_'’]{0,60}?):\s*(.*)$", line)
        if m and len(m.group(1).split()) <= 6:
            if cur_sp is not None: turns.append((cur_sp, " ".join(cur_buf).strip()))
            cur_sp, cur_buf = m.group(1).strip(), [m.group(2)]
        else:
            if cur_sp is None: cur_sp, cur_buf = "U", []
            cur_buf.append(line)
    if cur_sp is not None: turns.append((cur_sp, " ".join(cur_buf).strip()))
    return turns


def get_banky_candidates(existing_texts: set):
    out = []
    for path in sorted(TRANS.glob("*.txt")):
        for sp, txt in parse_turns(path):
            if not BP.match(sp.strip()): continue
            t = txt.strip()
            if t in existing_texts: continue
            n = len(t.split())
            if n < 8: continue
            if any(p.search(t) for p in BIO_BAD): continue
            out.append({"source": path.stem, "text": t})
    return out


# ===== Prompts =====
BANKY_PROMPT = """The MENtality podcast is about masculinity. Banky W is a panelist with progressive views (marriage partnership, fatherhood, vulnerability, men's emotional life, provider pressure).

ACCEPT this snippet if it makes any observation, claim, or reflection about masculinity, marriage, fatherhood, men's roles, provider pressure, mental health, or gender. Be reasonable — every Banky utterance about gender even if short counts.

REJECT only if it's:
  - pure conversational filler ("you know what I mean?")
  - logistical question to other panelists
  - clearly off-topic (no masculinity link at all)

SNIPPET: \"\"\"{text}\"\"\"
JSON: {{"accept":true|false,"theme":"<short>","reason":"<sentence>"}}"""


REGRESSIVE_PROMPT = """Filter this {creator} tweet for a Nigerian masculinity content analysis. {creator} is a REGRESSIVE Nigerian masculinity creator.

ACCEPT if it makes a clear, codable observation about marriage, dating, women, sex, fatherhood, money/provider, female sexuality, female submission, gender debate, hypergamy, infidelity, polygamy, sexual ethics, male grievance/accountability/vulnerability, or masculinity. Stand-alone clear meaning.

REJECT if: pure conversational filler, off-topic (politics/food/sports), promo, link-only, mid-sentence fragment, vague reply needing parent context.

TEXT: \"\"\"{text}\"\"\"
JSON: {{"accept":true|false,"theme":"<short>","reason":"<sentence>"}}"""


CTX_PROMPT = """One sentence (max 25 words) describing this for a research coder unfamiliar with Nigerian context.
TEXT: \"\"\"{text}\"\"\"
JSON: {{"context":"..."}}"""


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


# ===== Per-creator backfill =====
async def backfill_banky(client, sem):
    fp = FINAL / "Banky Wellington_Podcast.xlsx"
    fin = pd.read_excel(fp)
    fin["text_norm"] = fin["Verbatim Text (CODE THIS)"].astype(str).str.strip()
    existing = set(fin["text_norm"])
    print(f"\nBanky: current {len(fin)}, finding new MENtality candidates...")
    cands = get_banky_candidates(existing)
    print(f"  candidates not in Final: {len(cands)}")
    if not cands:
        return
    # Filter
    coros = [call(client, sem, BANKY_PROMPT.format(text=c["text"])) for c in cands]
    res = await atqdm.gather(*coros, desc="Banky")
    accepted = [(cands[i], r.get("theme",""), r.get("reason","")) for i, r in enumerate(res) if r.get("accept") is True]
    print(f"  accepted: {len(accepted)}")
    if not accepted:
        return
    # Context
    ctx_coros = [call(client, sem, CTX_PROMPT.format(text=a[0]["text"])) for a in accepted]
    ctx_res = await atqdm.gather(*ctx_coros, desc="Banky-ctx")
    new_rows = [{
        "Segment ID": "PENDING",
        "Influencer": "Banky Wellington",
        "Platform": "YouTube (MENtality podcast)",
        "Content Type": "Podcast snippet",
        "Context (NOT CODED - comprehension only)": x.get("context", a[2]),
        "Verbatim Text (CODE THIS)": a[0]["text"],
    } for a, x in zip(accepted, ctx_res)]
    nd = pd.DataFrame(new_rows)
    fin_clean = fin.drop(columns="text_norm")
    comb = pd.concat([fin_clean, nd], ignore_index=True).drop_duplicates(subset=["Verbatim Text (CODE THIS)"]).reset_index(drop=True)
    comb["Segment ID"] = [f"BNK_{i+1:03d}" for i in range(len(comb))]
    comb.to_excel(fp, index=False)
    print(f"  → Banky: {len(fin)} → {len(comb)}")


async def backfill_regressive(creator, raw_path, fin_filename, prefix, client, sem):
    fp = FINAL / fin_filename
    fin = pd.read_excel(fp)
    fin_t = set(fin["Verbatim Text (CODE THIS)"].astype(str).map(deep_decode).str.strip())

    raw = pd.read_excel(RAW / raw_path)
    raw["t"] = raw["text"].astype(str).map(deep_decode).str.strip()
    cands = raw[~raw["t"].isin(fin_t)].copy()
    cands["n"] = cands["t"].str.split().apply(len)
    cands = cands[cands["n"] >= 6].reset_index(drop=True)
    # No mid-sentence
    cands = cands[cands["t"].str[:1].str.isupper() | cands["t"].str.startswith(("@", '"', "'", "#"))].reset_index(drop=True)
    print(f"\n{creator}: current {len(fin)}, candidates not in Final: {len(cands)}")
    if len(cands) == 0:
        return
    coros = [call(client, sem, REGRESSIVE_PROMPT.format(creator=creator, text=str(t)[:1200])) for t in cands["t"]]
    res = await atqdm.gather(*coros, desc=creator[:12])
    accepted = [(cands.iloc[i]["t"], r.get("theme","")) for i, r in enumerate(res) if r.get("accept") is True]
    print(f"  accepted: {len(accepted)}")
    if not accepted:
        return
    ctx_coros = [call(client, sem, CTX_PROMPT.format(text=t[:1200])) for t,_ in accepted]
    ctx_res = await atqdm.gather(*ctx_coros, desc=f"{creator[:10]}-ctx")
    new_rows = [{
        "Segment ID": "PENDING",
        "Influencer": creator,
        "Platform": "X",
        "Content Type": "Tweet",
        "Context (NOT CODED - comprehension only)": x.get("context", ""),
        "Verbatim Text (CODE THIS)": t,
    } for (t, _), x in zip(accepted, ctx_res)]
    nd = pd.DataFrame(new_rows)
    comb = pd.concat([fin, nd], ignore_index=True).drop_duplicates(subset=["Verbatim Text (CODE THIS)"]).reset_index(drop=True)
    comb["Segment ID"] = [f"{prefix}_{i+1:03d}" for i in range(len(comb))]
    comb.to_excel(fp, index=False)
    print(f"  → {fin_filename}: {len(fin)} → {len(comb)}")


async def main():
    print("=== Rebuilding full content for 4 creators (post-cap restoration) ===")
    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    await backfill_banky(client, sem)
    await backfill_regressive("Shola",         "Shola/Shola_Twitter_Raw.xlsx",
                              "Shola_Twitter.xlsx", "SHO", client, sem)
    await backfill_regressive("Agba John Doe", "Agba John Doe/Agba John Doe_Twitter_Raw.xlsx",
                              "Agba John Doe_Twitter.xlsx", "AGB", client, sem)

    print("\n=== FINAL STATE ===")
    total = 0
    for p in sorted(FINAL.glob("*.xlsx")):
        if p.name.startswith("~$"): continue
        n = len(pd.read_excel(p))
        print(f"  {p.name:<45} {n:>5}")
        total += n
    print(f"  {'TOTAL':<45} {total:>5}")


if __name__ == "__main__":
    asyncio.run(main())

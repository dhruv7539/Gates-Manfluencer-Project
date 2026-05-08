"""Extract Ebuka Obi-Uchendu's turns from the 6 MENtality podcast transcripts.

Ebuka is the host. He frames episodes with declarative monologues, asks pointed
questions, and offers his own takes on masculinity / fatherhood / marriage / men's
emotional life. This is progressive masculinity content from the same source as
Banky's content — no scraping needed.

Pipeline:
  1. Parse 6 MENtality transcripts, extract all Ebuka turns
  2. Word-count chunk turns >250 words into 100-200 word paragraphs
  3. Drop pure-question turns and ultra-short utterances
  4. gpt-4o STRICT scope filter (must engage masculinity / gender content)
  5. Generate context notes
  6. Save as Nigeria/Content Analysis/Content - Final/Ebuka Obi-Uchendu_Podcast.xlsx
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

TRANS = ROOT / "Nigeria" / "Content Analysis" / "Content - Raw" / "Banky Wellington" / "Transcripts"
OUT_PATH = ROOT / "Nigeria" / "Content Analysis" / "Content - Final" / "Ebuka Obi-Uchendu_Podcast.xlsx"

LLM_MODEL   = "gpt-4o"
CONCURRENCY = 6
MIN_WORDS   = 25
TARGET_WORDS = 150
MAX_WORDS_PER_CHUNK = 200

# YouTube IDs verified earlier in conversation for the 6 MENtality episodes
EPISODE_URLS = {
    "Masculinity + Money":               "https://www.youtube.com/watch?v=f6WW9g5hqLI",
    "Masculinity + Relationships":       "https://www.youtube.com/watch?v=mU5uAVhVEzA",
    "Pt 2 Masculinity + Relationships":  "https://www.youtube.com/watch?v=7uLzlPGsiVo",
    "Masculinity + Friendship":          "https://www.youtube.com/watch?v=-YGXo00-fHw",
    "Masculinity + Fatherhood":          "https://www.youtube.com/watch?v=V_eHJfW87iA",
    "Masculinity + Young Boys":          "https://www.youtube.com/watch?v=XbFCPgdK8QQ",
}


EBUKA = re.compile(r"^ebuka( obi-?\s*uchendu)?$", re.I)


def parse(path):
    text = path.read_text()
    turns = []
    cur_sp, cur_buf = None, []
    for line in text.split("\n"):
        line = line.rstrip()
        if not line: continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9 .\-_'’]{0,60}?):\s*(.*)$", line)
        if m and len(m.group(1).split()) <= 6:
            if cur_sp is not None:
                turns.append((cur_sp, " ".join(cur_buf).strip()))
            cur_sp, cur_buf = m.group(1).strip(), [m.group(2)]
        else:
            if cur_sp is None: cur_sp, cur_buf = "U", []
            cur_buf.append(line)
    if cur_sp is not None:
        turns.append((cur_sp, " ".join(cur_buf).strip()))
    return turns


def chunk_long_turn(text, target=TARGET_WORDS, max_w=MAX_WORDS_PER_CHUNK):
    """Word-count chunk a long turn at sentence boundaries when possible."""
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split()
    if len(words) <= max_w:
        return [text]
    chunks = []
    i = 0
    while i < len(words):
        end = min(i + target, len(words))
        if end < len(words):
            window = " ".join(words[end:end + 30])
            m = re.search(r"[.!?]\s", window)
            if m:
                end += len(window[: m.start() + 1].split())
        chunks.append(" ".join(words[i:end]).strip())
        i = end
    return chunks


SCOPE_PROMPT = """You are filtering a paragraph by Ebuka Obi-Uchendu — the host of MENtality, a Nigerian podcast about masculinity. Ebuka frames each episode with declarative monologues and pointed questions about fatherhood, marriage, men's emotional life, gender roles, provider pressure, and male vulnerability. His stance is progressive-leaning.

ACCEPT only if the paragraph clearly engages a masculinity / gender theme:
  - male accountability, fatherhood, raising boys
  - marriage as partnership, household dynamics, divorce
  - men's emotional life, vulnerability, mental health
  - provider pressure, men + money expectations
  - gender debate, feminism, equality, "men vs women"
  - sexual ethics, dating, double standards
  - critique of toxic masculinity, "real man" tropes
  - generational father-son trauma / role-modelling
  - rape culture, consent, male perpetrators

REJECT if:
  - pure interview transitions / "let's hear from X"
  - thanking guests / podcast logistics / intro pleasantries / outros
  - pure questions to other panelists with no Ebuka stance
  - off-topic anecdotes (TV shows, celebrities) without gender claim
  - generic motivational
  - mid-thought fragments needing prior turn for sense

PARAGRAPH:
\"\"\"{text}\"\"\"

JSON only:
{{"accept": true | false,
  "theme": "<short label if accepted>",
  "reason": "<one short sentence>"}}"""


CRITIQUE_PROMPT = """A first-pass scope filter said this Ebuka Obi-Uchendu paragraph is in-scope for a Nigerian masculinity content analysis.

CHALLENGE that decision. Re-read the paragraph carefully. Is it 100% scope-relevant — does it make a clear, codable claim or observation about masculinity / men / fatherhood / male emotional life / sexual integrity / marriage partnership / gender roles?

REJECT if any of:
  - the gender claim is implicit / requires inference
  - it's mostly an interview transition, intro, outro, or panelist introduction
  - it's mostly a question to a panelist with no Ebuka stance embedded
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
    print("=== Extracting Ebuka Obi-Uchendu turns from 6 MENtality transcripts ===\n")

    # Step 1: collect Ebuka turns + chunk
    all_paragraphs = []
    for path in sorted(TRANS.glob("*.txt")):
        ep = path.stem
        turns = parse(path)
        ebuka_turns = [t for sp, t in turns if EBUKA.match(sp.strip())]
        chunks_this_ep = []
        for t in ebuka_turns:
            if len(t.split()) < MIN_WORDS:
                continue
            for c in chunk_long_turn(t):
                if len(c.split()) >= MIN_WORDS:
                    chunks_this_ep.append({"episode": ep, "text": c})
        all_paragraphs.extend(chunks_this_ep)
        print(f"  {ep}: {len(ebuka_turns)} Ebuka turns → {len(chunks_this_ep)} substantive paragraphs")

    print(f"\n  TOTAL substantive paragraphs: {len(all_paragraphs)}")

    if not all_paragraphs:
        return

    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    # Step 2a: STRICT scope filter (pass 1) — chunk for incremental progress
    BATCH = 24
    print(f"\n  Pass 1: scope filter ({len(all_paragraphs)} gpt-4o calls in batches of {BATCH})…", flush=True)
    pass1_results = []
    for i in range(0, len(all_paragraphs), BATCH):
        batch = all_paragraphs[i:i+BATCH]
        coros = [call(client, sem, SCOPE_PROMPT.format(text=p["text"])) for p in batch]
        batch_res = await asyncio.gather(*coros)
        pass1_results.extend(batch_res)
        n_acc = sum(1 for r in pass1_results if r and r.get("accept") is True)
        print(f"    [{i+len(batch)}/{len(all_paragraphs)}] cumulative pass-1 accepts: {n_acc}", flush=True)
    pass1_accepts = [(p, r.get("theme",""), r.get("reason","")) for p, r in zip(all_paragraphs, pass1_results) if r and r.get("accept") is True]
    print(f"  Pass 1 accepted: {len(pass1_accepts)} / {len(all_paragraphs)}", flush=True)

    if not pass1_accepts:
        return

    # Step 2b: CRITIQUE pass (pass 2)
    print(f"\n  Pass 2: critique pass ({len(pass1_accepts)} gpt-4o calls in batches of {BATCH})…", flush=True)
    crit_results = []
    for i in range(0, len(pass1_accepts), BATCH):
        batch = pass1_accepts[i:i+BATCH]
        coros = [call(client, sem, CRITIQUE_PROMPT.format(text=p[0]["text"])) for p in batch]
        batch_res = await asyncio.gather(*coros)
        crit_results.extend(batch_res)
        n_acc = sum(1 for r in crit_results if r and r.get("accept") is True)
        print(f"    [{i+len(batch)}/{len(pass1_accepts)}] cumulative critique accepts: {n_acc}", flush=True)
    accepted = [a for a, c in zip(pass1_accepts, crit_results) if c and c.get("accept") is True]
    print(f"  Pass 2 accepted (filter+critique unanimous): {len(accepted)} / {len(pass1_accepts)}", flush=True)

    if not accepted:
        return

    # Step 3: context notes
    print(f"\n  generating context notes ({len(accepted)} calls)…")
    ctx_coros = [call(client, sem, CTX_PROMPT.format(text=a[0]["text"])) for a in accepted]
    ctx_results = await atqdm.gather(*ctx_coros, desc="ctx")

    rows = []
    for i, (a, c) in enumerate(zip(accepted, ctx_results)):
        rows.append({
            "Segment ID":   f"EBK_{i+1:03d}",
            "Influencer":   "Ebuka Obi-Uchendu",
            "Platform":     "YouTube (MENtality podcast — host)",
            "Content Type": "Podcast monologue / framing",
            "Source File":  f"{a[0]['episode']}.txt",
            "Source URL":   EPISODE_URLS.get(a[0]['episode'], ""),
            "Theme(s)":     a[1],
            "Context (NOT CODED - comprehension only)": c.get("context", a[2]),
            "Verbatim Text (CODE THIS)": a[0]["text"],
        })
    df = pd.DataFrame(rows)
    df.to_excel(OUT_PATH, index=False)
    print(f"\n  → {OUT_PATH.relative_to(ROOT)}: {len(df)} rows")

    # Per-episode + theme
    from collections import Counter
    print(f"\n  per-episode yield:")
    eps = Counter(a[0]['episode'] for a in accepted)
    for ep, n in sorted(eps.items(), key=lambda x: -x[1]):
        print(f"    {n:>3}  {ep}")
    print(f"\n  theme breakdown:")
    tm = Counter(a[1] for a in accepted)
    for theme, n in tm.most_common(15):
        print(f"    {n:>3}  {theme}")


if __name__ == "__main__":
    asyncio.run(main())

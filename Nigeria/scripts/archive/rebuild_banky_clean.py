"""Rebuild Banky Wellington_Podcast.xlsx from transcripts with tight misattribution filters.

Replaces the over-aggressive Pass-5 scope cull. Steps:

1. Re-extract every 'Banky W' turn from the 6 MENtality transcripts.
2. Drop turns < MIN_WORDS (filler).
3. Drop turns with biographical contradictions (Banky has 2 sons, married
   Adesua 2017 — anyone saying 'our daughter' / 'I don't have a son' / 'married
   post-COVID' / 'the girls I have' as first-person statement is mislabelled
   by Gemini and is actually another panelist).
4. Drop pure scope-fail fillers (single utterances of confusion / sound check).
5. Generate a 1-sentence context note via gpt-4o for each kept snippet.

Output: Nigeria/Content Analysis/Content - Final/Banky Wellington_Podcast.xlsx
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

TRANS_DIR = ROOT / "Nigeria" / "Content Analysis" / "Content - Raw" / "Banky Wellington" / "Transcripts"
OUT_PATH  = ROOT / "Nigeria" / "Content Analysis" / "Content - Final" / "Banky Wellington_Podcast.xlsx"

MIN_WORDS = 12  # raise from 5 → 12; drops "yeah / exactly / I'm lost" reactions but keeps witty one-liners

EPISODES = [
    {"file": "Masculinity + Money.txt",                "topic": "Masculinity & Money"},
    {"file": "Masculinity + Relationships.txt",        "topic": "Masculinity & Relationships"},
    {"file": "Pt 2 Masculinity + Relationships.txt",   "topic": "Masculinity & Relationships Pt 2"},
    {"file": "Masculinity + Friendship.txt",           "topic": "Masculinity & Friendship"},
    {"file": "Masculinity + Fatherhood.txt",           "topic": "Masculinity & Fatherhood"},
    {"file": "Masculinity + Young Boys.txt",           "topic": "Masculinity & Young Boys"},
]

BANKY_PATTERNS = [
    re.compile(r"^banky( wellington)?$", re.I),
    re.compile(r"^banky w$", re.I),
    re.compile(r"^banky w\..*", re.I),
    re.compile(r"^bankole( wellington)?$", re.I),
]


def is_banky(label):
    label = label.strip()
    return any(p.match(label) for p in BANKY_PATTERNS)


def parse_turns(path):
    """Yield (speaker, text) per labelled turn."""
    text = path.read_text()
    turns = []
    cur_sp, cur_buf = None, []
    for line in text.split("\n"):
        line = line.rstrip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9 .\-_'’]{0,60}?):\s*(.*)$", line)
        if m and len(m.group(1).split()) <= 6:
            if cur_sp is not None:
                turns.append((cur_sp, " ".join(cur_buf).strip()))
            cur_sp = m.group(1).strip()
            cur_buf = [m.group(2)]
        else:
            if cur_sp is None:
                cur_sp, cur_buf = "UNKNOWN", []
            cur_buf.append(line)
    if cur_sp is not None:
        turns.append((cur_sp, " ".join(cur_buf).strip()))
    return turns


# Biographical contradictions — first-person statements impossible for Banky
BIO_CONTRADICTIONS = [
    re.compile(r"\b(our|my) daughter\b(?! is a doctor)", re.I),  # excludes hypothetical Jewish parable
    re.compile(r"\bthe girls I have\b", re.I),
    re.compile(r"\bI don['’]t have (a |any )?(son|sons|kids|children)\b", re.I),
    re.compile(r"\b(coming off of|after|post[- ]?)covid.{0,40}(get|got|had to get) married\b", re.I),
    re.compile(r"\b(I|we) (just )?got married\b.{0,80}\b(202[12345])\b", re.I),
    re.compile(r"\bI['’]m (a |an )?(comedian|stand[- ]?up)\b", re.I),
]

# Pure-filler scope drops
FILLER_PATTERNS = [
    re.compile(r"^(yeah|yes|no|exactly|right|i agree|true|same|okay|ok|wow|hmm)[\s\.,!\?]*$", re.I),
    re.compile(r"^(sorry|thank you|please|hello|hi|bye)[\s\.,!\?]*$", re.I),
]


def is_bio_contradiction(text):
    for p in BIO_CONTRADICTIONS:
        if p.search(text):
            return p.pattern
    return None


def is_filler(text):
    if any(p.match(text.strip()) for p in FILLER_PATTERNS):
        return True
    return False


CTX_PROMPT = """One concise sentence (max 25 words) explaining what this MENtality podcast snippet is about. Episode topic: {topic}. Speaker: Banky W. The note is for a research coder unfamiliar with the show — flag any Pidgin / Yoruba / Nigerian references the coder might miss.

SNIPPET:
\"\"\"{text}\"\"\"

JSON only: {{"context": "..."}}"""


async def gen_context(client, sem, topic, text):
    async with sem:
        for attempt in range(5):
            try:
                resp = await client.chat.completions.create(
                    model="gpt-4o", temperature=0,
                    response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": CTX_PROMPT.format(topic=topic, text=text[:1800])}],
                )
                return json.loads(resp.choices[0].message.content).get("context", "")
            except Exception as e:
                if "429" in str(e) or "rate" in str(e).lower():
                    await asyncio.sleep(5 * (2 ** attempt))
                    continue
                if attempt == 4:
                    return ""
                await asyncio.sleep(2 ** attempt)


async def main():
    print("=== rebuild Banky Wellington_Podcast.xlsx ===", flush=True)
    rows = []
    for ep in EPISODES:
        path = TRANS_DIR / ep["file"]
        turns = parse_turns(path)
        banky_turns = [t for sp, t in turns if is_banky(sp)]
        kept_ep = 0
        bio_dropped = filler_dropped = short_dropped = 0
        for txt in banky_turns:
            if len(txt.split()) < MIN_WORDS:
                short_dropped += 1
                continue
            bio_pat = is_bio_contradiction(txt)
            if bio_pat:
                bio_dropped += 1
                print(f"  DROP misattribution [{ep['topic']}]: pattern={bio_pat!r}: {txt[:140]}…", flush=True)
                continue
            if is_filler(txt):
                filler_dropped += 1
                continue
            rows.append({"episode": ep["file"], "topic": ep["topic"], "text": txt})
            kept_ep += 1
        print(f"  {ep['topic']}: banky_turns={len(banky_turns)} kept={kept_ep} short={short_dropped} bio={bio_dropped} filler={filler_dropped}", flush=True)

    print(f"\n  TOTAL kept: {len(rows)}", flush=True)

    # Generate contexts
    print(f"\n  generating context notes ({len(rows)} gpt-4o calls)…", flush=True)
    client = AsyncOpenAI()
    sem = asyncio.Semaphore(4)
    coros = [gen_context(client, sem, r["topic"], r["text"]) for r in rows]
    contexts = await atqdm.gather(*coros, desc="context")

    # Build dataframe in canonical schema
    out_rows = []
    for i, (r, ctx) in enumerate(zip(rows, contexts)):
        out_rows.append({
            "Segment ID":   f"BNK_{i+1:03d}",
            "Influencer":   "Banky Wellington",
            "Platform":     "YouTube (MENtality podcast)",
            "Content Type": "Podcast snippet",
            "Context (NOT CODED - comprehension only)": ctx,
            "Verbatim Text (CODE THIS)": r["text"],
        })
    df = pd.DataFrame(out_rows)
    df.to_excel(OUT_PATH, index=False)
    print(f"\n  → {OUT_PATH.relative_to(ROOT)}: {len(df)} rows", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

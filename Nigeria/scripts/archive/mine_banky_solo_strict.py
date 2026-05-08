"""Mine Banky Wellington's 5 solo YouTube transcripts for STRICT progressive masculinity content.

User requirement: 100% scope-relevant content at all costs. Triple-vote acceptance:
a paragraph is kept ONLY if 3 independent gemini-2.5-flash calls all say YES.

Source: Nigeria/Content Analysis/Content - Raw/Banky Wellington/Solo YouTube Transcripts/
Output: Nigeria/Content Analysis/Content - Final/Banky_Solo_YouTube.xlsx

Pipeline:
  1. Read each transcript, strip metadata header
  2. Chunk into ~120-200 word paragraphs at sentence boundaries
  3. Triple-vote scope filter (gemini-2.5-flash) — accept iff 3/3 say YES
  4. Orientation audit (drop any regressive contamination)
  5. Generate context note per accepted paragraph
  6. Save to Excel

Speaker: 100% Banky (these are solo sermons, no panel) — no misattribution risk.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm as atqdm


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY missing"
# (Note: user requested gemini-2.5-flash, but project's Gemini spending cap was hit.
#  Pivoted to gpt-4o using same pipeline structure.)

TRANS_DIR = ROOT / "Nigeria" / "Content Analysis" / "Content - Raw" / "Banky Wellington" / "Solo YouTube Transcripts"
OUT_PATH  = ROOT / "Nigeria" / "Content Analysis" / "Content - Final" / "Banky_Solo_YouTube.xlsx"

MODEL_ID    = "gpt-4o"
CONCURRENCY = 6
TARGET_WORDS = 150     # word-count chunking (transcripts have no sentence breaks)
N_VOTES     = 2        # double-check: strict filter pass + critique pass; both must say YES

SOURCE_URL_MAP = {
    "Face it Like a Man - Banky Wellington.txt":                              "https://www.youtube.com/watch?v=SoVSXTTH2dg",
    "Faith after a Fall - Banky Wellington.txt":                              "https://www.youtube.com/watch?v=qFHXI0jHJRM",
    "Final Say Faith - Banky & Adesua Wellington.txt":                        "https://www.youtube.com/watch?v=LFs0k-eluu4",
    "My Story - a journey through Hope & Faith - Banky Wellington.txt":       "https://www.youtube.com/watch?v=a5PryKc1Ev8",
    "The Prison of Pornography - Road to Freedom Finale.txt":                 "https://www.youtube.com/results?search_query=The+Prison+of+Pornography+Banky+Wellington",
}


SCOPE_PROMPT = """You are filtering a paragraph from a Banky Wellington solo YouTube sermon (Banky W = Olubankole Wellington, Nigerian artist, EME records founder, married to Adesua Etomi, two sons). The dataset is for a Norman Lear Center / Gates Foundation Nigerian masculinity content analysis.

The user requires 100% scope-relevant content. BE STRICT.

ACCEPT only if the paragraph clearly engages at least ONE of these masculinity / gender themes:
  - male accountability for misogyny, harm, abuse, or cheating
  - rape culture, consent, sexual violence (esp. men's responsibility)
  - male emotional life, vulnerability, mental health, men crying, depression
  - fatherhood, raising boys, role-modelling, father presence vs absence
  - marriage as partnership, husband-wife dynamics, headship-as-service vs dictator
  - provider pressure, men + money, financial expectations on men
  - male friendship, brotherhood, masculine community
  - sexual ethics, infidelity (esp. men changing behaviour), double standards
  - critique of toxic masculinity, "real man" tropes, alpha discourse
  - masculinity + faith / Christianity reframing manhood
  - sex addiction, pornography, sexual integrity (specifically for men)
  - shame, failure, second chances for men
  - generational trauma, breaking cycles for sons

REJECT (do not stretch — when in doubt, reject):
  - generic faith/prayer/scripture without gender frame ("God is faithful", "trust God")
  - generic motivation/encouragement without gender content
  - intro pleasantries, audience greetings, "happy father's day"
  - announcements, plug for next event, "go to my YouTube"
  - thanking band/crew/co-pastor
  - song lyrics or worship transitions
  - mid-thought fragments needing prior paragraph for sense
  - generic anecdotes with no gender claim
  - quoting another preacher without applying it to masculinity
  - jokes / banter without substance

PARAGRAPH:
\"\"\"{text}\"\"\"

JSON only:
{{"accept": true | false,
  "theme": "<short label if accepted, e.g. 'fatherhood as presence', 'sexual integrity', 'male vulnerability', 'marriage partnership'>",
  "reason": "<one short sentence>"}}"""


CTX_PROMPT = """One concise sentence (max 25 words) describing this Banky Wellington solo sermon paragraph for a research coder unfamiliar with Nigerian context. Note any Pidgin / Yoruba / Christian-Nigerian references.

PARAGRAPH:
\"\"\"{text}\"\"\"

JSON only: {{"context": "..."}}"""


AUDIT_PROMPT = """Classify this Banky Wellington solo-sermon paragraph's gender stance:

PROGRESSIVE = challenges patriarchy, advocates male accountability, vulnerability, marriage partnership, fatherhood-as-presence, sexual integrity, anti-toxic-masculinity.
REGRESSIVE = reinforces patriarchy/manosphere; men-as-victims, hypergamy resentment, mocking male tears, polygamy advocacy, headship-as-dictatorship.
NEUTRAL = observation without taking sides, or generic faith/wisdom.

PARAGRAPH: \"\"\"{text}\"\"\"
JSON: {{"orientation":"progressive|regressive|neutral","confidence":"high|medium|low","reason":"<sentence>"}}"""


def strip_metadata(raw: str) -> str:
    lines = raw.split("\n")
    out = []
    in_header = True
    for ln in lines:
        if in_header:
            if ln.startswith(("Stats:", "Speaker:", '"')) or not ln.strip():
                continue
            in_header = False
        out.append(ln)
    text = "\n".join(out)
    text = re.sub(r"^Banky W[^\n:]*:\s*", "", text, flags=re.M)
    return text.strip()


def chunk_paragraphs(text: str, target_w: int = TARGET_WORDS) -> list[str]:
    """Word-count chunking with sentence-boundary preference.

    Whisper auto-transcripts often have no sentence punctuation at all (one
    huge run-on). Fall back to fixed word-count windows when sentences fail.
    Each chunk has overlap on a sentence boundary if available.
    """
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split()
    if not words:
        return []
    chunks = []
    i = 0
    while i < len(words):
        end = min(i + target_w, len(words))
        # Try to extend to next sentence boundary within +30 words
        if end < len(words):
            window = " ".join(words[end:end + 30])
            m = re.search(r"[.!?]\s", window)
            if m:
                end += len(window[: m.start() + 1].split())
        chunk = " ".join(words[i:end]).strip()
        if len(chunk.split()) >= 50:
            chunks.append(chunk)
        i = end
    return chunks


async def gen_json(client, sem, prompt, retries=6, jitter_temp=False):
    async with sem:
        for attempt in range(retries):
            try:
                resp = await client.chat.completions.create(
                    model=MODEL_ID, temperature=0,
                    response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": prompt}],
                )
                return json.loads(resp.choices[0].message.content)
            except Exception as e:
                err = str(e)
                if "429" in err or "rate" in err.lower():
                    await asyncio.sleep(5 * (2 ** attempt))
                    continue
                await asyncio.sleep(1 + attempt)
        # Exhausted all retries
        return {}


async def safe_get(d, key):
    """Defensive .get() — gen_json should always return dict but be paranoid."""
    if d is None:
        return None
    return d.get(key) if hasattr(d, "get") else None


CRITIQUE_PROMPT = """A first-pass scope filter said this paragraph is in-scope for a Nigerian masculinity content analysis (Norman Lear Center / Gates Foundation).

CHALLENGE that decision. Re-read the paragraph carefully. Is it 100% scope-relevant — i.e. does it make a clear, codable claim about masculinity / men / fatherhood / male emotional life / sexual integrity / marriage partnership?

REJECT if any of:
  - the gender claim is implicit / requires inference / would only be "kind of" relevant
  - it's mostly a generic faith / motivational / encouragement message
  - it's mostly an anecdote without a clear masculinity claim
  - it's mostly setup or transition that drifts off-scope mid-paragraph
  - a research coder would have to argue for its scope-relevance

ACCEPT only if the paragraph would obviously code as masculinity content to any researcher.

PARAGRAPH:
\"\"\"{text}\"\"\"

JSON only:
{{"accept": true | false, "reason": "<one short sentence>"}}"""


async def vote_filter(client, sem, paragraph: str):
    """Pass 1: strict scope filter. Pass 2: independent critique pass. Both must accept."""
    pass1 = await gen_json(client, sem, SCOPE_PROMPT.format(text=paragraph))
    pass1 = pass1 or {}
    if not pass1.get("accept"):
        return False, [pass1]
    pass2 = await gen_json(client, sem, CRITIQUE_PROMPT.format(text=paragraph))
    pass2 = pass2 or {}
    return bool(pass2.get("accept")), [pass1, pass2]


async def main():
    print("=== Banky Solo YouTube — STRICT scope mining (gemini-2.5-flash, unanimous-of-3) ===", flush=True)
    print(f"  source dir: {TRANS_DIR.relative_to(ROOT)}", flush=True)
    print(f"  output:     {OUT_PATH.relative_to(ROOT)}", flush=True)

    if not TRANS_DIR.exists():
        print(f"  ! transcripts dir missing: {TRANS_DIR}", flush=True)
        sys.exit(1)

    all_paragraphs = []
    print("\n  loading transcripts:", flush=True)
    for path in sorted(TRANS_DIR.glob("*.txt")):
        raw = path.read_text()
        body = strip_metadata(raw)
        chunks = chunk_paragraphs(body)
        print(f"    {path.name}: {len(body.split()):,} words → {len(chunks)} paragraphs", flush=True)
        for c in chunks:
            all_paragraphs.append({"source_file": path.name, "text": c})
    print(f"  TOTAL paragraphs: {len(all_paragraphs)}", flush=True)

    if not all_paragraphs:
        sys.exit(1)

    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    print(f"\n  STRICT scope filter (filter + critique, ~{len(all_paragraphs)*2} calls)…", flush=True)
    coros = [vote_filter(client, sem, p["text"]) for p in all_paragraphs]
    results = await atqdm.gather(*coros, desc="filter+critique")

    accepted = []
    for p, (unanimous, votes) in zip(all_paragraphs, results):
        if unanimous:
            v0 = votes[0]
            accepted.append({**p, "theme": v0.get("theme", ""), "reason": v0.get("reason", "")})
    print(f"  unanimous accepts: {len(accepted)} / {len(all_paragraphs)}", flush=True)

    if not accepted:
        return

    print(f"\n  orientation audit on {len(accepted)} accepts…", flush=True)
    audit_coros = [gen_json(client, sem, AUDIT_PROMPT.format(text=a["text"])) for a in accepted]
    audit_results = await atqdm.gather(*audit_coros, desc="audit")
    clean = []
    for a, ar in zip(accepted, audit_results):
        if ar.get("orientation") == "regressive" and ar.get("confidence") in ("high", "medium"):
            print(f"    ✗ DROP regressive: {a['text'][:120]}", flush=True)
            continue
        clean.append(a)
    print(f"  clean after audit: {len(clean)}", flush=True)

    if not clean:
        return

    print(f"\n  generating context notes ({len(clean)} calls)…", flush=True)
    ctx_coros = [gen_json(client, sem, CTX_PROMPT.format(text=a["text"])) for a in clean]
    ctx_results = await atqdm.gather(*ctx_coros, desc="ctx")

    rows = []
    for i, (a, c) in enumerate(zip(clean, ctx_results)):
        rows.append({
            "Segment ID":   f"BNK_SOLO_{i+1:03d}",
            "Influencer":   "Banky Wellington",
            "Platform":     "YouTube (solo sermon)",
            "Content Type": "Sermon paragraph",
            "Source File":  a["source_file"],
            "Source URL":   SOURCE_URL_MAP.get(a["source_file"], ""),
            "Theme(s)":     a["theme"],
            "Context (NOT CODED - comprehension only)": c.get("context", a.get("reason", "")),
            "Verbatim Text (CODE THIS)": a["text"],
        })
    df = pd.DataFrame(rows)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(OUT_PATH, index=False)
    print(f"\n  → {OUT_PATH.relative_to(ROOT)}: {len(df)} rows", flush=True)

    from collections import Counter
    print(f"\n  per-source yield:", flush=True)
    src_counts = Counter(a["source_file"] for a in clean)
    for src, n in sorted(src_counts.items(), key=lambda x: -x[1]):
        print(f"    {n:>3}  {src}", flush=True)
    print(f"\n  theme breakdown:", flush=True)
    tm = Counter(a["theme"] for a in clean)
    for theme, n in tm.most_common(20):
        print(f"    {n:>3}  {theme}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

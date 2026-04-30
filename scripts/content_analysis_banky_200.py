"""Generate 200 scope-relevant coding units from Banky Wellington's 5 transcripts.

40 per video × 5 videos = 200 total. Same Kibe_Jagero schema as the existing
content analysis: Segment ID | Influencer | Platform | Content Type | Theme(s)
| Context (NOT CODED - comprehension only) | Verbatim Text (CODE THIS).

Uses gpt-4o with a structured JSON prompt that preserves words exactly (punctuation
and capitalization restored, filler words removed for readability per Kibe reference).
Output cached per video.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from tqdm.auto import tqdm


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY")
client = OpenAI()

TRANSCRIPTS_DIR = ROOT / "Generated Transcripts" / "Nigeria"
OUTPUT_DIR = ROOT / "Nigeria/Content Analysis" / "Banky Wellington"
CACHE_DIR = ROOT / "temp" / "content_analysis_banky_200"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

BANKY_SPEAKER = "Banky W (Olubankole Wellington)"
SEGMENTS_PER_VIDEO = 40
LLM_MODEL = "gpt-4o"

BANKY_VIDEOS = [
    {"title": "Final Say Faith - Banky & Adesua Wellington",
     "file": "Final Say Faith - Banky & Adesua Wellington.txt",
     "context_hint": "Church sermon / testimony on marriage, IVF struggles, and faith, co-delivered with Adesua Wellington."},
    {"title": "My Story - a journey through Hope & Faith",
     "file": "My Story - a journey through Hope & Faith - Banky Wellington.txt",
     "context_hint": "First-person testimony sermon about Banky's cancer diagnosis, recovery, and faith journey."},
    {"title": "The Prison of Pornography - Road to Freedom Finale",
     "file": "The Prison of Pornography - Road to Freedom Finale.txt",
     "context_hint": "Church sermon on pornography addiction, sexual temptation, and male spiritual discipline."},
    {"title": "Face it Like a Man - Banky Wellington",
     "file": "Face it Like a Man - Banky Wellington.txt",
     "context_hint": "Father's Day sermon on Christian manhood, fatherhood, providership, and male spiritual responsibility."},
    {"title": "Faith after a Fall - Banky Wellington",
     "file": "Faith after a Fall - Banky Wellington.txt",
     "context_hint": "Sermon on Peter's denial of Christ, applied to male failure, shame, and restoration in faith."},
]

SYSTEM_PROMPT = """You are a qualitative research assistant preparing coding units from a Nigerian Christian sermon / testimony by Banky Wellington for a masculinity study.

You will receive a raw speech-to-text transcript. Produce EXACTLY N topically coherent coding units — sample from the transcript, don't rewrite it.

## Hard size limits (critical — self-check before emitting each unit)
- EXACTLY N units. Not more, not fewer.
- Each `verbatim_text` MUST be between 60 and 130 words. COUNT THE WORDS before emitting. If a unit would be over 130 words, cut it shorter OR split it into two units earlier in the list. Absolutely never emit anything over 130 words.

## What to INCLUDE — this is the research scope
Banky is a male Christian creator speaking to a faith-based audience about manhood. ANY of the following counts as scope-relevant:

1. **Direct masculinity / gender teaching** — "as a man…", what men should do, gender role statements, manhood framing
2. **Marriage, fatherhood, husband/wife dynamics** — partnership, provision, domestic life
3. **Male emotional life** — shame, pride, vulnerability, failure, restoration, grief, male mental health
4. **Sexual morality, temptation, discipline, pornography** — especially from male perspective
5. **Banky's own male-experience testimony** — HIS stories from HIS life as a husband, father, son, working man, Christian man: IVF / fertility struggle, cancer diagnosis and recovery, career hustle, robbery survival, music career, family loss, financial hardship. These ARE male-lens content because Banky is narrating his own male experience, even when he doesn't say "as a man".
6. **Faith applied to how a man should live** — biblical figures interpreted through male-experience lens (David, Peter, Paul, Moses, Job) when Banky ties it to male identity, leadership, or male spiritual discipline

## What to EXCLUDE
- Pure Bible exposition / verse-by-verse teaching with no personal OR male-lens application (if Banky just explains what a verse means, theology only, no life application → skip)
- Song / book / album / event promotions ("I have a new song out…", "Come to our event…")
- Music cues ("[Music]"), greetings, altar calls, prayer formulas, applause cues, sermon openers / closers with no content
- Generic teaching metaphors (product manual, road sign) that never connect back to male experience
- Content where Banky is quoting someone else at length without commentary

## Verbatim text rules
- Literal excerpt: words in transcript order, contiguous.
- Restore sentence-ending punctuation and capitalize sentence-starts, proper nouns, "God", "Jesus", "Bible".
- Drop "um", "uh", "[music]", and stuttered "and and" → "and". Keep "you know", "like" as meaningful discourse markers.
- Preserve Pidgin / Yoruba / Swahili code-switching exactly.
- Preserve apostrophes, hyphens, quoted phrases.

## Per-unit fields
- `segment_index` (1..N)
- `verbatim_text` — 60 to 130 words. COUNT BEFORE EMITTING.
- `context` — ONE sentence (max 25 words), neutral third person, in square brackets
- `themes` — 2-4 multi-word theme tags (e.g., "Faith-framed masculinity", "Male spiritual discipline", "Marriage endurance", "Provider role", "Male vulnerability", "Fatherhood", "Sexual discipline", "Shame and restoration")

Return a JSON object: {"units": [{"segment_index": 1, "verbatim_text": "...", "context": "[...]", "themes": ["...", "..."]}, ...]}.
Output nothing else."""


def extract_banky_raw(path):
    text = Path(path).read_text(encoding="utf-8")
    body_parts = re.split(r"\n\s*\n", text, maxsplit=1)
    body = body_parts[1] if len(body_parts) == 2 else text
    turns = [t.strip() for t in re.split(r"\n\s*\n", body) if t.strip()]
    chunks = []
    for turn in turns:
        m = re.match(r"^([^:\n]{2,120}):\s*(.+)$", turn, flags=re.DOTALL)
        if not m:
            continue
        speaker, content = m.group(1).strip(), m.group(2).strip()
        if speaker != BANKY_SPEAKER:
            continue
        content = re.sub(r"\s+", " ", content).strip()
        if content:
            chunks.append(content)
    return " ".join(chunks)


def cache_key(label):
    return hashlib.sha1(label.encode("utf-8")).hexdigest()[:16]


def llm_segment(video, raw_text, n=SEGMENTS_PER_VIDEO):
    key = cache_key(f"{video['file']}::n={n}")
    cache_path = CACHE_DIR / f"{key}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text())

    user_msg = (
        f"Video: {video['title']}\n"
        f"Context hint: {video['context_hint']}\n"
        f"N = {n}\n\n"
        f"Raw transcript (Banky's speech only):\n{raw_text}"
    )
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                temperature=0,
                max_tokens=16000,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
            )
            if resp.choices[0].finish_reason == "length":
                raise ValueError("response truncated")
            data = json.loads(resp.choices[0].message.content)
            cache_path.write_text(json.dumps(data, indent=2))
            return data
        except Exception as e:
            print(f"  attempt {attempt+1} failed: {e}")
            if attempt == 2:
                raise


def main():
    rows = []
    for video in tqdm(BANKY_VIDEOS, desc="Banky videos"):
        raw = extract_banky_raw(TRANSCRIPTS_DIR / video["file"])
        print(f"\n  {video['title'][:50]}: raw={len(raw.split())} words")
        result = llm_segment(video, raw)
        units = result.get("units", [])
        print(f"    -> {len(units)} units")
        for u in units:
            rows.append({
                "Segment ID": None,
                "Influencer": "Banky Wellington",
                "Platform": "YouTube",
                "Content Type": "Sermon / Testimony",
                "Theme(s)": "; ".join(u.get("themes", [])),
                "Context (NOT CODED - comprehension only)": u.get("context", ""),
                "Verbatim Text (CODE THIS)": u.get("verbatim_text", ""),
                "_video": video["title"],
            })

    df = pd.DataFrame(rows)
    df["Segment ID"] = range(1, len(df) + 1)
    out_cols = ["Segment ID", "Influencer", "Platform", "Content Type",
                "Theme(s)", "Context (NOT CODED - comprehension only)",
                "Verbatim Text (CODE THIS)"]
    out_path = OUTPUT_DIR / "Banky Wellington_Coding_Units_200.xlsx"
    df[out_cols].to_excel(out_path, index=False)

    # Video breakdown
    breakdown = df.groupby("_video").size().reset_index(name="units")
    print("\n=== PER-VIDEO BREAKDOWN ===")
    print(breakdown.to_string(index=False))
    print(f"\nTotal units: {len(df)}")
    print(f"Written: {out_path.relative_to(ROOT)}")

    # QA
    wc = df["Verbatim Text (CODE THIS)"].str.split().str.len()
    print(f"\nWord counts: min={wc.min()}, med={int(wc.median())}, max={wc.max()}")
    print(f"Units over 140 words: {(wc > 140).sum()}")
    print(f"Empty themes: {df['Theme(s)'].str.strip().eq('').sum()}")
    print(f"Empty context: {df['Context (NOT CODED - comprehension only)'].str.strip().eq('').sum()}")


if __name__ == "__main__":
    main()

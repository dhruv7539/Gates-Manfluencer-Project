"""Finalize Banky MENtality transcripts using Gemini for speaker labelling.

Skips pyannote entirely (which was MPS-bound, slow). Sends each whisper
transcript to Gemini 2.5 Flash with the panel context; Gemini infers speaker
turns from conversational cues (introductions, name addresses, style).

Trade-off: less precise on rapid-fire interruptions vs pyannote, but accurate
on longer turns (>30 words) which is what we filter for in Banky-snippet coding.

All 6 episodes run in parallel via async Gemini calls. ETA: 5-15 min total.

Reads from cached whisper.json files in temp/transcribe_mentality/.
Writes to: Nigeria/Content Analysis/Content - Raw/Banky Wellington/Transcripts/<episode>.txt
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
assert os.getenv("GEMINI_API_KEY"), "GEMINI_API_KEY missing"

TRANS_DIR = ROOT / "Nigeria" / "Content Analysis" / "Content - Raw" / "Banky Wellington" / "Transcripts"
TEMP_DIR  = ROOT / "temp" / "transcribe_mentality"
TRANS_DIR.mkdir(parents=True, exist_ok=True)

GEMINI_MODEL = "gemini-2.5-flash"
CONCURRENCY = 6  # all 6 episodes in parallel
CHUNK_WORDS = 4000  # split long episodes into ~4000-word chunks for stable Gemini responses

EPISODES = [
    {"audio": "Masculinity + Money.mp3",
     "panel": ["Ebuka Obi-Uchendu (host)", "Banky W (Bankole Wellington)", "Seun Kuti", "Noble Igwe"]},
    {"audio": "Masculinity + Relationships.mp3",
     "panel": ["Ebuka Obi-Uchendu (host)", "Banky W", "Bovi Ugboma", "Do2dtun Energy gAD"]},
    {"audio": "Pt 2 Masculinity + Relationships.mp3",
     "panel": ["Ebuka Obi-Uchendu (host)", "Banky W", "Alex Ikemefuna", "Johnny Drille"]},
    {"audio": "Masculinity + Friendship.mp3",
     "panel": ["Ebuka Obi-Uchendu (host)", "Banky W", "Alex Ikemefuna"]},
    {"audio": "Masculinity + Fatherhood.mp3",
     "panel": ["Ebuka Obi-Uchendu (host)", "Banky W", "Timi Dakolo", "Hermes Iyele"]},
    {"audio": "Masculinity + Young Boys.mp3",
     "panel": ["Ebuka Obi-Uchendu (host)", "Banky W", "IK Osakioduwa", "Murewa", "Sonariwo OnDeck"]},
]

PROMPT_TEMPLATE = """You are a transcript editor. Below is a raw, unsegmented transcript chunk from one episode of the MENtality podcast (a Nigerian show about masculinity hosted by Ebuka Obi-Uchendu, with Banky W as a recurring panelist).

The transcript has NO speaker labels. Your job: read the conversational flow and assign each speaker turn to a specific named panelist from the list below. Use cues like:
- Direct name addresses ("Banky, what do you think?", "Seun, you mentioned...")
- Introductions and host-style transitions (Ebuka usually hosts, asks questions, transitions topics)
- Personal references (someone mentioning their own song, child, project, etc.)
- Speaking style and content patterns
- Pidgin / Yoruba / English code-switching patterns specific to each speaker

Format the output as:
SPEAKER NAME: full text of their turn

SPEAKER NAME: next speaker's turn

Each turn separated by a blank line. Use the EXACT speaker name as listed in the panel. If you genuinely cannot tell who said something, label it `UNCLEAR:` (avoid this — try hard to attribute first).

Do NOT add commentary, headers, or chunk markers. Output ONLY the labelled transcript.

Episode panel: {panel}

Transcript chunk:
---
{transcript}
---"""


def chunk_words(text, max_words):
    """Split text into chunks of approximately max_words, breaking on sentence boundaries when possible."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), max_words):
        chunks.append(" ".join(words[i:i + max_words]))
    return chunks


def whisper_to_text(whisper_data):
    """Concat all whisper segment texts into one continuous string."""
    return " ".join(s.get("text", "").strip() for s in whisper_data.get("segments", []))


async def label_chunk(client, panel, chunk_text):
    prompt = PROMPT_TEMPLATE.format(panel=", ".join(panel), transcript=chunk_text)
    for attempt in range(4):
        try:
            resp = await asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_MODEL,
                contents=prompt,
            )
            return resp.text.strip()
        except Exception as e:
            if attempt == 3:
                raise
            await asyncio.sleep(2 ** attempt)


async def label_episode(client, ep):
    audio = Path(ep["audio"])
    final = TRANS_DIR / f"{audio.stem}.txt"
    if final.exists():
        print(f"  ✓ already done: {final.name}", flush=True)
        return final

    whisper_path = TEMP_DIR / f"{audio.stem}.whisper.json"
    if not whisper_path.exists():
        print(f"  ! missing whisper cache: {whisper_path.name}", flush=True)
        return None

    print(f"  starting {audio.stem}", flush=True)
    t0 = time.time()
    whisper_data = json.loads(whisper_path.read_text())
    full_text = whisper_to_text(whisper_data)
    word_count = len(full_text.split())

    chunks = chunk_words(full_text, CHUNK_WORDS)
    print(f"  {audio.stem}: {word_count:,} words → {len(chunks)} chunks", flush=True)

    labelled_chunks = []
    for i, chunk in enumerate(chunks):
        labelled = await label_chunk(client, ep["panel"], chunk)
        labelled_chunks.append(labelled)
        print(f"    [{audio.stem}] chunk {i+1}/{len(chunks)} done", flush=True)

    final.write_text("\n\n".join(labelled_chunks))
    print(f"  ✓ {final.relative_to(ROOT)} ({time.time()-t0:.0f}s)", flush=True)
    return final


async def main():
    print(f"=== Gemini-only finalization (no pyannote) ===", flush=True)
    print(f"  model: {GEMINI_MODEL}", flush=True)
    print(f"  episodes: {len(EPISODES)} (running in parallel)", flush=True)
    t0 = time.time()

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    sem = asyncio.Semaphore(CONCURRENCY)

    async def run(ep):
        async with sem:
            try:
                return await label_episode(client, ep)
            except Exception as e:
                print(f"  ✗ FAILED {ep['audio']}: {e}", flush=True)
                import traceback; traceback.print_exc()
                return None

    await asyncio.gather(*(run(ep) for ep in EPISODES))

    print(f"\n=== ALL DONE ({(time.time()-t0)/60:.1f} min) ===", flush=True)
    for p in sorted(TRANS_DIR.glob("*.txt")):
        text = p.read_text()
        speakers = set()
        for line in text.split("\n"):
            if ":" in line:
                speakers.add(line.split(":", 1)[0].strip())
        words = sum(len(line.split(":", 1)[1].split()) for line in text.split("\n") if ":" in line)
        print(f"  {p.name}: {words:,} words, {len(speakers)} speakers", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

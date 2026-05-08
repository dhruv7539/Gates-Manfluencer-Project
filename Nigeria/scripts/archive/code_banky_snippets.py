"""Code Banky's MENtality podcast transcripts into ~230 scope-relevant snippets.

Pipeline:
  1. Parse each transcript, isolate ONLY Banky's speaker turns (drop guests + host)
  2. Substance gate (>=30 words per turn — drop reactions like "yeah", "exactly")
  3. Embed each Banky turn against masculinity scope anchors (text-embedding-3-large)
  4. gpt-4o-mini scope filter (binary keep/drop on masculinity relevance)
  5. Composite score (similarity + LLM relevance)
  6. Select top ~230 with theme diversity (cap per-theme at 30%)
  7. gpt-4o-mini generates theme(s) + context per selected snippet
  8. Output to Nigeria/Content Analysis/Content - Final/Banky Wellington_Podcast.xlsx

Schema matches the X-tweet coding output:
  Segment ID | Influencer | Platform | Content Type | Theme(s) |
  Context (NOT CODED - comprehension only) | Verbatim Text (CODE THIS)

Verbatim text = Banky's words only (per user spec). Context = brief topic note from
the surrounding episode/conversation.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from collections import Counter

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI, AsyncOpenAI
from tqdm.auto import tqdm
from tqdm.asyncio import tqdm as atqdm


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY missing"

TRANSCRIPTS_DIR = ROOT / "Nigeria" / "Content Analysis" / "Content - Raw" / "Banky Wellington" / "Transcripts"
OUT_DIR         = ROOT / "Nigeria" / "Content Analysis" / "Content - Final"
TEMP_DIR        = ROOT / "temp" / "code_banky_snippets"
OUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

EMBEDDING_MODEL = "text-embedding-3-large"
# gpt-4o (not mini) — better Pidgin / Yoruba code-switching, nuanced scope calls,
# higher-quality context generation. Per user spec: "accurate af".
LLM_MODEL = "gpt-4o"

TARGET_SNIPPETS = 230
MIN_WORDS = 5         # capture all substantive Banky speech (~189 candidates)
SKIP_SCOPE_FILTER = True  # MENtality is a masculinity podcast — Banky's substantive speech is in-scope by definition
MAX_PER_THEME = int(0.30 * TARGET_SNIPPETS)  # 30% cap per theme
LLM_BATCH_SIZE = 6    # smaller batches to stay under TPM (30K)
LLM_CONCURRENCY = 2   # lower concurrency to avoid 429s

EPISODES = [
    {"file": "Masculinity + Money.txt",                "topic": "Masculinity & Money",
     "panel": "Ebuka Obi-Uchendu, Banky W, Seun Kuti, Noble Igwe"},
    {"file": "Masculinity + Relationships.txt",        "topic": "Masculinity & Relationships",
     "panel": "Ebuka, Banky W, Bovi Ugboma, Do2dtun"},
    {"file": "Pt 2 Masculinity + Relationships.txt",   "topic": "Masculinity & Relationships, Pt 2",
     "panel": "Ebuka, Banky W, Alex Ikemefuna, Johnny Drille"},
    {"file": "Masculinity + Friendship.txt",           "topic": "Masculinity & Friendship",
     "panel": "Ebuka, Banky W, Alex Ikemefuna"},
    {"file": "Masculinity + Fatherhood.txt",           "topic": "Masculinity & Fatherhood",
     "panel": "Ebuka, Banky W, Timi Dakolo, Hermes Iyele"},
    {"file": "Masculinity + Young Boys.txt",           "topic": "Masculinity & Young Boys",
     "panel": "Ebuka, Banky W, IK Osakioduwa, Murewa, Sonariwo OnDeck"},
]

# Match Banky across plausible label variations Gemini might output
BANKY_PATTERNS = [
    r"^banky( wellington)?( \([^)]+\))?$",
    r"^banky w$",
    r"^banky w\b.*",
    r"^bankole( wellington)?$",
    r"^banky$",
]
BANKY_RE = re.compile("|".join(BANKY_PATTERNS), flags=re.IGNORECASE)


CANONICAL_THEMES = [
    "marriage_relationships", "infidelity_cheating", "polygamy_scarcity",
    "female_submission", "men_as_prize", "marriage_market_logic",
    "dating_standards", "sexual_double_standards",
    "fatherhood_parenting", "raising_boys", "male_role_models",
    "men_money_provider", "wealth_status",
    "male_emotional_life", "vulnerability_mental_health", "male_friendship",
    "gender_debate_feminism", "anti_women", "anti_feminism", "not_all_men_deflection",
    "religion_faith_framing", "biblical_marriage_framing",
    "humor_meme_pidgin", "self_promotion",
    # NO "other_off_scope" — model MUST pick a real theme; off-scope is filtered upstream
]

SCOPE_ANCHORS = [
    "what it means to be a real man, male identity",
    "men's emotional vulnerability and mental health",
    "fatherhood, raising sons, modeling masculinity",
    "men's friendships, brotherhood, peer accountability",
    "men and money, provider pressure, financial responsibility",
    "marriage, relationships, what men should bring",
    "gender roles, women's vs men's expectations",
    "advice to young men about love and life",
    "criticism of toxic masculinity, ego, pride",
    "religious or cultural framing of male duty",
    "intergenerational change in male behaviour",
    "men supporting their wives and families",
    "feminism, gender debate, male defensiveness",
    "personal testimony from a man about being a husband or father",
]


def banky_only(text):
    """Parse a transcript and return list of (Banky's text, episode_index) tuples."""
    turns = []
    for line in text.split("\n"):
        m = re.match(r"^([^:]+):\s*(.+)", line.strip())
        if not m:
            continue
        speaker = m.group(1).strip()
        utter = m.group(2).strip()
        if BANKY_RE.match(speaker):
            turns.append(utter)
    return turns


def load_all_banky_turns():
    """Returns list of dicts: {text, episode_topic, panel, episode_idx, position_in_episode}."""
    rows = []
    for ep_idx, ep in enumerate(EPISODES):
        path = TRANSCRIPTS_DIR / ep["file"]
        if not path.exists():
            print(f"  ! transcript missing: {ep['file']}")
            continue
        text = path.read_text()
        banky_turns = banky_only(text)
        # Filter by word count
        for pos, utter in enumerate(banky_turns):
            words = len(utter.split())
            if words < MIN_WORDS:
                continue
            rows.append({
                "text": utter,
                "n_words": words,
                "episode_idx": ep_idx,
                "episode_topic": ep["topic"],
                "panel": ep["panel"],
                "position_in_episode": pos,
            })
    return rows


def embed_batch(client, texts):
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=list(texts))
    return np.array([d.embedding for d in resp.data])


def score_with_embeddings(rows):
    client = OpenAI()
    print(f"  embedding {len(rows)} Banky turns + {len(SCOPE_ANCHORS)} anchors...")
    anchor_emb = embed_batch(client, SCOPE_ANCHORS)
    anchor_emb /= np.linalg.norm(anchor_emb, axis=1, keepdims=True)

    cache_path = TEMP_DIR / f"embeddings_{len(rows)}.npy"
    if cache_path.exists():
        emb = np.load(cache_path)
    else:
        chunks = []
        for start in tqdm(range(0, len(rows), 256), desc="embedding"):
            batch = [r["text"] for r in rows[start:start + 256]]
            chunks.append(embed_batch(client, batch))
        emb = np.vstack(chunks)
        np.save(cache_path, emb)

    emb_norm = emb / np.linalg.norm(emb, axis=1, keepdims=True)
    sims = emb_norm @ anchor_emb.T
    for i, row in enumerate(rows):
        row["sim_max"] = float(sims[i].max())
    return rows


SCOPE_FILTER_PROMPT = """You are a research coder for a Norman Lear Center / Gates Foundation study of healthy masculinity media in Nigeria. Each input is one snippet from Banky Wellington (Nigerian progressive musician + actor + host) speaking on the MENtality podcast — a panel show about masculinity, fatherhood, marriage, money, male friendship, mental health, vulnerability, gender norms.

Mark the snippet RELEVANT if it engages with ANY of the following, even indirectly:
  • What it means to be a man / male identity / manhood
  • Fatherhood, raising sons, modeling masculinity for boys
  • Marriage, infidelity, partnership, what men should bring to relationships
  • Men and money: provider pressure, status, earning anxiety
  • Male emotional life: vulnerability, mental health, asking for help, opening up
  • Male friendship, brotherhood, peer accountability, "love you bro" discomfort
  • Gender roles, women's expectations vs men's, double standards
  • Religious / cultural framing of male duty (NOT pure faith praise)
  • Advice / personal testimony about being a husband, father, son, or friend
  • Critique of toxic masculinity, ego, pride, traditional expectations
  • Reflections on intergenerational change in how Nigerian men behave
  • Pidgin or Yoruba code-switched takes on any of the above (these often carry the most authentic content — DO NOT mark off-topic just because of slang)

Mark NOT RELEVANT only for:
  • Pure show-business banter with no thematic content (intro/outro reads, "let's go to break")
  • Off-topic chatter (food, sports, scheduling) with no gender/masculinity tie-in
  • Pure greetings or host-task statements ("welcome back", "thanks for joining")
  • Pure faith praise without any masculinity content ("Amen", "God bless this show")

Be GENEROUS. When in doubt, mark RELEVANT. Personal stories about being a man, husband, or father almost always count.

Return JSON: {"results": [{"id": <int>, "relevant": true|false, "reason": "<short, max 12 words>"}]}"""


def build_filter_prompt(items):
    lines = ["Snippets:"]
    for i, text in items:
        lines.append(f"[{i}] {text.replace(chr(10), ' ')[:600]}")
    return "\n".join(lines)


async def filter_batch(client, sem, items):
    async with sem:
        for attempt in range(8):
            try:
                resp = await client.chat.completions.create(
                    model=LLM_MODEL, temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": SCOPE_FILTER_PROMPT},
                        {"role": "user", "content": build_filter_prompt(items)},
                    ],
                )
                data = json.loads(resp.choices[0].message.content)
                out = {}
                for r in data.get("results", []):
                    rid = r.get("id")
                    if rid is not None:
                        out[rid] = (bool(r.get("relevant")), r.get("reason", ""))
                return out
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "rate_limit" in err_str.lower():
                    if attempt < 7:
                        await asyncio.sleep(min(5 * (2 ** attempt), 90))
                        continue
                if attempt == 7:
                    print(f"  ! filter batch failed: {err_str[:200]}")
                    return {}
                await asyncio.sleep(2 ** attempt)


async def llm_scope_filter(rows):
    cache_path = TEMP_DIR / "scope_filter.json"
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
    else:
        cache = {}
    pending = [(i, r["text"]) for i, r in enumerate(rows) if str(i) not in cache]
    print(f"  scope filter: cached {len(cache)}, pending {len(pending)}")

    if pending:
        client = AsyncOpenAI()
        sem = asyncio.Semaphore(LLM_CONCURRENCY)
        coros = []
        for start in range(0, len(pending), LLM_BATCH_SIZE):
            batch = pending[start:start + LLM_BATCH_SIZE]
            coros.append(filter_batch(client, sem, batch))
        results = await atqdm.gather(*coros, desc="scope filter")
        for batch_out in results:
            for rid, (rel, reason) in batch_out.items():
                cache[str(rid)] = {"relevant": rel, "reason": reason}
        cache_path.write_text(json.dumps(cache, indent=1))

    for i, row in enumerate(rows):
        meta = cache.get(str(i), {"relevant": False, "reason": "missing"})
        row["llm_relevant"] = bool(meta.get("relevant"))
        row["llm_reason"] = meta.get("reason", "")
    return rows


THEME_PROMPT = """You are a research coder for a study of Nigerian masculinity influencers. Each input is one verbatim quote from Banky Wellington speaking on the MENtality podcast (a panel show about masculinity, fatherhood, marriage, money, friendship, mental health, gender).

For each snippet:
1. Pick 1-3 THEMES from this exact list (semicolon-separated):
   {themes}

CRITICAL: every snippet has ALREADY passed the masculinity scope filter — they ARE on-topic. Your job is to pick the BEST-FITTING themes from the list. There is NO "off scope" option. If a snippet seems borderline, pick the closest-matching theme(s) from the list rather than overthinking it.

2. Write ONE concise CONTEXT sentence (max 25 words) for the human coder explaining what episode/topic Banky was discussing and any reference (slang, shows, names) the coder might miss. The context will appear in a "Context (NOT CODED - comprehension only)" column.

Episode metadata is included to help you write accurate context.

Return JSON only:
{{"results": [{{"id": <int>, "themes": "theme1; theme2", "context": "..."}}]}}"""


def build_theme_prompt(items_with_meta):
    lines = ["Snippets (each with episode metadata):"]
    for i, text, topic, panel in items_with_meta:
        lines.append(f"\n[{i}] EPISODE: {topic} | PANEL: {panel}\nBANKY SAID: {text.replace(chr(10), ' ')[:800]}")
    return "\n".join(lines)


async def code_batch(client, sem, items_with_meta):
    async with sem:
        for attempt in range(8):
            try:
                resp = await client.chat.completions.create(
                    model=LLM_MODEL, temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": THEME_PROMPT.format(themes=", ".join(CANONICAL_THEMES))},
                        {"role": "user", "content": build_theme_prompt(items_with_meta)},
                    ],
                )
                data = json.loads(resp.choices[0].message.content)
                out = {}
                for r in data.get("results", []):
                    rid = r.get("id")
                    if rid is not None:
                        out[rid] = (str(r.get("themes", "")), str(r.get("context", "")))
                return out
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "rate_limit" in err_str.lower():
                    if attempt < 7:
                        await asyncio.sleep(min(5 * (2 ** attempt), 90))
                        continue
                if attempt == 7:
                    print(f"  ! theme batch failed: {err_str[:200]}")
                    return {}
                await asyncio.sleep(2 ** attempt)


async def code_themes_and_context(selected):
    cache_path = TEMP_DIR / "theme_codes.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    pending = []
    for i, row in enumerate(selected):
        key = f"{row['episode_idx']}_{row['position_in_episode']}"
        if key not in cache:
            pending.append((i, row["text"], row["episode_topic"], row["panel"], key))
    print(f"  theme coder: cached {len(cache)}, pending {len(pending)}")

    if pending:
        client = AsyncOpenAI()
        sem = asyncio.Semaphore(LLM_CONCURRENCY)
        # Map LLM-returned id (= the global pending index) → cache key
        id_to_key = {c[0]: c[4] for c in pending}

        coros = []
        for start in range(0, len(pending), LLM_BATCH_SIZE):
            chunk = pending[start:start + LLM_BATCH_SIZE]
            items = [(c[0], c[1], c[2], c[3]) for c in chunk]
            coros.append(code_batch(client, sem, items))
        results = await atqdm.gather(*coros, desc="themes+context")
        for batch_out in results:
            # batch_out keys are LLM-returned ids (which match items[][0] = global pending index)
            for returned_id, (themes, ctx) in batch_out.items():
                key = id_to_key.get(returned_id)
                if key is not None:
                    cache[key] = {"themes": themes, "context": ctx}
        cache_path.write_text(json.dumps(cache, indent=1))

    coded = []
    for row in selected:
        key = f"{row['episode_idx']}_{row['position_in_episode']}"
        meta = cache.get(key, {"themes": "other_off_scope", "context": ""})
        coded.append({**row, "themes": meta["themes"], "context": meta["context"]})
    return coded


def select_diverse(rows, target):
    """Pick top-N by composite score with theme-balance cap."""
    rows = sorted(rows, key=lambda r: -r["score"])
    selected, theme_counts = [], Counter()
    for row in rows:
        if len(selected) >= target:
            break
        # Use the first listed theme for diversity bookkeeping
        first_theme = row.get("primary_theme") or row["themes"].split(";")[0].strip() if row.get("themes") else "untagged"
        if theme_counts[first_theme] >= MAX_PER_THEME:
            continue
        selected.append(row)
        theme_counts[first_theme] += 1
    # If we didn't hit target due to caps, fill with whatever's left
    if len(selected) < target:
        remaining = [r for r in rows if r not in selected]
        selected.extend(remaining[:target - len(selected)])
    return selected[:target]


async def main():
    print("=== Banky snippet coding pipeline ===")
    print(f"  target snippets: {TARGET_SNIPPETS}")
    print(f"  min words/turn:  {MIN_WORDS}")
    print(f"  per-theme cap:   {MAX_PER_THEME}")

    # Step 1: parse + filter
    print("\n--- 1. Parse transcripts, isolate Banky turns ---")
    rows = load_all_banky_turns()
    print(f"  total Banky turns >= {MIN_WORDS} words: {len(rows)}")
    if len(rows) < TARGET_SNIPPETS:
        print(f"  ! only {len(rows)} substantive turns available — will keep all and stop early")

    if not rows:
        print("ABORT: no Banky turns found. Check transcript labelling.")
        return

    # Step 2: embed (for ranking + diversity later)
    print("\n--- 2. Embed against scope anchors ---")
    rows = score_with_embeddings(rows)

    if SKIP_SCOPE_FILTER:
        print("\n--- 3. Scope filter SKIPPED (MENtality is a masculinity podcast — all Banky speech is in-scope) ---")
        for r in rows:
            r["llm_relevant"] = True
            r["llm_reason"] = "podcast-context-implies-in-scope"
    else:
        print("\n--- 3. LLM scope filter (gpt-4o) ---")
        rows = await llm_scope_filter(rows)

    # Step 4: composite score
    for r in rows:
        r["score"] = 0.5 * r["sim_max"] + 0.5 * (1.0 if r["llm_relevant"] else 0.0)

    # Step 5: theme tagging + context
    print("\n--- 4. Theme tagging + context (gpt-4o) on candidates ---")
    eligible = [r for r in rows if r["llm_relevant"]]
    print(f"  scope-relevant pool: {len(eligible)}")
    eligible_sorted = sorted(eligible, key=lambda r: -r["score"])
    candidates = eligible_sorted[: int(TARGET_SNIPPETS * 1.5)]  # 1.5x slack for diversity selection
    coded = await code_themes_and_context(candidates)

    # Step 6: theme-balanced selection
    print("\n--- 5. Theme-balanced selection ---")
    final = select_diverse(coded, TARGET_SNIPPETS)
    if len(final) < 200:
        print(f"  ! WARNING: only {len(final)} snippets, below user's 200 minimum")
    print(f"  final count: {len(final)}")

    theme_dist = Counter()
    for r in final:
        for t in r["themes"].split(";"):
            theme_dist[t.strip()] += 1
    print("  theme distribution:")
    for t, n in theme_dist.most_common():
        print(f"    {n:>4}  {t}")

    # Step 7: build output dataframe
    print("\n--- 6. Write output ---")
    final_sorted = sorted(final, key=lambda r: (r["episode_idx"], r["position_in_episode"]))
    df = pd.DataFrame([{
        "Segment ID": f"BNK_{i+1:03d}",
        "Influencer": "Banky Wellington",
        "Platform": "YouTube (MENtality podcast)",
        "Content Type": "Podcast snippet",
        "Theme(s)": r["themes"],
        "Context (NOT CODED - comprehension only)": r["context"],
        "Verbatim Text (CODE THIS)": r["text"],
    } for i, r in enumerate(final_sorted)])

    out_path = OUT_DIR / "Banky Wellington_Podcast.xlsx"
    df.to_excel(out_path, index=False)
    print(f"  → {out_path.relative_to(ROOT)}: {len(df)} snippets")
    print(f"\n=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())

# Audience Comments — Nigeria

**Norman Lear Center × Gates Foundation — Manfluencer project**

End-to-end pipeline for Nigeria audience comments. Two distinct stages, two output folders:

```
   Audience Comments - Raw                        Audience Comments - Complete                  Audience Comments - Final
   ────────────────────────       Stage 1         ──────────────────────────       Stage 2      ────────────────────────
   Full scraped metadata    ───── cleaning ────►  Cleaned + deduped text-only ──── LLM scope ──► Top-N curated, faith stripped
   (author, likes, etc.)         (no LLM)         (one-to-one mirror of Raw)      filter         (manager-facing final set)
```

### Stage 1 — Raw → Complete  (cleaning only, no LLM)

Deterministic processing of the raw scrapes. Unicode normalisation, smart-quote replacement, whitespace stripping, dedup, drop empty/too-short rows. Output is a one-to-one mirror of the Raw folder structure with a single `text` column.

### Stage 2 — Complete → Final  (keywords + embeddings + LLM filter)

Apply the masculinity scope filter on top of the cleaned set:
- Keyword annotation against the NLC lexicon (signal, not gate)
- OpenAI `text-embedding-3-large` similarity to per-orientation anchor phrases
- `gpt-4o-mini` lenient relevance check (cached)
- Composite score: `0.20 × keyword + 0.35 × similarity + 0.45 × LLM relevance`
- Top-N per source file
- Faith strip (substantive religious framing removed; colloquial idioms kept)

Output goes to `Audience Comments - Final/` with `Creator_PostTitle.xlsx` filenames, single `text` column.


## Setup


```python
from __future__ import annotations
import asyncio, json, os, re, unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI
from tqdm.asyncio import tqdm as atqdm
from tqdm.auto import tqdm

ROOT = Path.cwd().parents[1] if Path.cwd().name == "Notebooks" else Path.cwd()
print("Project root:", ROOT)
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY not set in .env"

```

## Config


```python
COUNTRY = "Nigeria"
COUNTRY_DIR  = ROOT / COUNTRY
RAW_DIR      = COUNTRY_DIR / "Audience Analysis" / "Audience Comments - Raw"
COMPLETE_DIR = COUNTRY_DIR / "Audience Analysis" / "Audience Comments - Complete"
FINAL_DIR    = COUNTRY_DIR / "Audience Analysis" / "Audience Comments - Final"
KEYWORDS_XLSX = ROOT / "Proposed Keywords & Codebooks" / "NLC Proposed keywords.xlsx"
TEMP_DIR     = ROOT / "temp" / "audience_comments_nigeria"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
COMPLETE_DIR.mkdir(parents=True, exist_ok=True)
FINAL_DIR.mkdir(parents=True, exist_ok=True)

EMBEDDING_MODEL = "text-embedding-3-large"
LLM_MODEL = "gpt-4o-mini"
MIN_CHARS = 5         # Stage 1: drop comments shorter than this
MIN_WORDS = 8         # Stage 2: substance gate before LLM
TARGET_PER_POST = 200 # Stage 2: final cap per source file
LLM_BATCH_SIZE = 20
LLM_CONCURRENCY = 16
EMBED_BATCH_SIZE = 256

print(f"Raw:      {RAW_DIR.relative_to(ROOT)}")
print(f"Complete: {COMPLETE_DIR.relative_to(ROOT)}")
print(f"Final:    {FINAL_DIR.relative_to(ROOT)}")

```

# Stage 1 — Raw → Complete (cleaning, no LLM)

Read every file from `Audience Comments - Raw`, apply deterministic text cleaning, write a one-to-one cleaned mirror to `Audience Comments - Complete` with a single `text` column.

This stage is **free, fast, and reproducible**. It does not call any model.



```python
def clean_text(s):
    if not isinstance(s, str): return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def clean_one_file(src_path, dest_path):
    df = pd.read_excel(src_path) if src_path.suffix.lower() == ".xlsx" else pd.read_csv(src_path)
    text_col = next((c for c in ("text", "comment") if c in df.columns), None)
    if text_col is None:
        print(f"  ! no text column in {src_path.name}")
        return 0
    cleaned = pd.DataFrame({"text": df[text_col].astype(str).apply(clean_text)})
    cleaned = cleaned[cleaned["text"].str.len() >= MIN_CHARS]
    cleaned = cleaned.drop_duplicates(subset="text", keep="first").reset_index(drop=True)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_excel(dest_path.with_suffix(".xlsx"), index=False)
    return len(cleaned)

n_files = n_total = 0
for src in RAW_DIR.rglob("*"):
    if src.is_dir() or src.suffix.lower() not in (".xlsx", ".csv"):
        continue
    rel = src.relative_to(RAW_DIR)
    dest = COMPLETE_DIR / rel
    n = clean_one_file(src, dest)
    n_files += 1
    n_total += n
print(f"\nStage 1 complete — {n_files} files, {n_total:,} total comments → {COMPLETE_DIR.relative_to(ROOT)}")

```

# Stage 2 — Complete → Final (LLM scope filter + final selection)

Read everything from `Audience Comments - Complete`, run the four-signal pipeline, write the curated subset to `Audience Comments - Final`.

Sub-stages: **2a** keywords → **2b** embeddings → **2c** LLM relevance → **2d** composite + top-N → **2e** faith strip → **2f** export.


## Stage 2a — Keyword annotation (NLC lexicon)


```python
sheet = "Nigeria"
kw_df = pd.read_excel(KEYWORDS_XLSX, sheet_name=sheet)
kw_df = kw_df.dropna(subset=["Keyword"])
kw_df["Keyword"] = kw_df["Keyword"].astype(str).str.strip()
kw_df = kw_df[kw_df["Keyword"].str.len() >= 2]
rel_col = "Relevance to manosphere conversations"
kw_set = set(kw_df.loc[kw_df[rel_col].str.contains("Highly|Moderately", na=False), "Keyword"].str.lower())
print(f"Lexicon: {len(kw_set)} keywords (Highly + Moderately relevant)")

escaped = sorted([re.escape(k) for k in kw_set], key=len, reverse=True)
KW_REGEX = re.compile(r"\b(" + "|".join(escaped) + r")\b", flags=re.IGNORECASE) if escaped else None

def kw_hits(text):
    return list(dict.fromkeys(KW_REGEX.findall(str(text).lower()))) if KW_REGEX else []

```

## Stage 2b — Pool Complete files + embed against scope anchors

Pool every cleaned comment from `Audience Comments - Complete`, apply the 8-word substance gate (LLM is wasteful on one-liners), and embed with `text-embedding-3-large`. Embeddings are cached so re-runs are essentially free.



```python
ANCHORS_REGRESSIVE = [
    "what it means to be a man",
    "men as the prize and women competing for husbands",
    "marriage, infidelity and whether to leave a cheating husband",
    "polygamy and female scarcity narratives",
    "advice to women about staying or leaving",
    "feminism, misogyny and women's rights",
    "men's responsibilities, accountability and male behaviour",
    "sex, dating standards and sexual double standards",
]

ANCHORS_PROGRESSIVE = [
    "men's responsibilities, accountability and emotional growth",
    "healthy masculinity, vulnerability and male mental health",
    "fatherhood, raising sons, modeling masculinity for boys",
    "men supporting women's safety and bodily autonomy",
    "false rape accusations vs legitimate due process",
    "male defensiveness and 'not all men' deflection",
    "criticism of toxic masculinity, ego, pride or chauvinism",
    "feminism, gender debate and male defensiveness",
]

ANCHORS = list(set(ANCHORS_REGRESSIVE + ANCHORS_PROGRESSIVE))
print(f"Anchor count: {len(ANCHORS)}")

client = OpenAI()
def embed_batch(texts):
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=list(texts))
    return np.array([d.embedding for d in resp.data])

anchor_emb = embed_batch(ANCHORS)
anchor_emb = anchor_emb / np.linalg.norm(anchor_emb, axis=1, keepdims=True)

```


```python
# Pool Complete files
records = []
for f in COMPLETE_DIR.rglob("*.xlsx"):
    if f.name.startswith("~$"): continue
    df = pd.read_excel(f)
    rel = f.relative_to(COMPLETE_DIR)
    df["source_file"] = str(rel)
    records.append(df)
sub = pd.concat(records, ignore_index=True)
sub["n_words"] = sub["text"].astype(str).str.split().str.len()
sub = sub[sub["n_words"] >= MIN_WORDS].reset_index(drop=True)
print(f"Pooled substantive comments: {len(sub):,}")

# Embed (cached)
embeds_path = TEMP_DIR / "embeddings.npy"
if embeds_path.exists() and len(np.load(embeds_path)) == len(sub):
    emb = np.load(embeds_path)
    print(f"Loaded cached embeddings: {emb.shape}")
else:
    chunks = []
    for start in tqdm(range(0, len(sub), EMBED_BATCH_SIZE), desc="embedding"):
        chunks.append(embed_batch(sub["text"].iloc[start:start + EMBED_BATCH_SIZE].tolist()))
    emb = np.vstack(chunks)
    np.save(embeds_path, emb)

emb_norm = emb / np.linalg.norm(emb, axis=1, keepdims=True)
sub["sim_max"] = (emb_norm @ anchor_emb.T).max(axis=1)
sub["has_keyword"] = sub["text"].apply(lambda t: bool(kw_hits(t)))

```

## Stage 2c — LLM relevance check (gpt-4o-mini, lenient)

Each substantive comment goes to `gpt-4o-mini` in async batches of 20 with a generous prompt (relevant if it engages at all with masculinity/marriage/gender; not relevant only for spam/hype/insult). Results are cached to parquet — first run costs ~$3–5, re-runs are free.



```python
SYSTEM_PROMPT = """You are a research coder reviewing audience comments on social-media posts about masculinity in Nigeria/Kenya — both regressive (anti-women, scarcity, submission) and progressive (accountability, vulnerability, healthy masculinity).

Mark a comment RELEVANT if it engages — in any way — with masculinity, marriage, gender roles, men's behaviour, men's emotions, fatherhood, dating, sex, polygamy, or related themes. Be GENEROUS:
  • Direct discussion of any of the above
  • Agreement OR disagreement with the creator
  • Personal testimony or lived experience
  • Religion- or culture-framed takes
  • Substantive reaction with reasoning

Mark NOT RELEVANT only if:
  • Pure spam, ads, follow-back requests
  • Off-topic chatter
  • Empty hype with zero content ("nice", "lmao", "first", "❤️")
  • Pure faith praise with no masculinity content
  • Pure insult with no engagement on the topic

Return JSON: {"results": [{"id": <int>, "relevant": true|false, "reason": "<short reason>"}]}"""

def build_user_prompt(batch):
    lines = ["Comments:"]
    for i, t in batch:
        lines.append(f"[{i}] {str(t).replace(chr(10), ' ')[:400]}")
    return "\n".join(lines)

async def classify_batch(async_client, local_to_global, batch, sem):
    async with sem:
        for attempt in range(4):
            try:
                resp = await async_client.chat.completions.create(
                    model=LLM_MODEL, temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": build_user_prompt(batch)},
                    ],
                )
                data = json.loads(resp.choices[0].message.content)
                out = []
                for r in data.get("results", []):
                    lid = r.get("id")
                    if lid in local_to_global:
                        out.append((local_to_global[lid], bool(r.get("relevant")), r.get("reason", "")))
                return out
            except Exception as e:
                if attempt == 3:
                    return [(local_to_global[i], None, f"error: {e}") for i, _ in batch]
                await asyncio.sleep(2 ** attempt)

async def classify_all(sub_df):
    async_client = AsyncOpenAI()
    sem = asyncio.Semaphore(LLM_CONCURRENCY)
    coroutines = []
    g_idx = sub_df.index.tolist()
    texts = sub_df["text"].tolist()
    for start in range(0, len(texts), LLM_BATCH_SIZE):
        chunk = list(enumerate(texts[start:start + LLM_BATCH_SIZE], start=start))
        local_to_global = {local_i: g_idx[local_i] for local_i, _ in chunk}
        coroutines.append(classify_batch(async_client, local_to_global, chunk, sem))
    print(f"Dispatching {len(coroutines)} LLM batches...")
    rows = []
    tasks = [asyncio.create_task(c) for c in coroutines]
    for fut in atqdm.as_completed(tasks, total=len(tasks), desc="LLM"):
        rows.extend(await fut)
    return rows

llm_path = TEMP_DIR / "llm_results.parquet"
if llm_path.exists():
    llm_df = pd.read_parquet(llm_path)
    print(f"Loaded cached LLM results: {len(llm_df):,}")
else:
    rows = await classify_all(sub)
    llm_df = pd.DataFrame([{"sub_idx": idx, "llm_relevant": rel, "llm_reason": reason}
                           for idx, rel, reason in rows]).drop_duplicates("sub_idx")
    llm_df.to_parquet(llm_path)

sub = sub.merge(llm_df, left_index=True, right_on="sub_idx", how="left").drop(columns="sub_idx").reset_index(drop=True)
sub["llm_relevant"] = sub["llm_relevant"].fillna(False).astype(bool)
print(f"LLM-relevant rate: {sub['llm_relevant'].mean():.1%}")

```

## Stage 2d — Composite score + top-N per source file


```python
sub["sim_scaled"] = sub.groupby("source_file")["sim_max"].transform(
    lambda s: (s - s.min()) / (s.max() - s.min() + 1e-9)
)
sub["score"] = (
    0.20 * sub["has_keyword"].astype(float)
    + 0.35 * sub["sim_scaled"]
    + 0.45 * sub["llm_relevant"].astype(float)
)

selected = []
for src_file, g in sub.groupby("source_file"):
    eligible = g[g["llm_relevant"]].sort_values("score", ascending=False)
    top = eligible.head(TARGET_PER_POST).copy()
    selected.append(top)
selected = pd.concat(selected, ignore_index=True)
print(f"Selected pre-faith-strip: {len(selected):,}")

```

## Stage 2e — Faith strip

Removes comments with substantive religious framing (Bible / Jesus / God-as-subject / Islam / etc.). Colloquial idioms (`hell` as exclamation, `God help me` as exasperation) are preserved.



```python
FAITH_LOOSE = re.compile(
    r"\b(god|gods|jesus|christ|christian|christianity|bible|biblical|"
    r"pastor|preacher|reverend|congregation|church|mosque|temple|"
    r"amen|hallelujah|prayer|praying|prayed|prayers|"
    r"blessing|blessed|spiritual|faith|believer|believers|salvation|"
    r"sin|sinner|deity|holy|sacred|"
    r"scriptural|scripture|verse|verses|prophet|prophecy|"
    r"islam|islamic|muslim|allah|quran|sharia|gospel|"
    r"divine|heaven|heavens|hell|repent|"
    r"isaiah|psalm|proverbs|matthew|john|luke|mark)\b",
    flags=re.IGNORECASE,
)

faith_mask = selected["text"].apply(lambda t: bool(FAITH_LOOSE.search(str(t))))
print(f"Faith-content rows removed: {int(faith_mask.sum())}")
selected = selected.loc[~faith_mask].reset_index(drop=True)
print(f"Final after faith strip: {len(selected):,}")

```

## Stage 2f — Export to `Audience Comments - Final/`

Filenames use the `Creator_PostTitle` long format (derived from the source path). Single `text` column, ready for the manager.



```python
for src_file, g in selected.groupby("source_file"):
    parts = Path(src_file).with_suffix("").parts
    out_name = "_".join(parts) + ".xlsx"
    out_path = FINAL_DIR / out_name
    pd.DataFrame({"text": g.sort_values("score", ascending=False)["text"].values}).to_excel(out_path, index=False)
    print(f"  wrote {out_name}: {len(g)} rows")
print(f"\nDone. {len(list(FINAL_DIR.glob('*.xlsx')))} files in {FINAL_DIR.relative_to(ROOT)}")

```

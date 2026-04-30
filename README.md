# GATES Manfluencer Project

**Norman Lear Center, USC Annenberg — Gates Foundation**

A multi-method analysis of masculinity-focused media content in and adjacent to the "manosphere" in **Kenya** and **Nigeria**. This repository contains the technical pipeline for transcribing, cleaning, scoping, and analyzing influencer content and audience comments.

---

## Project Scope

The study focuses on media content that explicitly or implicitly promotes or challenges gender norms, with four interrelated components:

1. **Landscape Analysis** — Review of masculinity-related discourse, influencers, platforms, and keywords in Kenya and Nigeria
2. **Content Analysis** — Analysis of 10 high-reach creators (5 per country) across their media outputs
3. **Audience Reception Analysis** — Engagement metrics and qualitative analysis of audience comments
4. **Playbook Development** — Counternarrative strategies for healthier masculinity content

### Creators Studied

| Creator | Country | Orientation | Platform | Content Focus |
|---|---|---|---|---|
| Eric Amunga (Amerix) | Kenya | Regressive | X | Sexual hierarchy, female submission, #MasculinitySaturday |
| Andrew Kibe | Kenya | Regressive | X / YouTube | Anti-women cynicism, status, male advice |
| Philip Karanja | Kenya | Progressive | YouTube | Fatherhood (Girl Dad), violence against women, allyship |
| Onyango Otieno (Rixpoet) | Kenya | Progressive | YouTube | Trauma recovery, anti-toxic masculinity, mental health |
| Eddy Kimani | Kenya | Progressive | TikTok / YouTube | Depression, failure recovery, men's mental health |
| Banky Wellington | Nigeria | Progressive | YouTube (MENtality) | Healthy masculinity, marriage, fatherhood, vulnerability |
| Deyemi Okanlawon | Nigeria | Progressive | X | Male accountability, rape culture, anti-deflection |
| Wizarab | Nigeria | Regressive | X | Denigrating women, feminists, single mothers |
| Shola | Nigeria | Regressive | X | Availability trap, female submission, provider anxiety |
| Agba John Doe | Nigeria | Regressive | X | Soft patriarchy, marriage-market logic, sexual double standards |

---

## Repository Structure

The project is split by country at the top level. Country-specific data, notebooks, and scripts all live under `Nigeria/` or `Kenya/`. Only project-wide assets (codebook, scope docs) sit at the root.

```
Gates-Manfluencer-Project/
├── Nigeria/
│   ├── Audience Analysis/
│   │   ├── Audience Comments - Raw/        # Full unfiltered scrapes per creator
│   │   │   ├── Agba John Doe/
│   │   │   ├── Banky Wellington/
│   │   │   │   ├── YouTube/                # Sermons (legacy, not in final scope)
│   │   │   │   ├── Instagram/              # IG posts (legacy, not in final scope)
│   │   │   │   └── MENtality/              # 6 episodes — used for final analysis
│   │   │   ├── Deyemi Okanlawon/
│   │   │   ├── Shola/
│   │   │   └── Wizarab/
│   │   ├── Audience Comments - Complete/   # Cleaned + deduped, single `text` column
│   │   │                                   # (one-to-one mirror of Raw, no LLM filter)
│   │   └── Audience Comments - Final/      # Curated, scope-relevant set for the manager
│   │       ├── Agba John Doe_Never Leave Marriage Because Husband Cheated.xlsx
│   │       ├── Shola_7 Women Will Beg One Man to Marry.xlsx
│   │       ├── Deyemi Okanlawon_Stop Raping Women Response.xlsx
│   │       └── Banky Wellington_MENtality Podcast.xlsx
│   ├── Content Analysis/                   # Per-creator coding units (qualitative)
│   ├── Notebooks/
│   │   ├── Audience Comments.ipynb         # Stage 1 (clean) → Stage 2 (LLM scope filter)
│   │   ├── Content Analysis.ipynb          # Coding-unit pipeline (placeholder)
│   │   └── Data Acquisition Pipeline.ipynb # Scraping + transcription (consolidated)
│   ├── Scraped Tweets/                     # Apify creator-tweet scrapes
│   └── scripts/                            # Python utilities (scrapers, transcription, etc.)
│
├── Kenya/
│   ├── Audience Comments - Raw/            # 10 raw scrapes (X, YouTube, TikTok, Instagram)
│   ├── Audience Analysis Plots/            # Generated plots from earlier analysis
│   ├── Captions/, Generated Transcripts/   # Source captions + ASR transcripts
│   └── Topic Relevant Comments/            # Earlier-pass topic-filtered output
│
├── Proposed Keywords & Codebooks/
│   ├── Gates Content Analysis Codebook.docx
│   └── NLC Proposed keywords.xlsx          # 400+ keyword lexicon (Nigeria + Kenya sheets)
│
├── Scope/                                  # Project-wide scope + analysis sample docs
│   ├── Gates Masculinity Scope - Streamlined.docx
│   ├── Landscape & Content Analysis - Participants, Creators.docx
│   ├── KENYA - Content and Audience Analysis Samples.docx
│   ├── NIGERIA - Content and Audience Analysis Samples.docx
│   └── imgs/Video ASR Workflow.png
│
├── README.md
├── requirements.txt
└── temp/                                   # Caches (gitignored)
```

---

## Audience Comments Pipeline (3 Tiers)

For each creator, audience comments flow through three stages:

```
Audience Comments - Raw       Stage 1       Audience Comments - Complete       Stage 2        Audience Comments - Final
─────────────────────────  ── cleaning ──►  ──────────────────────────────  ── LLM filter ──►  ────────────────────────
Full scraped metadata          (no LLM)     Cleaned + deduped text-only     keywords +         Top-N curated, faith
(author, likes, etc.)                       (one-to-one mirror of Raw)      embeddings +       stripped (manager set)
                                                                            gpt-4o-mini
```

Both stages are wired up in `Nigeria/Notebooks/Audience Comments.ipynb`.

### Tier 1 — Raw

Full unfiltered scrapes. Schema preserved exactly as scraped:
- **YouTube**: `author`, `comment`, `likes`, `reply_count`
- **X / Twitter**: `author`, `text`, `likes`, `replies`, `retweets`, `timestamp`, `url`
- **TikTok / Instagram**: platform-specific schemas

For Banky, comments are organised by source platform: `YouTube/` (sermons), `Instagram/` (3 posts), `MENtality/` (6 podcast episodes — the source for the final dataset).

### Tier 2 — Complete (cleaning, no LLM)

Output of **Stage 1** in `Audience Comments.ipynb`. Deterministic processing only — no API calls:

- Unicode normalisation (NFKC)
- Smart-quote replacement
- Whitespace collapsing
- Drop empty + too-short comments (< 5 chars)
- Drop exact duplicates
- Single `text` column, one-to-one mirror of Raw

Free, fast, repeatable.

### Tier 3 — Final (LLM scope filter + manual curation)

Output of **Stage 2** in `Audience Comments.ipynb`, with additional manual curation. Stage 2 sub-stages:

- **2a — Keyword annotation** against NLC Nigeria/Kenya lexicon
- **2b — Embedding similarity** to per-orientation anchor phrases (`text-embedding-3-large`)
- **2c — LLM relevance check** (`gpt-4o-mini`, async batched, cached)
- **2d — Composite score** + top-N per source file (`0.20 × keyword + 0.35 × similarity + 0.45 × LLM relevance`)
- **2e — Faith strip** (substantive religious framing removed; colloquial idioms kept)
- **2f — Export** to `Audience Comments - Final/<Creator>_<PostTitle>.xlsx`

The 4 final Nigeria datasets after manual curation:

| Creator | Source | Comments |
|---|---|---:|
| Agba John Doe | X — *Never Leave Marriage Because Husband Cheated* | 177 |
| Shola | X — *7 Women Will Beg One Man to Marry* | 89 |
| Deyemi Okanlawon | X — *Stop Raping Women Response* | 194 |
| Banky Wellington | YouTube — *MENtality Podcast* (6 episodes pooled) | 505 |
| **Total** | | **965** |

Each final file has a single `text` column. Beyond the notebook output, manual review passes also removed: duplicates, OP-text leakage, generic praise, format critiques, weak jokes, and Grok bot pings (`@grok` prompts that aren't real audience opinions).

---

## Content Analysis Pipeline

Per-creator coding-unit datasets in `Nigeria/Content Analysis/`. The pipeline lives in `Nigeria/Notebooks/Content Analysis.ipynb` (currently a placeholder skeleton — full implementation is the next step).

Existing per-creator data:

- **Banky Wellington** — splits 5 YouTube transcripts into ~40 topically coherent coding units per video (~200 total) via `gpt-4o`, with punctuation / capitalization restored and Pidgin / Yoruba code-switching preserved
- **Deyemi / Shola / Agba / Wizarab** — one coding unit per X post, with themes and context generated via `gpt-4o`

Schema matches the Kibe/Jagero reference: `Segment ID | Influencer | Platform | Content Type | Theme(s) | Context (NOT CODED) | Verbatim Text (CODE THIS)`.

---

## Data Acquisition Pipeline

`Nigeria/Notebooks/Data Acquisition Pipeline.ipynb` is the consolidated entry point for:

1. **Scraping audience comments** — X / Twitter (creator tweets + replies via Apify), YouTube comments (yt-dlp), Instagram
2. **Transcribing creator videos** — yt-dlp → ffmpeg → whisper → pyannote diarisation → Gemini refinement
3. **Caption-based improvement** — align YouTube captions onto diarised transcripts (eliminates LLM over/under-generation)
4. **Speaker label correction** — deterministic fixes for corrupted labels + Gemini-assisted relabeling using YouTube metadata

### Transcription stages

![Transcription Pipeline Flowchart](Scope/imgs/Video%20ASR%20Workflow.png)

1. **Media Acquisition** — `yt-dlp` downloads video + auto-captions; `ffmpeg` converts audio to 16kHz mono WAV
2. **ASR** — `mlx-whisper` (Apple Silicon) / `faster-whisper` produces word-level timestamps
3. **Diarization** — `pyannote.audio` assigns speaker IDs to time segments
4. **LLM Refinement** — `gemini-2.5-flash` refines raw ASR + diarization with video-context grounding
5. **Caption-Based Improvement** (`align_transcripts_with_captions.py`) — uses YouTube captions as authoritative word source; position-proportional alignment transfers speaker labels onto caption text
6. **Speaker Label Correction** (`fix_speaker_labels.py`) — deterministic + Gemini-assisted relabeling

### Transcript accuracy results

All 15 transcripts hit research-grade quality. **Average: Precision 99.3% | Recall 99.2% | F1 99.3% | Coverage 99.9%** — full per-transcript table in `Kenya/Generated Transcripts/`.

---

## Keyword Lexicon

`Proposed Keywords & Codebooks/NLC Proposed keywords.xlsx` — 400+ keywords across three sheets:

- **Nigeria** — Pidgin, Yoruba, Igbo, Hausa slang (e.g., "ashawo", "agba baller", "yahoo boy", "woman-wrapper")
- **Kenya** — Swahili, Sheng, Gikuyu (e.g., "malaya", "mubaba", "mwanaume ni jasho")
- **Source links** — Academic papers and articles on African masculinity discourse

Tagged by relevance: **Highly**, **Moderately**, or **Not relevant**.

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` at the repo root with:

```
OPENAI_API_KEY=your_openai_api_key
GEMINI_API_KEY=your_gemini_api_key
HF_TOKEN=your_huggingface_token
APIFY_API_KEY=your_apify_api_key
```

### Key dependencies

- `mlx-whisper` / `faster-whisper` — speech recognition
- `pyannote.audio` — speaker diarization
- `google-genai` — Gemini LLM integration
- `openai` — GPT-4o / GPT-4o-mini + embeddings
- `apify-client` — X / Twitter / IG scraping
- `yt-dlp` — YouTube download and metadata
- `ffmpeg` — audio processing (system binary)
- `pandas` / `openpyxl` / `pyarrow` — data I/O

---

## Usage

### Audience Comments Pipeline (Nigeria)

Open `Nigeria/Notebooks/Audience Comments.ipynb`. Run **Stage 1** (cleaning) at any time — free and fast. Run **Stage 2** (LLM scope filter) when you want to regenerate Final from scratch — first run costs ~$3-5 in `gpt-4o-mini` calls; subsequent runs use the parquet cache for free.

> **Note:** the 4 Nigeria Final files have been **manually curated** beyond the notebook output (Grok prompt removal, OP-text leak fix, weak-row trims, speaker filter for Banky, stricter faith strip). Re-running the notebook would overwrite these — only do so if you want to start fresh.

### Audience Comments Pipeline (Kenya)

`Kenya/` is currently in its earlier-pass state (raw + topic-relevant + plots). To produce a Kenya Final dataset matching Nigeria's structure, copy `Nigeria/Notebooks/Audience Comments.ipynb` into a new `Kenya/Notebooks/`, swap the country name in the config cell, and run.

### Content Analysis (Nigeria)

Open `Nigeria/Notebooks/Content Analysis.ipynb` — placeholder skeleton, full implementation pending.

### Data Acquisition

Open `Nigeria/Notebooks/Data Acquisition Pipeline.ipynb` for the transcription stages. Scraping cells will be added to consolidate the scrapers in `Nigeria/scripts/`.

---

## Project Status

| Component | Status |
|---|---|
| Transcription (Kenya, 10 videos) | Complete — avg F1 99.2% |
| Transcription (Nigeria, 5 videos) | Complete — avg F1 99.5% |
| Caption ground truth | Available for all 15 videos |
| Nigeria raw audience comments | Collected (10,819 raw → cleaned to Complete tier) |
| Nigeria scope filter (Stage 2) | Notebook implemented; final dataset manually curated |
| Nigeria Final dataset | **Locked — 965 comments across 4 creators** |
| Nigeria content analysis | Per-creator coding units in place; notebook pipeline pending |
| Kenya raw audience comments | Collected (10 datasets); Final pipeline pending |
| Kenya audience analysis | Plots from earlier pass available |
| Content analysis codebook | Defined |
| Keyword lexicon | 400+ terms across Nigeria + Kenya |

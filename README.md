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

The project is split by country at the top level. Country-specific data lives under `Nigeria/` or `Kenya/`. Shared assets (notebooks, scripts, codebooks, transcripts, audio) sit at the root.

```
Gates-Manfluencer-Project/
├── Nigeria/
│   ├── Audience Comments - Raw/         # Full unfiltered scrapes per creator
│   │   ├── Agba John Doe/
│   │   ├── Banky Wellington/
│   │   │   ├── YouTube/                 # Sermons (legacy, not in final scope)
│   │   │   ├── Instagram/               # IG posts (legacy, not in final scope)
│   │   │   └── MENtality/               # 6 episodes — used for final analysis
│   │   ├── Deyemi Okanlawon/
│   │   ├── Shola/
│   │   └── Wizarab/
│   ├── Audience Comments - Filtered/    # Scope-filtered (LLM + length gate)
│   │   ├── Agba John Doe/
│   │   ├── Banky Wellington/
│   │   │   └── MENtality Podcast.xlsx   # 6 sheets, one per episode
│   │   ├── Deyemi Okanlawon/
│   │   ├── Shola/
│   │   ├── Wizarab/
│   │   └── _funnel / _summary xlsx
│   ├── Audience Comments - Final/       # Final demo dataset for the manager
│   │   ├── agba_tweet.xlsx              # 177 comments
│   │   ├── shola_tweet.xlsx             # 89 comments
│   │   ├── deyemi_tweet.xlsx            # 194 comments
│   │   ├── banky_podcast.xlsx           # 505 comments (MENtality, pooled)
│   │   └── _summary.xlsx
│   ├── Content Analysis/                # Per-creator coding-unit datasets
│   ├── Content Analysis Datasets/
│   ├── Content Analysis Plots/
│   ├── Audience Analysis Plots/
│   ├── Topic Relevant Comments/
│   └── Scraped Tweets/
│
├── Kenya/
│   ├── Audience Comments - Raw/         # 10 raw scrapes (X, YouTube, TikTok, Instagram)
│   ├── Audience Analysis Plots/
│   └── Topic Relevant Comments/
│
├── Notebooks/                            # End-to-end analysis pipelines
│   ├── Transcription Pipeline.ipynb               # ASR → diarization → LLM refinement
│   ├── Audience Comment Analysis.ipynb            # Raw comment cleaning
│   ├── Audience Demo Comments.ipynb               # Final scope-relevant audience demo
│   ├── Audience Analysis.ipynb                    # Nigeria audience analysis
│   ├── Audience Analysis - Kenya.ipynb            # Kenya audience analysis
│   └── Content Analysis - Nigeria.ipynb           # Nigeria content coding units
│
├── scripts/                              # Reproducible builders + scrapers
│   ├── build_*.py                       # Notebook generators
│   ├── filter_scope_relevant_comments.py # Two-tier scope filter (LLM + length)
│   ├── scrape_*.py                      # Apify / yt-dlp scrapers
│   ├── content_analysis_*.py            # Content coding-unit generators
│   ├── transcribe_videos.py
│   ├── align_transcripts_with_captions.py
│   ├── fix_speaker_labels.py
│   └── transcript_output_utils.py
│
├── Audio Files/                          # Source audio (Kenya + Nigeria)
├── Generated Transcripts/                # 15 research-grade transcripts
├── Captions/                             # 15 YouTube caption files (ground truth)
├── Codebook and Keywords/                # Codebook docx + 400+ keyword lexicon
├── Scope/                                # Project scope documents
├── Analysis Samples/                     # Reviewer-facing sample docs
├── imgs/                                 # Workflow diagrams
├── temp/                                 # Caches (gitignored)
├── README.md
├── requirements.txt
└── .env                                  # API keys (not committed)
```

---

## Audience Pipeline (3 Tiers)

For each creator, audience comments flow through three stages:

```
Audience Comments - Raw   →   Audience Comments - Filtered   →   Audience Comments - Final
   (full scrapes)              (LLM scope-filtered + length    (heavily cleaned demo set
                                gate, per-creator subfolders)   sent to manager)
```

### Tier 1 — Raw

Full unfiltered scrapes. For Banky, comments are organised by source platform (YouTube sermons, Instagram, MENtality podcast). Schema preserved exactly as scraped (`author`, `comment`, `likes`, `reply_count` for YouTube; `author`, `text`, `likes`, `replies`, `retweets`, `timestamp`, `url` for X / Twitter).

### Tier 2 — Filtered

Output of `scripts/filter_scope_relevant_comments.py`. A two-tier classifier (`gpt-4o-mini`) marks each comment as `KEEP_TIER_1`, `KEEP_TIER_2`, or `DROP` against the masculinity scope, then a length gate (≥100 chars / ≥15 words) trims short reactions. For Banky, all 6 MENtality episodes are pooled into one `MENtality Podcast.xlsx` with 6 sheets (Money / Relationships / Pt 2 Relationships / Fatherhood / Young Boys / Friendship).

### Tier 3 — Final (sent to manager)

Top-N per creator after additional manual curation:

| Creator | Source | Comments |
|---|---|---:|
| Agba John Doe | X — *Never Leave Marriage Because Husband Cheated* | 177 |
| Shola | X — *7 Women Will Beg One Man to Marry* | 89 |
| Deyemi Okanlawon | X — *Stop Raping Women Response* | 194 |
| Banky Wellington | YouTube — *MENtality Podcast* (6 episodes pooled) | 505 |
| **Total** | | **965** |

Each final file has a single `text` column. Cleaning passes applied:

- Substance gate (>7 words after stripping URLs / mentions / emojis)
- Keyword annotation against NLC Nigeria lexicon
- Embedding similarity to per-creator anchor phrases (`text-embedding-3-large`)
- Lenient LLM relevance check (`gpt-4o-mini`) tuned per-creator (regressive vs progressive themes)
- Composite scoring: `0.20 × keyword + 0.35 × similarity + 0.45 × LLM relevance`
- Top-200 per post (or all available if < 200)
- Speaker filter (Banky only): drops comments mentioning other MENtality guests without Banky
- Faith strip: removes religious framing (Bible / scripture / Jesus / God-as-subject / Islam / etc.) — colloquial idioms (`hell` as exclamation, `blessed` as hyperbole, `God help me`) preserved
- Manual review passes: removed duplicates, OP-text leakage, generic praise, format critiques, weak jokes, and Grok bot pings (`@grok` prompts that aren't real audience opinions)

---

## Content Analysis Pipeline

Per-creator coding-unit datasets in `Nigeria/Content Analysis/`. For each creator the pipeline:

- **Banky Wellington** — splits 5 YouTube transcripts into ~40 topically coherent coding units per video (~200 total) via `gpt-4o`, with punctuation / capitalization restored and Pidgin / Yoruba code-switching preserved
- **Deyemi / Shola / Agba / Wizarab** — one coding unit per X post, with themes and context generated via `gpt-4o`

Outputs: `<Creator>/<Creator>_Coding_Units.xlsx`, plus `_corpus_full.xlsx` and `_summary.xlsx`. Built by `scripts/build_content_analysis_nigeria.py` and `scripts/content_analysis_*.py`.

---

## Transcription Pipeline

Generates research-grade transcripts from YouTube videos.

![Transcription Pipeline Flowchart](imgs/Video%20ASR%20Workflow.png)

### Stages

1. **Media Acquisition** — `yt-dlp` downloads video + auto-captions; `ffmpeg` converts audio to 16kHz mono WAV
2. **ASR** — `mlx-whisper` (Apple Silicon) / `faster-whisper` produces word-level timestamps
3. **Diarization** — `pyannote.audio` assigns speaker IDs to time segments
4. **LLM Refinement** — `gemini-2.5-flash` refines raw ASR + diarization with video-context grounding
5. **Caption-Based Improvement** (`align_transcripts_with_captions.py`) — uses YouTube captions as authoritative word source; position-proportional alignment transfers speaker labels onto caption text
6. **Speaker Label Correction** (`fix_speaker_labels.py`) — deterministic fixes for corrupted labels + Gemini-assisted relabeling using YouTube metadata

### Transcript Accuracy Results

All 15 transcripts hit research-grade quality. **Average: Precision 99.3% | Recall 99.2% | F1 99.3% | Coverage 99.9%** — full per-transcript table in `Generated Transcripts/`.

---

## Keyword Lexicon

`Codebook and Keywords/NLC Proposed keywords.xlsx` — 400+ keywords across three sheets:

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

Create a `.env` with:

```
OPENAI_API_KEY=your_openai_api_key
GEMINI_API_KEY=your_gemini_api_key
HF_TOKEN=your_huggingface_token
APIFY_API_KEY=your_apify_api_key
```

### Key Dependencies

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

### Run Transcription Pipeline

```bash
python scripts/transcribe_videos.py
python scripts/align_transcripts_with_captions.py --skip-download --skip-gemini --force
python scripts/fix_speaker_labels.py
```

### Run Audience Comment Cleaning

Open `Notebooks/Audience Comment Analysis.ipynb` — cleans all 10 raw datasets in place.

### Run Scope Filter (Tier 2)

```bash
python scripts/filter_scope_relevant_comments.py --country Nigeria --orientation all
```

### Build Final Demo Datasets (Tier 3)

```bash
# All four creators in one shot:
python scripts/build_audience_demo.py --creator all

# Or individually:
python scripts/build_audience_demo.py --creator agba_shola
python scripts/build_audience_demo.py --creator deyemi
python scripts/build_audience_demo.py --creator banky
```

---

## Project Status

| Component | Status |
|---|---|
| Transcription (Kenya, 10 videos) | Complete — avg F1 99.2% |
| Transcription (Nigeria, 5 videos) | Complete — avg F1 99.5% |
| Caption ground truth | Available for all 15 videos |
| Nigeria raw audience comments | Complete (10,819 → 9,735 cleaned, 89.8% retention) |
| Nigeria scope filtering (Tier 2) | Complete — per-creator subfolders + Banky MENtality sheetwise |
| Nigeria final demo set (Tier 3) | Complete — 965 comments across 4 creators |
| Nigeria content analysis | Complete — coding units per creator |
| Kenya raw audience comments | Collected (10 datasets) |
| Kenya audience analysis | Plots generated |
| Content analysis codebook | Defined |
| Keyword lexicon | 400+ terms across Nigeria + Kenya |

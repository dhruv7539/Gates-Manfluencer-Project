# GATES Manfluencer Project

**Norman Lear Center, USC Annenberg — Gates Foundation**

A multi-method analysis of masculinity-focused media content in and adjacent to the "manosphere" in **Kenya** and **Nigeria**. This repository contains the technical pipeline for transcribing, cleaning, and analyzing influencer content and audience comments.

---

## Project Scope

The study focuses on media content that explicitly or implicitly promotes or challenges gender norms, with four interrelated components:

1. **Landscape Analysis** — Review of masculinity-related discourse, influencers, platforms, and keywords in Kenya and Nigeria
2. **Content Analysis** — Analysis of 10 high-reach creators (5 per country) across their media outputs
3. **Audience Reception Analysis** — Engagement metrics and qualitative analysis of audience comments
4. **Playbook Development** — Counternarrative strategies for healthier masculinity content

### Creators Studied

| Creator | Country | Orientation | Platform | Content Focus |
|---------|---------|-------------|----------|---------------|
| Eric Amunga (Amerix) | Kenya | Regressive | X | Sexual hierarchy, female submission, #MasculinitySaturday |
| Andrew Kibe | Kenya | Regressive | X/YouTube | Anti-women cynicism, status, male advice |
| Philip Karanja | Kenya | Progressive | YouTube | Fatherhood (Girl Dad series), violence against women, allyship |
| Onyango Otieno (Rixpoet) | Kenya | Progressive | YouTube | Trauma recovery, anti-toxic masculinity, men's mental health |
| Eddy Kimani | Kenya | Progressive | TikTok/YouTube | Depression, failure recovery, men's mental health |
| Banky Wellington | Nigeria | Progressive | YouTube | Faith, marriage, illness/recovery, emotional openness |
| Deyemi Okanlawon | Nigeria | Progressive | X | Male accountability, rape culture, victim protection |
| Wizarab | Nigeria | Regressive | X | Denigrating women, feminists, single mothers |
| Shola | Nigeria | Regressive | X | Availability trap, female submission, provider anxiety |
| Agba John Doe | Nigeria | Regressive | X | Soft patriarchy, marriage-market logic, sexual double standards |

---

## Repository Structure

```
Gates-Manfluencer-Project/
├── Notebooks/
│   ├── Transcription Pipeline.ipynb                      # ASR + diarization + LLM refinement
│   ├── Audience Comment Analysis.ipynb                   # Raw comment cleaning pipeline
│   ├── Topic Relevant Comment Filtering - Nigeria.ipynb  # 5-stage topic relevance + themes
│   └── Topic Relevant Comment Filtering - Nigeria v2.ipynb  # Simplified binary relevance
├── scripts/
│   ├── run_all_transcriptions.py             # Batch runner for the transcription notebook
│   ├── improve_transcripts_with_captions.py  # Caption-based transcript improvement
│   ├── fix_speaker_labels.py                 # Speaker label correction (deterministic + Gemini)
│   ├── check_accuracy.py                     # Transcript accuracy measurement against captions
│   └── transcript_output_utils.py            # Shared transcript parsing utilities
├── Audio Files/                              # Source audio extracted from YouTube
│   ├── Kenya Audio Files/                    # 10 files (Andrew Kibe, Onyango, Philip Karanja)
│   └── Nigeria Audio Files/                  # 5 files (Banky Wellington)
├── Generated Transcripts/                    # 15 research-grade transcripts
│   ├── Kenya/                                # 10 transcripts
│   └── Nigeria/                              # 5 transcripts
├── Captions/                                 # 15 YouTube caption files (ground truth)
│   ├── Kenya/
│   └── Nigeria/
├── Nigeria Audience Comments/                # Raw scraped audience data (10 datasets)
│   ├── Agba John Doe/
│   ├── Banky Wellington/
│   ├── Deyemi Okanlawon/
│   ├── Shola/
│   └── Wizarab/
├── Topic Relevant Comments - Nigeria - Final/  # Post-filter labeled outputs
├── Scope/                                    # Project scope documents
│   ├── Gates Masculinity Scope - Streamlined.docx
│   └── Landscape & Content Analysis - Participants, Creators.docx
├── Codebook and Keywords/
│   ├── Gates Content Analysis Codebook.docx  # Coding variables for content analysis
│   └── NLC Proposed keywords.xlsx            # 400+ keyword lexicon (Nigeria + Kenya)
├── Analysis Samples/
│   ├── KENYA - Content and Audience Analysis Samples.docx
│   └── NIGERIA - Content and Audience Analysis Samples.docx
├── temp/                                     # Intermediate checkpoints
│   ├── embeddings/                           # OpenAI text-embedding-3-large vectors
│   ├── topic_relevance_checkpoints/          # 5-stage topic filter parquets
│   └── mih_style_topic_relevance/            # GPT-4o-mini batch request artifacts
├── imgs/
│   └── Video ASR Workflow.png                # Transcription pipeline flowchart
├── MIH.ipynb                                 # Reference/template notebook (Made in Heaven labeling)
├── requirements.txt
└── .env                                      # API keys (GEMINI_API_KEY, OPENAI_API_KEY)
```

---

## Pipeline 1: Transcription Pipeline

Generates research-grade transcripts from YouTube videos through a multi-stage process.

![Transcription Pipeline Flowchart](imgs/Video%20ASR%20Workflow.png)

### Stage 1: Media Acquisition
- **yt-dlp** downloads YouTube videos and auto-generated captions (VTT/SRT)
- **ffmpeg** converts audio to 16kHz mono WAV for ASR compatibility
- YouTube metadata (title, description, channel) fetched for speaker identification context

### Stage 2: Speech-to-Text (ASR)
- **Whisper** (mlx-whisper on Apple Silicon, faster-whisper fallback) transcribes audio
- Produces word-level timestamps for each recognized word
- Handles mixed-language content (English, Kiswahili, Sheng, Pidgin)

### Stage 3: Speaker Diarization
- **pyannote.audio** identifies distinct speakers and assigns time segments
- Each audio segment is labeled with a speaker ID (SPEAKER_00, SPEAKER_01, etc.)
- Word-level timestamps from Whisper are aligned with speaker segments

### Stage 4: LLM Refinement
- **Google Gemini** (gemini-2.5-flash) refines raw ASR+diarization output
- Video context grounding to identify speakers by name using video metadata
- Chunk-by-chunk processing with strict instructions to preserve original words

### Stage 5: Caption-Based Improvement (`improve_transcripts_with_captions.py`)
- Uses YouTube captions as the **authoritative word source** (eliminates LLM over/under-generation)
- **Position-proportional alignment** transfers speaker labels from the diarized transcript onto caption text
- Local speaker label smoothing (window=15) to fix noisy label transitions
- Falls back to plain-text captions with Unicode-normalized fuzzy filename matching

### Stage 6: Speaker Label Correction (`fix_speaker_labels.py`)
- **Phase 1 — Deterministic fixes**: Corrects corrupted labels (e.g., "Happy. Jagero" → "Jagero"), removes sentence-level duplicate content (>60% overlap threshold)
- **Phase 2 — Gemini-assisted relabeling**: Uses YouTube metadata + video excerpts to rename generic labels (e.g., "Host" → "Richard Njau", "Interviewee 1" → "Onyango Otieno")
- **Phase 3 — Resegmentation**: For transcripts with missing speakers, Gemini resegments dialogue based on metadata and conversational patterns

### Stage 7: Accuracy Verification (`check_accuracy.py`)
- Compares each transcript against its corresponding YouTube caption file
- Metrics: **Precision** (transcript content that matches captions), **Recall** (caption content captured), **F1** (harmonic mean), **Coverage** (word count ratio)
- Research-grade threshold: F1 >= 90% AND Coverage 90-110%

### Transcript Accuracy Results

All 15 transcripts achieved research-grade quality:

| # | Transcript | Creator | Country | Precision % | Recall % | F1 % | Coverage % | Status |
|---|-----------|---------|---------|------------|---------|------|-----------|--------|
| 1 | Face it Like a Man | Banky Wellington | Nigeria | 100.0 | 100.0 | **100.0** | 100.0 | Research-ready |
| 2 | Final Say Faith | Banky & Adesua Wellington | Nigeria | 100.0 | 100.0 | **100.0** | 100.0 | Research-ready |
| 3 | My Story - Journey Through Hope & Faith | Banky Wellington | Nigeria | 100.0 | 100.0 | **100.0** | 100.0 | Research-ready |
| 4 | 071 Andrew Kibe - 28 Commandments | Andrew Kibe | Kenya | 100.0 | 100.0 | **100.0** | 100.0 | Research-ready |
| 5 | NaRelate Men's Mental Health Workshop | Onyango Otieno | Kenya | 100.0 | 100.0 | **100.0** | 100.0 | Research-ready |
| 6 | Men, Addiction, and Violence | Onyango Otieno | Kenya | 100.0 | 100.0 | **100.0** | 100.0 | Research-ready |
| 7 | My Childhood Upbringing | Philip Karanja | Kenya | 100.0 | 100.0 | **100.0** | 100.0 | Research-ready |
| 8 | Episode 1 - A Girl Dad on a Mission | Philip Karanja | Kenya | 100.0 | 100.0 | **100.0** | 100.0 | Research-ready |
| 9 | Episode 2 - A Girl Dad on a Mission | Philip Karanja | Kenya | 99.8 | 99.9 | **99.9** | 100.1 | Research-ready |
| 10 | Undoing My Father's Damage | Onyango Otieno | Kenya | 99.5 | 99.1 | **99.3** | 99.6 | Research-ready |
| 11 | Your Story - Sex & Depression | Onyango Otieno | Kenya | 99.7 | 98.7 | **99.2** | 99.0 | Research-ready |
| 12 | The Prison of Pornography | Banky Wellington | Nigeria | 98.1 | 99.8 | **99.0** | 101.7 | Research-ready |
| 13 | Faith after a Fall | Banky Wellington | Nigeria | 98.9 | 98.8 | **98.9** | 99.8 | Research-ready |
| 14 | Toxic Masculinity | Onyango Otieno | Kenya | 97.8 | 97.9 | **97.8** | 100.2 | Research-ready |
| 15 | Season Finale - A Girl Dad on a Mission | Philip Karanja | Kenya | 95.5 | 94.3 | **94.9** | 98.8 | Research-ready |

**Average: Precision 99.3% | Recall 99.2% | F1 99.3% | Coverage 99.9% | 15/15 Research-ready**

---

## Pipeline 2: Audience Comment Cleaning

Cleans and standardizes the 10 scraped audience comment datasets for the Nigeria audience reception analysis.

### Input
10 Excel files containing audience comments/replies scraped from YouTube and X (Twitter):

| Creator | Source Post | Platform | Raw Rows |
|---------|-----------|----------|----------|
| Banky Wellington | Final Say Faith | YouTube | 7,206 |
| Banky Wellington | My Story - Journey Through Hope & Faith | YouTube | 765 |
| Shola | Women and Availability Trap | X | 246 |
| Shola | 7 Women Will Beg One Man to Marry | X | 491 |
| Wizarab | Sex Toys and Raping Young Boys | X | 351 |
| Wizarab | Child Support and Divorce | X | 185 |
| Deyemi Okanlawon | Men Must Hold Men Accountable | X | 74 |
| Deyemi Okanlawon | Stop Raping Women Response | X | 684 |
| Agba John Doe | Never Leave Marriage Because Husband Cheated | X | 550 |
| Agba John Doe | Single Woman Earning Above 1.5M | X | 267 |

### Cleaning Steps

1. **Schema normalization** — Three different raw schemas (YouTube, X standard, X alternate) unified into consistent column sets
2. **Column reduction** — Dropped empty/redundant columns (`id`, `images`, `quotes`, `videoID`, `twitterUrl`, `bookmarkCount`, `isRetweet`, `isQuote`, `commentsCount`, `pageUrl`, `title`, `type`)
3. **Text normalization** — Unicode NFKC normalization, smart quotes converted to straight quotes, whitespace collapsed
4. **Author extraction** — X handles extracted from URLs; YouTube authors preserved as-is
5. **Timestamp standardization** — Parsed to timezone-naive datetime for Excel compatibility
6. **Junk removal** — Empty texts, texts under 5 characters, and exact duplicates dropped

### Output Schema

**YouTube (Banky Wellington):** `author`, `comment`, `likes`, `reply_count`

**X / Twitter (all others):** `author`, `text`, `likes`, `replies`, `retweets`, `timestamp`, `url`

### Cleaning Results

| Creator | Source Post | Raw | Clean | Dropped |
|---------|-----------|-----|-------|---------|
| Banky Wellington | Final Say Faith | 7,206 | 6,389 | 817 |
| Banky Wellington | My Story | 765 | 712 | 53 |
| Shola | Women and Availability Trap | 246 | 225 | 21 |
| Shola | 7 Women Will Beg One Man | 491 | 454 | 37 |
| Wizarab | Sex Toys and Raping Young Boys | 351 | 311 | 40 |
| Wizarab | Child Support and Divorce | 185 | 183 | 2 |
| Deyemi Okanlawon | Men Must Hold Men Accountable | 74 | 58 | 16 |
| Deyemi Okanlawon | Stop Raping Women Response | 684 | 647 | 37 |
| Agba John Doe | Never Leave Marriage | 550 | 511 | 39 |
| Agba John Doe | Single Woman Earning 1.5M | 267 | 245 | 22 |
| **TOTAL** | | **10,819** | **9,735** | **1,084** |

---

## Pipeline 3: Topic Relevance Filtering + Thematic Labeling (Nigeria)

Classifies cleaned audience comments for topical relevance to the masculinity study and applies multi-label themes + sentiment.

### Stages

1. **Stage 1 — Keyword annotation**: Matches comment text against the NLC Nigeria keyword lexicon (Pidgin / Yoruba / Igbo / Hausa slang)
2. **Stage 2 — LLM pre-filter**: `GPT-4o-mini` assigns candidate themes from the canonical list (Batch API)
3. **Stage 3 — Semantic filtering**: OpenAI `text-embedding-3-large` similarity scoring against anchor definitions
4. **Stage 4 — High-precision LLM pass**: `GPT-4o` refines themes + assigns sentiment
5. **Stage 5 — Master annotation compile**: Combines all stage outputs into final labeled dataset

### Canonical Themes (from Gates codebook)

- Attention-getting strategies
- Primary topics: dating, family, money/status, fitness, mental health, gender, religion
- Masculinity norms: regressive vs. progressive
- Problems identified, solutions proposed
- Communication modes, sentiment toward men / women / gender norms

### Intermediate Artifacts (`temp/`)

- `temp/embeddings/text-embedding-3-large_comments.parquet` — comment embeddings
- `temp/topic_relevance_checkpoints/stage*.parquet` — per-stage checkpoints
- `temp/mih_style_topic_relevance/` — GPT-4o-mini Batch API request/response files

### Output

`Topic Relevant Comments - Nigeria - Final/` contains one `.xlsx` per creator-post with:
- original comment text + author
- topic-relevance flag
- multi-label themes
- sentiment

A `_summary.xlsx` aggregates per-dataset retention counts.

---

## Keyword Lexicon

The `Codebook and Keywords/NLC Proposed keywords.xlsx` file contains 400+ keywords across three sheets:

- **Nigeria** — Pidgin, Yoruba, Igbo, Hausa slang with cultural annotations (e.g., "ashawo", "agba baller", "yahoo boy", "woman-wrapper")
- **Kenya** — Swahili, Sheng, Gikuyu terms (e.g., "malaya", "mubaba", "msenge", "mwanaume ni jasho")
- **Source links** — Academic papers and articles on African masculinity discourse

Keywords are tagged by relevance tier: **Highly relevant**, **Moderately relevant**, or **Not relevant**.

---

## Content Analysis Codebook

The `Gates Content Analysis Codebook.docx` defines structured coding variables:

- **Attention-getting strategies** — Questions, humor, shock, sexuality, news hooks
- **Primary topics** — Dating/marriage, family, money/status, fitness, mental health, gender issues, religion
- **Masculinity norms** — Regressive/traditional vs. progressive/equitable
- **What men "should" do** — Dominate, provide, be self-reliant, be emotionally open, be equal partners
- **Problems identified** — Political, Western influence, women/feminism, economic pressure, mental health
- **Solutions proposed** — Political change, assert dominance, build wealth, emotional growth, equality
- **Communication modes** — Advice, personal story, debate, humor, motivational
- **Sentiment** — Toward men, women, and traditional gender norms

---

## Setup

### Requirements

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file with:

```
GEMINI_API_KEY=your_gemini_api_key
OPENAI_API_KEY=your_openai_api_key
HF_TOKEN=your_huggingface_token       # required for pyannote diarization
```

### Key Dependencies

- `mlx-whisper` / `faster-whisper` — Speech recognition
- `pyannote.audio` — Speaker diarization
- `google-genai` — Gemini LLM integration
- `openai` — GPT-4o / GPT-4o-mini + embeddings
- `yt-dlp` — YouTube download and metadata
- `ffmpeg` — Audio processing (system binary)
- `pandas` / `openpyxl` / `pyarrow` — Data + parquet I/O
- `scikit-learn` / `numpy` — Similarity + numerics

---

## Usage

### Run Transcription Pipeline

```bash
# Full pipeline (all videos)
python scripts/run_all_transcriptions.py

# Caption-based improvement (uses captions as ground truth)
python scripts/improve_transcripts_with_captions.py --skip-download --skip-gemini --force

# Fix speaker labels
python scripts/fix_speaker_labels.py

# Check accuracy against captions
python scripts/check_accuracy.py
```

### Run Audience Comment Cleaning

Open and run `Notebooks/Audience Comment Analysis.ipynb` — cleans all 10 datasets in place.

### Run Topic Relevance Filtering

Open and run `Notebooks/Topic Relevant Comment Filtering - Nigeria.ipynb` for the full 5-stage pipeline. The v2 notebook provides a simplified binary on/off-topic classifier without multi-label themes.

---

## Project Status

| Component | Status |
|-----------|--------|
| Transcription (Kenya, 10 videos) | Complete — avg F1 99.2% |
| Transcription (Nigeria, 5 videos) | Complete — avg F1 99.5% |
| Caption ground truth | Available for all 15 videos |
| Nigeria audience comment cleaning | Complete (9,735 rows, 89.8% retention) |
| Nigeria topic relevance filtering | 5-stage pipeline implemented, outputs curated |
| Nigeria theme + sentiment labeling | Complete via GPT-4o-mini + GPT-4o ensemble |
| Kenya audience comments | Pending collection |
| Content analysis codebook | Defined |
| Keyword lexicon | 400+ terms across Nigeria + Kenya |

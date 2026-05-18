"""Run the diarized transcript pipeline locally from the command line."""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger('pipeline')

ROOT = Path.cwd()
YOUTUBE_URL = 'https://www.youtube.com/watch?v=ilsjWBXvX2c'
OUTPUT_DIR = ROOT / 'output'
TEMP_DIR = ROOT / 'temp'
WHISPER_MODEL = 'large-v3'
HF_TOKEN = ''
NUM_SPEAKERS = None
MIN_SPEAKERS = None
MAX_SPEAKERS = None
PRIMARY_SPEAKER_NAME = None
TRANSCRIPT_FILENAME = 'transcript.txt'


def clean_text(text: str) -> str:
    text = re.sub(r'\s+', ' ', text or '').strip()
    text = re.sub(r'\s+([,.;:!?%])', r'\1', text)
    text = re.sub(r'([\(\[\{])\s+', r'\1', text)
    text = re.sub(r'\s+([\)\]\}])', r'\1', text)
    return text.strip()


def safe_slug(text: str, fallback: str = 'audio') -> str:
    text = re.sub(r'\[[^\]]+\]', '', text)
    text = re.sub(r'[^A-Za-z0-9._-]+', '_', text).strip('._-')
    return text[:120] or fallback


def pretty_count(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def infer_primary_speaker_name(metadata: dict, explicit_name: Optional[str] = None) -> Optional[str]:
    if explicit_name:
        return explicit_name
    title = (metadata.get('title') or '').strip()
    uploader = (metadata.get('uploader') or '').strip()
    channel = (metadata.get('channel') or '').strip()
    title_match = re.search(r'\s-\s([^\-]+)$', title)
    if title_match:
        candidate = clean_text(title_match.group(1))
        if candidate and len(candidate.split()) <= 5:
            return candidate
    for field in (uploader, channel):
        if not field:
            continue
        if 'youtube' in field.lower():
            continue
        if len(field.split()) <= 6:
            return field
    return None


def build_stats_line(metadata: dict) -> Optional[str]:
    stats = []
    if metadata.get('view_count') is not None:
        stats.append(f"Views: {pretty_count(metadata['view_count'])}")
    if metadata.get('like_count') is not None:
        stats.append(f"Likes: {pretty_count(metadata['like_count'])}")
    if metadata.get('comment_count') is not None:
        stats.append(f"Comments: {pretty_count(metadata['comment_count'])}")
    if not stats:
        return None
    return 'Stats: ' + '; '.join(stats) + '.'


def main():
    import getpass

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    hf_token = HF_TOKEN or getpass.getpass('Enter your Hugging Face access token: ')

    # --- Step 1: Download audio ---
    print('\n=== Step 1: Downloading audio from YouTube ===')
    from yt_dlp import YoutubeDL

    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': False,
        'restrictfilenames': False,
        'outtmpl': str(TEMP_DIR / '%(title).200B [%(id)s].%(ext)s'),
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(YOUTUBE_URL, download=True)
        requested_downloads = info.get('requested_downloads') or []
        downloaded_path = requested_downloads[0].get('filepath') if requested_downloads else ydl.prepare_filename(info)

    source_audio = Path(downloaded_path).resolve()
    metadata = {
        'title': info.get('title') or source_audio.stem,
        'uploader': info.get('uploader'),
        'channel': info.get('channel'),
        'view_count': info.get('view_count'),
        'like_count': info.get('like_count'),
        'comment_count': info.get('comment_count'),
        'webpage_url': info.get('webpage_url') or YOUTUBE_URL,
    }
    print(f'Title: {metadata["title"]}')
    print(f'Source: {source_audio}')

    # --- Step 2: Convert to WAV ---
    print('\n=== Step 2: Converting to 16kHz mono WAV ===')
    wav_name = safe_slug(metadata['title']) + '_16khz_mono.wav'
    wav_path = TEMP_DIR / wav_name
    subprocess.run([
        'ffmpeg', '-y', '-i', str(source_audio),
        '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le',
        str(wav_path),
    ], check=True, capture_output=True, text=True)
    print(f'WAV: {wav_path}')

    # --- Step 3: Transcribe with faster-whisper ---
    print(f'\n=== Step 3: Transcribing with faster-whisper ({WHISPER_MODEL}) ===')
    print('This may take a while on CPU...')
    from faster_whisper import WhisperModel

    model = WhisperModel(WHISPER_MODEL, device='cpu', compute_type='int8')
    segments, _info = model.transcribe(
        str(wav_path),
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        language='en',
        condition_on_previous_text=True,
    )
    segments = list(segments)

    words = []
    for segment in segments:
        for word in getattr(segment, 'words', None) or []:
            if word.start is None or word.end is None:
                continue
            words.append({
                'word': word.word,
                'start': float(word.start),
                'end': float(word.end),
            })

    print(f'Transcription complete: {len(words)} words')

    # --- Step 4: Speaker diarization ---
    print('\n=== Step 4: Speaker diarization with pyannote ===')
    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(
        'pyannote/speaker-diarization-3.1',
        token=hf_token,
    )
    diarization = pipeline(str(wav_path),
                           **(({'num_speakers': NUM_SPEAKERS} if NUM_SPEAKERS else {}) |
                              ({'min_speakers': MIN_SPEAKERS} if MIN_SPEAKERS else {}) |
                              ({'max_speakers': MAX_SPEAKERS} if MAX_SPEAKERS else {})))

    label_map = {}
    speaker_segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        if speaker not in label_map:
            label_map[speaker] = f'Speaker {len(label_map) + 1}'
        speaker_segments.append({
            'speaker': label_map[speaker],
            'start': round(float(turn.start), 3),
            'end': round(float(turn.end), 3),
        })

    unique_speakers = sorted(set(s['speaker'] for s in speaker_segments))
    print(f'Diarization complete: {len(speaker_segments)} segments, {len(unique_speakers)} speakers')

    # --- Step 5: Merge ---
    print('\n=== Step 5: Merging transcription + diarization ===')
    ordered_segs = sorted(speaker_segments, key=lambda s: (s['start'], s['end']))

    assigned = []
    for w in words:
        mid = (w['start'] + w['end']) / 2.0
        speaker = None
        for seg in ordered_segs:
            if seg['start'] <= mid <= seg['end']:
                speaker = seg['speaker']
                break
        if speaker is None:
            nearest, nearest_d = None, None
            for seg in ordered_segs:
                d = max(0, seg['start'] - mid) if mid < seg['start'] else max(0, mid - seg['end'])
                if nearest_d is None or d < nearest_d:
                    nearest_d, nearest = d, seg
            speaker = nearest['speaker'] if nearest and nearest_d <= 0.5 else 'Unknown'
        assigned.append({**w, 'speaker': speaker})

    # Collapse into turns
    turns = []
    current = None
    for item in assigned:
        token, start, end = item['word'], item['start'], item['end']
        speaker = item['speaker']
        if current is None:
            current = {'speaker': speaker, 'start': start, 'end': end, 'tokens': [token]}
            continue
        gap = start - current['end']
        if speaker != current['speaker'] or gap > 0.9:
            text = _join_tokens(current['tokens'])
            if text:
                turns.append({'speaker': current['speaker'], 'start': current['start'], 'end': current['end'], 'text': text})
            current = {'speaker': speaker, 'start': start, 'end': end, 'tokens': [token]}
        else:
            current['tokens'].append(token)
            current['end'] = end
    if current:
        text = _join_tokens(current['tokens'])
        if text:
            turns.append({'speaker': current['speaker'], 'start': current['start'], 'end': current['end'], 'text': text})

    # Relabel dominant speaker
    primary_name = infer_primary_speaker_name(metadata, PRIMARY_SPEAKER_NAME)
    if primary_name:
        duration_by = defaultdict(float)
        for t in turns:
            duration_by[t['speaker']] += t['end'] - t['start']
        generic = [s for s in duration_by if s.startswith('Speaker ')]
        if generic:
            dominant = max(generic, key=lambda s: duration_by[s])
            for t in turns:
                if t['speaker'] == dominant:
                    t['speaker'] = primary_name

    # Merge adjacent same-speaker turns
    merged = []
    for t in turns:
        text = clean_text(t['text'])
        if not text:
            continue
        if merged and merged[-1]['speaker'] == t['speaker'] and (t['start'] - merged[-1]['end']) <= 0.9:
            merged[-1]['end'] = t['end']
            merged[-1]['text'] = clean_text(merged[-1]['text'] + ' ' + text)
        else:
            merged.append({**t, 'text': text})

    print(f'Final turns: {len(merged)}')
    print(f'Speakers: {sorted(set(t["speaker"] for t in merged))}')

    # --- Step 6: Write output ---
    print('\n=== Step 6: Writing transcript ===')
    transcript_path = OUTPUT_DIR / TRANSCRIPT_FILENAME

    lines = [f'"{metadata["title"]}"']
    stats = build_stats_line(metadata)
    if stats:
        lines.append(stats)
    if primary_name:
        lines.append(f'Speaker: {primary_name}')
    lines.append('')

    for t in merged:
        lines.append(f'{t["speaker"]}: {t["text"]}')
        lines.append('')

    transcript_text = '\n'.join(lines).rstrip() + '\n'
    transcript_path.write_text(transcript_text, encoding='utf-8')

    print(f'\nSaved to: {transcript_path}')
    print('\n--- Preview (first 3000 chars) ---')
    print(transcript_text[:3000])

    # Cleanup temp
    for f in [source_audio, wav_path]:
        try:
            if f.exists() and TEMP_DIR in f.parents:
                f.unlink()
        except Exception:
            pass


def _join_tokens(tokens: list[str]) -> str:
    pieces = []
    for token in tokens:
        if not token:
            continue
        if not pieces:
            pieces.append(token.lstrip())
        elif token.startswith(' ') or re.match(r'^[,.;:!?%\)\]\}]', token) or token.startswith(("'", "\u2019")):
            pieces.append(token)
        else:
            pieces.append(' ' + token)
    return clean_text(''.join(pieces))


if __name__ == '__main__':
    main()

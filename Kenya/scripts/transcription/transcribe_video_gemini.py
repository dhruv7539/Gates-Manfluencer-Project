import os
import sys
import time
import tempfile
import subprocess
from pytubefix import YouTube
from google import genai
from google.genai import types

API_KEY = "AIzaSyAu1wqxV9UZ_8QnrDIApWXyxrKiYnFGThY"
VIDEO_URL = "https://www.youtube.com/watch?v=rAIQEqQ2WTo"
SEGMENT_MINUTES = 15


def download_audio(url, output_dir):
    print(f"Downloading audio from {url}...")
    yt = YouTube(url)
    print(f"Title: {yt.title}")
    print(f"Duration: {yt.length} seconds ({yt.length // 60} min)")

    stream = yt.streams.filter(only_audio=True).order_by("abr").desc().first()
    filepath = stream.download(output_path=output_dir, filename="audio_raw")
    file_size = os.path.getsize(filepath) / (1024 * 1024)
    print(f"Downloaded audio: {filepath} ({file_size:.1f} MB)")
    return filepath, yt.length, yt.title


def split_audio(audio_path, output_dir, total_duration, segment_minutes=SEGMENT_MINUTES):
    segment_secs = segment_minutes * 60
    num_segments = (total_duration + segment_secs - 1) // segment_secs
    print(f"\nSplitting into {num_segments} segments of ~{segment_minutes} min each...")

    segments = []
    for i in range(num_segments):
        start = i * segment_secs
        out_path = os.path.join(output_dir, f"segment_{i:02d}.mp3")
        cmd = [
            "ffmpeg", "-y", "-i", audio_path,
            "-ss", str(start), "-t", str(segment_secs),
            "-vn", "-acodec", "libmp3lame", "-ab", "64k", "-ar", "16000", "-ac", "1",
            out_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        size_mb = os.path.getsize(out_path) / (1024 * 1024)
        print(f"  Segment {i}: start={start}s, file={out_path} ({size_mb:.1f} MB)")
        segments.append(out_path)

    return segments


def cleanup_old_files(client):
    try:
        for f in client.files.list():
            try:
                client.files.delete(name=f.name)
                print(f"  Deleted old file: {f.name}")
            except Exception:
                pass
    except Exception:
        pass


def upload_and_wait(client, filepath):
    uploaded = client.files.upload(file=filepath)
    while uploaded.state.name == "PROCESSING":
        time.sleep(3)
        uploaded = client.files.get(name=uploaded.name)
    if uploaded.state.name == "FAILED":
        raise RuntimeError(f"File processing failed for {filepath}")
    return uploaded


def transcribe_segment(client, audio_file, segment_idx, total_segments, prev_context=""):
    context_note = ""
    if prev_context:
        context_note = f"\n\nFor continuity, here are the last few lines from the previous segment's transcript:\n---\n{prev_context}\n---\nContinue from where this left off. Do not repeat these lines."

    prompt = f"""You are a professional linguistic transcription assistant working on an academic media research project. This is audio segment {segment_idx + 1} of {total_segments} from a single video.

Produce a complete verbatim speaker-diarized transcript of this audio segment.

Instructions:
- Identify each unique speaker.
- If speaker names are mentioned or inferable from context (introductions, how speakers address each other), use their real names. Otherwise label them as Speaker A, Speaker B, etc.
- Format each line as: Speaker Name: Dialogue
- Do not omit, censor, or sanitize any dialogue — accuracy is critical for research integrity.
- Do not add timestamps.
- Do not summarize or paraphrase — transcribe exactly what is spoken word for word.
- Transcribe the ENTIRE segment from start to finish without stopping or truncating.
- Include all filler words (um, uh, like, you know, etc.) as spoken.
- Note any significant non-verbal audio cues in [brackets] such as [laughs], [applause], [music], etc.
{context_note}

Begin the transcript now."""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_uri(
                                file_uri=audio_file.uri,
                                mime_type=audio_file.mime_type,
                            ),
                            types.Part.from_text(text=prompt),
                        ],
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=65536,
                ),
            )
            text = response.text
            if not text and response.candidates:
                parts = response.candidates[0].content.parts
                text = "\n".join(p.text for p in parts if hasattr(p, "text") and p.text)
            return text or ""
        except Exception as e:
            if "429" in str(e) and attempt < max_retries - 1:
                wait = 60 * (attempt + 1)
                print(f"  Rate limited. Waiting {wait}s before retry...")
                time.sleep(wait)
            else:
                raise


def get_last_lines(text, n=5):
    if not text:
        return ""
    lines = [l for l in text.strip().split("\n") if l.strip()]
    return "\n".join(lines[-n:])


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path, duration, yt_title = download_audio(VIDEO_URL, tmpdir)
        segments = split_audio(audio_path, tmpdir, duration)

        client = genai.Client(api_key=API_KEY)

        print("\nCleaning up old uploaded files...")
        cleanup_old_files(client)

        all_transcripts = []
        prev_context = ""

        for i, seg_path in enumerate(segments):
            print(f"\n{'='*60}")
            print(f"Processing segment {i + 1}/{len(segments)}")
            print(f"{'='*60}")

            print(f"  Uploading {seg_path}...")
            audio_file = upload_and_wait(client, seg_path)
            print(f"  Upload complete: {audio_file.uri}")

            print(f"  Transcribing...")
            transcript = transcribe_segment(client, audio_file, i, len(segments), prev_context)
            if transcript:
                all_transcripts.append(transcript)
                prev_context = get_last_lines(transcript)
                print(f"  Done. Got {len(transcript)} chars.")
            else:
                all_transcripts.append(f"[Segment {i+1} returned empty response]")
                print(f"  WARNING: Empty response for segment {i+1}")

            try:
                client.files.delete(name=audio_file.name)
            except Exception:
                pass

            if i < len(segments) - 1:
                print("  Waiting 10s before next segment...")
                time.sleep(10)

    full_transcript = "\n\n".join(all_transcripts)

    print("\n" + "=" * 80)
    print("FULL TRANSCRIPT")
    print("=" * 80 + "\n")
    print(full_transcript)

    safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in yt_title)[:80].strip()
    output_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), f"transcript_{safe_title}.txt"
    )
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(full_transcript)
    print(f"\nTranscript saved to: {output_file}")


if __name__ == "__main__":
    main()

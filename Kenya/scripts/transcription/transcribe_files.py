import argparse
import json
import os
from pathlib import Path

import numpy as np
import torch
import torchaudio
from faster_whisper import WhisperModel
from pyannote.audio import Pipeline
from sklearn.cluster import AgglomerativeClustering


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Whisper + speaker diarization transcript")
    parser.add_argument("audio_file", help="Path to input audio file")
    parser.add_argument(
        "--model",
        default="medium",
        help="Whisper model name (tiny, base, small, medium, large)",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Force language code for Whisper (for example: en). Leave empty for auto-detect.",
    )
    parser.add_argument(
        "--beam-size",
        type=int,
        default=1,
        help="Beam size for decoding. Lower is faster.",
    )
    parser.add_argument(
        "--compute-type",
        default=None,
        help="faster-whisper compute type (int8, int8_float16, float16, float32).",
    )
    parser.add_argument(
        "--num-speakers",
        type=int,
        default=None,
        help="Optional fixed number of speakers for diarization.",
    )
    return parser.parse_args()


def overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def best_speaker_for_segment(start: float, end: float, diarized_turns: list[dict]) -> str:
    best_label = "UNKNOWN_SPEAKER"
    best_overlap = 0.0

    for turn in diarized_turns:
        ov = overlap(start, end, turn["start"], turn["end"])
        if ov > best_overlap:
            best_overlap = ov
            best_label = turn["speaker"]

    if best_overlap > 0:
        return best_label

    # Fallback: choose closest segment midpoint when there is no overlap.
    midpoint = (start + end) / 2.0
    closest = min(
        diarized_turns,
        key=lambda t: abs(midpoint - ((t["start"] + t["end"]) / 2.0)),
        default=None,
    )
    return closest["speaker"] if closest else best_label


def format_ts(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def cluster_speakers_with_ecapa(
    audio_file: Path, whisper_segments: list[dict], num_speakers: int | None
) -> list[str]:
    if not whisper_segments:
        return []

    if not hasattr(torchaudio, "list_audio_backends"):
        torchaudio.list_audio_backends = lambda: ["soundfile"]  # type: ignore[attr-defined]
    if not hasattr(torchaudio, "set_audio_backend"):
        torchaudio.set_audio_backend = lambda backend: None  # type: ignore[attr-defined]

    from speechbrain.inference import EncoderClassifier

    device = "cuda" if torch.cuda.is_available() else "cpu"
    classifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir="pretrained_models/spkrec-ecapa-voxceleb",
        run_opts={"device": device},
    )

    waveform, sample_rate = torchaudio.load(str(audio_file))
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    target_sr = 16000
    if sample_rate != target_sr:
        resampler = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=target_sr)
        waveform = resampler(waveform)
        sample_rate = target_sr

    valid_indices: list[int] = []
    embeddings: list[np.ndarray] = []
    min_samples = int(0.35 * sample_rate)

    for idx, seg in enumerate(whisper_segments):
        start = max(0.0, float(seg["start"]))
        end = max(start + 0.1, float(seg["end"]))
        start_i = int(start * sample_rate)
        end_i = int(end * sample_rate)
        end_i = min(end_i, waveform.shape[1])

        if end_i <= start_i:
            continue

        chunk = waveform[:, start_i:end_i]
        if chunk.shape[1] < min_samples:
            pad = min_samples - chunk.shape[1]
            chunk = torch.nn.functional.pad(chunk, (0, pad))

        signal = chunk.squeeze(0).unsqueeze(0).to(classifier.device)
        with torch.inference_mode():
            emb = classifier.encode_batch(signal).squeeze().detach().cpu().numpy()

        valid_indices.append(idx)
        embeddings.append(emb)

    if not embeddings:
        return ["SPEAKER_00"] * len(whisper_segments)

    n_clusters = num_speakers if num_speakers is not None else 2
    n_clusters = max(1, min(n_clusters, len(embeddings)))
    if n_clusters == 1:
        cluster_labels = np.zeros(len(embeddings), dtype=int)
    else:
        cluster_labels = AgglomerativeClustering(n_clusters=n_clusters).fit_predict(
            np.vstack(embeddings)
        )

    labels: list[str | None] = [None] * len(whisper_segments)
    for local_i, seg_i in enumerate(valid_indices):
        labels[seg_i] = f"SPEAKER_{int(cluster_labels[local_i]):02d}"

    last_label = "SPEAKER_00"
    for i in range(len(labels)):
        if labels[i] is None:
            labels[i] = last_label
        else:
            last_label = labels[i]

    return [label for label in labels if label is not None]


def main() -> None:
    args = parse_args()
    audio_file = Path(args.audio_file)

    if not audio_file.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_file}")

    out_base = audio_file.with_suffix("")
    out_txt = out_base.parent / f"{out_base.name}.speaker_transcript.txt"
    out_json = out_base.parent / f"{out_base.name}.speaker_transcript.json"
    out_whisper_cache = out_base.parent / f"{out_base.name}.whisper_segments.json"

    hf_token = (
        os.getenv("HF_TOKEN")
        or os.getenv("HUGGINGFACE_TOKEN")
        or os.getenv("HUGGINGFACEHUB_API_TOKEN")
    )
    if not hf_token:
        raise RuntimeError(
            "Missing Hugging Face token. Set HF_TOKEN (or HUGGINGFACE_TOKEN) in env."
        )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Running on device: {device}", flush=True)

    compute_type = args.compute_type or ("float16" if device == "cuda" else "int8")
    whisper_segments: list[dict]
    if out_whisper_cache.exists():
        print(f"Loading cached Whisper segments from: {out_whisper_cache}", flush=True)
        with out_whisper_cache.open("r", encoding="utf-8") as f_cache:
            whisper_segments = json.load(f_cache)["segments"]
    else:
        print(
            f"Loading Whisper model '{args.model}' with faster-whisper (compute_type={compute_type})...",
            flush=True,
        )
        model = WhisperModel(args.model, device=device, compute_type=compute_type)

        print("Transcribing with Whisper...", flush=True)
        transcript_iter, _ = model.transcribe(
            str(audio_file),
            language=args.language,
            beam_size=args.beam_size,
            best_of=1,
            condition_on_previous_text=False,
            vad_filter=True,
        )
        whisper_segments = [
            {"start": float(seg.start), "end": float(seg.end), "text": seg.text.strip()}
            for seg in transcript_iter
        ]
        with out_whisper_cache.open("w", encoding="utf-8") as f_cache:
            json.dump(
                {
                    "source_file": str(audio_file),
                    "model": args.model,
                    "segments": whisper_segments,
                },
                f_cache,
                indent=2,
                ensure_ascii=False,
            )
        print(f"Saved Whisper cache: {out_whisper_cache}", flush=True)

    speaker_segments = []
    try:
        print("Loading pyannote speaker diarization pipeline...", flush=True)
        if not hasattr(torchaudio, "list_audio_backends"):
            torchaudio.list_audio_backends = lambda: ["soundfile"]  # type: ignore[attr-defined]
        if not hasattr(torchaudio, "set_audio_backend"):
            torchaudio.set_audio_backend = lambda backend: None  # type: ignore[attr-defined]

        try:
            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                token=hf_token,
            )
        except TypeError:
            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=hf_token,
            )
        if torch.cuda.is_available():
            pipeline.to(torch.device("cuda"))

        print("Running speaker diarization...", flush=True)
        diarization_kwargs = {}
        if args.num_speakers:
            diarization_kwargs["num_speakers"] = args.num_speakers
        diarization = pipeline(str(audio_file), **diarization_kwargs)
        diarized_turns = [
            {"start": turn.start, "end": turn.end, "speaker": speaker}
            for turn, _, speaker in diarization.itertracks(yield_label=True)
        ]

        for seg in whisper_segments:
            seg_start = float(seg["start"])
            seg_end = float(seg["end"])
            seg_text = str(seg["text"]).strip()
            speaker = best_speaker_for_segment(seg_start, seg_end, diarized_turns)
            speaker_segments.append(
                {
                    "start": seg_start,
                    "end": seg_end,
                    "speaker": speaker,
                    "text": seg_text,
                }
            )
    except Exception as err:
        print(
            "pyannote diarization unavailable; falling back to ECAPA embedding clustering. "
            f"Reason: {type(err).__name__}: {err}",
            flush=True,
        )
        labels = cluster_speakers_with_ecapa(audio_file, whisper_segments, args.num_speakers)
        for seg, speaker in zip(whisper_segments, labels):
            speaker_segments.append(
                {
                    "start": float(seg["start"]),
                    "end": float(seg["end"]),
                    "speaker": speaker,
                    "text": str(seg["text"]).strip(),
                }
            )

    with out_txt.open("w", encoding="utf-8") as f_txt:
        for item in speaker_segments:
            f_txt.write(
                f"[{format_ts(item['start'])} - {format_ts(item['end'])}] "
                f"{item['speaker']}: {item['text']}\n"
            )

    with out_json.open("w", encoding="utf-8") as f_json:
        json.dump(
            {
                "source_file": str(audio_file),
                "model": args.model,
                "segments": speaker_segments,
            },
            f_json,
            indent=2,
            ensure_ascii=False,
        )

    print(f"Done. Wrote:\n- {out_txt}\n- {out_json}", flush=True)


if __name__ == "__main__":
    main()

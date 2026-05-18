"""
ASR transcription using NVIDIA NeMo Parakeet.

Parakeet-TDT is a fast, accurate CTC/TDT model that supports word-level
timestamps out of the box.
"""

import logging
from pathlib import Path

from config import DEFAULT_PARAKEET_MODEL

logger = logging.getLogger(__name__)


def transcribe_with_parakeet(
    audio_path: str,
    model_name: str = DEFAULT_PARAKEET_MODEL,
) -> dict:
    """
    Transcribe *audio_path* with a pretrained Parakeet model.

    Returns
    -------
    dict with keys:
        full_text  – the complete transcript string
        words      – list[dict] each with word, start, end (seconds)
    """
    try:
        import nemo.collections.asr as nemo_asr
    except ImportError:
        raise ImportError(
            "NVIDIA NeMo ASR is not installed.\n"
            "Install with:  pip install nemo_toolkit[asr]\n"
            "See README.md for full setup instructions."
        )

    audio = Path(audio_path)
    if not audio.exists():
        raise FileNotFoundError(f"Audio file not found: {audio}")

    logger.info("Loading Parakeet model: %s …", model_name)
    model = nemo_asr.models.ASRModel.from_pretrained(model_name=model_name)

    logger.info("Transcribing %s …", audio.name)
    # timestamps=True tells NeMo to return word-level timing information.
    output = model.transcribe(
        [str(audio.resolve())],
        timestamps=True,
        batch_size=1,
    )

    full_text, words = _parse_nemo_output(output)
    logger.info("ASR produced %d words.", len(words))
    return {"full_text": full_text, "words": words}


# ---------------------------------------------------------------------------
# Internal: normalise the (version-dependent) NeMo output into a stable schema
# ---------------------------------------------------------------------------

def _parse_nemo_output(output) -> tuple[str, list[dict]]:
    """
    NeMo's transcribe() return value varies across versions.  This function
    tries several known layouts and returns (full_text, words) where each word
    is {"word": str, "start": float, "end": float}.
    """

    # --- 1. output is a dataclass / object with .text and .timestamp ---------
    if hasattr(output, "text"):
        return _extract_from_object(output)

    # --- 2. output is a list (one entry per file) ----------------------------
    if isinstance(output, (list, tuple)):
        if len(output) == 0:
            raise RuntimeError("Parakeet returned empty output.")

        first = output[0]

        # 2a. list of dataclass-like objects
        if hasattr(first, "text"):
            return _extract_from_object(first)

        # 2b. list of strings (no timestamps returned separately)
        if isinstance(first, str):
            return first, []

        # 2c. list of dicts
        if isinstance(first, dict):
            return _extract_from_dict(first)

        # 2d. tuple of (texts_list, hypotheses_list)
        if isinstance(first, (list, tuple)):
            texts = first
            hypotheses = output[1] if len(output) > 1 else None
            text = texts[0] if texts else ""
            if hypotheses and len(hypotheses) > 0:
                return _extract_words_from_hypothesis(text, hypotheses[0])
            return text, []

    # --- 3. output is a dict --------------------------------------------------
    if isinstance(output, dict):
        return _extract_from_dict(output)

    raise RuntimeError(f"Unexpected Parakeet output type: {type(output)}")


def _extract_from_object(obj) -> tuple[str, list[dict]]:
    """Handle NeMo result objects that expose .text / .timestamp / .timestep."""
    text = getattr(obj, "text", "") or ""
    if isinstance(text, list):
        text = text[0] if text else ""

    words: list[dict] = []

    # .timestamp is the most common attribute for word timing
    ts = getattr(obj, "timestamp", None) or getattr(obj, "timestamps", None)
    if ts is not None:
        words = _normalise_timestamps(ts)

    # Some versions nest timestamps inside .hypotheses
    if not words:
        hyps = getattr(obj, "hypotheses", None)
        if hyps:
            _, words = _extract_words_from_hypothesis(text, hyps[0] if isinstance(hyps, list) else hyps)

    return text, words


def _extract_from_dict(d: dict) -> tuple[str, list[dict]]:
    text = d.get("text", d.get("pred_text", ""))
    if isinstance(text, list):
        text = text[0] if text else ""

    words: list[dict] = []
    ts = d.get("timestamp", d.get("timestamps", d.get("word_timestamps", None)))
    if ts is not None:
        words = _normalise_timestamps(ts)
    return text, words


def _extract_words_from_hypothesis(text: str, hyp) -> tuple[str, list[dict]]:
    """Pull word timestamps from a NeMo Hypothesis object."""
    words: list[dict] = []
    ts = getattr(hyp, "timestamp", None) or getattr(hyp, "timestamps", None)
    if ts:
        words = _normalise_timestamps(ts)
    t = getattr(hyp, "text", text) or text
    if isinstance(t, list):
        t = t[0] if t else text
    return t, words


def _normalise_timestamps(ts) -> list[dict]:
    """
    Accept various timestamp layouts and return a flat list of
    {"word": str, "start": float, "end": float}.

    Known layouts:
      - dict with "word" list and "start"/"end" lists
      - list of dicts with word/start/end keys
      - list of tuples (word, start, end)
    """
    words: list[dict] = []

    if isinstance(ts, dict):
        w_list = ts.get("word", ts.get("words", []))
        s_list = ts.get("start", ts.get("start_offset", []))
        e_list = ts.get("end", ts.get("end_offset", []))
        if w_list and s_list and e_list:
            for w, s, e in zip(w_list, s_list, e_list):
                words.append({"word": str(w), "start": float(s), "end": float(e)})
        return words

    if isinstance(ts, (list, tuple)):
        for item in ts:
            if isinstance(item, dict):
                w = item.get("word", item.get("char", ""))
                s = item.get("start", item.get("start_offset", 0.0))
                e = item.get("end", item.get("end_offset", 0.0))
                words.append({"word": str(w), "start": float(s), "end": float(e)})
            elif isinstance(item, (list, tuple)) and len(item) >= 3:
                words.append({"word": str(item[0]), "start": float(item[1]), "end": float(item[2])})
        return words

    return words

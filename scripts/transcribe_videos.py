from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path
from time import perf_counter


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = ROOT / "Notebooks" / "Transcription Pipeline.ipynb"

for import_path in (ROOT, ROOT / "scripts"):
    import_path_str = str(import_path)
    if import_path_str not in sys.path:
        sys.path.insert(0, import_path_str)

SETUP_CELL_MARKERS = [
    "from __future__ import annotations",
    'YOUTUBE_URL = ""',
    "VIDEO_JOBS = {",
]
PREFLIGHT_CELL_MARKERS = [
    'require_binary("ffmpeg")',
    "def ensure_runtime_is_ready() -> None:",
    "class VideoContextPayload(TypedDict, total=False):",
]
PIPELINE_EXTRA_CELL_MARKERS = [
    "def convert_to_wav_16k_mono(input_path: str, output_path: str) -> str:",
    "def normalize_word_entries(raw_words: list[dict], *, source: str) -> list[dict]:",
    "def derive_diarization_constraints(metadata: dict) -> dict:",
    "def assign_speakers_to_words(words: list[dict], speaker_segments: list[dict], tolerance: float = 0.75) -> list[dict]:",
    "# transcripts_utils guards",
    "def is_audience_like_turn(text: str) -> bool:",
    "def resolve_transcript_output_path(output_dir: Path, metadata: dict, transcript_filename: str | None) -> Path:",
    "preview_text = Path(saved_path).read_text(encoding='utf-8')",
]

log = logging.getLogger("run_all_transcriptions")


def load_notebook_code_cells() -> dict[int, str]:
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    code_cells: dict[int, str] = {}
    for index, cell in enumerate(notebook["cells"]):
        if cell.get("cell_type") != "code":
            continue
        code_cells[index] = "".join(cell.get("source", []))
    return code_cells


def resolve_cell_index(code_cells: dict[int, str], marker: str) -> int:
    matches = [index for index, source in code_cells.items() if marker in source]
    if not matches:
        raise RuntimeError(f"Notebook cell marker not found: {marker}")
    if len(matches) > 1:
        raise RuntimeError(f"Notebook cell marker is ambiguous: {marker} -> {matches}")
    return matches[0]


def resolve_notebook_indexes(code_cells: dict[int, str] | None = None) -> tuple[list[int], list[int], list[int]]:
    code_cells = code_cells or load_notebook_code_cells()
    setup_indexes = [resolve_cell_index(code_cells, marker) for marker in SETUP_CELL_MARKERS]
    preflight_indexes = [resolve_cell_index(code_cells, marker) for marker in PREFLIGHT_CELL_MARKERS]
    pipeline_indexes = preflight_indexes + [
        resolve_cell_index(code_cells, marker) for marker in PIPELINE_EXTRA_CELL_MARKERS
    ]
    return setup_indexes, preflight_indexes, pipeline_indexes


SETUP_CELL_INDEXES, PREFLIGHT_CELL_INDEXES, PIPELINE_CELL_INDEXES = resolve_notebook_indexes()


def build_runtime() -> dict:
    runtime = {"__name__": "__main__"}
    code_cells = load_notebook_code_cells()
    for index in SETUP_CELL_INDEXES:
        exec(compile(code_cells[index], f"Transcription Pipeline.ipynb::cell_{index}", "exec"), runtime)
    return runtime


def get_job_names(runtime: dict) -> list[str]:
    return list(runtime["VIDEO_JOBS"].keys())


def run_cells(runtime: dict, indexes: list[int]) -> None:
    code_cells = load_notebook_code_cells()
    for index in indexes:
        exec(compile(code_cells[index], f"Transcription Pipeline.ipynb::cell_{index}", "exec"), runtime)


def run_single_job(job_name: str, *, preflight_only: bool = False) -> tuple[bool, float, str | None]:
    started = perf_counter()
    runtime = build_runtime()
    runtime["apply_video_job"](job_name)
    try:
        run_cells(runtime, PREFLIGHT_CELL_INDEXES if preflight_only else PIPELINE_CELL_INDEXES)
    except Exception as exc:
        elapsed = perf_counter() - started
        return False, elapsed, "".join(traceback.format_exception(exc))
    elapsed = perf_counter() - started
    return True, elapsed, None


def run_preflight(job_names: list[str]) -> bool:
    log.info("Running preflight across %s jobs...", len(job_names))
    failures: list[tuple[str, str]] = []
    for index, job_name in enumerate(job_names, start=1):
        log.info("Preflight %s/%s: %s", index, len(job_names), job_name)
        ok, elapsed, error = run_single_job(job_name, preflight_only=True)
        if ok:
            log.info("Preflight passed for %s in %.1fs", job_name, elapsed)
        else:
            log.error("Preflight failed for %s in %.1fs", job_name, elapsed)
            failures.append((job_name, error or "unknown error"))
    if failures:
        log.error("Preflight failed for %s job(s).", len(failures))
        for job_name, error in failures:
            log.error("FAILED PRECHECK %s\n%s", job_name, error)
        return False
    log.info("All job preflights passed.")
    return True


def run_batch(job_names: list[str]) -> int:
    failures: list[tuple[str, str]] = []
    for index, job_name in enumerate(job_names, start=1):
        log.info("Running job %s/%s: %s", index, len(job_names), job_name)
        ok, elapsed, error = run_single_job(job_name, preflight_only=False)
        if ok:
            log.info("Completed %s in %.1f minutes", job_name, elapsed / 60.0)
            continue
        log.error("Job failed: %s after %.1f minutes", job_name, elapsed / 60.0)
        if error:
            log.error("Traceback for %s\n%s", job_name, error)
        failures.append((job_name, error or "unknown error"))
    if failures:
        log.error("Batch finished with %s failure(s).", len(failures))
        for job_name, error in failures:
            log.error("FAILED JOB %s\n%s", job_name, error)
        return 1
    log.info("Batch completed successfully for %s job(s).", len(job_names))
    return 0


def configure_logging(log_path: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run all transcription jobs from the notebook pipeline.")
    parser.add_argument("--country", choices=["all", "nigeria", "kenya"], default="all")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--jobs", nargs="*", default=None, help="Explicit notebook job names to run.")
    parser.add_argument("--log-file", default=str(ROOT / "transcription_batch.log"))
    return parser.parse_args()


def select_jobs(runtime: dict, country: str, explicit_jobs: list[str] | None) -> list[str]:
    if explicit_jobs:
        unknown = [job for job in explicit_jobs if job not in runtime["VIDEO_JOBS"]]
        if unknown:
            raise SystemExit(f"Unknown job(s): {', '.join(unknown)}")
        return explicit_jobs

    all_jobs = list(runtime["VIDEO_JOBS"].items())
    if country == "all":
        return [name for name, _ in all_jobs]
    if country == "nigeria":
        return [name for name, job in all_jobs if str(job.get("output_subdir", "")).startswith("Nigeria")]
    return [name for name, job in all_jobs if str(job.get("output_subdir", "")).startswith("Kenya")]


def main() -> int:
    args = parse_args()
    configure_logging(Path(args.log_file) if args.log_file else None)
    runtime = build_runtime()
    job_names = select_jobs(runtime, args.country, args.jobs)
    log.info("Selected %s jobs.", len(job_names))
    for job_name in job_names:
        log.info(" - %s", job_name)
    if not args.skip_preflight:
        if not run_preflight(job_names):
            return 1
    return run_batch(job_names)


if __name__ == "__main__":
    raise SystemExit(main())

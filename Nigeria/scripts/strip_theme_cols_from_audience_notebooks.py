"""
Strip the 9 LLM front-summary columns (Primary Theme, Sentiment, Tone, etc.)
from the export step of both audience LLM coding notebooks so future re-runs
match the polished xlsx (which has only metadata + Q-cols).

Patches:
    Nigeria/Notebooks/LLM Coding Notebook - Audience Analysis.ipynb
    Kenya/Notebooks/LLM Coding Notebook  - Audience Analysis.ipynb

Idempotent — safe to run multiple times.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

NOTEBOOKS = [
    ROOT / "Nigeria" / "Notebooks" / "LLM Coding Notebook - Audience Analysis.ipynb",
    ROOT / "Kenya"   / "Notebooks" / "LLM Coding Notebook - Audience Analysis.ipynb",
]

DROP_LINES = [
    "Primary Theme",
    "Secondary Theme 1",
    "Secondary Theme 2",
    "Masculinity Identity",
    "Normative Orientation",
    "Target of Claim",
    "'Sentiment':",
    "'Emotion Detection':",
    "'Tone':",
    "# NEW separate columns",
]

DROP_PRINT_FRAGMENTS = [
    "out['Primary Theme'].value_counts",
    "out['Normative Orientation'].value_counts",
    "out['Target of Claim'].value_counts",
    "out['Sentiment'].value_counts",
    "groupby(['creator','Sentiment'])",
    "groupby(['creator','Tone'])",
    "groupby(['creator','Primary Theme'])",
    "groupby(['creator','Normative Orientation'])",
    "groupby(['creator','Target of Claim'])",
    "Sentiment × creator",
    "Tone × creator",
    "Primary Theme × creator",
    "Normative Orientation × creator",
    "Target of Claim × creator",
]


def strip_lines(src_lines: list[str]) -> tuple[list[str], int]:
    out, drops = [], 0
    for ln in src_lines:
        if any(d in ln for d in DROP_LINES):
            drops += 1
            continue
        if any(p in ln for p in DROP_PRINT_FRAGMENTS):
            drops += 1
            continue
        out.append(ln)
    return out, drops


def patch_notebook(path: Path) -> None:
    with open(path) as f:
        nb = json.load(f)
    total_drops = 0
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        new_src, drops = strip_lines(cell["source"])
        if drops:
            cell["source"] = new_src
            total_drops += drops
    with open(path, "w") as f:
        json.dump(nb, f, indent=1, ensure_ascii=False)
    print(f"  patched {path.name}: dropped {total_drops} lines")


def main():
    for nb_path in NOTEBOOKS:
        if nb_path.exists():
            patch_notebook(nb_path)
        else:
            print(f"  skip {nb_path} — not found")


if __name__ == "__main__":
    main()

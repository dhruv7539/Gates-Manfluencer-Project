"""Quick accuracy check: compare caption text against generated transcripts."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_all_transcriptions import build_runtime
from transcript_output_utils import split_header_and_body, parse_transcript_style_lines, clean_text

ROOT = Path(__file__).resolve().parents[1]
CAPTIONS_ROOT = ROOT / "Captions"
TRANSCRIPTS_ROOT = ROOT / "Generated Transcripts"

CAPTION_MAP = {
    "face_it_like_a_man": "Nigeria/Face it Like a Man - Banky Wellington.txt",
    "faith_after_a_fall": "Nigeria/Faith after a Fall - Banky Wellington.txt",
    "final_say_faith": "Nigeria/Final Say Faith - Banky & Adesua Wellington.txt",
    "my_story_journey_through_hope_and_faith": "Nigeria/My Story - a journey through Hope & Faith - Banky Wellington.txt",
    "the_prison_of_pornography": "Nigeria/The Prison of Pornography - Road to Freedom Finale.txt",
    "andrew_kibe_071_28_commandments_of_journeying_into_wealth_health_and_respect": "Kenya/Andrew Kibe/071 Andrew Kibe and the 28 Commandments of Journeying into Wealth, Health and Respect.txt",
    "onyango_narelate_mens_mental_health_workshop_nakuru_january_2023": "Kenya/Onyango Otieno (Rixpoet)/#NaRelate Men's Mental Health Workshop #Nakuru #MentalHealth by Onyango Otieno January 2023.txt",
    "onyango_men_addiction_and_violence_the_story_of_our_childhood_trauma": "Kenya/Onyango Otieno (Rixpoet)/Men, Addiction, and Violence; The Story of our Childhood Trauma.txt",
    "onyango_my_voice_was_beaten_out_of_me_by_my_father_toxic_masculinity": "Kenya/Onyango Otieno (Rixpoet)/My voice was beaten out of me by my father - Toxic masculinity.txt",
    "onyango_undoing_my_fathers_damage": "Kenya/Onyango Otieno (Rixpoet)/Undoing My Father's Damage - Onyango Otieno (Rix poet).txt",
    "onyango_your_story_i_thought_having_a_lot_of_sex_would_cure_my_depression": "Kenya/Onyango Otieno (Rixpoet)/Your Story I Thought Having A Lot Of Sex Would Cure My Depression.txt",
    "philip_karanja_my_childhood_upbringing": "Kenya/Philip Karanja/1753. My Childhood Upbringing - Philip Karanja (@OfficialPhilKaranja) #cta101.txt",
    "philip_karanja_episode_1_a_girl_dad_on_a_mission": "Kenya/Philip Karanja/Episode 1 A Girl Dad on a MissionIs my daughter really safe in this world.txt",
    "philip_karanja_episode_2_a_girl_dad_on_a_mission": "Kenya/Philip Karanja/Episode 2 A Girl Dad on a Mission1 in 4 young women are married as children.txt",
    "philip_karanja_season_finale_a_girl_dad_on_a_mission": "Kenya/Philip Karanja/Season Finale A Girl Dad on a Mission Rape as Background Noise A Society Numbed by Violence.txt",
}

TRANSCRIPT_MAP = {
    "face_it_like_a_man": "Nigeria/Face it Like a Man - Banky Wellington.txt",
    "faith_after_a_fall": "Nigeria/Faith after a Fall - Banky Wellington.txt",
    "final_say_faith": "Nigeria/Final Say Faith - Banky & Adesua Wellington.txt",
    "my_story_journey_through_hope_and_faith": "Nigeria/My Story - a journey through Hope & Faith - Banky Wellington.txt",
    "the_prison_of_pornography": "Nigeria/The Prison of Pornography - Road to Freedom Finale.txt",
    "andrew_kibe_071_28_commandments_of_journeying_into_wealth_health_and_respect": "Kenya/Andrew Kibe/071 Andrew Kibe and the 28 Commandments of Journeying into Wealth, Health and Respect.txt",
    "onyango_narelate_mens_mental_health_workshop_nakuru_january_2023": "Kenya/Onyango Otieno (Rixpoet)/#NaRelate Men's Mental Health Workshop #Nakuru #MentalHealth by Onyango Otieno January 2023.txt",
    "onyango_men_addiction_and_violence_the_story_of_our_childhood_trauma": "Kenya/Onyango Otieno (Rixpoet)/Men, Addiction, and Violence; The Story of our Childhood Trauma.txt",
    "onyango_my_voice_was_beaten_out_of_me_by_my_father_toxic_masculinity": "Kenya/Onyango Otieno (Rixpoet)/My voice was beaten out of me by my father - Toxic masculinity.txt",
    "onyango_undoing_my_fathers_damage": "Kenya/Onyango Otieno (Rixpoet)/Undoing My Father\u2019s Damage - Onyango Otieno (Rix poet).txt",
    "onyango_your_story_i_thought_having_a_lot_of_sex_would_cure_my_depression": "Kenya/Onyango Otieno (Rixpoet)/Your Story I Thought Having A Lot Of Sex Would Cure My Depression.txt",
    "philip_karanja_my_childhood_upbringing": "Kenya/Philip Karanja/1753. My Childhood Upbringing - Philip Karanja (@OfficialPhilKaranja) #cta101.txt",
    "philip_karanja_episode_1_a_girl_dad_on_a_mission": "Kenya/Philip Karanja/Episode 1 A Girl Dad on a MissionIs my daughter really safe in this world.txt",
    "philip_karanja_episode_2_a_girl_dad_on_a_mission": "Kenya/Philip Karanja/Episode 2 A Girl Dad on a Mission1 in 4 young women are married as children.txt",
    "philip_karanja_season_finale_a_girl_dad_on_a_mission": "Kenya/Philip Karanja/Season Finale A Girl Dad on a Mission Rape as Background Noise A Society Numbed by Violence.txt",
}


def _resolve_path(root: Path, rel: str) -> Path:
    """Resolve a path, falling back to fuzzy match if exact path doesn't exist."""
    exact = root / rel
    if exact.exists():
        return exact
    parent = exact.parent
    if parent.is_dir():
        target_norm = exact.name.lower().replace("\u2018", "'").replace("\u2019", "'")
        for f in parent.iterdir():
            f_norm = f.name.lower().replace("\u2018", "'").replace("\u2019", "'")
            if f_norm == target_norm:
                return f
    return exact


def normalize_word(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", w.lower())


def tokenize(text: str) -> list[str]:
    return [normalize_word(w) for w in re.findall(r"\S+", text) if normalize_word(w)]


def extract_transcript_body(text: str) -> str:
    _, body = split_header_and_body(text)
    turns = parse_transcript_style_lines(body)
    return " ".join(clean_text(t.get("text", "")) for t in turns)


def lcs_length(a: list[str], b: list[str]) -> int:
    """Length of longest common subsequence (word-level). Uses O(min(m,n)) space."""
    if len(a) < len(b):
        a, b = b, a
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        curr = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev = curr
    return prev[len(b)]


def compute_metrics(caption_words: list[str], transcript_words: list[str]) -> dict:
    """Bag-of-words overlap accounting for word frequency."""
    from collections import Counter

    cap_counts = Counter(caption_words)
    trans_counts = Counter(transcript_words)
    overlap = sum(min(cap_counts[w], trans_counts[w]) for w in cap_counts)

    caption_len = len(caption_words)
    transcript_len = len(transcript_words)
    precision = overlap / transcript_len if transcript_len else 0.0
    recall = overlap / caption_len if caption_len else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    coverage = transcript_len / caption_len if caption_len else 0.0
    return {
        "caption_words": caption_len,
        "transcript_words": transcript_len,
        "overlap_words": overlap,
        "precision": round(precision * 100, 1),
        "recall": round(recall * 100, 1),
        "f1": round(f1 * 100, 1),
        "coverage_pct": round(coverage * 100, 1),
    }


def main() -> None:
    print("=" * 100)
    print(f"{'Job':<55} {'Cap':>5} {'Trans':>6} {'Ovlap':>6} {'Prec%':>6} {'Recall%':>7} {'F1%':>5} {'Cov%':>6}")
    print("-" * 100)

    all_results = []
    for job_name in CAPTION_MAP:
        caption_path = _resolve_path(CAPTIONS_ROOT, CAPTION_MAP[job_name])
        transcript_path = _resolve_path(TRANSCRIPTS_ROOT, TRANSCRIPT_MAP[job_name])

        if not caption_path.exists():
            print(f"{job_name:<55} CAPTION MISSING")
            continue
        if not transcript_path.exists():
            print(f"{job_name:<55} TRANSCRIPT MISSING")
            continue

        caption_text = caption_path.read_text(encoding="utf-8")
        transcript_text = transcript_path.read_text(encoding="utf-8")

        cap_words = tokenize(caption_text)
        trans_body = extract_transcript_body(transcript_text)
        trans_words = tokenize(trans_body)

        metrics = compute_metrics(cap_words, trans_words)
        metrics["job"] = job_name
        all_results.append(metrics)

        short_name = job_name[:54]
        print(
            f"{short_name:<55} {metrics['caption_words']:>5} {metrics['transcript_words']:>6} "
            f"{metrics['overlap_words']:>6} {metrics['precision']:>5.1f}% {metrics['recall']:>6.1f}% "
            f"{metrics['f1']:>5.1f} {metrics['coverage_pct']:>5.1f}%"
        )

    print("-" * 100)

    if all_results:
        avg_prec = sum(r["precision"] for r in all_results) / len(all_results)
        avg_recall = sum(r["recall"] for r in all_results) / len(all_results)
        avg_f1 = sum(r["f1"] for r in all_results) / len(all_results)
        avg_cov = sum(r["coverage_pct"] for r in all_results) / len(all_results)
        print(
            f"{'AVERAGE':<55} {'':>5} {'':>6} {'':>6} {avg_prec:>5.1f}% {avg_recall:>6.1f}% "
            f"{avg_f1:>5.1f} {avg_cov:>5.1f}%"
        )

    print("\n" + "=" * 100)
    print("METRIC DEFINITIONS:")
    print("  Cap       = caption word count (ground truth)")
    print("  Trans     = transcript word count (current output)")
    print("  Match     = words from captions found in transcript (greedy forward)")
    print("  Precision = Match / Trans (how much of transcript is real caption content)")
    print("  Recall    = Match / Cap  (how much of caption content is captured)")
    print("  F1        = harmonic mean of precision & recall")
    print("  Coverage  = Trans / Cap  (>100% = over-generation, <100% = under-generation)")
    print()
    print("RESEARCH-GRADE THRESHOLDS:")
    print("  F1 >= 90%  AND  Coverage 90-110%  =>  Research-ready")
    print("  F1 80-90%  OR   Coverage off       =>  Usable with caveats")
    print("  F1 < 80%                           =>  Needs rework")

    research_ready = [r for r in all_results if r["f1"] >= 90.0 and 90 <= r["coverage_pct"] <= 110]
    usable = [r for r in all_results if r not in research_ready and r["f1"] >= 80.0]
    needs_work = [r for r in all_results if r["f1"] < 80.0]

    print(f"\n  Research-ready: {len(research_ready)}/15")
    print(f"  Usable:         {len(usable)}/15")
    print(f"  Needs work:     {len(needs_work)}/15")

    if needs_work:
        print("\n  Transcripts needing work:")
        for r in sorted(needs_work, key=lambda x: x["f1"]):
            print(f"    - {r['job']}: F1={r['f1']}%, Coverage={r['coverage_pct']}%")

    over_generated = [r for r in all_results if r["coverage_pct"] > 110]
    if over_generated:
        print(f"\n  Over-generated transcripts (coverage > 110%):")
        for r in sorted(over_generated, key=lambda x: -x["coverage_pct"]):
            print(f"    - {r['job']}: Coverage={r['coverage_pct']}% ({r['transcript_words'] - r['caption_words']:+d} words)")

    under_generated = [r for r in all_results if r["coverage_pct"] < 85]
    if under_generated:
        print(f"\n  Under-generated transcripts (coverage < 85%):")
        for r in sorted(under_generated, key=lambda x: x["coverage_pct"]):
            print(f"    - {r['job']}: Coverage={r['coverage_pct']}% (missing ~{r['caption_words'] - r['transcript_words']} words)")


if __name__ == "__main__":
    main()

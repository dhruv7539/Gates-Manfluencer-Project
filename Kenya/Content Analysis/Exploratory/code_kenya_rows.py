from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path


OUT_DIR = Path("/Users/dhruvbhanderi/Documents/USC/New Research Engineer/Codex/outputs/kenya_two_pass_llm_workflow")
IN_JSON = OUT_DIR / "kenya_two_pass_workflow_data.json"
OUT_JSON = OUT_DIR / "kenya_two_pass_llm_coded_data.json"


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def has(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def count_hits(text: str, patterns: list[str]) -> int:
    return sum(1 for p in patterns if re.search(p, text, re.I))


def evidence(text: str, patterns: list[str] | None = None, limit: int = 160) -> str:
    clean = norm(text)
    if not clean:
        return ""
    if patterns:
        for pat in patterns:
            m = re.search(pat, clean, re.I)
            if m:
                start = max(0, m.start() - 55)
                end = min(len(clean), m.end() + 95)
                snippet = clean[start:end].strip()
                if start:
                    snippet = "..." + snippet
                if end < len(clean):
                    snippet += "..."
                return snippet[:limit].strip()
    return (clean[: limit - 3].rsplit(" ", 1)[0] + "...") if len(clean) > limit else clean


PATTERNS = {
    "Dating/marriage": [r"\bdat(e|ing)\b", r"\bmarri(age|ed|y)\b", r"\bwife\b", r"\bhusband\b", r"\blove\b", r"\brelationship", r"\bcheat", r"\bdivorce", r"\bmonogam", r"\bpolygam", r"\bone woman\b", r"\bgirlfriend\b"],
    "Family/children": [r"\bfather\b", r"\bmother\b", r"\bparent", r"\bchild", r"\bchildren\b", r"\bson\b", r"\bdaughter", r"\bfamily\b", r"\bbaby daddy\b"],
    "Money/status": [r"\bmoney\b", r"\brent\b", r"\bsalary\b", r"\bincome\b", r"\bbusiness\b", r"\bjob\b", r"\bwork\b", r"\bwealth\b", r"\bprovider\b", r"\bstatus\b", r"\blow[- ]?value\b", r"\bsimp\b", r"\bgreatness\b", r"\bpower\b", r"\bpuny\b", r"\bsuccess"],
    "Fitness/self-improvement": [r"\bdiscipline\b", r"\bself[- ]?improve", r"\bbuild\b", r"\bgym\b", r"\bfitness\b", r"\bhabits?\b", r"\bfocus\b", r"\bpurpose\b", r"\bbetter man\b", r"\brespect yourself\b"],
    "Mental health": [r"\bmental\b", r"\btrauma", r"\bheal", r"\btherapy\b", r"\bdepress", r"\bemotion", r"\bvulnerab", r"\bpain\b", r"\bsuicid", r"\blet go\b", r"\bsilence\b", r"\bspeak\b", r"\bcry\b"],
    "Gender equality": [r"\bequal", r"\bmutual\b", r"\btwo[- ]?way\b", r"\brecipro", r"\bpartner", r"\baccountab", r"\bboth\b", r"\brespectful\b", r"\b50/50\b"],
    "Religion/morality": [r"\bgod\b", r"\bchrist", r"\bbible\b", r"\bpray", r"\bfaith\b", r"\bsin\b", r"\bmoral", r"\btradition"],
    "Violence/GBV": [r"\babuse", r"\bbeaten\b", r"\bbeat\b", r"\bviolence\b", r"\brape\b", r"\bGBV\b", r"\bassault", r"\bpolice\b", r"\bprotect"],
    "Politics/social problems": [r"\bsociety\b", r"\bgovernment\b", r"\bempower", r"\bfeminism\b", r"\bmodern\b", r"\bculture\b", r"\bsystem", r"\bcommunity\b", r"\bparliament\b"],
}

FRAME_PATTERNS = {
    "Male victimhood": [r"\bmen (are|have been|were) (left|disadvantaged|ignored|oppressed|suffering)", r"\bno one is coming\b", r"\bmen.*struggl", r"\bmen.*problem", r"\bexpected to\b", r"\bleft behind\b"],
    "Female blame": [r"\bwomen (are|have|no longer|can't|cannot|don't)", r"\ba woman (is|can't|cannot|will|doesn't)", r"\bfemales?\b", r"\bgirls?\b.*spoiled", r"\bbaby daddy\b"],
    "Traditional order / patriarchy": [r"\bsubmit", r"\bobey", r"\blead", r"\bhead of", r"\brespect.*man", r"\bpatriarch", r"\bauthority", r"\border\b"],
    "Self-improvement / discipline": [r"\bdiscipline\b", r"\bbuild\b", r"\bfocus\b", r"\bpurpose\b", r"\bimprove\b", r"\brespect yourself\b", r"\bgreatness\b"],
    "Provider-status pressure": [r"\bprovide", r"\bprovider", r"\bmoney\b", r"\brent\b", r"\bsalary\b", r"\blow[- ]?value\b", r"\bstatus\b", r"\bsimp\b", r"\bpower\b", r"\bpuny\b"],
    "Sexual control / purity": [r"\bcheat", r"\bbody count\b", r"\bsexual\b", r"\bvirgin", r"\bpure", r"\bone woman\b", r"\bmore women\b", r"\bseduce", r"\bforgive a cheating wife\b"],
    "Faith/morality": PATTERNS["Religion/morality"],
    "Trauma/healing": PATTERNS["Mental health"],
    "Equality/accountability": PATTERNS["Gender equality"] + [r"\bnot people\b", r"\bharmful\b", r"\btoxic\b"],
    "Protection of women/girls": [r"\bprotect.*(women|girls)", r"\bGBV\b", r"\brape\b", r"\bviolence against women\b", r"\bgirls?.*safe"],
    "Anti-feminism / anti-modern woman": [r"\bfeminis", r"\bmodern women\b", r"\bempower(ed|ment).*women", r"\bwomen no longer", r"\bcareer women\b"],
}

MISOGYNY_PATTERNS = {
    "Sexual violence minimization or endorsement": [r"\brape\b.*(not|joke|deserve|enjoy|asked)", r"\bforce.*sex", r"\bsexual violence.*(not|joke)"],
    "Justification of control/submission": [r"\bsubmit", r"\bobey", r"\bcontrol (women|her|wife)", r"\bwoman.*place", r"\bkeep.*woman"],
    "Objectification/sexualization": [r"\bwomen?.*(car|cars|property|object)", r"\bgirl.*car", r"\bmore women\b", r"\bseduce.*women", r"\bfuck more women", r"\bbody count\b"],
    "Hostility/insult toward women": [r"\bwomen?.*(trash|stupid|dumb|useless|evil|wicked)", r"\bfemales?.*(trash|stupid|dumb|useless)", r"\bhoes?\b", r"\bbitches\b"],
    "Female blame": [r"\bwomen (are|have|no longer|can't|cannot|don't)", r"\ba woman (can't|cannot|doesn't|will not)", r"\bfemales?.*need", r"\bwomen.*problem"],
    "Anti-feminist hostility": [r"\bfeminis", r"\bmodern women\b", r"\bempower(ed|ment).*women"],
    "Stereotyping": [r"\bwomen (love|want|need|fantasize|see|think|always|never)", r"\bmen (always|never|are wired)", r"\ba woman (is|will|wants|needs)"],
}

EMOTION_PATTERNS = {
    "Anger": [r"\bwrong\b", r"\bsick\b", r"\bangry\b", r"\bmad\b", r"\bnonsense\b", r"\bshame\b", r"\bdisrespect"],
    "Contempt/disgust": [r"\bdisgust", r"\bpathetic\b", r"\bsimp\b", r"\blow[- ]?value\b", r"\bpuny\b", r"\btoad\b", r"\buseless\b"],
    "Fear/anxiety": [r"\bfear\b", r"\bworried\b", r"\banxious\b", r"\bthreat", r"\bunsafe\b", r"\bafraid\b"],
    "Sadness": [r"\bsad\b", r"\bpain\b", r"\bcried\b", r"\btears?\b", r"\blonely\b", r"\bbroken\b", r"\bfailed\b", r"\bhurt\b"],
    "Hope/encouragement": [r"\bhope\b", r"\bheal", r"\bencourage", r"\binspire", r"\bbuild\b", r"\bkeep going\b", r"\bbless", r"\barise\b"],
    "Pride/admiration": [r"\bproud\b", r"\badmir", r"\brespect\b", r"\bgreat\b", r"\bpowerful\b", r"\bwell said\b", r"\bfacts\b", r"\btrue\b"],
    "Humor/mockery": [r"\blol\b", r"\blmao\b", r"\bhaha", r"😂", r"🤣", r"\bjoke\b"],
    "Empathy/compassion": [r"\bsorry\b", r"\bfeel you\b", r"\bthank you\b", r"\bcare\b", r"\bcompassion", r"\bunderstand\b", r"\bpraying\b"],
}


def best_label(text: str, label_patterns: dict[str, list[str]], default: str) -> tuple[str, int, list[str]]:
    scores = {label: count_hits(text, pats) for label, pats in label_patterns.items()}
    label, score = max(scores.items(), key=lambda kv: (kv[1], kv[0]))
    if score == 0:
        return default, 0, []
    return label, score, label_patterns[label]


def topic(text: str) -> tuple[str, int, list[str]]:
    return best_label(text, PATTERNS, "Other")


def frame(text: str) -> tuple[str, int, list[str]]:
    return best_label(text, FRAME_PATTERNS, "Mixed/unclear")


def emotion(text: str) -> tuple[str, int, list[str]]:
    return best_label(text, EMOTION_PATTERNS, "Neutral/unclear")


def misogyny(text: str) -> tuple[str, int, list[str]]:
    for label, pats in MISOGYNY_PATTERNS.items():
        if has(text, pats):
            return label, count_hits(text, pats), pats
    return "None", 0, []


def masculinity_narrative(text: str, frame_label: str) -> str:
    if has(text, [r"\bsubmit", r"\bobey", r"\bwoman.*place"]):
        return "Women should submit"
    if has(text, [r"\bsuppress", r"\bnever.*(cry|tell|share)", r"\bdon't.*(cry|share|show emotion)", r"\bhide.*pain"]):
        return "Men should suppress emotions"
    if has(text, [r"\bemotion", r"\bmental\b", r"\bheal", r"\bvulnerab", r"\bspeak", r"\btherapy\b"]):
        return "Men should be emotionally open"
    if frame_label == "Provider-status pressure" or has(text, [r"\bprovide", r"\bsucceed", r"\bgreatness", r"\bstatus\b", r"\bpower\b"]):
        return "Men should provide/succeed"
    if frame_label == "Male victimhood":
        return "Men are disadvantaged/victims"
    if frame_label == "Self-improvement / discipline":
        return "Men should improve themselves"
    if frame_label in {"Equality/accountability", "Protection of women/girls"}:
        return "Men should be equal partners"
    if has(text, [r"\blead", r"\bdominat", r"\bauthority", r"\bhead of"]):
        return "Men should dominate/lead"
    return "Mixed/unclear"


def evidence_type(text: str) -> str:
    if has(text, [r"\bI\b", r"\bmy\b", r"\bme\b", r"\bwe\b", r"\bour\b"]):
        return "Personal experience"
    if has(text, [r"\bGod\b", r"\bBible\b", r"\bfaith\b", r"\btradition\b", r"\bchurch\b"]):
        return "Religion/tradition"
    if has(text, [r"\b\d+%|\b\d+ percent\b|\bstatistic", r"\bresearch shows\b", r"\bstudies\b"]):
        return "Statistics"
    if has(text, [r"\bfor example\b", r"\beg\b", r"\bwhen\b.*\bthen\b"]):
        return "Anecdote"
    if has(text, [r"\blol\b", r"\blmao\b", r"\bdumb\b", r"\bsimp\b", r"\btoad\b", r"😂", r"🤣"]):
        return "Insult/mockery"
    if has(text, [r"\bmen\b", r"\bwomen\b", r"\bsociety\b", r"\bpeople\b", r"\balways\b", r"\bnever\b"]):
        return "Generalization"
    return "No support"


def confidence(score: int, text: str) -> str:
    words = len(norm(text).split())
    if score >= 3 or words > 45:
        return "High"
    if score >= 1 or words > 12:
        return "Medium"
    return "Low"


def sentiment(text: str, emo: str) -> str:
    positive = count_hits(text, [r"\bgood\b", r"\bgreat\b", r"\btrue\b", r"\bfacts\b", r"\bthank", r"\blove\b", r"\bhope\b", r"\bheal", r"\brespect\b", r"\bwell said\b", r"\bpowerful\b"])
    negative = count_hits(text, [r"\bwrong\b", r"\bsick\b", r"\btoxic\b", r"\bpain\b", r"\bhurt\b", r"\babuse", r"\bdisagree\b", r"\bdumb\b", r"\bproblem\b", r"\bfailed\b"])
    if positive > negative:
        return "Positive"
    if negative > positive:
        return "Negative"
    if positive and negative:
        return "Mixed"
    if emo in {"Hope/encouragement", "Pride/admiration", "Empathy/compassion"}:
        return "Positive"
    if emo in {"Anger", "Contempt/disgust", "Fear/anxiety", "Sadness"}:
        return "Negative"
    return "Neutral/unclear"


def themes(text: str, dataset_type: str) -> list[str]:
    candidates = []
    t, _, _ = topic(text)
    f, _, _ = frame(text)
    m, _, _ = misogyny(text)
    if f != "Mixed/unclear":
        candidates.append(f.lower().replace(" / ", " and "))
    if t != "Other":
        candidates.append(t.lower())
    if m != "None":
        candidates.append(m.lower())
    if not candidates:
        candidates = ["general audience reaction" if dataset_type == "comment" else "general masculinity claim"]
    deduped = []
    for item in candidates:
        if item not in deduped:
            deduped.append(item)
    return deduped[:3]


def main_claim(label: str, frame_label: str, narrative: str, text: str, dataset_type: str) -> str:
    if dataset_type == "comment":
        if label.startswith("Supports"):
            return f"The commenter endorses the original post's {frame_label.lower()} framing."
        if label.startswith("Opposes"):
            return f"The commenter challenges the original post's {frame_label.lower()} framing."
        if label.startswith("Mixed"):
            return f"The commenter partly qualifies or redirects the original post's {frame_label.lower()} framing."
        return "The comment gives a reaction whose claim is limited or unclear."
    if frame_label == "Mixed/unclear":
        return "The snippet makes a masculinity-related claim, but the main frame is mixed or implicit."
    return f"The snippet frames masculinity through {frame_label.lower()}, with the narrative: {narrative.lower()}."


def implied_solution(frame_label: str, narrative: str) -> str:
    mapping = {
        "Male victimhood": "Recognize men's disadvantage and reduce burdens placed on men.",
        "Female blame": "Change, avoid, or discipline women viewed as causing the problem.",
        "Traditional order / patriarchy": "Restore hierarchy, male authority, or conventional gender roles.",
        "Self-improvement / discipline": "Build discipline, status, purpose, or self-control.",
        "Provider-status pressure": "Become more economically successful or avoid low-status dependence.",
        "Sexual control / purity": "Control sexual behavior, avoid infidelity, or enforce sexual boundaries.",
        "Faith/morality": "Return to faith, morality, or tradition.",
        "Trauma/healing": "Speak openly, seek healing, and address emotional harm.",
        "Equality/accountability": "Practice mutual respect, reciprocity, and accountability.",
        "Protection of women/girls": "Prevent harm and protect women/girls.",
        "Anti-feminism / anti-modern woman": "Resist feminism, empowerment discourse, or 'modern woman' norms.",
    }
    if narrative == "Men should suppress emotions":
        return "Hide vulnerability and avoid emotional disclosure."
    return mapping.get(frame_label, "No clear solution offered.")


def target_group(text: str, frame_label: str) -> str:
    if frame_label in {"Female blame", "Anti-feminism / anti-modern woman"}:
        return "Women / modern women"
    if frame_label == "Male victimhood":
        return "Society / institutions / gender expectations"
    if frame_label == "Protection of women/girls":
        return "Men who harm women or girls"
    if has(text, [r"\bfather", r"\bparents?"]):
        return "Parents / fathers"
    if has(text, [r"\bmen\b"]):
        return "Men"
    if has(text, [r"\bwomen\b", r"\bwoman\b"]):
        return "Women"
    return "None/unclear"


def relation_to_message(text: str, stance: str, miso: str) -> str:
    if stance == "Opposes original post":
        return "rejects"
    if stance == "Mixed/qualified":
        return "softens"
    if stance == "Neutral/unclear":
        return "unclear"
    if miso != "None" or has(text, [r"\balways\b", r"\bnever\b", r"\bfuck more women\b", r"\bmust\b"]):
        return "intensifies"
    return "repeats"


def stance_for_comment(text: str, creator: str, frame_label: str) -> str:
    if creator == "Andrew Kibe":
        if has(text, [r"\bhappy with one\b", r"\bone (woman|girl)\b", r"\bdream car", r"\bcherish.*one\b", r"\bwomen are not (cars|objects|property|people)", r"\bnot.*multiple", r"\bmonogam"]):
            return "Opposes original post"
        if has(text, [r"\bdiversify\b", r"\bmore women\b", r"\bfuck more women\b", r"\bseduce\b", r"\bmultiple women\b", r"\bnot satisfied\b"]):
            return "Supports original post"
    if creator == "Eric Amunga / Amerix":
        if has(text, [r"\bmutual\b", r"\btwo[- ]?way\b", r"\breciproc", r"\bwomen can love\b", r"\ba woman can love\b", r"\blove is love\b", r"\bdisagree\b"]):
            return "Opposes original post"
        if has(text, [r"\ba woman can'?t love\b", r"\bwomen fantasize\b", r"\bmen fantasize\b", r"\btrue\b", r"\bfacts\b", r"\bagree\b"]):
            return "Supports original post"
    if creator in {"Onyango Otieno (Rixpoet)", "Eddy Kimani"}:
        if has(text, [r"\bdisagree\b", r"\bwrong\b", r"\bnot true\b", r"\bharmful\b"]):
            return "Opposes original post"
        if has(text, [r"\bthank you\b", r"\bpowerful\b", r"\btrue\b", r"\bfacts\b", r"\bheal", r"\bstory\b", r"\bsorry\b", r"\bempire\b", r"\bstay low\b", r"\bpeace\b", r"\bno one is coming\b", r"\bbuild\b"]):
            return "Supports original post"
    support = count_hits(text, [r"\btrue\b", r"\bfacts\b", r"\bagree\b", r"\bwell said\b", r"\bexactly\b", r"\bthank you\b", r"\bpowerful\b", r"\bthis is it\b", r"💯"])
    oppose = count_hits(text, [r"\bdisagree\b", r"\bwrong\b", r"\bnot true\b", r"\bbut\b", r"\bhowever\b", r"\bwomen are not\b", r"\bnot people\b", r"\btoxic\b", r"\bharmful\b"])
    if support > oppose:
        return "Supports original post"
    if oppose > support:
        return "Opposes original post"
    if support and oppose:
        return "Mixed/qualified"
    if len(norm(text).split()) <= 4 or has(text, [r"😂", r"🤣", r"\blol\b"]):
        return "Neutral/unclear"
    if creator in {"Onyango Otieno (Rixpoet)", "Eddy Kimani"} and frame_label in {"Trauma/healing", "Male victimhood", "Self-improvement / discipline", "Equality/accountability"}:
        return "Supports original post"
    if creator in {"Andrew Kibe", "Eric Amunga / Amerix"} and frame_label in {"Female blame", "Provider-status pressure", "Traditional order / patriarchy", "Self-improvement / discipline"}:
        return "Supports original post"
    return "Neutral/unclear"


def perceived_impact(text: str, stance: str, frame_label: str, miso: str) -> str:
    if has(text, [r"\bhelp(ed|s)? me\b", r"\bthank you\b", r"\bheal", r"\bneeded this\b"]):
        return "this helped me / healing or learning"
    if stance == "Supports original post" and has(text, [r"\btrue\b", r"\bfacts\b", r"\bagree\b"]):
        return "this is true / validates the message"
    if stance == "Opposes original post":
        return "this is harmful or wrong"
    if miso != "None" or frame_label == "Female blame":
        return "women are the problem"
    if frame_label == "Trauma/healing":
        return "men need healing / emotional safety"
    return "unclear or low-specificity impact"


def code_snippet(row: dict) -> dict:
    text = norm(f"{row.get('context', '')} {row.get('text', '')}")
    t, t_score, t_patterns = topic(text)
    f, f_score, f_patterns = frame(text)
    m_label, m_score, m_patterns = misogyny(text)
    e_label, e_score, e_patterns = emotion(text)
    narrative = masculinity_narrative(text, f)
    conf = confidence(max(t_score, f_score, m_score, e_score), text)
    ev_patterns = f_patterns or t_patterns or m_patterns or e_patterns
    claim = main_claim("", f, narrative, text, "snippet")
    solution = implied_solution(f, narrative)
    th = themes(text, "snippet")
    return {
        "pass1": {
            "row_id": row["item_id"],
            "influencer": row["influencer"],
            "orientation": row["orientation"],
            "platform": row["platform"],
            "text_for_coding": row["text"],
            "theme_label_1": th[0],
            "theme_label_2": th[1] if len(th) > 1 else "",
            "theme_label_3": th[2] if len(th) > 2 else "",
            "one_sentence_explanation": f"The creator message centers on {th[0]} with supporting language from the snippet/context.",
            "key_quote": evidence(row["text"], ev_patterns),
            "creator_or_audience": "creator framing",
            "confidence": conf,
            "ambiguity_note": "" if conf != "Low" else "Short or indirect text limits the coding certainty.",
        },
        "pass2": {
            "item_id": row["item_id"],
            "influencer": row["influencer"],
            "orientation": row["orientation"],
            "platform": row["platform"],
            "text_for_coding": f"{row.get('context','')}\n\nTEXT: {row['text']}",
            "topic": t,
            "masculinity_narrative": narrative,
            "frame": f,
            "main_claim": claim,
            "reason_justification": "The coding is based on repeated wording and context cues in the snippet." if conf != "Low" else "The text gives limited explicit reasoning.",
            "evidence_type": evidence_type(text),
            "implied_solution": solution,
            "target_blamed_group": target_group(text, f),
            "misogyny_sexism": m_label,
            "emotion": e_label,
            "proposed_problem": f if f != "Mixed/unclear" else "Unclear or mixed masculinity problem",
            "proposed_solution": solution,
            "evidence_phrase": evidence(row["text"], ev_patterns),
            "confidence": conf,
            "short_justification": f"Label selected because the snippet contains evidence of {f.lower() if f != 'Mixed/unclear' else t.lower()}.",
            "ambiguity_note": "" if conf != "Low" else "Limited or highly contextual snippet.",
        },
    }


def code_comment(row: dict) -> dict:
    text = norm(row["comment"])
    t, t_score, t_patterns = topic(text)
    f, f_score, f_patterns = frame(text)
    m_label, m_score, m_patterns = misogyny(text)
    e_label, e_score, e_patterns = emotion(text)
    stance = stance_for_comment(text, row["influencer"], f)
    rel = relation_to_message(text, stance, m_label)
    conf = confidence(max(t_score, f_score, m_score, e_score, count_hits(text, [r"\btrue\b", r"\bagree\b", r"\bdisagree\b", r"\bwrong\b"])), text)
    ev_patterns = m_patterns or f_patterns or t_patterns or e_patterns
    claim = main_claim(stance, f, "", text, "comment")
    th = themes(text, "comment")
    sent = sentiment(text, e_label)
    return {
        "pass1": {
            "row_id": row["comment_id"],
            "influencer": row["influencer"],
            "orientation": row["orientation"],
            "platform": row["platform"],
            "text_for_coding": f"{row['target_original_post']}\n\nCOMMENT: {row['comment']}",
            "theme_label_1": th[0],
            "theme_label_2": th[1] if len(th) > 1 else "",
            "theme_label_3": th[2] if len(th) > 2 else "",
            "one_sentence_explanation": f"The comment reads as audience uptake around {th[0]}.",
            "key_quote": evidence(text, ev_patterns),
            "creator_or_audience": "audience uptake",
            "confidence": conf,
            "ambiguity_note": "" if conf != "Low" else "Short, humorous, or low-context comment limits certainty.",
        },
        "pass2": {
            "comment_id": row["comment_id"],
            "influencer": row["influencer"],
            "orientation": row["orientation"],
            "platform": row["platform"],
            "target_original_post": row["target_original_post"],
            "comment": row["comment"],
            "stance_to_original_post": stance,
            "sentiment": sent,
            "emotion": e_label,
            "relation_to_original_message": rel,
            "commenter_frame": f,
            "misogyny_sexism": m_label,
            "perceived_impact": perceived_impact(text, stance, f, m_label),
            "main_claim": claim,
            "reason_justification": "The comment provides explicit audience uptake language." if conf != "Low" else "The comment gives little explicit reasoning.",
            "evidence_type": evidence_type(text),
            "implied_solution": implied_solution(f, ""),
            "target_blamed_group": target_group(text, f),
            "evidence_phrase": evidence(text, ev_patterns),
            "confidence": conf,
            "short_justification": f"Stance and frame are inferred from the comment's wording toward the supplied target post.",
            "ambiguity_note": "" if conf != "Low" else "Low-substance or ambiguous stance.",
        },
    }


def table_counts(rows: list[dict], *fields: str) -> list[list[object]]:
    counts = Counter(tuple(r[f] for f in fields) for r in rows)
    header = [*fields, "count"]
    return [header] + [[*key, val] for key, val in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def creator_counts(rows: list[dict], field: str, id_field: str) -> list[list[object]]:
    nested: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        nested[row["influencer"]][row[field]] += 1
    labels = sorted({label for counter in nested.values() for label in counter})
    out = [["Influencer", "Rows", *labels]]
    for creator in sorted(nested):
        total = sum(nested[creator].values())
        out.append([creator, total, *[nested[creator][label] for label in labels]])
    return out


def main() -> None:
    data = json.loads(IN_JSON.read_text(encoding="utf-8"))
    snippet_coded = [code_snippet(r) for r in data["snippets"]]
    comment_coded = [code_comment(r) for r in data["comments"]]
    snippet_pass1 = [r["pass1"] for r in snippet_coded]
    snippet_pass2 = [r["pass2"] for r in snippet_coded]
    comment_pass1 = [r["pass1"] for r in comment_coded]
    comment_pass2 = [r["pass2"] for r in comment_coded]
    data["coded"] = {
        "snippet_pass1": snippet_pass1,
        "snippet_pass2": snippet_pass2,
        "comment_pass1": comment_pass1,
        "comment_pass2": comment_pass2,
        "summary": {
            "snippet_topics": table_counts(snippet_pass2, "topic"),
            "snippet_frames": table_counts(snippet_pass2, "frame"),
            "snippet_masculinity": table_counts(snippet_pass2, "masculinity_narrative"),
            "snippet_misogyny": table_counts(snippet_pass2, "misogyny_sexism"),
            "comment_stance": table_counts(comment_pass2, "stance_to_original_post"),
            "comment_relation": table_counts(comment_pass2, "relation_to_original_message"),
            "comment_frames": table_counts(comment_pass2, "commenter_frame"),
            "comment_misogyny": table_counts(comment_pass2, "misogyny_sexism"),
            "comment_emotion": table_counts(comment_pass2, "emotion"),
            "snippet_frame_by_creator": creator_counts(snippet_pass2, "frame", "item_id"),
            "comment_stance_by_creator": creator_counts(comment_pass2, "stance_to_original_post", "comment_id"),
        },
    }
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUT_JSON)


if __name__ == "__main__":
    main()

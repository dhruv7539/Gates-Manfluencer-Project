import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const OUT_DIR = "/Users/dhruvbhanderi/Documents/USC/New Research Engineer/Codex/outputs/kenya_two_pass_llm_workflow";
const DATA_PATH = path.join(OUT_DIR, "kenya_two_pass_llm_coded_data.json");
const OUTPUT_PATH = path.join(OUT_DIR, "Kenya - LLM Coded Two Pass Analysis.xlsx");

const data = JSON.parse(await fs.readFile(DATA_PATH, "utf8"));
const workbook = Workbook.create();

function colLetter(n) {
  let s = "";
  while (n > 0) {
    const m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - m) / 26);
  }
  return s;
}

function rangeAddress(startRow, startCol, rows, cols) {
  return `${colLetter(startCol)}${startRow}:${colLetter(startCol + cols - 1)}${startRow + rows - 1}`;
}

function writeMatrix(sheet, startRow, startCol, matrix) {
  if (!matrix.length || !matrix[0].length) return;
  sheet.getRange(rangeAddress(startRow, startCol, matrix.length, matrix[0].length)).values = matrix;
}

function styleTitle(range) {
  range.format = {
    fill: "#12343B",
    font: { name: "Calibri", size: 16, color: "#FFFFFF", bold: true },
    verticalAlignment: "center",
    wrapText: true,
  };
}

function styleNote(range) {
  range.format = {
    fill: "#F4F6F8",
    font: { name: "Calibri", size: 10, color: "#344054", italic: true },
    verticalAlignment: "top",
    wrapText: true,
  };
}

function styleHeader(range, fill = "#2E6F7E") {
  range.format = {
    fill,
    font: { name: "Calibri", size: 10, color: "#FFFFFF", bold: true },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#C7D7DE" },
  };
}

function styleBody(range) {
  range.format = {
    font: { name: "Calibri", size: 10, color: "#1F2937" },
    verticalAlignment: "top",
    wrapText: true,
    borders: { preset: "inside", style: "thin", color: "#E5E7EB" },
  };
}

function setWidths(sheet, widths) {
  for (const [col, px] of Object.entries(widths)) {
    sheet.getRange(`${col}:${col}`).format.columnWidthPx = px;
  }
}

function addBasicSheet(name, title, note, headers, rows, widths, freezeRows = 1) {
  const sheet = workbook.worksheets.add(name);
  sheet.getRange("A1").values = [[title]];
  styleTitle(sheet.getRange(rangeAddress(1, 1, 1, Math.max(headers.length, 8))));
  if (note) {
    sheet.getRange("A2").values = [[note]];
    styleNote(sheet.getRange(rangeAddress(2, 1, 1, Math.max(headers.length, 8))));
  }
  writeMatrix(sheet, 4, 1, [headers, ...rows]);
  styleHeader(sheet.getRange(rangeAddress(4, 1, 1, headers.length)));
  if (rows.length) styleBody(sheet.getRange(rangeAddress(5, 1, rows.length, headers.length)));
  setWidths(sheet, widths);
  sheet.freezePanes.freezeRows(freezeRows + 3);
  return sheet;
}

const codebookRows = [
  ["Topic", "Dating/marriage", "Romantic relationships, spouse selection, marriage, loyalty, infidelity, monogamy, divorce."],
  ["Topic", "Family/children", "Fatherhood, parenting, children, family authority, intergenerational responsibility."],
  ["Topic", "Money/status", "Provision, class, work, wealth, rent, bills, status, success, provider identity."],
  ["Topic", "Fitness/self-improvement", "Discipline, health, body, self-mastery, confidence, routines."],
  ["Topic", "Mental health", "Emotion, trauma, therapy, vulnerability, depression, healing, emotional safety."],
  ["Topic", "Gender equality", "Reciprocity, partnership, equality, accountability across genders."],
  ["Topic", "Religion/morality", "God, faith, morality, sin, tradition, spiritual authority."],
  ["Topic", "Violence/GBV", "Violence, abuse, sexual violence, protection of women/girls, safety."],
  ["Topic", "Politics/social problems", "Institutions, economy, feminism as social change, law, public problems."],
  ["Topic", "Other", "Use only when no listed topic fits."],
  ["Masculinity narrative", "Men should dominate/lead", "Men are framed as rightful authorities, leaders, controllers, or decision-makers."],
  ["Masculinity narrative", "Men should provide/succeed", "Masculinity depends on earning, provision, status, success, or competence."],
  ["Masculinity narrative", "Men are disadvantaged/victims", "Men are framed as harmed by women, feminism, institutions, or social expectations."],
  ["Masculinity narrative", "Men should improve themselves", "Men should build discipline, skill, purpose, health, or status."],
  ["Masculinity narrative", "Men should be emotionally open", "Men should speak, heal, disclose, seek care, or reject silence."],
  ["Masculinity narrative", "Men should suppress emotions", "Men should avoid vulnerability, hide pain, be stoic, or not disclose problems."],
  ["Masculinity narrative", "Men should be equal partners", "Men are framed as accountable, reciprocal, caring, collaborative partners."],
  ["Masculinity narrative", "Women should submit", "Women are framed as obligated to obey, defer, respect, or be controlled by men."],
  ["Masculinity narrative", "Mixed/unclear", "Use when multiple narratives are present or the text is too ambiguous."],
  ["Frame", "Male victimhood", "Men's harms, losses, or unfair treatment are the organizing problem."],
  ["Frame", "Female blame", "Women or girls are named as the main cause of men's problems or social decline."],
  ["Frame", "Traditional order / patriarchy", "Return to hierarchy, male authority, or conventional gender roles."],
  ["Frame", "Self-improvement / discipline", "Personal discipline, routines, growth, and self-control are the main solution."],
  ["Frame", "Provider-status pressure", "Manhood is organized around money, work, provision, or status anxiety."],
  ["Frame", "Sexual control / purity", "Sexual discipline, purity, body count, cheating, control, or sexual access."],
  ["Frame", "Faith/morality", "Religious or moral authority frames the claim."],
  ["Frame", "Trauma/healing", "Pain, recovery, therapy, vulnerability, or healing is central."],
  ["Frame", "Equality/accountability", "Mutual respect, equality, responsibility, or critique of harmful male behavior."],
  ["Frame", "Protection of women/girls", "Women/girls' safety, GBV prevention, or care is foregrounded."],
  ["Frame", "Anti-feminism / anti-modern woman", "Feminism, empowerment, or modern women are framed as the problem."],
  ["Frame", "Mixed/unclear", "Use when the organizing frame cannot be determined."],
  ["Comment stance", "Supports original post", "Comment endorses, agrees with, validates, or extends the target post."],
  ["Comment stance", "Opposes original post", "Comment rejects, critiques, challenges, or fact-checks the target post."],
  ["Comment stance", "Mixed/qualified", "Comment partly agrees and partly disagrees, or adds conditions/limits."],
  ["Comment stance", "Neutral/unclear", "Comment is relevant but stance toward the target is unclear."],
  ["Comment stance", "Irrelevant", "Comment is unrelated, spam-like, or impossible to connect to the target."],
  ["Evidence type", "Personal experience", "Uses first-person testimony or lived experience."],
  ["Evidence type", "Generalization", "Uses broad claims about men, women, society, or culture without specific evidence."],
  ["Evidence type", "Religion/tradition", "Uses religious, moral, or traditional authority."],
  ["Evidence type", "Statistics", "Uses numerical/statistical evidence."],
  ["Evidence type", "Anecdote", "Uses a story or example not clearly first-person."],
  ["Evidence type", "Insult/mockery", "Relies mainly on ridicule, insult, sarcasm, or derision."],
  ["Evidence type", "No support", "Makes a claim without a reason or evidence."],
  ["Misogyny/sexism", "None", "No sexist or misogynistic content detected."],
  ["Misogyny/sexism", "Stereotyping", "Broad essentialist claims about women or gender roles."],
  ["Misogyny/sexism", "Female blame", "Women are blamed for men's problems or social decline."],
  ["Misogyny/sexism", "Objectification/sexualization", "Women are reduced to bodies, sexual access, possessions, or analogies."],
  ["Misogyny/sexism", "Hostility/insult toward women", "Insults, contempt, degradation, or antagonism toward women."],
  ["Misogyny/sexism", "Justification of control/submission", "Endorses controlling women or women's obedience/submission."],
  ["Misogyny/sexism", "Sexual violence minimization or endorsement", "Minimizes, excuses, jokes about, or endorses sexual violence."],
  ["Misogyny/sexism", "Anti-feminist hostility", "Hostility toward feminism, women's empowerment, or modern women as a class."],
  ["Misogyny/sexism", "Ambiguous/context-dependent", "Potentially sexist but context or target is unclear."],
  ["Emotion", "Anger", "Irritation, outrage, blame, grievance."],
  ["Emotion", "Contempt/disgust", "Disdain, moral disgust, superiority, dehumanizing contempt."],
  ["Emotion", "Fear/anxiety", "Worry, threat, uncertainty, insecurity."],
  ["Emotion", "Sadness", "Pain, loss, grief, despair."],
  ["Emotion", "Hope/encouragement", "Encouragement, improvement, healing, optimism."],
  ["Emotion", "Pride/admiration", "Admiration, validation, pride, respect."],
  ["Emotion", "Humor/mockery", "Jokes, sarcasm, ridicule."],
  ["Emotion", "Empathy/compassion", "Care, sympathy, solidarity, concern."],
  ["Emotion", "Neutral/unclear", "No clear emotional signal."],
];

const promptRows = [
  ["Pass 1 - snippets", "Goal", "Inductively identify open-ended themes in the influencer's message only. Do not code audience reception."],
  ["Pass 1 - snippets", "Prompt", "You are coding creator content about masculinity in Kenya. Read the snippet, context, platform, and influencer metadata. Return JSON with 1-3 short theme labels, one-sentence explanation, exact key quote from the text, creator_or_audience='creator framing', confidence high/medium/low, and ambiguity_note. Do not force predefined categories."],
  ["Pass 1 - comments", "Goal", "Inductively identify open-ended themes in the audience response only, with stance target defined as the original post."],
  ["Pass 1 - comments", "Prompt", "You are coding audience comments responding to an original post about masculinity in Kenya. The target is the provided original_post_target. Return JSON with 1-3 short theme labels, one-sentence explanation, exact key quote from the comment, creator_or_audience='audience uptake', confidence high/medium/low, and ambiguity_note. Do not infer stance unless the comment indicates it."],
  ["Pass 2 - snippets", "Goal", "Deductively code the influencer's message using the fixed codebook and evidence-first outputs."],
  ["Pass 2 - snippets", "Prompt", "Using only the snippet text and context, code: topic, masculinity_narrative, frame, main_claim, reason_justification, evidence_type, implied_solution, target_blamed_group, misogyny_sexism, emotion, proposed_problem, proposed_solution. For every label include confidence, short justification, exact evidence phrase, and ambiguity note. Use Mixed/unclear when evidence is insufficient."],
  ["Pass 2 - comments", "Goal", "Deductively code audience reception, including stance toward the original post as explicit target."],
  ["Pass 2 - comments", "Prompt", "Target for stance is original_post_target. Code: stance_to_original_post, relation_to_original_message (repeats/intensifies/softens/rejects/mixed/unclear), commenter_frame, misogyny_sexism, perceived_impact, emotion, sentiment, main_claim, reason_justification, evidence_type, implied_solution, target_blamed_group. For every label include confidence, short justification, exact evidence phrase, and ambiguity note."],
  ["Evidence rule", "Required", "Every coded row must include an exact evidence phrase from the row text. If no evidence supports a label, choose Neutral/unclear or Mixed/unclear and explain the ambiguity."],
  ["Comparison rule", "Required", "Use 'in this selected sample' and creator-specific language. Do not claim population-level Kenya/Nigeria differences from these non-symmetrical samples."],
];

const validationPlanRows = [
  ["Step", "Recommendation", "Reason"],
  ["Full LLM pass", "Run both passes on all snippet and comment rows separately.", "Produces auditable row-level labels while preserving creator/audience distinction."],
  ["Human coding", "Use the existing balanced 200-row snippet sample and 200-row audience sample, or downsample to 160-240 total if coder labor is limited.", "Keeps validation meaningful without requiring full human coding."],
  ["Balance checks", "Balance across country, influencer, orientation, comments/snippets, platform, and high/low LLM confidence.", "Avoids validating only easy or dominant cases."],
  ["Reliability", "Calculate human-human reliability and LLM-human agreement separately by variable.", "Some variables are more reliable than others."],
  ["Quantitative claims", "Prioritize relevance, stance, topic, sentiment, explicit misogyny/sexism, and masculinity narrative.", "These should be more stable for counts and comparisons."],
  ["Qualitative claims", "Use framing, emotion, argument mining, implied ideology, sarcasm/humor as exploratory support.", "These are higher-ambiguity variables."],
];

function addSummary() {
  const sheet = workbook.worksheets.add("README");
  sheet.getRange("A1").values = [["Kenya LLM-Coded Two-Pass Analysis"]];
  styleTitle(sheet.getRange("A1:H1"));
  sheet.getRange("A2").values = [["Purpose: row-level LLM coding for separate creator-content and audience-comment datasets, with exploratory Pass 1, structured Pass 2, evidence quotes, confidence, and human-validation hooks."]];
  styleNote(sheet.getRange("A2:H2"));
  writeMatrix(sheet, 4, 1, data.overview);
  styleHeader(sheet.getRange("A4:D4"));
  styleBody(sheet.getRange(`A5:D${3 + data.overview.length}`));
  writeMatrix(sheet, 10, 1, data.snippet_counts);
  styleHeader(sheet.getRange("A10:E10"));
  styleBody(sheet.getRange(`A11:E${9 + data.snippet_counts.length}`));
  writeMatrix(sheet, 10, 7, data.comment_counts);
  styleHeader(sheet.getRange("G10:K10"));
  styleBody(sheet.getRange(`G11:K${9 + data.comment_counts.length}`));
  writeMatrix(sheet, 18, 1, data.validation_summary);
  styleHeader(sheet.getRange("A18:D18"), "#5B4B2A");
  styleBody(sheet.getRange(`A19:D${17 + data.validation_summary.length}`));
  if (data.coded?.summary) {
    writeMatrix(sheet, 25, 1, data.coded.summary.snippet_topics);
    styleHeader(sheet.getRange("A25:B25"), "#42526E");
    styleBody(sheet.getRange(`A26:B${24 + data.coded.summary.snippet_topics.length}`));

    writeMatrix(sheet, 25, 4, data.coded.summary.snippet_frames);
    styleHeader(sheet.getRange("D25:E25"), "#42526E");
    styleBody(sheet.getRange(`D26:E${24 + data.coded.summary.snippet_frames.length}`));

    writeMatrix(sheet, 25, 7, data.coded.summary.comment_stance);
    styleHeader(sheet.getRange("G25:H25"), "#42526E");
    styleBody(sheet.getRange(`G26:H${24 + data.coded.summary.comment_stance.length}`));

    writeMatrix(sheet, 25, 10, data.coded.summary.comment_relation);
    styleHeader(sheet.getRange("J25:K25"), "#42526E");
    styleBody(sheet.getRange(`J26:K${24 + data.coded.summary.comment_relation.length}`));
  }
  setWidths(sheet, { A: 220, B: 110, C: 160, D: 520, E: 120, F: 40, G: 220, H: 110, I: 160, J: 520, K: 120 });
  sheet.freezePanes.freezeRows(4);
}

function addSourceSheets() {
  addBasicSheet(
    "Snippets_Source",
    "Creator Snippet Source Rows",
    "Use these rows for creator-message coding only. Comments should not be coded in this logic.",
    ["item_id", "country", "influencer", "orientation", "platform", "content_type", "source_url", "context", "text", "word_count", "original_sheet", "original_row"],
    data.snippets.map((r) => [r.item_id, r.country, r.influencer, r.orientation, r.platform, r.content_type, r.source_url, r.context, r.text, r.word_count, r.original_sheet, r.original_row]),
    { A: 150, B: 80, C: 210, D: 100, E: 190, F: 160, G: 240, H: 420, I: 620, J: 85, K: 180, L: 85 }
  );
  addBasicSheet(
    "Comments_Source",
    "Audience Comment Source Rows",
    "Use these rows for audience-response coding only. Stance target is the original_post_target field.",
    ["comment_id", "country", "influencer", "orientation", "platform", "source_url", "target_original_post", "comment", "word_count", "original_sheet", "original_row"],
    data.comments.map((r) => [r.comment_id, r.country, r.influencer, r.orientation, r.platform, r.source_url, r.target_original_post, r.comment, r.word_count, r.original_sheet, r.original_row]),
    { A: 165, B: 80, C: 210, D: 100, E: 110, F: 260, G: 470, H: 620, I: 85, J: 190, K: 85 }
  );
}

function addPassSheets() {
  const pass1Headers = ["row_id", "influencer", "orientation", "platform", "text_for_coding", "theme_label_1", "theme_label_2", "theme_label_3", "one_sentence_explanation", "key_quote", "creator_or_audience", "confidence", "ambiguity_note"];
  const snippetPass1Rows = data.coded?.snippet_pass1
    ? data.coded.snippet_pass1.map((r) => pass1Headers.map((h) => r[h] ?? ""))
    : data.snippets.map((r) => [r.item_id, r.influencer, r.orientation, r.platform, r.text, "", "", "", "", "", "creator framing", "", ""]);
  addBasicSheet(
    "Snippets_Pass1_Open",
    "Pass 1 Open Coding - Snippets",
    "Inductive themes for influencer message; do not force the fixed codebook in this pass.",
    pass1Headers,
    snippetPass1Rows,
    { A: 150, B: 210, C: 105, D: 150, E: 560, F: 170, G: 170, H: 170, I: 350, J: 320, K: 150, L: 100, M: 280 }
  );
  const commentPass1Rows = data.coded?.comment_pass1
    ? data.coded.comment_pass1.map((r) => pass1Headers.map((h) => r[h] ?? ""))
    : data.comments.map((r) => [r.comment_id, r.influencer, r.orientation, r.platform, `${r.target_original_post}\n\nCOMMENT: ${r.comment}`, "", "", "", "", "", "audience uptake", "", ""]);
  addBasicSheet(
    "Comments_Pass1_Open",
    "Pass 1 Open Coding - Comments",
    "Inductive themes for audience uptake; stance target is the original post/source content.",
    pass1Headers,
    commentPass1Rows,
    { A: 165, B: 210, C: 105, D: 120, E: 650, F: 170, G: 170, H: 170, I: 350, J: 320, K: 150, L: 100, M: 280 }
  );

  const snippetPass2Headers = ["item_id", "influencer", "orientation", "platform", "text_for_coding", "topic", "masculinity_narrative", "frame", "main_claim", "reason_justification", "evidence_type", "implied_solution", "target_blamed_group", "misogyny_sexism", "emotion", "proposed_problem", "proposed_solution", "evidence_phrase", "confidence", "short_justification", "ambiguity_note"];
  const snippetPass2Rows = data.coded?.snippet_pass2
    ? data.coded.snippet_pass2.map((r) => snippetPass2Headers.map((h) => r[h] ?? ""))
    : data.snippets.map((r) => [r.item_id, r.influencer, r.orientation, r.platform, `${r.context}\n\nTEXT: ${r.text}`, "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]);
  addBasicSheet(
    "Snippets_Pass2_Structured",
    "Pass 2 Structured Coding - Snippets",
    "Deductive creator-message fields for counts and comparison. Require evidence phrase and confidence.",
    snippetPass2Headers,
    snippetPass2Rows,
    { A: 150, B: 210, C: 105, D: 150, E: 650, F: 160, G: 220, H: 220, I: 320, J: 320, K: 150, L: 220, M: 200, N: 240, O: 170, P: 260, Q: 260, R: 320, S: 100, T: 330, U: 280 }
  );

  const commentPass2Headers = ["comment_id", "influencer", "orientation", "platform", "target_original_post", "comment", "stance_to_original_post", "sentiment", "emotion", "relation_to_original_message", "commenter_frame", "misogyny_sexism", "perceived_impact", "main_claim", "reason_justification", "evidence_type", "implied_solution", "target_blamed_group", "evidence_phrase", "confidence", "short_justification", "ambiguity_note"];
  const commentPass2Rows = data.coded?.comment_pass2
    ? data.coded.comment_pass2.map((r) => commentPass2Headers.map((h) => r[h] ?? ""))
    : data.comments.map((r) => [r.comment_id, r.influencer, r.orientation, r.platform, r.target_original_post, r.comment, "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]);
  addBasicSheet(
    "Comments_Pass2_Structured",
    "Pass 2 Structured Coding - Comments",
    "Deductive audience-reception fields. Stance always targets the original post, not the general topic.",
    commentPass2Headers,
    commentPass2Rows,
    { A: 165, B: 210, C: 105, D: 120, E: 470, F: 620, G: 180, H: 120, I: 170, J: 220, K: 220, L: 240, M: 260, N: 320, O: 320, P: 150, Q: 220, R: 200, S: 320, T: 100, U: 330, V: 280 }
  );
}

function addReferenceSheets() {
  addBasicSheet(
    "Codebook",
    "Fixed Codebook",
    "Use these labels in Pass 2. Keep misogyny/sexism separate from general toxicity.",
    ["Field", "Label", "Definition / coding note"],
    codebookRows,
    { A: 190, B: 270, C: 700 }
  );
  addBasicSheet(
    "Prompt_Templates",
    "Two-Pass Prompt Templates",
    "Paste row metadata and text into these prompts, or use them as the system/developer prompt in a batch LLM script.",
    ["Prompt", "Part", "Text"],
    promptRows,
    { A: 170, B: 150, C: 950 }
  );
  addBasicSheet(
    "Validation_Plan",
    "Human Validation Plan",
    "This sheet reflects the validation design: use human labels to audit LLM outputs, not as an afterthought.",
    ["Step", "Recommendation", "Reason"],
    validationPlanRows,
    { A: 180, B: 520, C: 520 }
  );
  addBasicSheet(
    "Validation_Index",
    "Existing Human-Coding Subset Index",
    "Rows already selected for human coding in the existing balanced Top 200 files.",
    ["dataset_type", "item_id", "comment_id", "influencer", "orientation", "platform", "coder", "source_file", "sample_design", "text"],
    data.validation_index.map((r) => [r.dataset_type, r.item_id, r.comment_id, r.influencer, r.orientation, r.platform, r.coder, r.source_file, r.overlap_design, r.text]),
    { A: 110, B: 150, C: 165, D: 210, E: 105, F: 160, G: 100, H: 390, I: 280, J: 650 }
  );
  addBasicSheet(
    "LLM_Run_Log",
    "LLM Run Log",
    "Fill this out whenever a batch is coded so model outputs remain auditable.",
    ["run_id", "date", "dataset", "pass", "model", "temperature", "prompt_version", "rows_coded", "operator", "notes"],
    [["", "", "", "", "", "", "", "", "", ""]],
    { A: 120, B: 110, C: 120, D: 90, E: 160, F: 110, G: 140, H: 110, I: 160, J: 520 }
  );
}

addSummary();
addSourceSheets();
addPassSheets();
addReferenceSheets();

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

for (const sheetName of ["README", "Codebook", "Snippets_Pass2_Structured", "Comments_Pass2_Structured", "Validation_Index"]) {
  const rendered = await workbook.render({ sheetName, range: "A1:H28", scale: 1 });
  console.log(`rendered ${sheetName}: ${rendered.size ?? "ok"}`);
}

await fs.mkdir(OUT_DIR, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(OUTPUT_PATH);
console.log(OUTPUT_PATH);

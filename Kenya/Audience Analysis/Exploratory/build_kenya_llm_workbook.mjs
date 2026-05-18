import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const DATA_PATH =
  "/Users/dhruvbhanderi/Documents/USC/New Research Engineer/Codex/outputs/kenya_llm_exploratory/kenya_audience_llm_analysis.json";
const OUTPUT_PATH =
  "/Users/dhruvbhanderi/Documents/USC/New Research Engineer/Codex/outputs/kenya_llm_exploratory/Kenya - Audience LLM Exploratory Data Analyses.xlsx";

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
  const endRow = startRow + rows - 1;
  const endCol = startCol + cols - 1;
  return `${colLetter(startCol)}${startRow}:${colLetter(endCol)}${endRow}`;
}

function writeMatrix(sheet, startRow, startCol, matrix) {
  if (!matrix.length || !matrix[0].length) return;
  sheet.getRange(rangeAddress(startRow, startCol, matrix.length, matrix[0].length)).values = matrix;
}

function styleTitle(range) {
  range.format = {
    fill: "#EAF4EF",
    font: { name: "Calibri", size: 16, color: "#163A2A", bold: true },
    verticalAlignment: "center",
    wrapText: true,
  };
}

function styleSubtitle(range) {
  range.format = {
    font: { name: "Calibri", size: 10, color: "#52616B", italic: true },
    verticalAlignment: "top",
    wrapText: true,
  };
}

function styleHeader(range, fill = "#214E5F") {
  range.format = {
    fill,
    font: { name: "Calibri", size: 10, color: "#FFFFFF", bold: true },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#C9D7DD" },
  };
}

function styleBody(range) {
  range.format = {
    font: { name: "Calibri", size: 10, color: "#1F2933" },
    verticalAlignment: "top",
    wrapText: true,
    borders: { preset: "inside", style: "thin", color: "#E4EAEE" },
  };
}

function styleSectionLabel(range) {
  range.format = {
    fill: "#F3F0E7",
    font: { name: "Calibri", size: 11, color: "#3F3424", bold: true },
    verticalAlignment: "center",
  };
}

function setWidths(sheet, widths) {
  for (const [col, px] of Object.entries(widths)) {
    sheet.getRange(`${col}:${col}`).format.columnWidthPx = px;
  }
}

function addSummary() {
  const sheet = workbook.worksheets.add("Summary");
  sheet.getRange("A1").values = [["Kenya - Audience LLM Exploratory Data Analyses"]];
  styleTitle(sheet.getRange("A1:H1"));
  sheet.getRange("A2").values = [[
    "Norman Lear Center x Gates Foundation | Exploratory coding from uploaded Kenya audience workbook",
  ]];
  styleSubtitle(sheet.getRange("A2:H2"));

  writeMatrix(sheet, 4, 1, data.summary.overview);
  styleHeader(sheet.getRange("A4:B4"));
  styleBody(sheet.getRange(`A5:B${3 + data.summary.overview.length}`));

  sheet.getRange("D4").values = [["Key takeaways"]];
  styleSectionLabel(sheet.getRange("D4:H4"));
  writeMatrix(sheet, 5, 4, data.summary.key_takeaways);
  styleHeader(sheet.getRange("D5:E5"));
  styleBody(sheet.getRange(`D6:E${4 + data.summary.key_takeaways.length}`));

  writeMatrix(sheet, 14, 1, data.summary.sentiment);
  styleHeader(sheet.getRange("A14:C14"));
  styleBody(sheet.getRange(`A15:C${13 + data.summary.sentiment.length}`));

  writeMatrix(sheet, 14, 5, data.summary.audience_response);
  styleHeader(sheet.getRange("E14:G14"));
  styleBody(sheet.getRange(`E15:G${13 + data.summary.audience_response.length}`));

  writeMatrix(sheet, 23, 1, data.summary.women_portrayal);
  styleHeader(sheet.getRange("A23:C23"));
  styleBody(sheet.getRange(`A24:C${22 + data.summary.women_portrayal.length}`));

  writeMatrix(sheet, 23, 5, data.summary.sentiment_by_creator);
  const sentRows = data.summary.sentiment_by_creator.length;
  const sentCols = data.summary.sentiment_by_creator[0].length;
  styleHeader(sheet.getRange(rangeAddress(23, 5, 1, sentCols)));
  styleBody(sheet.getRange(rangeAddress(24, 5, sentRows - 1, sentCols)));

  setWidths(sheet, {
    A: 170,
    B: 145,
    C: 100,
    D: 50,
    E: 520,
    F: 100,
    G: 100,
    H: 100,
  });
  sheet.freezePanes.freezeRows(4);
}

function addCreatorSummary() {
  const sheet = workbook.worksheets.add("Creator Summary");
  sheet.getRange("A1").values = [["Creator Summary"]];
  styleTitle(sheet.getRange("A1:K1"));
  writeMatrix(sheet, 3, 1, data.summary.creator_summary);
  const rows = data.summary.creator_summary.length;
  const cols = data.summary.creator_summary[0].length;
  styleHeader(sheet.getRange(rangeAddress(3, 1, 1, cols)));
  styleBody(sheet.getRange(rangeAddress(4, 1, rows - 1, cols)));
  setWidths(sheet, {
    A: 210,
    B: 210,
    C: 100,
    D: 85,
    E: 80,
    F: 80,
    G: 105,
    H: 260,
    I: 260,
    J: 90,
    K: 90,
  });
  sheet.freezePanes.freezeRows(3);
}

function addThemeSummary() {
  const sheet = workbook.worksheets.add("Theme Summary");
  sheet.getRange("A1").values = [["Controlled Theme Summary"]];
  styleTitle(sheet.getRange("A1:G1"));
  writeMatrix(sheet, 3, 1, data.summary.theme_summary);
  const rows = data.summary.theme_summary.length;
  const cols = data.summary.theme_summary[0].length;
  styleHeader(sheet.getRange(rangeAddress(3, 1, 1, cols)));
  styleBody(sheet.getRange(rangeAddress(4, 1, rows - 1, cols)));
  setWidths(sheet, {
    A: 300,
    B: 90,
    C: 115,
    D: 210,
    E: 80,
    F: 80,
    G: 110,
  });
  sheet.freezePanes.freezeRows(3);
}

function addTopicSummary() {
  const sheet = workbook.worksheets.add("Topic Clusters");
  sheet.getRange("A1").values = [["Emergent Topic Clusters"]];
  styleTitle(sheet.getRange("A1:F1"));
  writeMatrix(sheet, 3, 1, data.summary.topic_summary);
  const rows = data.summary.topic_summary.length;
  const cols = data.summary.topic_summary[0].length;
  styleHeader(sheet.getRange(rangeAddress(3, 1, 1, cols)));
  styleBody(sheet.getRange(rangeAddress(4, 1, rows - 1, cols)));

  writeMatrix(sheet, 10, 1, data.summary.response_by_creator);
  const cRows = data.summary.response_by_creator.length;
  const cCols = data.summary.response_by_creator[0].length;
  styleHeader(sheet.getRange(rangeAddress(10, 1, 1, cCols)), "#5A4C2E");
  styleBody(sheet.getRange(rangeAddress(11, 1, cRows - 1, cCols)));

  setWidths(sheet, {
    A: 330,
    B: 90,
    C: 80,
    D: 250,
    E: 280,
    F: 120,
    G: 110,
  });
  sheet.freezePanes.freezeRows(3);
}

function addQuotes() {
  const sheet = workbook.worksheets.add("Top Quotes");
  sheet.getRange("A1").values = [["Illustrative Quotes"]];
  styleTitle(sheet.getRange("A1:F1"));
  const headers = ["Theme", "Creator", "Sentiment", "Audience response", "Comment ID", "Quote"];
  const rows = data.quotes.map((q) => [
    q.theme,
    q.creator,
    q.sentiment,
    q.audience_response,
    q.comment_id,
    q.quote,
  ]);
  writeMatrix(sheet, 3, 1, [headers, ...rows]);
  styleHeader(sheet.getRange("A3:F3"));
  styleBody(sheet.getRange(`A4:F${3 + rows.length}`));
  setWidths(sheet, {
    A: 270,
    B: 210,
    C: 90,
    D: 230,
    E: 150,
    F: 650,
  });
  sheet.freezePanes.freezeRows(3);
}

function addAudienceRows() {
  const sheet = workbook.worksheets.add("audience");
  writeMatrix(sheet, 1, 1, [data.headers, ...data.rows]);
  const rows = data.rows.length + 1;
  const cols = data.headers.length;
  styleHeader(sheet.getRange(rangeAddress(1, 1, 1, cols)));
  styleBody(sheet.getRange(rangeAddress(2, 1, rows - 1, cols)));
  setWidths(sheet, {
    A: 150,
    B: 310,
    C: 520,
    D: 210,
    E: 85,
    F: 90,
    G: 210,
    H: 300,
    I: 75,
    J: 85,
    K: 260,
    L: 340,
    M: 100,
    N: 135,
    O: 240,
    P: 235,
    Q: 165,
    R: 190,
    S: 170,
    T: 175,
    U: 95,
    V: 135,
    W: 100,
    X: 100,
    Y: 105,
    Z: 210,
    AA: 310,
    AB: 360,
    AC: 360,
    AD: 190,
  });
  sheet.freezePanes.freezeRows(1);
}

addSummary();
addCreatorSummary();
addThemeSummary();
addTopicSummary();
addQuotes();
addAudienceRows();

const summaryCheck = await workbook.inspect({
  kind: "table",
  range: "Summary!A1:H29",
  include: "values",
  tableMaxRows: 29,
  tableMaxCols: 8,
});
console.log(summaryCheck.ndjson);

const audienceCheck = await workbook.inspect({
  kind: "table",
  range: "audience!A1:AD8",
  include: "values",
  tableMaxRows: 8,
  tableMaxCols: 30,
});
console.log(audienceCheck.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

for (const sheet of [
  "Summary",
  "Creator Summary",
  "Theme Summary",
  "Topic Clusters",
  "Top Quotes",
  "audience",
]) {
  await workbook.render({
    sheetName: sheet,
    range: sheet === "audience" ? "A1:AD12" : "A1:K28",
    scale: 1,
  });
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(OUTPUT_PATH);
console.log(`Saved ${OUTPUT_PATH}`);

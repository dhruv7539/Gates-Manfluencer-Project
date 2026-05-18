import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const DATA_PATH =
  "/Users/dhruvbhanderi/Documents/USC/New Research Engineer/Codex/outputs/kenya_audience_cleaned/cleaned_data.json";
const OUTPUT_PATH =
  "/Users/dhruvbhanderi/Documents/USC/New Research Engineer/Audience analysis kenya/Final/Kenya Audience Analysis Comments - Cleaned.xlsx";

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

function styleHeader(range) {
  range.format = {
    fill: "#1F4E79",
    font: { name: "Calibri", size: 11, color: "#FFFFFF", bold: true },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#D9E2F3" },
  };
}

function styleBody(range) {
  range.format = {
    font: { name: "Calibri", size: 10, color: "#1F2933" },
    verticalAlignment: "top",
    wrapText: true,
    borders: { preset: "inside", style: "thin", color: "#E5E7EB" },
  };
}

function styleDataSheet(sheet, rowCount) {
  const lastRow = Math.max(rowCount, 1);
  styleHeader(sheet.getRange("A1:E1"));
  if (lastRow > 1) {
    styleBody(sheet.getRange(`A2:E${lastRow}`));
  }
  sheet.getRange(`A1:A${lastRow}`).format.columnWidthPx = 170;
  sheet.getRange(`B1:B${lastRow}`).format.columnWidthPx = 115;
  sheet.getRange(`C1:C${lastRow}`).format.columnWidthPx = 95;
  sheet.getRange(`D1:D${lastRow}`).format.columnWidthPx = 310;
  sheet.getRange(`E1:E${lastRow}`).format.columnWidthPx = 620;
  sheet.freezePanes.freezeRows(1);
}

function addSummarySheet() {
  const sheet = workbook.worksheets.add("Summary Metrics");

  sheet.getRange("A1").values = [["Kenya Audience Analysis Summary"]];
  sheet.getRange("A1:F1").format = {
    fill: "#F2F6FA",
    font: { name: "Calibri", size: 16, color: "#1F2933", bold: true },
    verticalAlignment: "center",
  };

  writeMatrix(sheet, 3, 1, data.summary.overview);
  writeMatrix(sheet, 11, 1, data.summary.by_influencer);
  writeMatrix(sheet, 3, 8, data.summary.by_platform);
  writeMatrix(sheet, 11, 8, data.summary.by_type);

  styleHeader(sheet.getRange("A3:B3"));
  styleBody(sheet.getRange(`A4:B${2 + data.summary.overview.length}`));
  styleHeader(sheet.getRange("A11:F11"));
  styleBody(sheet.getRange(`A12:F${10 + data.summary.by_influencer.length}`));
  styleHeader(sheet.getRange("H3:I3"));
  styleBody(sheet.getRange(`H4:I${2 + data.summary.by_platform.length}`));
  styleHeader(sheet.getRange("H11:I11"));
  styleBody(sheet.getRange(`H12:I${10 + data.summary.by_type.length}`));

  sheet.getRange("A1:A20").format.columnWidthPx = 170;
  sheet.getRange("B1:B20").format.columnWidthPx = 130;
  sheet.getRange("C1:C20").format.columnWidthPx = 110;
  sheet.getRange("D1:F20").format.columnWidthPx = 115;
  sheet.getRange("H1:H20").format.columnWidthPx = 130;
  sheet.getRange("I1:I20").format.columnWidthPx = 105;
}

addSummarySheet();

for (const cleanSheet of data.sheets) {
  const sheet = workbook.worksheets.add(cleanSheet.name);
  const rows = [cleanSheet.headers, ...cleanSheet.rows];
  writeMatrix(sheet, 1, 1, rows);
  styleDataSheet(sheet, rows.length);
}

const summaryCheck = await workbook.inspect({
  kind: "table",
  range: "Summary Metrics!A1:I15",
  include: "values",
  tableMaxRows: 15,
  tableMaxCols: 9,
});
console.log(summaryCheck.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

for (const sheet of ["Summary Metrics", ...data.sheets.map((s) => s.name)]) {
  await workbook.render({ sheetName: sheet, range: sheet === "Summary Metrics" ? "A1:I16" : "A1:E12", scale: 1 });
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(OUTPUT_PATH);
console.log(`Saved ${OUTPUT_PATH}`);

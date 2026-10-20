# Photographed-report extraction regression

## Scope and safety contract

This change addresses photographed CBC tables being read as separate columns,
misidentified as one unknown result, or parsed with a unit exponent as the value.
The language model remains an optional explanation stage; it does not extract,
repair, or validate measurements. Original photographs stay local. Only
identifier-free synthetic table data are committed.

User journeys:

- Upload a photographed table and see test names associated with their own
  result, full unit, printed reference range, and source page.
- An unreadable value or reference remains undetermined rather than borrowing a
  neighboring cell or being repaired using a generic medical reference.
- Demographics, commentary, section headings, and page footers are not tests.
- A partial or failed reading must not sound like the whole report is normal.

## Investigation and RED evidence

The linked public example was inspected locally, not sent to an AI provider.
Tesseract's automatic text reading separated rows into column blocks and lost
some decimal points. Sparse word detection preserved better word readings but
required geometric row/cell reconstruction.

`python -m pytest tests/test_table_reading.py -q --tb=short` initially produced
17 failing tests out of 25. Reproductions included:

- A mixed-spacing row raising a Pydantic error because `value_text` was a float.
- `WBC 7.2 x 10 3/uL 4-11` incorrectly treating `3` as the measurement.
- Patient IDs, page numbers and explanatory prose becoming test results.
- Multiword units being truncated and qualitative results disappearing.
- Empty/unknown-only summaries claiming no results outside the reference range.

RED checkpoints: `c6880d0` isolates tests from the running app's upload directory;
`2731b24` records the failing regression tests. Tests must never purge uploads
belonging to the running development server.

## Verification commands

Run the deterministic regression suite (no live AI requests):

```powershell
python -m pytest -o addopts="" -q
```

Real-engine smoke checks require Tesseract and its language data configured with
`TESSERACT_CMD`, optionally `TESSDATA_DIR`, and `OCR_LANGUAGES`. Use only local
images with permission. Compare every recovered numeric value with the image;
checking the number of returned rows alone is not an accuracy test.

The complete hand-transcribed sample table in `test_table_reading.py` has
18 numeric tests plus one qualitative result (19 results, not 20). That test
verifies parsing of known text; it is not a claim that OCR reads every cell.
Low-confidence or conflicting OCR fields may intentionally remain unknown.

## GREEN and rendered evidence

On the local verification run:

- `python -m pytest -o addopts="" -q --tb=short`: **200 passed**.
- Coverage measured for `extractor`, `ocr`, `ocr_layout`, `pipeline`, and
  `report_summary`: **85% combined statement coverage**. This is not a claim
  about unmeasured modules or clinical accuracy.
- `npm.cmd run build`: succeeded.
- Playwright uploaded a PNG conversion of the linked full-resolution image
  through an isolated API instance, then displayed results at 1440px and 390px.
  No JavaScript errors and no AI-provider requests occurred.
- Real OCR retained **18 of 19 manually identified rows**: 12 normal, one low,
  two high, three unknown. RDW-SD, MCV, and Platelet Count remained unknown
  because their unit or reference was uncertain. MPV was omitted because its
  name did not meet the confidence/corroboration contract. No confident numeric
  measurement differed from the manually checked image.

The 19-row exact-fields parser test and the 18-row real-OCR smoke result measure
different layers. The former does not hide the latter's remaining limitations.
Screenshots and the original image remain outside Git in the local QA directory.

Independent agents reviewed the approach and challenged the parser with
synthetic counterexamples. Their findings became regression tests for corrupt
numeric suffixes, digit-bearing units, numeric analyte descriptors, genuine
bacterial tests, qualitative references, and operator ranges with units.
The final cross-module review also added checks for preserving trailing empty
cells and valid `/uL` units. A runtime mutation bypassing unit validation was
caught by the malformed-result regression; the original function was restored
without editing the source file.

## Upload formats

A photographed report reaches the app as an image file. The accepted formats
are PDF, JPG, JPEG, PNG and WebP, and the format is confirmed from the file's
own bytes rather than its name, so a renamed file is still rejected.

WebP is a RIFF container, and RIFF also wraps WAV and AVI files. Only the
`WEBP` form type at offset 8 identifies an image; a `RIFF`/`WAVE` file named
`.webp` is rejected as unreadable.

The linked example image is a `.webp` file. Before this change the server
answered "unsupported file type" and the browser's file picker hid the file,
so the report could not be uploaded at all.

Verification: `tests/test_image_formats.py` covers WebP acceptance, WebP
analysis, a renamed PNG rejected as `.webp`, a non-WebP RIFF container
rejected, and JPEG/PNG staying accepted.

## Limits

OCR confidence is not a calibrated medical-accuracy score. Bounded local OCR
and conservative parsing cannot guarantee that every layout or clear-looking
digit is correct. Inspect the original report and consult a qualified clinician.
Neither normal extracted values nor a successful software test establish health.

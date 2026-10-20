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

Three further rules apply, each with a regression test:

- **The format comes from the client's own name, not the display name.** The
  display name is sanitised for echoing back, and that sanitising used to
  remove a leading non-ASCII run. A file named `রোগীর রিপোর্ট.webp` therefore
  lost its extension and was refused as an unsupported type. The format is now
  read from the raw name, and the sanitised name is only a display label.
- **An image must actually open.** The container check proves the bytes look
  like an image; the upload handler also decodes it. A truncated PNG or a
  WebP header over a broken body is refused at upload with a clear message,
  instead of failing later on the results screen with a 422.
- **A display name cannot disguise its extension.** Letters, digits and
  combining marks from any script survive in the echoed name, while path
  separators, control characters and bidirectional overrides are replaced.

The frontend reads the accepted list from `/api/health` instead of repeating
it, so the file picker cannot drift away from what the API accepts. The same
response reports which of those formats are read as images, so the interface
never has to guess.

Two limits protect the server, and both are checked before the image is
decoded:

- The decode runs in a worker thread, so a large upload does not block the
  event loop while every other request waits.
- The pixel count is checked before decoding, and a file that describes more
  than 60 megapixels is refused. The limit sits above a 48 megapixel phone
  camera, because refusing a real photograph would be worse than decoding a
  large one.

Verification: `tests/test_image_formats.py` covers WebP acceptance, WebP
analysis, a renamed PNG rejected as `.webp`, a non-WebP RIFF container
rejected, JPEG/PNG staying accepted, Bangla filenames, undecodable images,
hostile file names, the pixel limit, and the display-name rules.

## A picture that is too small to read

A user uploaded a photographed CBC report as `images.jpg`. The application
reported eight "undetermined" results with names such as `Awe`, `Sea`,
`Hoemeagicese` and `osroghaly`. Four separate faults were behind that, found
by reading the server's stored OCR text rather than the screen.

**1. The picture was a web thumbnail.** The file was 386x518 pixels and 22 KB -
roughly 47 dots per inch for a whole page. The median recognised word stood
5.5 pixels tall. Tesseract needs about twenty pixels of letter height, so the
engine read the title and a few large words and invented the rest. Sixteen
combinations of upscale factor, sharpening and page-segmentation mode were
tried on that exact file; the best recovered 6 of 19 values, and those were
coincidental two-digit matches. No preprocessing can recover a picture that
does not contain the information.

The application now measures legibility instead of guessing. Two signals are
used: the median height of a recognised word, measured in the *original*
picture, and the engine's own confidence in the words it read. The height
alone is not enough - unreadable text produces tall, meaningless boxes - while
the confidence is monotonic. A clean 899x1200 report scores 12 pixels per
word and a confidence of 95; the thumbnail measures 5.5 pixels and scores 42;
text that is too small to read scores between 23 and 49. A picture below the
threshold is reported as unreadable, in Bangla, with the instruction to
upload the original. `tests/test_legibility.py` covers the measurement with
the real engine, in both directions.

The measurement is taken against the picture the engine actually saw, so a
phone photo stored sideways is not measured against the wrong side.

**2. The parser turned noise into results.** A line only became a result if it
had a name and something that looked like a reference range - and an
unparseable range such as `08/09/2025` or `7007` was enough. Eight lines of
OCR noise therefore became eight undetermined tests. A row now needs a
measurement, a recognised unit, or a *readable* reference range before it may
be shown as a result. The seven noise shapes from this file are pinned in
`tests/test_table_reading.py`. A row that came from the geometric table
layout keeps its own rule, because that layout has already decided the row is
real.

**3. The AI stage could never finish.** `gemini_client` asked for 2048 tokens.
A report with nineteen rows needs three short Bangla paragraphs each, so the
reply was cut off in the middle of an object and the whole explanation stage
failed with "the shape of the AI reply could not be read". The budget is now
`AI_MAX_TOKENS` (8192 by default, clamped to 256..32768) and a truncated
reply keeps every complete object it contains, dropping only the incomplete
trailing one. A reply that covered only some of the results is reported as an
incomplete answer, not as an error and not as a complete one.

**4. A misread heading disabled the whole table.** The heading was read as
`Reams` instead of `Results`, so no table could be recognised and the flat
parser took over. A heading now also matches when it is a close near-miss of a
known column name, by a documented character-similarity rule, and a heading
read with a low confidence may anchor a position - a heading is only a
position, while data cells keep the strict confidence floor.

## Reading a report that produced no results

Two files were uploaded that produced no results at all: a good photograph
(`A4sizeSD.png`, 990x1398) and the same report as a PDF with a text layer.
Both were read correctly once the following were found. The screen behind
`POST /api/reports/read-text` shows exactly what the reader made of a file -
the text, where it came from, how legible the picture was and how many rows
the parser could build from it - so this kind of failure is visible instead of
silent.

**5. The second column was called VALUE.** The heading row of that report is
`TEST | VALUE | UNIT | REFERENCE`. Only `Results` was a known name for the
measurement column, so one column never anchored, the whole table was
rejected, and the plain-text fallback was vetoed - the page came back empty.
`VALUE` and `Values` are now known names for that column.

**6. The name column ended in the middle of a long name.** The boundary
between the name column and the value column was drawn across the gap
between the two headings. `TOTAL LEUKOCYTE COUNT`, `HEMATOCRIT VALUE, HCT`,
`MEAN CORPUSCULAR VOLUME, MCV`, `MEAN CELL HAEMOGLOBIN, MCH` and
`MEAN CELL HAEMOGLOBIN CON, MCHC` all reach further right than that gap, so
each was cut in half and its row was lost. The boundary now comes from the
data: a column of measurements sits under its heading, and the measurements
themselves say where the column begins. Only words a measurement cell can
hold are used, so a long name cannot move the column.

**7. A comma in a name was taken for prose.** A name is rejected when it
looks like a sentence, and a comma was one of the signs. But
`HEMATOCRIT VALUE, HCT` is a name. A comma is now allowed in a short name
and still marks prose in a long one.

**8. A verdict marker was part of the name.** Reports print `L` or `H` right
after the test name, and it landed in the name cell. The marker is now
separated from the name, as it already was in the flat parser.

**9. A PDF's text layer holds one cell per line.** `page.get_text()` returns
`HEMOGLOBIN`, `15`, `g/dl`, `13 - 17` on four separate lines, so the flat
parser saw no rows. The positions of the words are still there, and those
positions are what the same four-column reconstruction used for a photograph
needs. A PDF page with a text layer now goes through that reconstruction
too, and its original text is kept alongside it.

Both files now produce the same thirteen results - twelve analytes and one
qualitative result - with the same verdicts.

## Limits

OCR confidence is not a calibrated medical-accuracy score. Bounded local OCR
and conservative parsing cannot guarantee that every layout or clear-looking
digit is correct. Inspect the original report and consult a qualified clinician.
Neither normal extracted values nor a successful software test establish health.

A picture whose text is only a few pixels tall cannot be read by any OCR
engine, and no amount of upscaling or sharpening adds the missing detail.
The application says so rather than inventing rows, but it cannot read a
report the user did not photograph at a usable resolution.

The table reconstruction still needs all four column headings. When the
reference column's heading is not read at all, the table is not reconstructed
and the report is reported as unread rather than guessed. Reading such a
photograph needs the original picture, so that case has not been closed here.


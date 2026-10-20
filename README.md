# AI Medical Report Explainer

Upload a medical test report as a **PDF or image** and read it explained in simple
**Bangla**.

The application extracts the facts printed on the report, decides whether each
value falls inside the reference range **that same report printed**, and only then
asks a Gemini model to explain those verified facts in plain language.

> **This is an education tool, not a diagnostic one.** It does not diagnose
> diseases, prescribe medication, or replace a doctor. See
> [Safety limitations](#safety-limitations).

---

## Contents

- [The core principle](#the-core-principle)
- [Architecture](#architecture)
- [Installation](#installation)
- [Gemini API setup](#gemini-api-setup)
- [OCR pipeline](#ocr-pipeline)
- [Extraction](#extraction)
- [Validation](#validation)
- [AI explanation](#ai-explanation)
- [Safety limitations](#safety-limitations)
- [Privacy approach](#privacy-approach)
- [API reference](#api-reference)
- [Testing](#testing)
- [Project structure](#project-structure)

---

## The core principle

The whole design follows one rule:

```
Original Report
      ↓
Extract Facts          (deterministic, no model)
      ↓
Verify Facts           (deterministic, no model)
      ↓
Compare With the Report's Own Reference Ranges
      ↓
AI Explains Verified Information
      ↓
Simple Bangla Summary
```

**The language model never decides whether a number is high or low.** That is
arithmetic, and arithmetic should not be delegated to something that can
hallucinate. A test result's status comes from ordinary Python, always.

The model is used for the one thing it is genuinely good at: turning a verified
number into a sentence a non-medical reader can understand.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  React frontend (Vite)                                   │
│  Home → Processing → Results                            │
└───────────────────────┬──────────────────────────────────┘
                        │  HTTP / JSON
┌───────────────────────▼──────────────────────────────────┐
│  FastAPI                                                 │
│                                                          │
│  POST   /api/reports/upload    validate + temp storage   │
│  POST   /api/reports/analyze   run the pipeline          │
│  GET    /api/reports/{id}      fetch a stored result     │
│  DELETE /api/reports/{id}      delete result + temp file │
└───────────────────────┬──────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────┐
│  Pipeline                                               │
│                                                          │
│  pdf_processor ──► extractor ──► validator ──► summary   │
│        │                                          ▲       │
│        └──► ocr (Tesseract / PaddleOCR)     authoritative│
│                                                          │
│  medical_explainer ──► gemini_client  (optional, prose)  │
│                                                          │
│  report_store (in-memory, TTL)    file_handler (temp)    │
└──────────────────────────────────────────────────────────┘
```

### Data flow

1. **Read** — PyMuPDF pulls the text layer from a PDF. A page without usable text
   is treated as a scan and rendered to an image for OCR. Images go straight to
   OCR. Every chunk of text keeps its 1-based page number.
2. **Extract** — regex-based parsing turns each report row into a structured
   `TestResult`. Patient demographics and lab metadata are filtered out.
3. **Validate** — `validator.py` compares each value against the reference range
   printed on the report and assigns `low` / `normal` / `high` / `abnormal` /
   `unknown`.
4. **Explain** — verified results are sent to Gemini, which returns Bangla prose
   in three parts: what the report shows, general information, and what cannot be
   determined.
5. **Check** — the model's own `status` field is compared against the verified
   status. Disagreement triggers one regeneration; persistent disagreement
   discards the model's prose entirely.
6. **Summarise** — counts come from the validated data, rendered as Bangla
   numerals.

The AI stage is **additive**. With no API key, or if the call fails, or if the
model contradicts the facts, the report still returns complete and correct
deterministic results.

---

## Installation

### Prerequisites

- Python 3.11+
- Node.js 18+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) — only needed for
  scanned PDFs and image uploads

### 1. Backend

```bash
git clone https://github.com/Athaher-Sayem/AI_Health_Checkup.git
cd AI_Health_Checkup

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Install Tesseract

Tesseract is a system dependency, not a Python package.

**Windows**
```powershell
winget install UB-Mannheim.TesseractOCR
```
Then add Tesseract to `PATH`, or set the full path in your `.env`:
```
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

**macOS**
```bash
brew install tesseract
```

**Ubuntu / Debian**
```bash
sudo apt-get install tesseract-ocr
```

Bangla language data (optional, for Bangla-labelled reports):
```bash
# Ubuntu/Debian
sudo apt-get install tesseract-ocr-ben
# macOS
brew install tesseract-lang
```

Verify the installation:
```bash
tesseract --version
```

### 3. Configure

```bash
cp .env.example .env
```

Edit `.env` and add your key (see below). `.env` is gitignored — never commit it.

### 4. Run the backend

```bash
python -m uvicorn backend.main:app --reload
```

The API is available at <http://127.0.0.1:8000>, with interactive docs at
<http://127.0.0.1:8000/docs>.

### 5. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to the backend, so no CORS
configuration is needed in development.

### 6. Run the tests

```bash
python -m pytest
```

---

## Gemini API setup

1. Get an API key from <https://aistudio.google.com/apikey>.
2. Put it in `.env` at the project root:

   ```env
   GEMINI_API_KEY=your_api_key_here
   ```

3. Restart the backend.

**Rules this project follows:**

- The key is read from the environment only. It is never hard-coded.
- The key never reaches the frontend. The client learns only *whether* AI is
  configured, via a boolean on `/api/health`.
- `.env` is listed in `.gitignore`.
- Error logging records the HTTP status code only — never the response body,
  which could echo report contents.

The app runs **without** a key. Every deterministic feature still works; the
results screen simply reports that AI explanation is unavailable.

### Optional settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Model used for explanation |
| `GEMINI_TIMEOUT_SECONDS` | `90` | Request timeout |
| `MAX_UPLOAD_SIZE_MB` | `12` | Upload size limit |
| `RESULT_TTL_MINUTES` | `30` | How long results stay in memory |
| `OCR_LANGUAGES` | `eng+ben` | Tesseract language packs |
| `TESSERACT_CMD` | auto | Full path to the Tesseract binary |

---

## OCR pipeline

Reports arrive in two very different forms, and the pipeline handles both.

### Text-based PDFs (fast path)

PyMuPDF reads the text layer directly. No OCR, no image conversion, no accuracy
loss. This is the preferred route whenever it works.

A page is considered to have a usable text layer when it has at least 12
characters containing at least one alphanumeric character. The threshold is
deliberately low: a page holding a single test row is short but is still a text
PDF, and OCR would be slower *and* less accurate for no benefit.

### Scanned PDFs and images

1. The page is rendered to a PNG at 220 DPI (`OCR_DPI`).
2. The image is preprocessed: EXIF orientation applied, converted to greyscale,
   autocontrast applied to sharpen faint print.
3. OCR runs and the text is tagged with the page it came from.

**OCR engine selection.** Tesseract is primary and works out of the box on all
three platforms. If `paddleocr` is importable it is used as a fallback when
Tesseract is unavailable. When no engine is installed, scanned documents do not
crash the request: the page is returned with a warning explaining that OCR is
unavailable.

### OCR quality

OCR can misread characters — `l0.2` for `10.2` is a classic. This project does
**not** silently repair such readings, because a plausible-looking correction is
worse than an obviously missing value. A value we cannot read becomes `unknown`,
the row stays visible, and the user can compare it against their paper report.

---

## Extraction

`extractor.py` is pure Python and makes no model call. For each line it
determines the test name, value, unit, reference range, qualitative result and
source page.

### Supported reference-range forms

| Printed as | Parsed as |
| --- | --- |
| `12 - 16` | `low=12, high=16` |
| `12.0-16.0` | `low=12.0, high=16.0` |
| `12 to 16` | `low=12, high=16` |
| `12-16 g/dL` | range plus unit |
| `>= 12`, `≥ 12` | lower bound only |
| `<= 13`, `≤ 13` | upper bound only |
| `> 40`, `< 5` | bound with a strict operator |

Bounds are treated as **inclusive**, matching how laboratories print them. A
report showing `40 - 50` means 40 and 50 are both acceptable.

### Qualitative results

Positive / Reactive / Detected and Negative / Not detected / Absent are
classified by their wording. Equivocal and Indeterminate stay `unknown`.

### What is deliberately skipped

A row is only extracted when it matches confidently. Patient name, age, sex,
phone number, weight, referring doctor and specimen metadata are filtered out —
they carry numbers that would otherwise look like test results, and they are
identifying information the explanation does not need.

If nothing can be extracted, the report says so rather than showing an empty
result page with no explanation.

---

## Validation

`validator.py` is the sole authority on status. It never calls a model and never
accepts model output.

```
value = 10.2,  reference = 12–16   →   10.2 < 12    →  LOW
value = 14,    reference = 12–16   →   in range     →  NORMAL
value = 18,    reference = 12–16   →   18 > 16      →  HIGH
value = 18,    no reference printed →  cannot tell  →  UNKNOWN
```

**The range printed on your report always wins.** When the report states no
range, the status is `unknown`. This project never substitutes a generic or
external reference range — even for well-known analytes like haemoglobin, where
temptation is highest. A lab's printed range may account for your lab's
methodology, your age, and your sex; substituting a generic one would be
quietly wrong.

`counts` and the three display groups are computed in the same module, so the
summary numbers are arithmetically consistent with the per-test statuses by
construction.

---

## AI explanation

### The prompt

The system instruction is explicit about what the model may not do:

```
Do not change numerical values.
Do not invent reference ranges.
Do not invent test results.
Do not diagnose diseases.
Do not claim that a person definitely has a disease.
Do not recommend any medication, dose, or stopping a medicine.
```

It also requires three distinct sections per test, so the user can always tell
extracted fact from general education:

1. **সহজ ব্যাখ্যা** — what the report actually shows.
2. **সাধারণ তথ্য** — what the test generally measures, and what an abnormal
   result can *sometimes* be associated with.
3. **যা নির্ধারণ করা যায়নি** — what cannot be concluded from this report.

### The validation layer

Prompting alone is not a guarantee, so the output is checked:

```
Extracted:   Hemoglobin = 10.2,  Reference = 12–16
Python:      Status = LOW
AI:          Status = NORMAL          ← contradiction detected
```

On detecting a contradiction the application regenerates the explanation once,
with the verified status made explicit. If the model still disagrees, **its
prose is discarded entirely** and only the deterministic results are shown.

Three things are structurally impossible for the model to influence:

| Field | Source | Why |
| --- | --- | --- |
| `status` | validator | Model's value is discarded on arrival |
| `source_page` | our own page tracking | A model claiming page 99 changes nothing |
| `value`, `unit`, `reference` | extractor | Rendered from parsed data, not model text |

The same applies to counts: they come from the validated data, so the model
cannot invent a summary number.

---

## Safety limitations

This application **must not** and does not:

- Diagnose a disease
- Prescribe medication or recommend a dosage
- Tell anyone to stop a medication
- Claim that an abnormal result proves a disease
- Invent a missing value or reference range
- Replace a doctor

Language is kept cautious by construction. The prompt requires phrasing such as
"এটি বিভিন্ন কারণে হতে পারে।" and "শুধু এই রিপোর্টের ভিত্তিতে কারণ নিশ্চিত করা যায় না।"

Status labels come from a **fixed vocabulary** — কম, স্বাভাবিক, বেশি, স্বাভাবিক
সীমার বাইরে, নির্ধারণ করা যায়নি. The word "dangerous" or "critical" appears
only when the report itself prints such a flag.

A disclaimer is displayed on the home screen, in the summary, and on the results
screen:

> এই অ্যাপটি শুধুমাত্র মেডিকেল রিপোর্টের তথ্য সহজ ভাষায় বোঝাতে সাহায্য করে।
> এটি কোনো রোগ নির্ণয় বা চিকিৎসার বিকল্প নয়।
> চিকিৎসা সংক্রান্ত সিদ্ধান্তের জন্য যোগ্য চিকিৎসকের পরামর্শ নিন।

**Limitations worth stating plainly:**

- Extraction is regex-based. An unusual report layout may not parse, and the
  application will show fewer results rather than wrong ones.
- Reference ranges vary between laboratories. This tool reports what *your*
  report says; it cannot tell you whether that range is right for you.
- A value inside the range is not proof of health, and a value outside it is not
  proof of disease. Many findings are context-dependent.
- This tool has not been validated as a medical device and is not intended for
  clinical decision-making.

---

## Privacy approach

Medical reports are sensitive. The following are enforced by tests in
`tests/test_privacy.py`.

| Concern | How it is handled |
| --- | --- |
| **Report retention** | Uploads live in a private temp directory and are deleted in a `finally` block — including when processing raises |
| **Uploaded files are never permanent** | No report bytes are ever written to a permanent location |
| **Delete option** | `DELETE /api/reports/{id}` removes the result and any temp file; the UI offers a "রিপোর্ট মুছে ফেলুন" button |
| **Automatic expiry** | Results are held in memory only, behind a 30-minute TTL |
| **No content logging** | Report text, values and patient details are never logged. Only HTTP status codes are logged from the Gemini client |
| **No public exposure** | Temp files are outside any served directory, with `0o600` permissions |
| **Filename safety** | The client filename is sanitised and never used as a real path; the stored filename is a server-generated UUID |
| **Content verification** | Magic bytes are checked so a zip renamed `.pdf` is rejected |
| **Identifier minimisation** | Patient name, age, sex, phone and referring doctor are filtered before extraction, so they never reach the model or the response |
| **Minimal data sent to the model** | Only test name, value, unit, printed reference range, verified status and page number — never a name or identifier |
| **Keys stay server-side** | The API key is never returned by any endpoint |

---

## API reference

### `POST /api/reports/upload`

Accepts the report. Returns a `report_id` used by the other endpoints.

**Accepted formats:** PDF, JPG, JPEG, PNG and WebP, up to
`MAX_UPLOAD_SIZE_MB` (12 MB by default). The format is confirmed from the
file's own bytes, so a renamed file is rejected. WebP is a RIFF container and
only its `WEBP` form type counts, which keeps WAV and AVI files out.

```bash
curl -X POST http://127.0.0.1:8000/api/reports/upload \
  -F "file=@report.pdf"
```

```json
{
  "report_id": "64a383200233423f909c6ca33e75d528",
  "filename": "report.pdf",
  "size_bytes": 1138,
  "expires_in_minutes": 30
}
```

**Errors:** `400` for an unsupported type, a size over the limit, a corrupted
file, a password-protected PDF, or content that contradicts the extension.

### `POST /api/reports/analyze`

Runs the full pipeline and returns the complete result.

```bash
curl -X POST http://127.0.0.1:8000/api/reports/analyze \
  -H "Content-Type: application/json" \
  -d '{"report_id":"64a383200233423f909c6ca33e75d528"}'
```

```json
{
  "report_id": "64a383200233423f909c6ca33e75d528",
  "filename": "report.pdf",
  "meta": {
    "document_kind": "pdf_text",
    "ocr_used": false,
    "page_count": 1,
    "warnings": []
  },
  "counts": { "total": 5, "normal": 2, "low": 1, "high": 1, "abnormal": 0, "unknown": 1 },
  "summary": {
    "headline": "রিপোর্টের সহজ সারাংশ",
    "bullets": [
      "২টি পরীক্ষার ফলাফল স্বাভাবিক সীমার মধ্যে।",
      "২টি ফলাফল রিপোর্টে দেওয়া সীমার বাইরে।"
    ],
    "important_note": "গুরুত্বপূর্ণ: এই সারাংশ কোনো রোগ নির্ণয় নয়। ..."
  },
  "groups": {
    "স্বাভাবিক": [ { "test_name": "HCT", "value": 45.0, "status": "normal", "source_page": 1 } ],
    "সীমার বাইরে": [ { "test_name": "Hemoglobin", "value": 10.2, "status": "low", "source_page": 1 } ],
    "নির্ধারণ করা যায়নি": [ { "test_name": "Vitamin D", "value": 18.0, "status": "unknown", "source_page": 1 } ]
  },
  "results": [],
  "explanations": [],
  "validation": { "checked": false, "contradictions": [], "repaired": false },
  "ai_enabled": false,
  "ai_error": "AI ব্যাখ্যার জন্য API key সেট করা নেই।",
  "disclaimer": "এই অ্যাপটি শুধুমাত্র ..."
}
```

**Errors:** `404` unknown id, `410` the temp file is gone.

### `GET /api/reports/{report_id}`

Returns a previously computed result. `404` if expired or deleted.

### `DELETE /api/reports/{report_id}`

Deletes the stored result and any remaining temp file.

### `GET /api/health`

Liveness probe. Returns `ai_configured` as a boolean — never the key itself.

---

## Testing

```bash
python -m pytest          # 89 tests
python -m pytest -v       # verbose
```

**The Gemini API is never called during tests.** The AI stage is mocked, so the
suite runs offline and deterministically.

### Coverage against the required scenarios

| # | Scenario | Test |
| --- | --- | --- |
| 1 | Normal blood test | `test_validator.py::TestNormalResults` |
| 2 | Low value | `test_validator.py::TestLowValues` |
| 3 | High value | `test_validator.py::TestHighValues` |
| 4 | Missing reference range | `test_validator.py::TestMissingReferenceRange` |
| 5 | OCR mistakes | `test_documents.py::TestOcrMistakes` |
| 6 | Multiple pages | `test_documents.py::TestMultiplePages` |
| 7 | Scanned PDF | `test_documents.py::TestScannedPdf` |
| 8 | Image report | `test_documents.py::TestImageReport` |
| 9 | Unsupported file | `test_documents.py::TestUnsupportedFiles` |
| 10 | Corrupted file | `test_documents.py::TestCorruptedFiles` |
| 11 | AI contradicting validation | `test_ai_layer.py::TestContradictionDetection` |
| 12 | Missing/uncertain information | `test_validator.py::TestUncertainInformation` |

### Test dataset

**No real patient data is used.** Test PDFs are generated in-memory with PyMuPDF
from hand-written sample text at test time — synthetic CBC, biochemistry and
serology rows covering normal, low, high, qualitative, missing-range and
missing-value cases. OCR paths use synthetic images and mocked OCR output.

### Accuracy

**No accuracy figure is claimed.** No benchmark against a labelled clinical
dataset has been run, so quoting an extraction-accuracy percentage would be
fabricated. To evaluate accuracy, build a labelled set of real reports, run the
extractor, and report precision and recall per field with the dataset described
explicitly.

### What the tests do guarantee

That the deterministic logic behaves as specified, that safety properties hold,
and that the model cannot override a verified result.

---

## Project structure

```
AI_Health_Checkup/
├── backend/
│   ├── main.py                     FastAPI app, CORS, health endpoint
│   ├── config.py                   Settings from environment
│   ├── api/
│   │   └── reports.py              upload / analyze / get / delete
│   ├── services/
│   │   ├── pdf_processor.py        Text extraction, scan detection
│   │   ├── ocr.py                  Tesseract + optional PaddleOCR
│   │   ├── extractor.py            Deterministic test extraction
│   │   ├── validator.py            Deterministic status authority
│   │   ├── medical_explainer.py    Prompt, parsing, contradiction check
│   │   ├── gemini_client.py        Gemini API call
│   │   ├── report_summary.py       Bangla summary with real counts
│   │   ├── pipeline.py             End-to-end orchestration
│   │   └── report_store.py         In-memory TTL store
│   ├── schemas/
│   │   └── report.py               Pydantic models
│   └── utils/
│       └── file_handler.py         Validation, temp storage, cleanup
├── frontend/
│   └── src/
│       ├── components/             SummaryCard, TestCard, Disclaimer
│       ├── pages/                  Home, Processing, Results
│       └── services/api.js         Fetch wrapper
├── tests/                          89 tests
├── .env.example
├── .gitignore
├── pytest.ini
├── requirements.txt
└── README.md
```

---

## Licence

Provided as an educational project. Not a medical device.

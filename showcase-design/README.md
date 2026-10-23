# Clearly — design-only medical-report explainer showcase

Open `index.html` directly or serve this folder with `python -m http.server 8000`. No reports can be uploaded, no results are analyzed, and no patient data is collected. The stage switcher only changes static explanatory text. The document illustration contains no clinical data or fabricated result.

Source: repository README on starting `main` (`44d837ac`) and its `frontend/`, `backend/` structure. The README describes React/Vite and FastAPI, PDF/image OCR, deterministic comparison against the **report's own reference range**, optional Gemini prose and a safety boundary: education, not diagnosis. This showcase is not the real frontend and does not claim that a live model, OCR engine or clinical service was tested. Seek qualified care for medical decisions.

Visual direction: quiet, readable health-information guide with soft lilac, midnight blue and citrus-yellow emphasis; Manrope for display, DM Sans for reading, Space Mono for process labels. The purely abstract document graphic avoids identifiable information. Source files outside `showcase-design/` are untouched.

Real rendered screenshots: `assets/screenshots/desktop.png`, `assets/screenshots/tablet.png`, `assets/screenshots/mobile.png`.

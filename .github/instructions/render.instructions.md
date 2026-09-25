---
applyTo: "render/**"
---
Rendering is stdlib Python + headless Chrome + pdftotext. Keep the text layer ATS-safe:
single column, no ligatures, real hyphens, no text in images. `render/ats_check.py` must
pass on every CV the change affects; run it. Never render a `TODO`. German output uses
reviewed `text_de` only and must never contain "Ingenieur" or "Ausbilder"
(`profile.example/de-glossary.json`).

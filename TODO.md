# TODO / Deferred options

Backlog of intentionally-deferred work, with the trigger that should promote each item. See
[`docs/design.md`](./docs/design.md) and [`docs/implementation-plan.md`](./docs/implementation-plan.md).

## Geometry OCR engine (Chandra / DeepSeek-OCR)

**Status:** deferred option · **Trigger:** Phase-1 metric — volume of scanned/image documents that
markitdown can't extract (routed to the human-classification queue).

v1 uses markitdown (text + char offsets, no bounding boxes) and flags text-less scans to a human
(design §5, §9). When the flagged-scan volume justifies it, add a self-hosted, layout-aware VLM OCR
engine — **Chandra OCR** (Datalab) or **DeepSeek-OCR** — evaluated on representative clinical docs:

- Keeps PHI **in-perimeter** (no third-party OCR of PHI); VLM-based, so no separate fallback engine.
- Produces text **and word-level geometry**, which:
  - lets scanned/image documents be extracted at all (not just flagged to human), and
  - **populates `provenance.bbox`**, unlocking pixel-level click-to-highlight on the original image
    (v1 highlights char-spans in the parsed text only).
- markitdown becomes the DOCX/text/spreadsheet fast path; OCR handles scans/images.
- Choose Chandra vs DeepSeek by benchmarking accuracy + box/grounding quality; box granularity drives
  provenance precision (word-level vs layout-block).

## Other deferred items

- **Additional extractors** — imaging, diagnoses, medications, procedures — authored against the DB
  registry (design §7); v1 ships `lab_report` + `genetics_report`.
- **Prefect work-pool autoscaling** — scale workers on queue backlog (KEDA / Cloud Run) once volume
  warrants; capped under the gemini rate limit (design §6).
- **Pydantic AI observability** — optional OpenTelemetry/Logfire, self-hosted with content capture off
  (PHI); off by default in v1 (design §10, §13).

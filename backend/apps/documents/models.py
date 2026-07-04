"""Normalized document + parsed text (design §3.1–3.2, §4).

A `SourceDocument` is one immutable ingested document (bytes in object storage,
metadata in the DB), deduplicated per patient by sha256. `DocumentText` is its
parsed text with character offsets, produced by markitdown (design §5).
"""
import os

from django.conf import settings
from django.db import models


def _upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    safe_patient = "".join(c if c.isalnum() or c in "-_" else "_" for c in instance.patient_ref)
    return f"documents/{safe_patient}/{instance.sha256}{ext}"


class Origin(models.TextChoices):
    MANUAL = "manual", "Manual upload"
    FHIR = "fhir", "FHIR sync"


class DocumentCategory(models.TextChoices):
    OFFICE_VISIT = "office_visit", "Office visit"
    DIAGNOSIS_HRV = "diagnosis_hrv", "Diagnosis / High-risk values"
    LABS = "labs", "Labs"
    BIOPSY = "biopsy", "Biopsy"
    IMAGING = "imaging", "Imaging"
    OTHER = "other", "Other"


class DocumentStatus(models.TextChoices):
    RECEIVED = "received", "Received"                       # ingested, not yet parsed
    PARSED = "parsed", "Parsed"                             # text extracted
    CLASSIFIED = "classified", "Classified"                # routed to ≥1 extractor type
    PARSE_FAILED = "parse_failed", "Parse failed"          # markitdown error
    NEEDS_CLASSIFICATION = "needs_classification", "Needs classification"  # scanned, or unclassified


class SourceDocument(models.Model):
    patient_ref = models.CharField(max_length=255, db_index=True)
    origin = models.CharField(max_length=16, choices=Origin.choices, default=Origin.MANUAL)

    file = models.FileField(upload_to=_upload_path)  # immutable original in object storage
    original_filename = models.CharField(max_length=512, blank=True, default="")
    mime = models.CharField(max_length=128)
    sha256 = models.CharField(max_length=64, db_index=True)
    byte_size = models.PositiveBigIntegerField(default=0)

    doc_datetime = models.DateTimeField(null=True, blank=True)  # clinical date (not extracted in Phase 1)
    fhir_document_reference_id = models.CharField(max_length=255, blank=True, default="")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    status = models.CharField(max_length=32, choices=DocumentStatus.choices, default=DocumentStatus.RECEIVED)

    # Review outcome (design §6 / SOP: categorize + mark verified)
    category = models.CharField(max_length=32, choices=DocumentCategory.choices, blank=True, default="")
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "source_document"
        constraints = [
            # sha256 dedup per patient (design §3.1)
            models.UniqueConstraint(fields=["patient_ref", "sha256"], name="uq_document_patient_sha256"),
        ]
        indexes = [models.Index(fields=["patient_ref", "status"])]

    def __str__(self):
        return f"doc#{self.pk} {self.original_filename or self.mime} ({self.patient_ref})"


class DocumentText(models.Model):
    """Parsed text for a document. One current version per document (re-parse
    overwrites; versioned rows come with the Prefect re-parse work later).
    `content` is the full markdown; `pages` describes offset segments so
    provenance can point into it (design §8/§9)."""

    document = models.OneToOneField(SourceDocument, on_delete=models.CASCADE, related_name="text")
    parser = models.CharField(max_length=64, default="markitdown")
    version = models.CharField(max_length=16, default="1")

    content = models.TextField(blank=True, default="")  # PHI
    char_len = models.PositiveIntegerField(default=0)
    pages = models.JSONField(default=list)  # [{index, char_start, char_end, char_len}]

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "document_text"

    def __str__(self):
        return f"text[{self.parser} v{self.version}] for doc#{self.document_id} ({self.char_len} chars)"


class ClassificationOutcome(models.TextChoices):
    ROUTED = "routed", "Routed"
    UNCLASSIFIED = "unclassified", "Unclassified"


class UnclassifiedReason(models.TextChoices):
    AMBIGUOUS = "ambiguous", "Ambiguous (low confidence)"
    OUT_OF_TAXONOMY = "out_of_taxonomy", "Out of taxonomy"


class DocumentClassification(models.Model):
    """Multi-label classification of a document (design §3.3, §4). Records the
    per-type scores, the types that cleared threshold, the routed/unclassified
    outcome (+ reason), and the immutable classifier version that produced it."""

    document = models.OneToOneField(SourceDocument, on_delete=models.CASCADE, related_name="classification")
    scores = models.JSONField(default=list)         # [{type, confidence}] over known types
    routed_types = models.JSONField(default=list)   # types at/above their threshold (may be empty)
    outcome = models.CharField(max_length=16, choices=ClassificationOutcome.choices)
    reason = models.CharField(max_length=20, choices=UnclassifiedReason.choices, blank=True, default="")

    classifier_version_id = models.PositiveIntegerField()  # soft ref → prompts.PromptVersion.id
    model = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "document_classification"

    def __str__(self):
        return f"classification doc#{self.document_id} {self.outcome} {self.routed_types}"


class ExtractionStatus(models.TextChoices):
    STAGED = "staged", "Staged"        # resolvable span, awaiting review
    FLAGGED = "flagged", "Flagged"     # span could not be resolved — needs a human
    APPROVED = "approved", "Approved"  # Phase 5
    REJECTED = "rejected", "Rejected"  # Phase 5


class ExtractionRecord(models.Model):
    """One extracted, provenance-bearing fact (design §3.4, §9). `payload` is the
    typed domain data; `provenance` carries the source span + the immutable
    extractor version that produced it."""

    document = models.ForeignKey(SourceDocument, on_delete=models.CASCADE, related_name="extractions")
    extractor_key = models.CharField(max_length=64)
    domain = models.CharField(max_length=32, blank=True, default="")
    payload = models.JSONField(default=dict)       # the fact's data (PHI)
    provenance = models.JSONField(default=dict)    # {document_id, page, char_start/end, snippet, extractor{…}, …} (PHI)
    extractor_version_id = models.PositiveIntegerField()  # 0 for reviewer-added manual facts
    confidence = models.FloatField(default=0.0)
    status = models.CharField(max_length=16, choices=ExtractionStatus.choices, default=ExtractionStatus.STAGED)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "extraction_record"
        indexes = [models.Index(fields=["document", "extractor_key"])]

    def __str__(self):
        return f"extraction doc#{self.document_id} {self.extractor_key} ({self.status})"

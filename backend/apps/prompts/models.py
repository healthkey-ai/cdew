"""DB-backed prompt registry (design §8).

A `PromptDefinition` is a stable registry entry (the classifier, or one extractor
per key). A `PromptVersion` is one revision — immutable once published. The
pipeline resolves the `active_version` at run time and records its id in
provenance so historical results stay reproducible.

Phase 3 seeds the classifier + extractor definitions and resolves the active
classifier. Extractor versions (prompt + JSON schema) and the authoring UI arrive
in Phase 4 / Phase 5.
"""
from django.conf import settings
from django.db import models


class PromptKind(models.TextChoices):
    CLASSIFIER = "classifier", "Classifier"
    EXTRACTOR = "extractor", "Extractor"


class PromptStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    ARCHIVED = "archived", "Archived"


class PromptDefinition(models.Model):
    kind = models.CharField(max_length=16, choices=PromptKind.choices)
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    domain = models.CharField(max_length=32, blank=True, default="")  # extractors (labs, genetics, …)
    enabled = models.BooleanField(default=True)
    triggers_on_types = models.JSONField(default=list)  # extractors: taxonomy types that route here
    active_version = models.ForeignKey(
        "prompts.PromptVersion", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "prompt_definition"

    def __str__(self):
        return f"{self.kind}:{self.key}"


class PromptVersion(models.Model):
    definition = models.ForeignKey(PromptDefinition, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=PromptStatus.choices, default=PromptStatus.DRAFT)

    prompt_text = models.TextField(blank=True, default="")
    json_schema = models.JSONField(default=dict)   # extractors (Phase 4)
    taxonomy = models.JSONField(default=list)      # classifier: [{type, description, threshold}]
    model = models.CharField(max_length=64, blank=True, default="")
    params = models.JSONField(default=dict)        # temperature, max_chars, low_floor, …

    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "prompt_version"
        constraints = [
            models.UniqueConstraint(fields=["definition", "version"], name="uq_prompt_version"),
        ]

    def __str__(self):
        return f"{self.definition.key} v{self.version} ({self.status})"


class PromptTestSample(models.Model):
    """A curated, already-parsed document used to dry-run draft versions (design
    §8.3). Scoped to one definition (a classifier or an extractor).

    ``expected_payload`` is the optional gold, interpreted by the definition kind:
    a **classifier** sample's gold is a list of expected type slugs (e.g.
    ``["lab_report"]``); an **extractor** sample's gold is a list of expected fact
    ``data`` objects."""

    definition = models.ForeignKey(
        "PromptDefinition", on_delete=models.CASCADE, related_name="test_samples", null=True, blank=True
    )
    document = models.ForeignKey("documents.SourceDocument", on_delete=models.CASCADE, related_name="+")
    label = models.CharField(max_length=128, blank=True, default="")
    expected_payload = models.JSONField(null=True, blank=True)  # optional gold (by kind, see above)
    # Last saved extraction for this sample (Extract): classifier → the result
    # object; extractor → the list of facts. Kept so it survives reloads and can
    # be compared against / copied into `expected_payload`.
    extracted_payload = models.JSONField(null=True, blank=True)
    extracted_version_id = models.PositiveIntegerField(null=True, blank=True)
    extracted_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "prompt_test_sample"

    def __str__(self):
        return self.label or f"sample#{self.pk} (doc {self.document_id})"

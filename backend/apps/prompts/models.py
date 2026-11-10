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


class ObjectType(models.Model):
    """One promop write target CDEW extracts (alignment §3–§4, #94): its source/raw
    field schema, synced from promop's OpenAPI (``catalog.py``,
    ``manage.py sync_object_types``), plus CDEW's extraction hints. Not
    author-editable — authors pick object types and add technique guidance."""

    key = models.SlugField(max_length=64, unique=True)   # the facts[] discriminator
    label = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    omop_target = models.CharField(max_length=64)          # promop table; code-lookup `omop_table`
    promop_endpoint = models.CharField(max_length=128)     # bulk-upsert target at commit (§8)
    source_schema = models.JSONField(default=dict)         # JSON Schema of the source/raw subset
    field_guide = models.JSONField(default=dict)           # {field: extraction hint}
    default_guidance = models.TextField(blank=True, default="")
    extraction_only = models.JSONField(default=list)       # CDEW-only fields, never committed (e.g. specimen)
    commit_required = models.JSONField(default=list)       # promop's required source fields at commit
    promop_required = models.JSONField(default=list)       # promop's whole required list — the commit contract (P4)
    promop_schema_version = models.CharField(max_length=64, blank=True, default="")
    sort_order = models.PositiveSmallIntegerField(default=0)
    synced_at = models.DateTimeField(null=True, blank=True)
    # CDEW-owned, never synced: flipped (Django admin) when this type's commit path
    # goes live (P5, #37). Then a promop-required field CDEW can't fill blocks
    # publishing an extractor that targets it (W101 → E110, schema-lint §5).
    commit_enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "object_type"
        ordering = ("sort_order", "key")

    def __str__(self):
        return self.key

    def definition(self) -> dict:
        """The definition a published version snapshots (alignment §9)."""
        from .catalog import SNAPSHOT_FIELDS

        return {f: getattr(self, f) for f in SNAPSHOT_FIELDS}


class DocumentType(models.Model):
    """One of promop's document types (``PatientDocument.doc_type``, P3 #97), synced
    from its OpenAPI with the object catalog. Each classifier taxonomy type names
    the one it corresponds to (``promop_doc_type``)."""

    code = models.CharField(max_length=50, unique=True)  # e.g. LAB_RESULTS
    label = models.CharField(max_length=128)
    sort_order = models.PositiveSmallIntegerField(default=0)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "document_type"
        ordering = ("sort_order", "code")

    def __str__(self):
        return self.code


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

    prompt_text = models.TextField(blank=True, default="")  # classifier; legacy extractors
    json_schema = models.JSONField(default=dict)   # legacy extractors: one authored `data` schema
    taxonomy = models.JSONField(default=list)      # classifier: [{type, description, threshold}]
    # Object-type extractors (alignment §4.2, #95). Set on the version, not the
    # definition, so changing what an extractor targets is a new version like any
    # other content change. A version with object_types is composed from the
    # catalog; one without is a legacy json_schema extractor.
    object_types = models.JSONField(default=list)  # [catalog key, …] — one or many
    guidance = models.JSONField(default=dict)      # {key: extraction-technique guidance}
    # Filled at publish: each targeted object type's definition (catalog.SNAPSHOT_FIELDS),
    # so a published version keeps running against the schemas it was tested on.
    object_type_snapshot = models.JSONField(default=dict)
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

    @property
    def is_object_typed(self) -> bool:
        return bool(self.object_types)

    def object_type_definitions(self) -> list[dict]:
        """The definitions this version extracts against, in its selection order:
        the publish-time snapshot, else (a draft) the live catalog."""
        if self.object_type_snapshot:
            return [self.object_type_snapshot[k] for k in self.object_types if k in self.object_type_snapshot]
        live = {o.key: o for o in ObjectType.objects.filter(key__in=self.object_types)}
        return [live[k].definition() for k in self.object_types if k in live]


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

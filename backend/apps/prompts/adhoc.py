"""Ad-hoc extraction: pick object types for one document (#114, alignment §6.2).

No authoring: the run uses a **transient version** on a system-owned `ad_hoc`
definition. The definition is never routed (``enabled=False``) and hidden from
the authoring API. Each version pins the selected object types and a snapshot of
their catalog definitions, and carries no guidance, so the composer builds the
zero-config prompt from the catalog's `default_guidance`. Provenance, review and
reproducibility then work exactly as for any published version.

An identical selection reuses its version while the catalog hasn't changed, so
re-running it replaces that run's facts (idempotency per `(document, version)`)
and a different selection adds facts beside them.
"""
from django.db.models import Max
from django.utils import timezone

from .lint.linter import lint_object_types
from .models import ObjectType, PromptDefinition, PromptKind, PromptVersion

AD_HOC_KEY = "ad_hoc"


class AdHocSelectionError(ValueError):
    """The selection fails the object-type lint; ``findings`` says why."""

    def __init__(self, findings):
        super().__init__("invalid object type selection")
        self.findings = findings


def ad_hoc_definition() -> PromptDefinition:
    definition, _ = PromptDefinition.objects.get_or_create(
        key=AD_HOC_KEY,
        defaults={
            "kind": PromptKind.EXTRACTOR,
            "name": "Ad-hoc extraction",
            "description": "System-owned: transient versions for per-document object-type picks (#114).",
            "enabled": False,  # never routed — runs only when a reviewer asks
            "triggers_on_types": [],
        },
    )
    return definition


def ad_hoc_version(object_types, *, user=None) -> PromptVersion:
    """The published transient version for this selection (reused when unchanged).
    Raises ``AdHocSelectionError`` for an empty, unknown or duplicated selection."""
    live = {o.key: o for o in ObjectType.objects.all()}
    catalog = {k: {**o.definition(), "commit_enabled": o.commit_enabled} for k, o in live.items()}
    findings = [f for f in lint_object_types(list(object_types or []), {}, catalog) if f.level == "error"]
    if findings:
        raise AdHocSelectionError(findings)

    keys = [k for k in live if k in set(object_types)]  # catalog order, de-duplicated
    snapshot = {k: live[k].definition() for k in keys}
    definition = ad_hoc_definition()
    for version in definition.versions.filter(status="published").order_by("-version"):
        if version.object_types == keys and version.object_type_snapshot == snapshot:
            return version
    return PromptVersion.objects.create(
        definition=definition,
        version=(definition.versions.aggregate(m=Max("version"))["m"] or 0) + 1,
        status="published",
        object_types=keys,
        guidance={},
        object_type_snapshot=snapshot,
        notes=f"Ad-hoc: {', '.join(keys)}",
        created_by=user if getattr(user, "is_authenticated", False) else None,
        published_at=timezone.now(),
    )

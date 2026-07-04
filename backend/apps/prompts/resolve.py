"""Resolve the active prompt versions the pipeline should run (design §8.2)."""
from .models import PromptDefinition, PromptKind, PromptVersion

CLASSIFIER_KEY = "document_classifier"


class NoActiveVersion(Exception):
    pass


def get_active_classifier() -> PromptVersion:
    try:
        definition = PromptDefinition.objects.select_related("active_version").get(
            kind=PromptKind.CLASSIFIER, key=CLASSIFIER_KEY, enabled=True
        )
    except PromptDefinition.DoesNotExist as exc:
        raise NoActiveVersion("No enabled classifier definition.") from exc
    if definition.active_version is None:
        raise NoActiveVersion("Classifier has no active (published) version.")
    return definition.active_version


def resolve_extractors(routed_types) -> list[PromptDefinition]:
    """Enabled extractor definitions whose triggers intersect the routed types.

    Used to fan out extraction in Phase 4; returned here so routing is testable now.
    """
    wanted = set(routed_types)
    out = []
    for ext in PromptDefinition.objects.filter(kind=PromptKind.EXTRACTOR, enabled=True):
        if wanted.intersection(ext.triggers_on_types):
            out.append(ext)
    return out

"""Prefect flow wrapping the pipeline orchestrator (design §6).

Prefect runs each flow run in a **fresh subprocess** (the runner's flow-run
executor), which has *not* called ``django.setup()`` — so the flow must configure
Django before importing anything ORM, or model import raises ``AppRegistryNotReady``.
The thin wrapper delegates to ``service.execute_pipeline`` so job-state transitions
live in one place; per-task retries + the gemini concurrency limit arrive with the
LLM tasks (#54).
"""
import os

from prefect import flow


def _ensure_django() -> None:
    """Configure Django in the flow-run process if it isn't already (design §6).
    No-op in-process (tests / `local` dispatch); does the real setup in Prefect's
    execution subprocess, which inherits ``DJANGO_SETTINGS_MODULE`` but never ran
    ``django.setup()``."""
    from django.apps import apps

    if apps.ready:
        return
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    django.setup()


@flow(name="extract-document")
def extract_document(job_id: int):
    _ensure_django()
    # Delegate to the plain orchestrator so job-state transitions live in one
    # place (service.execute_pipeline), whether run under Prefect or locally.
    from .service import execute_pipeline

    execute_pipeline(job_id)

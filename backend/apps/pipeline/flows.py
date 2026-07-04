"""Prefect flow wrapping the pipeline orchestrator (design §6).

The worker process must configure Django (DJANGO_SETTINGS_MODULE + django.setup())
so tasks use the ORM. Phase 2 is a thin wrapper for observability; per-task
retries + the gemini global concurrency limit are added with the LLM tasks in
Phase 3/4.
"""
from prefect import flow


@flow(name="extract-document")
def extract_document(job_id: int):
    # Delegate to the plain orchestrator so job-state transitions live in one
    # place (service.execute_pipeline), whether run under Prefect or locally.
    from .service import execute_pipeline

    execute_pipeline(job_id)

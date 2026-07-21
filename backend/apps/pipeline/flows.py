"""Prefect flow wrapping the pipeline orchestrator (design §6).

Prefect runs each flow run in a **fresh subprocess** (the runner's flow-run
executor), which has *not* called ``django.setup()`` — so the flow must configure
Django before importing anything ORM, or model import raises ``AppRegistryNotReady``.
The thin wrapper delegates to ``service.execute_pipeline`` so job-state transitions
live in one place; per-task retries + the gemini concurrency limit arrive with the
LLM tasks (#54).
"""
import os
from pathlib import Path

from prefect import flow


def _django_root() -> Path | None:
    """Find the Django project root — the dir with ``manage.py`` + the ``apps/``
    package — by walking up from this file and the cwd. Robust to how Prefect's
    flow-from-storage loader sets ``__file__`` / cwd (which aren't the backend dir)."""
    for start in (Path(__file__).resolve(), Path.cwd().resolve()):
        for d in (start, *start.parents):
            if (d / "manage.py").is_file() and (d / "apps" / "__init__.py").is_file():
                return d
    return None


def _ensure_django() -> bool:
    """Configure Django in the flow-run process if it isn't already (design §6).
    No-op in-process (tests / `local` / `thread` dispatch — Django already set up);
    does the real setup in Prefect's execution subprocess, which inherits
    ``DJANGO_SETTINGS_MODULE`` but never ran ``django.setup()``. Returns True only
    when this call performed the setup (i.e. we own the connection's teardown)."""
    from django.apps import apps

    if apps.ready:
        return False
    import sys

    import django

    root = _django_root()
    if root:
        # Prefect puts the flow file's own dir (…/apps/pipeline, which contains an
        # `apps.py` AppConfig) on sys.path[0] — that shadows the top-level `apps`
        # *package* as a module ("'apps' is not a package"). Force the Django project
        # root to the very front (dedup) so `apps` / `config` resolve to the packages.
        rs = str(root)
        sys.path[:] = [rs] + [p for p in sys.path if p != rs]
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    django.setup()
    return True


@flow(name="extract-document")
def extract_document(job_id: int):
    owns_django = _ensure_django()
    # Delegate to the plain orchestrator so job-state transitions live in one
    # place (service.execute_pipeline); inject the Prefect task runner so the LLM
    # steps run as retried, concurrency-capped tasks (#54).
    # Absolute imports: Prefect loads this flow file under a non-canonical module
    # name, so relative imports (`.service`) would build a duplicate module tree and
    # re-register the models. `apps.pipeline.*` always resolves to the real package.
    from apps.pipeline.service import execute_pipeline
    from apps.pipeline.tasks import PrefectRunner

    try:
        execute_pipeline(job_id, runner=PrefectRunner())
    finally:
        _close_django(owns_django)


@flow(name="dry-run")
def dry_run_flow(job_id: int):
    owns_django = _ensure_django()
    # Async Test Set dry-run (#55): fan out one gemini task per sample; job-state
    # transitions stay in dryrun.execute_dry_run.
    from apps.pipeline.dryrun import execute_dry_run
    from apps.pipeline.tasks import DryRunPrefectRunner

    try:
        execute_dry_run(job_id, runner=DryRunPrefectRunner())
    finally:
        _close_django(owns_django)


@flow(name="geometry")
def geometry_flow(doc_id: int):
    owns_django = _ensure_django()
    # On-demand geometry for the review overlay (#67): Doc AI call as a task;
    # DocumentGeometry state transitions stay in geometry.execute_geometry.
    from apps.documents.geometry.service import execute_geometry
    from apps.pipeline.tasks import GeometryPrefectRunner

    try:
        execute_geometry(doc_id, runner=GeometryPrefectRunner())
    finally:
        _close_django(owns_django)


def _close_django(owns_django: bool) -> None:
    # Only in the Prefect execution subprocess we configured: close its Django DB
    # connection so it isn't reported leaked at interpreter shutdown. Skipped
    # in-process (tests / `local` / `thread`) — closing there would break the
    # caller's connection/transaction. (The pydantic-ai event-loop/HTTP-transport
    # ResourceWarnings are its own internals and remain.)
    if owns_django:
        from django.db import connections

        connections.close_all()

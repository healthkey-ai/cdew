"""Pluggable dispatch for the extract-document flow (design §6), mirroring
hk-labs' TASK_BACKEND pattern:

  - ``local``      — run synchronously in-process (tests, and the simplest dev).
                     No Prefect runtime imported, so CI stays hermetic.
  - ``thread``     — run the Prefect flow in a background thread (dev: upload
                     returns immediately, flow runs via Prefect's ephemeral API).
  - ``deployment`` — trigger a registered Prefect deployment on the self-hosted
                     server (staging/prod); store the flow_run_id on the job.

Selected by ``settings.PREFECT_DISPATCH``.
"""
import logging
import threading

from django.conf import settings

from .models import DryRunJob, ExtractionJob

logger = logging.getLogger("apps.pipeline")


def dispatch_extract(job_id: int) -> None:
    backend = getattr(settings, "PREFECT_DISPATCH", "local")
    if backend == "deployment":
        _dispatch_deployment(job_id)
    elif backend == "thread":
        threading.Thread(target=_run_flow, args=(job_id,), daemon=True).start()
    else:  # local
        from .service import execute_pipeline

        execute_pipeline(job_id)


def _run_flow(job_id: int) -> None:
    try:
        from .flows import extract_document

        extract_document(job_id)
    except Exception:
        logger.warning("pipeline: flow thread crashed job=%s", job_id)


def _dispatch_deployment(job_id: int) -> None:
    from prefect.deployments import run_deployment

    run = run_deployment(
        name=settings.PREFECT_DEPLOYMENT,
        parameters={"job_id": job_id},
        timeout=0,  # return immediately; don't wait for completion
    )
    ExtractionJob.objects.filter(id=job_id).update(prefect_flow_run_id=str(getattr(run, "id", "")))


def dispatch_dry_run(job_id: int) -> None:
    """Dispatch a DryRunJob (#55), mirroring dispatch_extract — same backends."""
    backend = getattr(settings, "PREFECT_DISPATCH", "local")
    if backend == "deployment":
        _dispatch_dry_run_deployment(job_id)
    elif backend == "thread":
        threading.Thread(target=_run_dry_run_flow, args=(job_id,), daemon=True).start()
    else:  # local
        from .dryrun import execute_dry_run

        execute_dry_run(job_id)


def _run_dry_run_flow(job_id: int) -> None:
    try:
        from .flows import dry_run_flow

        dry_run_flow(job_id)
    except Exception:
        logger.warning("dryrun: flow thread crashed job=%s", job_id)


def _dispatch_dry_run_deployment(job_id: int) -> None:
    from prefect.deployments import run_deployment

    run = run_deployment(
        name=settings.PREFECT_DRYRUN_DEPLOYMENT,
        parameters={"job_id": job_id},
        timeout=0,
    )
    DryRunJob.objects.filter(id=job_id).update(prefect_flow_run_id=str(getattr(run, "id", "")))

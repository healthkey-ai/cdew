"""Run the local Prefect serve process for the extract-document flow (design §6, #53).

This is the dev "worker": it registers the deployment named by
``settings.PREFECT_DEPLOYMENT`` (default ``extract-document/default``) and then
blocks, executing runs triggered by the API's ``run_deployment`` call
(``PREFECT_DISPATCH=deployment``). Because it runs under ``manage.py``, Django is
configured, so flow tasks have ORM access.

Local dev loop (three terminals):

    make prefect-server      # Prefect API + UI on http://localhost:4200
    make prefect-worker      # this command (has Django/ORM)
    python manage.py runserver

Prefect is imported lazily here so the hermetic ``local`` dispatch/test path never
loads a Prefect runtime.
"""
import os

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Serve the extract-document + dry-run Prefect deployments locally (executes runs the API triggers)."

    def handle(self, *args, **options):
        from prefect import serve

        from apps.pipeline.flows import dry_run_flow, extract_document, geometry_flow

        # Prefect runs each flow in a subprocess that loads the flow "from storage"
        # without the Django project root importable — so `django.setup()` there
        # can't find `apps.*` / `config.*`. Put the root on PYTHONPATH; the
        # subprocess inherits it (reliable, unlike deriving it from __file__/cwd).
        os.environ["PYTHONPATH"] = os.pathsep.join(
            p for p in (str(settings.BASE_DIR), os.environ.get("PYTHONPATH", "")) if p
        )

        extract_dep = _dep_name(getattr(settings, "PREFECT_DEPLOYMENT", "extract-document/default"))
        dryrun_dep = _dep_name(getattr(settings, "PREFECT_DRYRUN_DEPLOYMENT", "dry-run/default"))
        geometry_dep = _dep_name(getattr(settings, "PREFECT_GEOMETRY_DEPLOYMENT", "geometry/default"))

        if not os.environ.get("PREFECT_API_URL"):
            self.stdout.write(
                self.style.WARNING(
                    "PREFECT_API_URL is not set — Prefect will fall back to an ephemeral local API "
                    "(no shared server/UI). Start `make prefect-server` and set "
                    "PREFECT_API_URL=http://127.0.0.1:4200/api to use the server."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Serving '{extract_document.name}/{extract_dep}' + '{dry_run_flow.name}/{dryrun_dep}' + "
                f"'{geometry_flow.name}/{geometry_dep}'. "
                "Trigger via upload / test-set Extract / review while PREFECT_DISPATCH=deployment. Ctrl-C to stop."
            )
        )
        # Blocks: registers the deployments and polls for scheduled runs.
        serve(
            extract_document.to_deployment(name=extract_dep),
            dry_run_flow.to_deployment(name=dryrun_dep),
            geometry_flow.to_deployment(name=geometry_dep),
        )


def _dep_name(deployment: str) -> str:
    _, _, name = deployment.partition("/")
    return name or "default"

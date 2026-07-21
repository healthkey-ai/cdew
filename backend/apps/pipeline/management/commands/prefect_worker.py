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
    help = "Serve the extract-document Prefect deployment locally (executes runs triggered by the API)."

    def handle(self, *args, **options):
        from apps.pipeline.flows import extract_document

        deployment = getattr(settings, "PREFECT_DEPLOYMENT", "extract-document/default")
        flow_name, _, dep_name = deployment.partition("/")
        dep_name = dep_name or "default"
        if flow_name and flow_name != extract_document.name:
            self.stderr.write(
                self.style.WARNING(
                    f"PREFECT_DEPLOYMENT flow '{flow_name}' != flow '{extract_document.name}' — "
                    "run_deployment will not find this deployment."
                )
            )

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
                f"Serving deployment '{extract_document.name}/{dep_name}'. "
                "Trigger it with an upload while PREFECT_DISPATCH=deployment. Ctrl-C to stop."
            )
        )
        # Blocks: registers the deployment and polls for scheduled runs.
        extract_document.serve(name=dep_name)

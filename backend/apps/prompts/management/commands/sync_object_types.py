"""Refresh the object catalog from promop's OpenAPI (alignment §5, #94).

    manage.py sync_object_types                    # live: $PROMOP_BASE_URL/api/v1/schema/
    manage.py sync_object_types --file schema.json # a downloaded schema
    manage.py sync_object_types --fixture          # the captured fixture (what migrations seed)
    manage.py sync_object_types --dry-run          # report changes, write nothing
    manage.py sync_object_types --save-fixture     # also refresh the captured fixture

Idempotent: unchanged types are left alone. A type promop no longer publishes is
reported, not deleted — published versions snapshot their definitions anyway.
Only affects future published versions; existing ones keep their snapshot.
"""
import json

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.prompts import catalog
from apps.prompts.models import ObjectType

_COMPARED = (*catalog.SNAPSHOT_FIELDS, "sort_order")


class Command(BaseCommand):
    help = "Sync the extraction object catalog from promop's OpenAPI schema."

    def add_arguments(self, parser):
        src = parser.add_mutually_exclusive_group()
        src.add_argument("--url", help="OpenAPI URL (default: PROMOP_BASE_URL + /api/v1/schema/).")
        src.add_argument("--file", help="Read the OpenAPI document from a file.")
        src.add_argument("--fixture", action="store_true", help="Use the captured fixture.")
        parser.add_argument("--dry-run", action="store_true", help="Report changes without writing.")
        parser.add_argument("--save-fixture", action="store_true", help="Overwrite the captured fixture.")

    def handle(self, *args, **opts):
        openapi = self._load(opts)
        try:
            definitions = catalog.derive_object_types(openapi)
        except ValueError as exc:
            raise CommandError(str(exc)) from None

        existing = {o.key: o for o in ObjectType.objects.all()}
        now = timezone.now()
        for d in definitions:
            row = existing.get(d["key"])
            if row is None:
                self.stdout.write(f"+ {d['key']} (new)")
                if not opts["dry_run"]:
                    ObjectType.objects.create(**d, synced_at=now)
                continue
            changed = [f for f in _COMPARED if getattr(row, f) != d[f]]
            if not changed:
                self.stdout.write(f"= {d['key']}")
                continue
            self.stdout.write(f"~ {d['key']}: {', '.join(changed)}")
            if not opts["dry_run"]:
                for f in _COMPARED:
                    setattr(row, f, d[f])
                row.synced_at = now
                row.save()
        for key in sorted(set(existing) - {d["key"] for d in definitions}):
            self.stdout.write(self.style.WARNING(f"! {key}: no longer derived from promop (kept)"))
        for key, fields in catalog.unguided_fields(definitions).items():
            self.stdout.write(self.style.WARNING(f"? {key}: no extraction hint for {', '.join(fields)} (catalog.OVERLAY)"))

        if opts["save_fixture"] and not opts["dry_run"]:
            doc = {"_comment": json.loads(catalog.FIXTURE.read_text()).get("_comment", ""),
                   **catalog.trim_openapi(openapi)}
            catalog.FIXTURE.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
            self.stdout.write(f"fixture saved: {catalog.FIXTURE}")
        self.stdout.write(self.style.SUCCESS("dry run — nothing written" if opts["dry_run"] else "catalog synced"))

    def _load(self, opts) -> dict:
        if opts["fixture"]:
            return catalog.load_fixture()
        if opts["file"]:
            with open(opts["file"]) as fh:
                return json.load(fh)
        url = opts["url"] or (settings.PROMOP_BASE_URL.rstrip("/") + "/api/v1/schema/" if settings.PROMOP_BASE_URL else "")
        if not url:
            raise CommandError("Set PROMOP_BASE_URL, or pass --url, --file or --fixture.")
        try:
            resp = httpx.get(url, params={"format": "json"}, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CommandError(f"Could not read promop's OpenAPI ({type(exc).__name__}).") from None

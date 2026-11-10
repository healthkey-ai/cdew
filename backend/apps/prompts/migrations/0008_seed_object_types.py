"""Seed the object catalog from the captured promop OpenAPI fixture (#94).

A fresh database (CI, a new environment) gets the five object types without
calling promop. `manage.py sync_object_types` refreshes them from a live promop.
"""
from django.db import migrations
from django.utils import timezone


def seed(apps, schema_editor):
    from apps.prompts.catalog import derive_object_types, load_fixture

    ObjectType = apps.get_model("prompts", "ObjectType")
    now = timezone.now()
    for d in derive_object_types(load_fixture()):
        ObjectType.objects.update_or_create(key=d["key"], defaults={**d, "synced_at": now})


def unseed(apps, schema_editor):
    apps.get_model("prompts", "ObjectType").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("prompts", "0007_object_catalog")]
    operations = [migrations.RunPython(seed, unseed)]

from django.contrib import admin

from .models import ObjectType, PromptDefinition, PromptVersion


@admin.register(ObjectType)
class ObjectTypeAdmin(admin.ModelAdmin):
    """The catalog is synced from promop (`sync_object_types`); the only field a
    person sets is `commit_enabled` — flipped when the type's commit path goes
    live (P5, #37), which turns its W101 lint into the E110 publish gate."""

    list_display = ("key", "label", "omop_target", "commit_enabled", "promop_schema_version", "synced_at")
    list_editable = ("commit_enabled",)
    fields = ("commit_enabled", "key", "label", "omop_target", "promop_endpoint", "promop_required",
              "commit_required", "promop_schema_version", "synced_at")
    readonly_fields = tuple(f for f in fields if f != "commit_enabled")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PromptVersionInline(admin.TabularInline):
    model = PromptVersion
    fk_name = "definition"
    extra = 0
    fields = ("version", "status", "model", "published_at")
    readonly_fields = ("created_at",)


@admin.register(PromptDefinition)
class PromptDefinitionAdmin(admin.ModelAdmin):
    list_display = ("key", "kind", "domain", "enabled", "active_version")
    list_filter = ("kind", "enabled")
    search_fields = ("key", "name")
    inlines = [PromptVersionInline]


@admin.register(PromptVersion)
class PromptVersionAdmin(admin.ModelAdmin):
    list_display = ("definition", "version", "status", "model", "published_at")
    list_filter = ("status", "definition__kind")
    search_fields = ("definition__key",)

from django.contrib import admin

from .models import PromptDefinition, PromptVersion


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

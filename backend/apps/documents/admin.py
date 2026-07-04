from django.contrib import admin

from .models import DocumentText, SourceDocument


@admin.register(SourceDocument)
class SourceDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "patient_ref", "original_filename", "mime", "status", "byte_size", "created_at")
    list_filter = ("status", "origin", "mime")
    search_fields = ("patient_ref", "sha256", "original_filename")
    readonly_fields = ("sha256", "byte_size", "created_at", "updated_at")


@admin.register(DocumentText)
class DocumentTextAdmin(admin.ModelAdmin):
    list_display = ("document", "parser", "version", "char_len", "updated_at")
    search_fields = ("document__patient_ref",)

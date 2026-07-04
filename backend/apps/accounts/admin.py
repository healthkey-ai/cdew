from django.contrib import admin

from .models import Identity, RoleAssignment


class RoleAssignmentInline(admin.TabularInline):
    model = RoleAssignment
    fk_name = "identity"
    extra = 0
    autocomplete_fields = ("granted_by",)


@admin.register(Identity)
class IdentityAdmin(admin.ModelAdmin):
    list_display = ("id", "email", "issuer", "sub", "is_staff", "is_active")
    search_fields = ("email", "sub")
    list_filter = ("issuer", "is_staff", "is_active")
    inlines = [RoleAssignmentInline]


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("identity", "role", "granted_at", "granted_by")
    list_filter = ("role",)
    search_fields = ("identity__email",)
    autocomplete_fields = ("identity", "granted_by")

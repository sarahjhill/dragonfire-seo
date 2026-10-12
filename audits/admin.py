import csv

from django.contrib import admin
from django.http import HttpResponse
from django.urls import reverse
from django.utils.html import format_html

from .models import Audit, Lead


@admin.register(Audit)
class AuditAdmin(admin.ModelAdmin):
    list_display = ("domain", "brand", "score", "heat", "created", "open_report")
    search_fields = ("domain", "brand", "target")
    readonly_fields = ("results",)

    @admin.display(description="Report")
    def open_report(self, obj):
        return format_html('<a href="{}" target="_blank">Open →</a>', reverse("audits:report", args=[obj.pk]))


@admin.action(description="Download selected leads as CSV")
def export_csv(modeladmin, request, queryset):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="dragonfire-leads.csv"'
    w = csv.writer(response)
    w.writerow(["Date", "Name", "Email", "Business", "What they do", "Town", "Website", "Score", "Status", "Consent", "Tips emails", "Tips opt-in date"])
    for l in queryset:
        w.writerow([l.created.date(), l.name, l.email, l.business, l.service, l.town, l.website,
                    l.score, l.get_status_display(), "yes" if l.consent else "no",
                    "yes" if l.newsletter_optin else "no", l.newsletter_optin_at or ""])
    return response


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("created", "name", "business", "town", "score", "status", "newsletter_optin", "website_link", "report")
    list_filter = ("status", "newsletter_optin", "town", "consent")
    list_editable = ("status",)
    search_fields = ("name", "email", "business", "website")
    readonly_fields = ("token", "audit", "created", "consent", "newsletter_optin", "newsletter_optin_at")
    actions = [export_csv]

    @admin.display(description="Website")
    def website_link(self, obj):
        url = obj.website if obj.website.startswith("http") else f"https://{obj.website}"
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, obj.website)

    @admin.display(description="Full report")
    def report(self, obj):
        if not obj.audit:
            return "—"
        return format_html('<a href="{}" target="_blank">Open →</a>', reverse("audits:report", args=[obj.audit.pk]))

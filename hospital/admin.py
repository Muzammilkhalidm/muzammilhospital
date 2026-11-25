from django.contrib import admin

from . import models

admin.site.site_header = "Muzammil's Hospital - Django Admin"
admin.site.register(models.Doctor)
admin.site.register(models.Patient)
admin.site.register(models.Appointment)
admin.site.register(models.AdminProfile)


class ItemInline(admin.TabularInline):
    model = models.PrescriptionItem
    extra = 0


@admin.register(models.Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ("code", "patient_name", "doctor", "status", "fee", "paid_at")
    list_filter = ("status",)
    inlines = [ItemInline]

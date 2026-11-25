from django.conf import settings

from .models import Doctor
from .roles import get_role


def hospital(request):
    ctx = {"HOSPITAL_NAME": settings.HOSPITAL_NAME, "CURRENCY": settings.CURRENCY}
    user = request.user
    if user.is_authenticated:
        role = get_role(user)
        ctx["role"] = role
        ctx["is_main_admin"] = user.is_superuser
        if role == "admin":
            ctx["me"] = user.admin_profile
            ctx["pending_doctors_count"] = Doctor.objects.filter(status=Doctor.PENDING).count()
        elif role == "doctor":
            ctx["me"] = user.doctor
        elif role == "patient":
            ctx["me"] = user.patient
        elif hasattr(user, "doctor"):
            ctx["me"] = user.doctor
    return ctx

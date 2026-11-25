from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

from .models import AdminProfile


def get_role(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        AdminProfile.objects.get_or_create(user=user)
        return "admin"
    if hasattr(user, "admin_profile"):
        return "admin" if user.admin_profile.can_work else None
    if hasattr(user, "doctor"):
        return "doctor"
    if hasattr(user, "patient"):
        return "patient"
    return None


def role_required(role, main_admin_only=False):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"/login/?next={request.path}")
            if get_role(request.user) != role:
                messages.error(request, "You do not have access to that page.")
                return redirect("go")
            if main_admin_only and not request.user.is_superuser:
                messages.error(request, "Only the main admin can open that page.")
                return redirect("admin-dashboard")
            if role == "doctor" and not request.user.doctor.is_approved:
                return redirect("doctor-status")
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


admin_required = role_required("admin")
main_admin_required = role_required("admin", main_admin_only=True)
doctor_required = role_required("doctor")
patient_required = role_required("patient")

from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect


class TemporaryAdminExpiryMiddleware:
    """Logs out temporary admins whose access has expired or been switched off."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and not user.is_superuser:
            profile = getattr(user, "admin_profile", None)
            if profile is not None and not profile.can_work:
                logout(request)
                messages.error(request, "Your temporary admin access has ended. Please contact the main admin.")
                return redirect("login")
        return self.get_response(request)

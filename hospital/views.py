import calendar
from pathlib import Path
from datetime import date, datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import archive, forms
from .models import AdminProfile, Appointment, Doctor, Patient, PrescriptionItem, Visit
from .roles import (admin_required, doctor_required, get_role, main_admin_required,
                    patient_required)


# --------------------------------------------------------------------------- helpers
def _today_range():
    now = timezone.localtime()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _sum(qs, field):
    return qs.aggregate(t=Sum(field))["t"] or 0


def _month_start():
    now = timezone.localtime()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _last_7_days(paid_qs):
    """Return a list of (label, amount, percent_height) for the revenue bars."""
    today = timezone.localtime().date()
    rows = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        s = timezone.make_aware(datetime.combine(d, datetime.min.time()))
        total = _sum(paid_qs.filter(paid_at__gte=s, paid_at__lt=s + timedelta(days=1)), "fee")
        rows.append({"label": d.strftime("%a"), "date": d, "total": total})
    peak = max([r["total"] for r in rows] + [1])
    for r in rows:
        r["pct"] = max(4, int(r["total"] * 100 / peak)) if r["total"] else 4
    return rows


# --------------------------------------------------------------------------- public + auth
def home(request):
    doctors = Doctor.objects.filter(status=Doctor.APPROVED).select_related("user")[:8]
    stats = {
        "doctors": Doctor.objects.filter(status=Doctor.APPROVED).count(),
        "patients": Patient.objects.count(),
        "checkups": Visit.objects.filter(status=Visit.PAID).count(),
    }
    return render(request, "public/home.html", {"doctors": doctors, "stats": stats})


class StyledAuthForm(AuthenticationForm):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields["username"].widget.attrs.update({"class": "input", "placeholder": "Username", "autofocus": True})
        self.fields["password"].widget.attrs.update({"class": "input", "placeholder": "Password"})


class HospitalLoginView(LoginView):
    template_name = "public/login.html"
    authentication_form = StyledAuthForm
    redirect_authenticated_user = True


def go(request):
    """Send each user to the right home page after login."""
    if not request.user.is_authenticated:
        return redirect("login")
    role = get_role(request.user)
    if role == "admin":
        return redirect("admin-dashboard")
    if role == "doctor":
        return redirect("doctor-dashboard")
    if role == "patient":
        return redirect("patient-dashboard")
    if hasattr(request.user, "doctor"):
        return redirect("doctor-status")
    logout(request)
    messages.error(request, "This account has no access. Please contact the hospital.")
    return redirect("login")


def logout_view(request):
    logout(request)
    return redirect("home")


def register_patient(request):
    if request.user.is_authenticated:
        return redirect("go")
    form = forms.PatientRegisterForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
        messages.success(request, "Registration complete. You can sign in now.")
        return redirect("login")
    return render(request, "public/register_patient.html", {"form": form})


def register_doctor(request):
    if request.user.is_authenticated:
        return redirect("go")
    form = forms.DoctorRegisterForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
        messages.success(request, "Application sent. The admin will review your degree and approve your account.")
        return redirect("login")
    return render(request, "public/register_doctor.html", {"form": form, "year": date.today().year})


def doctor_status(request):
    if not request.user.is_authenticated or not hasattr(request.user, "doctor"):
        return redirect("go")
    doc = request.user.doctor
    if doc.is_approved:
        return redirect("doctor-dashboard")
    return render(request, "doctor/status.html", {"doctor": doc})


# --------------------------------------------------------------------------- shared: profile + password
class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        for f in self.fields.values():
            f.widget.attrs["class"] = "input"


class PasswordChange(SuccessMessageMixin, PasswordChangeView):
    template_name = "shared/password_change.html"
    form_class = StyledPasswordChangeForm
    success_url = reverse_lazy("profile")
    success_message = "Your password was changed successfully."


def _profile_form_class(role):
    return {"admin": forms.AdminProfileForm, "doctor": forms.DoctorProfileForm,
            "patient": forms.PatientProfileForm}[role]


def profile(request):
    if not request.user.is_authenticated:
        return redirect("login")
    role = get_role(request.user)
    if role is None:
        return redirect("go")
    if role == "doctor" and not request.user.doctor.is_approved:
        return redirect("doctor-status")
    obj = {"admin": lambda u: u.admin_profile, "doctor": lambda u: u.doctor, "patient": lambda u: u.patient}[role](request.user)
    user_form = forms.UserBasicsForm(request.POST or None, instance=request.user, prefix="u")
    prof_form = _profile_form_class(role)(request.POST or None, request.FILES or None, instance=obj, prefix="p")
    if request.method == "POST" and user_form.is_valid() and prof_form.is_valid():
        user_form.save()
        prof_form.save()
        messages.success(request, "Profile updated.")
        return redirect("profile")
    return render(request, "shared/profile.html", {"user_form": user_form, "prof_form": prof_form, "obj": obj})


# --------------------------------------------------------------------------- shared: visit detail / print
def _can_view_visit(user, visit):
    role = get_role(user)
    if role == "admin":
        return visit.status != Visit.DRAFT
    if role == "doctor":
        return visit.doctor.user_id == user.id
    if role == "patient":
        return visit.patient.user_id == user.id and visit.status == Visit.PAID
    return False


def _get_visit(request, pk):
    if not request.user.is_authenticated:
        return None
    visit = get_object_or_404(Visit.objects.select_related("patient__user", "doctor__user").prefetch_related("items"), pk=pk)
    if not _can_view_visit(request.user, visit):
        raise Http404()
    return visit


def visit_detail(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/login/?next={request.path}")
    visit = _get_visit(request, pk)
    role = get_role(request.user)
    ctx = {"visit": visit}
    if role == "admin" and visit.status == Visit.SUBMITTED:
        ctx["pay_form"] = forms.PaymentForm(initial={"fee": visit.doctor.consultation_fee, "payment_method": "Cash"})
    return render(request, "shared/visit_detail.html", ctx)


def visit_print(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/login/?next={request.path}")
    visit = _get_visit(request, pk)
    show_fee = get_role(request.user) in ("admin", "patient") and visit.fee is not None
    return render(request, "shared/visit_print.html", {"visit": visit, "show_fee": show_fee, "standalone": False})


# --------------------------------------------------------------------------- ADMIN
@admin_required
def admin_dashboard(request):
    start, end = _today_range()
    paid = Visit.objects.filter(status=Visit.PAID)
    ctx = {
        "doctors_count": Doctor.objects.filter(status=Doctor.APPROVED).count(),
        "pending_doctors": Doctor.objects.filter(status=Doctor.PENDING).select_related("user")[:5],
        "patients_count": Patient.objects.count(),
        "today_checkups": Visit.objects.filter(created_at__gte=start, created_at__lt=end).exclude(status=Visit.DRAFT).count(),
        "awaiting": Visit.objects.filter(status=Visit.SUBMITTED).count(),
        "today_revenue": _sum(paid.filter(paid_at__gte=start, paid_at__lt=end), "fee"),
        "month_revenue": _sum(paid.filter(paid_at__gte=_month_start()), "fee"),
        "month_hospital": _sum(paid.filter(paid_at__gte=_month_start()), "hospital_amount"),
        "month_doctors": _sum(paid.filter(paid_at__gte=_month_start()), "doctor_amount"),
        "awaiting_list": Visit.objects.filter(status=Visit.SUBMITTED).select_related("doctor__user", "patient__user").order_by("submitted_at")[:6],
        "recent_paid": paid.select_related("doctor__user").order_by("-paid_at")[:6],
        "bars": _last_7_days(paid),
        "booked_today": Appointment.objects.filter(date=timezone.localdate(), status=Appointment.BOOKED).count(),
    }
    return render(request, "panel/dashboard.html", ctx)


@admin_required
def admin_doctor_requests(request):
    pending = Doctor.objects.filter(status=Doctor.PENDING).select_related("user").order_by("applied_at")
    decided = Doctor.objects.exclude(status=Doctor.PENDING).select_related("user").order_by("-reviewed_at")[:15]
    return render(request, "panel/doctor_requests.html",
                  {"pending": pending, "decided": decided, "reject_form": forms.RejectForm()})


@admin_required
@require_POST
def approve_doctor(request, pk):
    doc = get_object_or_404(Doctor, pk=pk)
    doc.status = Doctor.APPROVED
    doc.rejection_reason = ""
    doc.reviewed_at = timezone.now()
    doc.save()
    messages.success(request, f"{doc.display_name} approved. The doctor can now sign in and treat patients.")
    return redirect(request.POST.get("next") or "admin-doctor-requests")


@admin_required
@require_POST
def reject_doctor(request, pk):
    doc = get_object_or_404(Doctor, pk=pk)
    form = forms.RejectForm(request.POST)
    doc.status = Doctor.REJECTED
    doc.rejection_reason = form.cleaned_data["reason"] if form.is_valid() else "Application rejected by admin."
    doc.reviewed_at = timezone.now()
    doc.save()
    messages.warning(request, f"{doc.display_name} was rejected.")
    return redirect("admin-doctor-requests")


@admin_required
def admin_doctors(request):
    q = request.GET.get("q", "").strip()
    qs = Doctor.objects.filter(status=Doctor.APPROVED).select_related("user")
    if q:
        qs = qs.filter(Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) | Q(specialization__icontains=q))
    qs = qs.annotate(patients_seen=Count("visits", filter=Q(visits__status=Visit.PAID), distinct=True))
    return render(request, "panel/doctors.html", {"doctors": qs, "q": q})


@admin_required
def admin_doctor_detail(request, pk):
    doc = get_object_or_404(Doctor.objects.select_related("user"), pk=pk)
    form = forms.DoctorTermsForm(request.POST or None, instance=doc)
    if request.method == "POST" and form.is_valid():
        if not request.user.is_superuser:
            messages.error(request, "Only the main admin can change doctor charges and share.")
        else:
            form.save()
            messages.success(request, "Doctor terms updated.")
        return redirect("admin-doctor-detail", pk=pk)
    paid = doc.visits.filter(status=Visit.PAID)
    ctx = {"doc": doc, "form": form, "reject_form": forms.RejectForm(),
           "total_earned": _sum(paid, "doctor_amount"), "total_patients": paid.count(),
           "recent": paid.select_related("patient__user")[:8]}
    return render(request, "panel/doctor_detail.html", ctx)


@admin_required
@require_POST
def delete_doctor(request, pk):
    if not request.user.is_superuser:
        messages.error(request, "Only the main admin can remove a doctor.")
        return redirect("admin-doctors")
    doc = get_object_or_404(Doctor, pk=pk)
    if doc.visits.exclude(status=Visit.DRAFT).exists():
        doc.status = Doctor.REJECTED
        doc.rejection_reason = "Account closed by admin."
        doc.reviewed_at = timezone.now()
        doc.save()
        messages.warning(request, "This doctor has check-up records, so the account was deactivated instead of deleted.")
    else:
        doc.user.delete()
        messages.success(request, "Doctor deleted.")
    return redirect("admin-doctors")


@admin_required
def admin_patients(request):
    q = request.GET.get("q", "").strip()
    qs = Patient.objects.select_related("user").annotate(n=Count("visits", filter=Q(visits__status=Visit.PAID)))
    if q:
        qs = qs.filter(Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) | Q(phone__icontains=q))
    return render(request, "panel/patients.html", {"patients": qs.order_by("-created_at"), "q": q})


@admin_required
def admin_patient_detail(request, pk):
    p = get_object_or_404(Patient.objects.select_related("user"), pk=pk)
    visits = p.visits.exclude(status=Visit.DRAFT).select_related("doctor__user")
    return render(request, "panel/patient_detail.html", {"p": p, "visits": visits})


@admin_required
@require_POST
def delete_patient(request, pk):
    if not request.user.is_superuser:
        messages.error(request, "Only the main admin can delete a patient.")
        return redirect("admin-patients")
    get_object_or_404(Patient, pk=pk).user.delete()
    messages.success(request, "Patient deleted.")
    return redirect("admin-patients")


@admin_required
def admin_appointments(request):
    status = request.GET.get("status", "booked")
    qs = Appointment.objects.select_related("patient__user", "doctor__user")
    if status in dict(Appointment.STATUS_CHOICES):
        qs = qs.filter(status=status)
    return render(request, "panel/appointments.html", {"appointments": qs.order_by("date", "created_at"), "status": status})


@admin_required
def admin_appointment_add(request):
    form = forms.AdminAppointmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Appointment booked.")
        return redirect("admin-appointments")
    return render(request, "panel/appointment_form.html", {"form": form})


@admin_required
@require_POST
def cancel_appointment(request, pk):
    ap = get_object_or_404(Appointment, pk=pk)
    if ap.status == Appointment.BOOKED:
        ap.status = Appointment.CANCELLED
        ap.save()
        messages.info(request, "Appointment cancelled.")
    return redirect(request.POST.get("next") or "admin-appointments")


@admin_required
def admin_billing(request):
    tab = request.GET.get("tab", "awaiting")
    q = request.GET.get("q", "").strip()
    qs = Visit.objects.select_related("doctor__user", "patient__user")
    if tab == "paid":
        qs = qs.filter(status=Visit.PAID).order_by("-paid_at")
    elif tab == "doctor":
        qs = qs.filter(status=Visit.DRAFT).order_by("-created_at")
    else:
        tab = "awaiting"
        qs = qs.filter(status=Visit.SUBMITTED).order_by("submitted_at")
    if q:
        qs = qs.filter(Q(patient_name__icontains=q) | Q(receipt_no__icontains=q))
    counts = {
        "awaiting": Visit.objects.filter(status=Visit.SUBMITTED).count(),
        "doctor": Visit.objects.filter(status=Visit.DRAFT).count(),
        "paid": Visit.objects.filter(status=Visit.PAID).count(),
    }
    return render(request, "panel/billing.html", {"visits": qs[:200], "tab": tab, "q": q, "counts": counts})


@admin_required
@require_POST
def collect_payment(request, pk):
    form = forms.PaymentForm(request.POST)
    with transaction.atomic():
        visit = get_object_or_404(Visit.objects.select_for_update().select_related("doctor", "patient__user"), pk=pk)
        if visit.status != Visit.SUBMITTED:
            messages.error(request, "This check-up is not waiting for payment.")
            return redirect("visit-detail", pk=pk)
        if not form.is_valid():
            messages.error(request, "Please enter valid charges.")
            return redirect("visit-detail", pk=pk)
        fee = form.cleaned_data["fee"]
        pct = visit.doctor.share_percent
        doctor_amount = int(round(fee * pct / 100))
        visit.fee = fee
        visit.payment_method = form.cleaned_data["payment_method"]
        visit.status = Visit.PAID
        visit.paid_at = timezone.now()
        visit.collected_by = request.user
        visit.receipt_no = f"RC-{timezone.localtime():%Y%m}-{visit.pk:05d}"
        visit.doctor_percent = pct
        visit.doctor_amount = doctor_amount
        visit.hospital_amount = fee - doctor_amount
        visit.save()
    prefetched = Visit.objects.select_related("patient__user", "doctor__user").prefetch_related("items").get(pk=pk)
    try:
        archive.save_snapshot(prefetched)
    except OSError:
        messages.warning(request, "Payment saved, but the record file could not be written to disk.")
    messages.success(request, f"Payment of Rs. {fee:,} received. Record saved and sent to the doctor.")
    return redirect(f"{reverse('visit-print', args=[pk])}?auto=1")


@admin_required
def admin_payments(request):
    start = request.GET.get("from") or (_month_start().date().isoformat())
    end = request.GET.get("to") or timezone.localdate().isoformat()
    doctor_id = request.GET.get("doctor", "")
    try:
        s = timezone.make_aware(datetime.combine(date.fromisoformat(start), datetime.min.time()))
        e = timezone.make_aware(datetime.combine(date.fromisoformat(end), datetime.min.time())) + timedelta(days=1)
    except ValueError:
        s, e = _month_start(), timezone.now() + timedelta(days=1)
    qs = Visit.objects.filter(status=Visit.PAID, paid_at__gte=s, paid_at__lt=e).select_related("doctor__user", "patient__user")
    if doctor_id.isdigit():
        qs = qs.filter(doctor_id=int(doctor_id))
    per_doctor = (qs.values("doctor__id", "doctor__user__first_name", "doctor__user__last_name", "doctor__share_percent")
                  .annotate(n=Count("id"), total=Sum("fee"), doc=Sum("doctor_amount"), hosp=Sum("hospital_amount"))
                  .order_by("-total"))
    ctx = {"visits": qs.order_by("-paid_at")[:300], "per_doctor": per_doctor, "start": start, "end": end,
           "doctor_id": doctor_id, "doctors": Doctor.objects.filter(status=Doctor.APPROVED).select_related("user"),
           "total": _sum(qs, "fee"), "doc_total": _sum(qs, "doctor_amount"), "hosp_total": _sum(qs, "hospital_amount"),
           "count": qs.count()}
    return render(request, "panel/payments.html", ctx)


@main_admin_required
def admin_staff(request):
    staff = AdminProfile.objects.filter(user__is_superuser=False).select_related("user").order_by("-created_at")
    return render(request, "panel/staff.html", {"staff": staff})


@main_admin_required
def admin_staff_add(request):
    form = forms.StaffAdminForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            user = User.objects.create_user(username=d["username"], password=d["password"], email=d.get("email", ""),
                                            first_name=d["first_name"], last_name=d["last_name"])
            AdminProfile.objects.create(user=user, phone=d.get("phone", ""), is_temporary=bool(d.get("expires_at")),
                                        expires_at=d.get("expires_at"))
        messages.success(request, "Admin account created.")
        return redirect("admin-staff")
    return render(request, "panel/staff_form.html", {"form": form})


@main_admin_required
@require_POST
def admin_staff_toggle(request, pk):
    prof = get_object_or_404(AdminProfile, pk=pk, user__is_superuser=False)
    prof.is_active_admin = not prof.is_active_admin
    prof.save()
    messages.info(request, f"{prof.full_name} is now {'active' if prof.is_active_admin else 'switched off'}.")
    return redirect("admin-staff")


@main_admin_required
@require_POST
def admin_staff_delete(request, pk):
    prof = get_object_or_404(AdminProfile, pk=pk, user__is_superuser=False)
    prof.user.delete()
    messages.success(request, "Admin account deleted.")
    return redirect("admin-staff")


@admin_required
def admin_records(request):
    paid = Visit.objects.filter(status=Visit.PAID)
    ctx = {"record_count": paid.count(), "patient_count": paid.values("patient").distinct().count(),
           "folder": Path(settings.MEDIA_ROOT) / "patient_records"}
    return render(request, "panel/records.html", ctx)


@admin_required
def download_all_records(request):
    data = archive.build_zip(Visit.objects.filter(status=Visit.PAID))
    resp = HttpResponse(data, content_type="application/zip")
    resp["Content-Disposition"] = f'attachment; filename="Muzammils_Hospital_Records_{date.today():%Y-%m-%d}.zip"'
    return resp


@admin_required
def download_patient_records(request, pk):
    p = get_object_or_404(Patient, pk=pk)
    data = archive.build_zip(Visit.objects.filter(status=Visit.PAID, patient=p), patients=[p])
    resp = HttpResponse(data, content_type="application/zip")
    resp["Content-Disposition"] = f'attachment; filename="{archive.patient_folder_name(p)}.zip"'
    return resp


# --------------------------------------------------------------------------- DOCTOR
@doctor_required
def doctor_dashboard(request):
    doc = request.user.doctor
    paid = doc.visits.filter(status=Visit.PAID)
    start, end = _today_range()
    ctx = {
        "queue": doc.appointments.filter(status=Appointment.BOOKED, date__lte=timezone.localdate() + timedelta(days=7))
                    .select_related("patient__user").order_by("date")[:6],
        "drafts": doc.visits.filter(status=Visit.DRAFT).select_related("patient__user")[:5],
        "today_count": doc.visits.filter(created_at__gte=start, created_at__lt=end).exclude(status=Visit.DRAFT).count(),
        "total_patients": paid.values("patient").distinct().count(),
        "month_earned": _sum(paid.filter(paid_at__gte=_month_start()), "doctor_amount"),
        "total_earned": _sum(paid, "doctor_amount"),
        "awaiting": doc.visits.filter(status=Visit.SUBMITTED).count(),
        "recent": paid.select_related("patient__user").order_by("-paid_at")[:5],
    }
    return render(request, "doctor/dashboard.html", ctx)


@doctor_required
def doctor_queue(request):
    doc = request.user.doctor
    qs = doc.appointments.filter(status=Appointment.BOOKED).select_related("patient__user").order_by("date", "created_at")
    patients = Patient.objects.select_related("user").order_by("user__first_name")
    return render(request, "doctor/queue.html", {"appointments": qs, "patients": patients})


def _new_visit(doctor, patient, appointment=None):
    return Visit.objects.create(
        patient=patient, doctor=doctor, appointment=appointment,
        patient_name=patient.full_name, age=patient.age, gender=patient.gender,
        height_cm=patient.height_cm, weight_kg=patient.weight_kg,
        problems=appointment.problem if appointment else "")


@doctor_required
@require_POST
def start_checkup(request, pk):
    doc = request.user.doctor
    ap = get_object_or_404(Appointment, pk=pk, doctor=doc, status=Appointment.BOOKED)
    existing = Visit.objects.filter(appointment=ap, status=Visit.DRAFT).first()
    visit = existing or _new_visit(doc, ap.patient, ap)
    return redirect("doctor-visit-edit", pk=visit.pk)


@doctor_required
@require_POST
def new_checkup(request):
    patient = get_object_or_404(Patient, pk=request.POST.get("patient") or 0)
    visit = _new_visit(request.user.doctor, patient)
    return redirect("doctor-visit-edit", pk=visit.pk)


@doctor_required
def doctor_visit_edit(request, pk):
    visit = get_object_or_404(Visit, pk=pk, doctor=request.user.doctor)
    if visit.is_locked:
        messages.info(request, "This check-up was already sent to the admin and cannot be edited.")
        return redirect("visit-detail", pk=pk)
    form = forms.VisitForm(request.POST or None, instance=visit)
    formset = forms.PrescriptionFormSet(request.POST or None, instance=visit)
    if request.method == "POST":
        send = "send" in request.POST
        if form.is_valid() and formset.is_valid():
            if send and not (form.cleaned_data["problems"] or "").strip():
                form.add_error("problems", "Write at least one problem before sending to admin.")
            else:
                with transaction.atomic():
                    v = form.save(commit=False)
                    if send:
                        v.status = Visit.SUBMITTED
                        v.submitted_at = timezone.now()
                    v.save()
                    items = formset.save(commit=False)
                    for obj in formset.deleted_objects:
                        obj.delete()
                    for it in items:
                        it.visit = v
                        if it.medicine.strip():
                            it.save()
                    if send:
                        p = v.patient
                        if v.height_cm:
                            p.height_cm = v.height_cm
                        if v.weight_kg:
                            p.weight_kg = v.weight_kg
                        p.save()
                        if v.appointment_id:
                            Appointment.objects.filter(pk=v.appointment_id).update(status=Appointment.DONE)
                if send:
                    messages.success(request, "Check-up sent to the admin desk for printing and payment.")
                    return redirect("visit-detail", pk=pk)
                messages.success(request, "Draft saved.")
                return redirect("doctor-visit-edit", pk=pk)
    return render(request, "doctor/visit_form.html", {"form": form, "formset": formset, "visit": visit})


@doctor_required
@require_POST
def doctor_visit_delete(request, pk):
    visit = get_object_or_404(Visit, pk=pk, doctor=request.user.doctor, status=Visit.DRAFT)
    visit.delete()
    messages.info(request, "Draft deleted.")
    return redirect("doctor-visits")


@doctor_required
def doctor_visits(request):
    doc = request.user.doctor
    q = request.GET.get("q", "").strip()
    st = request.GET.get("status", "")
    qs = doc.visits.select_related("patient__user")
    if st in dict(Visit.STATUS_CHOICES):
        qs = qs.filter(status=st)
    if q:
        qs = qs.filter(patient_name__icontains=q)
    return render(request, "doctor/visits.html", {"visits": qs[:200], "q": q, "st": st})


@doctor_required
def doctor_earnings(request):
    doc = request.user.doctor
    paid = doc.visits.filter(status=Visit.PAID)
    ctx = {
        "visits": paid.select_related("patient__user").order_by("-paid_at")[:200],
        "total": _sum(paid, "doctor_amount"),
        "month": _sum(paid.filter(paid_at__gte=_month_start()), "doctor_amount"),
        "gross": _sum(paid, "fee"),
        "count": paid.count(),
        "percent": doc.share_percent,
        "pending": doc.visits.filter(status=Visit.SUBMITTED).count(),
    }
    return render(request, "doctor/earnings.html", ctx)


# --------------------------------------------------------------------------- PATIENT
@patient_required
def patient_dashboard(request):
    p = request.user.patient
    ctx = {
        "upcoming": p.appointments.filter(status=Appointment.BOOKED).select_related("doctor__user").order_by("date")[:5],
        "records": p.visits.filter(status=Visit.PAID).select_related("doctor__user").order_by("-paid_at")[:5],
        "record_count": p.visits.filter(status=Visit.PAID).count(),
        "waiting": p.visits.exclude(status=Visit.PAID).exclude(status=Visit.DRAFT).count(),
        "doctors": Doctor.objects.filter(status=Doctor.APPROVED).select_related("user")[:6],
    }
    return render(request, "patient/dashboard.html", ctx)


@patient_required
def patient_book(request):
    form = forms.AppointmentForm(request.POST or None, initial={"doctor": request.GET.get("doctor")})
    if request.method == "POST" and form.is_valid():
        ap = form.save(commit=False)
        ap.patient = request.user.patient
        ap.save()
        messages.success(request, "Appointment booked. Please visit the hospital on the selected date.")
        return redirect("patient-appointments")
    return render(request, "patient/book.html", {"form": form})


@patient_required
def patient_appointments(request):
    qs = request.user.patient.appointments.select_related("doctor__user").order_by("-date")
    return render(request, "patient/appointments.html", {"appointments": qs})


@patient_required
@require_POST
def patient_cancel(request, pk):
    ap = get_object_or_404(Appointment, pk=pk, patient=request.user.patient, status=Appointment.BOOKED)
    ap.status = Appointment.CANCELLED
    ap.save()
    messages.info(request, "Appointment cancelled.")
    return redirect("patient-appointments")


@patient_required
def patient_records(request):
    qs = request.user.patient.visits.exclude(status=Visit.DRAFT).select_related("doctor__user").order_by("-created_at")
    return render(request, "patient/records.html", {"visits": qs})


@patient_required
def patient_doctors(request):
    q = request.GET.get("q", "").strip()
    qs = Doctor.objects.filter(status=Doctor.APPROVED).select_related("user")
    if q:
        qs = qs.filter(Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) | Q(specialization__icontains=q))
    return render(request, "patient/doctors.html", {"doctors": qs, "q": q})

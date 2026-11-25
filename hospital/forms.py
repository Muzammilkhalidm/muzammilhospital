from datetime import date

from django import forms
from django.contrib.auth.models import User
from django.forms import inlineformset_factory
from django.utils import timezone

from . import models


class StyledMixin:
    """Adds the CSS classes used by the UI to every widget."""

    def _style(self):
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault("class", "check")
            elif isinstance(w, forms.FileInput):
                w.attrs.setdefault("class", "file")
            else:
                w.attrs.setdefault("class", "input")
            if isinstance(w, forms.Textarea):
                w.attrs.setdefault("rows", 3)
            if field.label is None:
                continue


class StyledForm(StyledMixin, forms.Form):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._style()


class StyledModelForm(StyledMixin, forms.ModelForm):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._style()


class AccountFields(forms.Form):
    """Shared account fields used by registration forms."""
    first_name = forms.CharField(max_length=60)
    last_name = forms.CharField(max_length=60)
    username = forms.CharField(max_length=40, help_text="Used to sign in. No spaces.")
    email = forms.EmailField(required=False)
    password = forms.CharField(widget=forms.PasswordInput, min_length=6)
    confirm_password = forms.CharField(widget=forms.PasswordInput)

    def clean_username(self):
        u = self.cleaned_data["username"].strip()
        if " " in u:
            raise forms.ValidationError("Username cannot contain spaces.")
        if User.objects.filter(username__iexact=u).exists():
            raise forms.ValidationError("This username is already taken.")
        return u

    def clean(self):
        data = super().clean()
        if data.get("password") and data.get("password") != data.get("confirm_password"):
            self.add_error("confirm_password", "Passwords do not match.")
        return data


class DoctorRegisterForm(StyledMixin, AccountFields, forms.ModelForm):
    class Meta:
        model = models.Doctor
        fields = ["phone", "address", "specialization", "qualification", "university",
                  "passing_year", "experience_years", "license_no", "certificate", "photo", "bio"]
        widgets = {"bio": forms.Textarea(attrs={"rows": 3}),
                   "photo": forms.FileInput(attrs={"accept": "image/*"})}

    field_order = ["first_name", "last_name", "username", "email", "password", "confirm_password",
                   "phone", "address", "photo", "specialization", "qualification", "university",
                   "passing_year", "experience_years", "license_no", "certificate", "bio"]

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._style()
        self.fields["certificate"].required = True
        self.fields["license_no"].required = True

    def clean_passing_year(self):
        y = self.cleaned_data["passing_year"]
        if y > date.today().year:
            raise forms.ValidationError("Year cannot be in the future.")
        return y

    def save(self, commit=True):
        d = self.cleaned_data
        user = User.objects.create_user(
            username=d["username"], password=d["password"], email=d.get("email", ""),
            first_name=d["first_name"], last_name=d["last_name"])
        doctor = super().save(commit=False)
        doctor.user = user
        doctor.status = models.Doctor.PENDING
        doctor.save()
        return doctor


class PatientRegisterForm(StyledMixin, AccountFields, forms.ModelForm):
    class Meta:
        model = models.Patient
        fields = ["phone", "address", "gender", "date_of_birth", "blood_group", "height_cm", "weight_kg", "photo"]
        widgets = {"date_of_birth": forms.DateInput(attrs={"type": "date"}),
                   "photo": forms.FileInput(attrs={"accept": "image/*"})}

    field_order = ["first_name", "last_name", "username", "email", "password", "confirm_password",
                   "phone", "gender", "date_of_birth", "blood_group", "height_cm", "weight_kg", "address", "photo"]

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._style()
        self.fields["date_of_birth"].required = True

    def clean_date_of_birth(self):
        d = self.cleaned_data["date_of_birth"]
        if d and d > date.today():
            raise forms.ValidationError("Date of birth cannot be in the future.")
        return d

    def save(self, commit=True):
        d = self.cleaned_data
        user = User.objects.create_user(
            username=d["username"], password=d["password"], email=d.get("email", ""),
            first_name=d["first_name"], last_name=d["last_name"])
        patient = super().save(commit=False)
        patient.user = user
        patient.save()
        return patient


class UserBasicsForm(StyledModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]


class DoctorProfileForm(StyledModelForm):
    class Meta:
        model = models.Doctor
        fields = ["photo", "phone", "address", "bio"]
        widgets = {"photo": forms.FileInput(attrs={"accept": "image/*"})}


class PatientProfileForm(StyledModelForm):
    class Meta:
        model = models.Patient
        fields = ["photo", "phone", "address", "gender", "date_of_birth", "blood_group", "height_cm", "weight_kg"]
        widgets = {"date_of_birth": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "photo": forms.FileInput(attrs={"accept": "image/*"})}


class AdminProfileForm(StyledModelForm):
    class Meta:
        model = models.AdminProfile
        fields = ["photo", "phone"]
        widgets = {"photo": forms.FileInput(attrs={"accept": "image/*"})}


class DoctorTermsForm(StyledModelForm):
    """Admin edits money terms for an approved doctor."""
    class Meta:
        model = models.Doctor
        fields = ["consultation_fee", "share_percent"]
        labels = {"consultation_fee": "Default checking charges (Rs.)", "share_percent": "Doctor share of each payment (%)"}


class RejectForm(StyledForm):
    reason = forms.CharField(max_length=300, label="Reason for rejection",
                             widget=forms.Textarea(attrs={"rows": 2, "placeholder": "e.g. Certificate is not readable"}))


class AppointmentForm(StyledModelForm):
    doctor = forms.ModelChoiceField(queryset=models.Doctor.objects.none(), empty_label="Select a doctor")

    class Meta:
        model = models.Appointment
        fields = ["doctor", "date", "problem"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}), "problem": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields["doctor"].queryset = models.Doctor.objects.filter(status=models.Doctor.APPROVED).select_related("user")
        self.fields["doctor"].label_from_instance = lambda d: f"{d.display_name} - {d.specialization}"
        self.fields["date"].widget.attrs["min"] = date.today().isoformat()
        self.fields["date"].initial = date.today()

    def clean_date(self):
        d = self.cleaned_data["date"]
        if d < date.today():
            raise forms.ValidationError("Please choose today or a future date.")
        return d


class AdminAppointmentForm(AppointmentForm):
    patient = forms.ModelChoiceField(queryset=models.Patient.objects.none(), empty_label="Select a patient")

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields["patient"].queryset = models.Patient.objects.select_related("user").order_by("user__first_name")
        self.fields["patient"].label_from_instance = lambda p: f"{p.full_name} ({p.code}) - {p.phone}"
        self.order_fields(["patient", "doctor", "date", "problem"])

    class Meta(AppointmentForm.Meta):
        fields = ["patient", "doctor", "date", "problem"]


class VisitForm(StyledModelForm):
    class Meta:
        model = models.Visit
        fields = ["patient_name", "age", "gender", "height_cm", "weight_kg", "blood_pressure", "temperature",
                  "pulse", "problems", "diagnosis", "tests", "advice", "referral_to", "referral_notes", "follow_up"]
        widgets = {
            "problems": forms.Textarea(attrs={"rows": 5, "placeholder": "Fever for 3 days\nHeadache\nBody pain"}),
            "diagnosis": forms.Textarea(attrs={"rows": 3, "placeholder": "Viral fever"}),
            "tests": forms.Textarea(attrs={"rows": 3, "placeholder": "CBC\nMalaria parasite (MP)"}),
            "advice": forms.Textarea(attrs={"rows": 3, "placeholder": "Take plenty of fluids\nComplete bed rest"}),
            "follow_up": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "blood_pressure": forms.TextInput(attrs={"placeholder": "120/80"}),
            "temperature": forms.TextInput(attrs={"placeholder": "98.6"}),
            "pulse": forms.TextInput(attrs={"placeholder": "72"}),
            "referral_to": forms.TextInput(attrs={"placeholder": "e.g. Cardiologist, City Hospital"}),
        }


class PrescriptionItemForm(StyledModelForm):
    class Meta:
        model = models.PrescriptionItem
        fields = ["medicine", "dose", "frequency", "duration", "instructions"]
        widgets = {
            "medicine": forms.TextInput(attrs={"placeholder": "Medicine name"}),
            "dose": forms.TextInput(attrs={"placeholder": "500mg"}),
            "frequency": forms.TextInput(attrs={"placeholder": "1+0+1"}),
            "duration": forms.TextInput(attrs={"placeholder": "5 days"}),
            "instructions": forms.TextInput(attrs={"placeholder": "After meal"}),
        }


PrescriptionFormSet = inlineformset_factory(
    models.Visit, models.PrescriptionItem, form=PrescriptionItemForm, extra=2, can_delete=True)


class PaymentForm(StyledForm):
    fee = forms.IntegerField(min_value=0, label="Checking charges (Rs.)")
    payment_method = forms.ChoiceField(choices=models.Visit.METHODS)


class StaffAdminForm(StyledMixin, AccountFields):
    phone = forms.CharField(max_length=20, required=False)
    expires_at = forms.DateTimeField(
        required=False, label="Access ends on (optional)",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        help_text="Leave empty for permanent access. After this time the account is locked automatically.")

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._style()

    def clean_expires_at(self):
        v = self.cleaned_data.get("expires_at")
        if v and v < timezone.now():
            raise forms.ValidationError("Choose a time in the future.")
        return v


class ContactForm(StyledForm):
    name = forms.CharField(max_length=60)
    phone = forms.CharField(max_length=20)
    message = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), max_length=500)

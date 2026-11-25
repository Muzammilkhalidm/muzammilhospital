from datetime import date

from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

SPECIALIZATIONS = [
    "General Physician", "Cardiologist", "Dermatologist", "Neurologist", "Pediatrician",
    "Gynecologist", "Orthopedic Surgeon", "ENT Specialist", "Eye Specialist (Ophthalmologist)",
    "Dentist", "Psychiatrist", "Urologist", "Gastroenterologist", "Pulmonologist",
    "Endocrinologist", "General Surgeon", "Radiologist", "Other",
]
SPECIALIZATION_CHOICES = [(s, s) for s in SPECIALIZATIONS]

GENDER_CHOICES = [("Male", "Male"), ("Female", "Female"), ("Other", "Other")]
BLOOD_GROUPS = [(b, b) for b in ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]]


class AdminProfile(models.Model):
    """Extra data for admins. Main admin = superuser. Temporary admins can have an expiry."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="admin_profile")
    photo = models.ImageField(upload_to="photos/admins/", null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    is_temporary = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active_admin = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_expired(self):
        return bool(self.is_temporary and self.expires_at and self.expires_at < timezone.now())

    @property
    def can_work(self):
        return self.is_active_admin and not self.is_expired

    @property
    def full_name(self):
        return self.user.get_full_name() or self.user.username

    def __str__(self):
        return self.full_name


class Doctor(models.Model):
    PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"
    STATUS_CHOICES = [(PENDING, "Pending"), (APPROVED, "Approved"), (REJECTED, "Rejected")]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="doctor")
    photo = models.ImageField(upload_to="photos/doctors/", null=True, blank=True)
    phone = models.CharField(max_length=20)
    address = models.CharField(max_length=200, blank=True)
    specialization = models.CharField(max_length=60, choices=SPECIALIZATION_CHOICES, default="General Physician")
    qualification = models.CharField("Degree(s)", max_length=150, help_text="e.g. MBBS, FCPS (Medicine)")
    university = models.CharField("University / College", max_length=150)
    passing_year = models.PositiveIntegerField(
        "Year of graduation", validators=[MinValueValidator(1960), MaxValueValidator(2100)])
    experience_years = models.PositiveIntegerField("Experience (years)", default=0)
    license_no = models.CharField("PMDC / Registration No.", max_length=60)
    certificate = models.FileField(
        "Degree certificate (PDF / image)", upload_to="certificates/", null=True, blank=True,
        validators=[FileExtensionValidator(["pdf", "jpg", "jpeg", "png"])])
    bio = models.TextField("Short bio", blank=True, max_length=500)

    consultation_fee = models.PositiveIntegerField(default=1000)
    share_percent = models.PositiveSmallIntegerField(
        "Doctor share (%)", default=60, validators=[MaxValueValidator(100)])

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    rejection_reason = models.CharField(max_length=300, blank=True)
    applied_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    @property
    def full_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def display_name(self):
        return "Dr. " + self.full_name

    @property
    def is_approved(self):
        return self.status == self.APPROVED

    def __str__(self):
        return f"{self.display_name} ({self.specialization})"


class Patient(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="patient")
    photo = models.ImageField(upload_to="photos/patients/", null=True, blank=True)
    phone = models.CharField(max_length=20)
    address = models.CharField(max_length=200, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, default="Male")
    date_of_birth = models.DateField(null=True, blank=True)
    blood_group = models.CharField(max_length=3, choices=BLOOD_GROUPS, blank=True)
    height_cm = models.PositiveIntegerField("Height (cm)", null=True, blank=True)
    weight_kg = models.DecimalField("Weight (kg)", max_digits=5, decimal_places=1, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def full_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def code(self):
        return f"MH-{self.pk:05d}"

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        t = date.today()
        d = self.date_of_birth
        return t.year - d.year - ((t.month, t.day) < (d.month, d.day))

    def __str__(self):
        return f"{self.full_name} ({self.code})"


class Appointment(models.Model):
    BOOKED, DONE, CANCELLED = "booked", "done", "cancelled"
    STATUS_CHOICES = [(BOOKED, "Booked"), (DONE, "Checked"), (CANCELLED, "Cancelled")]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="appointments")
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="appointments")
    date = models.DateField("Preferred date")
    problem = models.TextField("What is the problem?", max_length=500)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=BOOKED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "created_at"]

    def __str__(self):
        return f"{self.patient.full_name} -> {self.doctor.display_name} on {self.date}"


class Visit(models.Model):
    """One check-up written digitally by a doctor."""
    DRAFT, SUBMITTED, PAID = "draft", "submitted", "paid"
    STATUS_CHOICES = [(DRAFT, "With doctor"), (SUBMITTED, "Awaiting payment"), (PAID, "Paid")]
    METHODS = [("Cash", "Cash"), ("Card", "Card"), ("Online", "Online transfer")]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="visits")
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="visits")
    appointment = models.ForeignKey(Appointment, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(default=timezone.now)

    # Snapshot of patient data on the day of the check-up
    patient_name = models.CharField(max_length=120)
    age = models.PositiveIntegerField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True)
    height_cm = models.PositiveIntegerField("Height (cm)", null=True, blank=True)
    weight_kg = models.DecimalField("Weight (kg)", max_digits=5, decimal_places=1, null=True, blank=True)
    blood_pressure = models.CharField("Blood pressure", max_length=15, blank=True)
    temperature = models.CharField("Temperature (°F)", max_length=8, blank=True)
    pulse = models.CharField("Pulse (bpm)", max_length=8, blank=True)

    problems = models.TextField("Problems / complaints (one point per line)")
    diagnosis = models.TextField("Diagnosis (one point per line)", blank=True)
    tests = models.TextField("Tests advised (one per line)", blank=True)
    advice = models.TextField("Advice / precautions (one point per line)", blank=True)
    referral_to = models.CharField("Refer patient to", max_length=150, blank=True)
    referral_notes = models.CharField("Reason for referral", max_length=250, blank=True)
    follow_up = models.DateField("Follow-up date", null=True, blank=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)

    # Billing
    fee = models.PositiveIntegerField("Checking charges", null=True, blank=True)
    payment_method = models.CharField(max_length=10, choices=METHODS, default="Cash")
    paid_at = models.DateTimeField(null=True, blank=True)
    collected_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="collected_visits")
    receipt_no = models.CharField(max_length=30, blank=True)
    doctor_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    doctor_amount = models.PositiveIntegerField(null=True, blank=True)
    hospital_amount = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def code(self):
        return f"V-{self.pk:06d}"

    @staticmethod
    def _lines(text):
        out = []
        for line in (text or "").splitlines():
            line = line.strip().lstrip("-•*").strip()
            if line:
                out.append(line)
        return out

    @property
    def problem_list(self):
        return self._lines(self.problems)

    @property
    def diagnosis_list(self):
        return self._lines(self.diagnosis)

    @property
    def test_list(self):
        return self._lines(self.tests)

    @property
    def advice_list(self):
        return self._lines(self.advice)

    @property
    def is_locked(self):
        return self.status != self.DRAFT

    def __str__(self):
        return f"{self.code} - {self.patient_name}"


class PrescriptionItem(models.Model):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="items")
    medicine = models.CharField(max_length=120)
    dose = models.CharField(max_length=60, blank=True, help_text="e.g. 500mg")
    frequency = models.CharField(max_length=60, blank=True, help_text="e.g. 1+0+1")
    duration = models.CharField(max_length=60, blank=True, help_text="e.g. 5 days")
    instructions = models.CharField(max_length=150, blank=True, help_text="e.g. after meal")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.medicine

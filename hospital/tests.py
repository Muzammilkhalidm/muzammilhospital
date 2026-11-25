import io
import zipfile
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AdminProfile, Appointment, Doctor, Patient, Visit

import tempfile
TMP_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class FullFlowTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("boss", password="Admin#12345", first_name="Main", last_name="Admin")

    def register_doctor(self, username="drali"):
        cert = SimpleUploadedFile("degree.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        r = self.client.post(reverse("register-doctor"), {
            "first_name": "Ali", "last_name": "Raza", "username": username, "email": "a@b.com",
            "password": "Doctor#123", "confirm_password": "Doctor#123", "phone": "03001234567",
            "address": "Lahore", "specialization": "Cardiologist", "qualification": "MBBS, FCPS",
            "university": "King Edward Medical University", "passing_year": 2012, "experience_years": 8,
            "license_no": "PMDC-12345", "certificate": cert, "bio": "Heart specialist"})
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        return Doctor.objects.get(user__username=username)

    def register_patient(self, username="pat1"):
        r = self.client.post(reverse("register-patient"), {
            "first_name": "Sara", "last_name": "Khan", "username": username, "email": "",
            "password": "Patient#123", "confirm_password": "Patient#123", "phone": "03111111111",
            "gender": "Female", "date_of_birth": "1995-04-12", "blood_group": "O+", "height_cm": 160,
            "weight_kg": "55.5", "address": "Lahore"})
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        return Patient.objects.get(user__username=username)

    def login(self, u, p):
        self.client.logout()
        r = self.client.post(reverse("login"), {"username": u, "password": p}, follow=True)
        self.assertEqual(r.status_code, 200)

    def test_complete_flow(self):
        doc = self.register_doctor()
        self.assertEqual(doc.status, Doctor.PENDING)
        pat = self.register_patient()

        # pending doctor sees the status page, not the dashboard
        self.login("drali", "Doctor#123")
        r = self.client.get(reverse("doctor-dashboard"))
        self.assertRedirects(r, reverse("doctor-status"))
        self.assertContains(self.client.get(reverse("doctor-status")), "Waiting for admin approval")

        # patient cannot book a pending doctor
        self.login("pat1", "Patient#123")
        r = self.client.post(reverse("patient-book"), {"doctor": doc.pk, "date": date.today().isoformat(), "problem": "Chest pain"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Appointment.objects.count(), 0)

        # patient cannot open admin pages
        self.assertEqual(self.client.get(reverse("admin-dashboard")).status_code, 302)

        # admin sees the request with certificate and approves
        self.login("boss", "Admin#12345")
        r = self.client.get(reverse("admin-doctor-requests"))
        self.assertContains(r, "King Edward Medical University")
        self.assertContains(r, "Open degree certificate")
        self.assertContains(self.client.get(reverse("admin-dashboard")), "Doctor requests waiting")
        self.client.post(reverse("approve-doctor", args=[doc.pk]))
        doc.refresh_from_db()
        self.assertEqual(doc.status, Doctor.APPROVED)
        self.client.post(reverse("admin-doctor-detail", args=[doc.pk]), {"consultation_fee": 1500, "share_percent": 70})

        # patient books
        self.login("pat1", "Patient#123")
        r = self.client.post(reverse("patient-book"), {"doctor": doc.pk, "date": date.today().isoformat(), "problem": "Chest pain\nBreathlessness"})
        self.assertEqual(r.status_code, 302)
        ap = Appointment.objects.get()
        self.assertContains(self.client.get(reverse("patient-dashboard")), "Upcoming appointments")

        # doctor starts check-up and writes the form
        self.login("drali", "Doctor#123")
        self.assertContains(self.client.get(reverse("doctor-dashboard")), "Patient queue")
        r = self.client.post(reverse("doctor-start", args=[ap.pk]))
        visit = Visit.objects.get()
        self.assertRedirects(r, reverse("doctor-visit-edit", args=[visit.pk]))
        self.assertContains(self.client.get(r.url), "Chest pain")
        data = {
            "patient_name": "Sara Khan", "age": 30, "gender": "Female", "height_cm": 162, "weight_kg": "56.0",
            "blood_pressure": "130/85", "temperature": "98.6", "pulse": "88",
            "problems": "Chest pain\nBreathlessness on walking", "diagnosis": "Suspected angina", "tests": "ECG\nEcho",
            "advice": "Avoid heavy work", "referral_to": "Cardiac Surgeon, City Hospital", "referral_notes": "Needs angiography",
            "follow_up": (date.today() + timedelta(days=7)).isoformat(),
            "items-TOTAL_FORMS": 3, "items-INITIAL_FORMS": 0, "items-MIN_NUM_FORMS": 0, "items-MAX_NUM_FORMS": 1000,
            "items-0-medicine": "Aspirin", "items-0-dose": "75mg", "items-0-frequency": "0+0+1", "items-0-duration": "30 days", "items-0-instructions": "After meal",
            "items-1-medicine": "Atorvastatin", "items-1-dose": "20mg", "items-1-frequency": "0+0+1", "items-1-duration": "30 days", "items-1-instructions": "",
            "items-2-medicine": "", "send": "1",
        }
        r = self.client.post(reverse("doctor-visit-edit", args=[visit.pk]), data)
        self.assertEqual(r.status_code, 302, r.context["form"].errors if r.context else "")
        visit.refresh_from_db()
        self.assertEqual(visit.status, Visit.SUBMITTED)
        self.assertEqual(visit.items.count(), 2)
        ap.refresh_from_db()
        self.assertEqual(ap.status, Appointment.DONE)
        # locked after sending
        self.assertEqual(self.client.get(reverse("doctor-visit-edit", args=[visit.pk])).status_code, 302)

        # patient cannot see unpaid record
        self.login("pat1", "Patient#123")
        self.assertEqual(self.client.get(reverse("visit-detail", args=[visit.pk])).status_code, 404)

        # admin collects
        self.login("boss", "Admin#12345")
        self.assertContains(self.client.get(reverse("admin-billing")), "Sara Khan")
        self.assertContains(self.client.get(reverse("visit-detail", args=[visit.pk])), "Receive payment")
        r = self.client.post(reverse("collect-payment", args=[visit.pk]), {"fee": 1500, "payment_method": "Cash"})
        self.assertRedirects(r, reverse("visit-print", args=[visit.pk]) + "?auto=1", fetch_redirect_response=False)
        visit.refresh_from_db()
        self.assertEqual(visit.status, Visit.PAID)
        self.assertEqual((visit.doctor_amount, visit.hospital_amount, visit.doctor_percent), (1050, 450, 70))
        self.assertTrue(visit.receipt_no.startswith("RC-"))
        # double payment blocked
        self.client.post(reverse("collect-payment", args=[visit.pk]), {"fee": 99999, "payment_method": "Cash"})
        visit.refresh_from_db()
        self.assertEqual(visit.fee, 1500)

        # print page has stamp, medicines, referral and fee
        r = self.client.get(reverse("visit-print", args=[visit.pk]))
        for needle in ("Dr. Ali Raza", "MBBS, FCPS", "King Edward Medical University", "PMDC-12345", "Aspirin",
                       "Cardiac Surgeon", "Breathlessness on walking", "Muzammil&#x27;s Hospital", "1,500", "130/85"):
            self.assertContains(r, needle)

        # record is stored on disk and in ZIP
        import os
        folders = os.listdir(os.path.join(TMP_MEDIA, "patient_records"))
        self.assertEqual(len(folders), 1)
        r = self.client.get(reverse("admin-records-zip"))
        z = zipfile.ZipFile(io.BytesIO(r.content))
        names = z.namelist()
        self.assertTrue(any(n.endswith(".html") for n in names) and "patients.csv" in names and "payments.csv" in names)
        self.assertEqual(self.client.get(reverse("admin-patient-zip", args=[pat.pk])).status_code, 200)

        # doctor gets the payment record with percentage
        self.login("drali", "Doctor#123")
        r = self.client.get(reverse("doctor-earnings"))
        self.assertContains(r, "Rs. 1,050")
        self.assertContains(r, "70%")
        # doctor can't open another doctor's visit
        # patient now sees the record
        self.login("pat1", "Patient#123")
        self.assertContains(self.client.get(reverse("patient-records")), "Print")
        self.assertEqual(self.client.get(reverse("visit-print", args=[visit.pk])).status_code, 200)

        # reports
        self.login("boss", "Admin#12345")
        r = self.client.get(reverse("admin-payments"))
        self.assertContains(r, "Rs. 1,050")
        for name in ("admin-dashboard", "admin-doctors", "admin-patients", "admin-appointments", "admin-records",
                     "admin-staff", "admin-doctor-requests", "profile", "password"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("admin-patient-detail", args=[pat.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin-doctor-detail", args=[doc.pk])).status_code, 200)

    def test_reject_flow(self):
        doc = self.register_doctor()
        self.login("boss", "Admin#12345")
        self.client.post(reverse("reject-doctor", args=[doc.pk]), {"reason": "Certificate unreadable"})
        doc.refresh_from_db()
        self.assertEqual(doc.status, Doctor.REJECTED)
        self.login("drali", "Doctor#123")
        self.assertContains(self.client.get(reverse("doctor-status")), "Certificate unreadable")

    def test_temporary_admin(self):
        self.login("boss", "Admin#12345")
        exp = (timezone.now() + timedelta(hours=2)).astimezone().strftime("%Y-%m-%dT%H:%M")
        r = self.client.post(reverse("admin-staff-add"), {
            "first_name": "Front", "last_name": "Desk", "username": "desk1", "email": "", "password": "Desk#12345",
            "confirm_password": "Desk#12345", "phone": "", "expires_at": exp})
        self.assertEqual(r.status_code, 302, r.context["form"].errors if r.context else "")
        prof = AdminProfile.objects.get(user__username="desk1")
        self.assertTrue(prof.is_temporary)
        self.login("desk1", "Desk#12345")
        self.assertEqual(self.client.get(reverse("admin-dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin-staff")).status_code, 302)  # main admin only
        self.assertEqual(self.client.get(reverse("admin-billing")).status_code, 200)
        # expire it
        prof.expires_at = timezone.now() - timedelta(minutes=1)
        prof.save()
        r = self.client.get(reverse("admin-dashboard"))
        self.assertRedirects(r, reverse("login"), fetch_redirect_response=False)
        # switched off
        prof.expires_at = None
        prof.is_active_admin = False
        prof.save()
        self.client.post(reverse("login"), {"username": "desk1", "password": "Desk#12345"})
        self.assertEqual(self.client.get(reverse("admin-dashboard")).status_code, 302)

    def test_password_and_photo(self):
        self.register_patient()
        self.login("pat1", "Patient#123")
        r = self.client.post(reverse("password"), {"old_password": "Patient#123", "new_password1": "NewPass#456", "new_password2": "NewPass#456"})
        self.assertRedirects(r, reverse("profile"), fetch_redirect_response=False)
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (20, 20), "teal").save(buf, "PNG")
        png = buf.getvalue()
        r = self.client.post(reverse("profile"), {
            "u-first_name": "Sara", "u-last_name": "Khan", "u-email": "s@k.com",
            "p-phone": "0300", "p-address": "x", "p-gender": "Female", "p-date_of_birth": "1995-04-12",
            "p-blood_group": "O+", "p-height_cm": 160, "p-weight_kg": "55.5",
            "p-photo": SimpleUploadedFile("me.png", png, content_type="image/png")})
        self.assertEqual(r.status_code, 302, r.context["prof_form"].errors if r.context else "")
        self.assertTrue(Patient.objects.get().photo)
        self.login("pat1", "NewPass#456")
        self.assertContains(self.client.get(reverse("profile")), "/media/photos/patients/")
        # admin and doctor pages
        self.login("boss", "Admin#12345")
        r = self.client.post(reverse("password"), {"old_password": "Admin#12345", "new_password1": "Another#789", "new_password2": "Another#789"})
        self.assertEqual(r.status_code, 302)

    def test_public_pages(self):
        for name in ("home", "login", "register-patient", "register-doctor"):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)
        self.assertContains(self.client.get(reverse("home")), "Muzammil&#x27;s Hospital")

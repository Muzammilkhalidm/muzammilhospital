from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from hospital import views as v

urlpatterns = [
    path("django-admin/", admin.site.urls),

    # public
    path("", v.home, name="home"),
    path("login/", v.HospitalLoginView.as_view(), name="login"),
    path("logout/", v.logout_view, name="logout"),
    path("go/", v.go, name="go"),
    path("register/patient/", v.register_patient, name="register-patient"),
    path("register/doctor/", v.register_doctor, name="register-doctor"),
    path("doctor/status/", v.doctor_status, name="doctor-status"),

    # shared
    path("profile/", v.profile, name="profile"),
    path("password/", v.PasswordChange.as_view(), name="password"),
    path("visit/<int:pk>/", v.visit_detail, name="visit-detail"),
    path("visit/<int:pk>/print/", v.visit_print, name="visit-print"),

    # admin
    path("panel/", v.admin_dashboard, name="admin-dashboard"),
    path("panel/doctor-requests/", v.admin_doctor_requests, name="admin-doctor-requests"),
    path("panel/doctor/<int:pk>/approve/", v.approve_doctor, name="approve-doctor"),
    path("panel/doctor/<int:pk>/reject/", v.reject_doctor, name="reject-doctor"),
    path("panel/doctors/", v.admin_doctors, name="admin-doctors"),
    path("panel/doctors/<int:pk>/", v.admin_doctor_detail, name="admin-doctor-detail"),
    path("panel/doctors/<int:pk>/delete/", v.delete_doctor, name="admin-doctor-delete"),
    path("panel/patients/", v.admin_patients, name="admin-patients"),
    path("panel/patients/<int:pk>/", v.admin_patient_detail, name="admin-patient-detail"),
    path("panel/patients/<int:pk>/delete/", v.delete_patient, name="admin-patient-delete"),
    path("panel/patients/<int:pk>/records.zip", v.download_patient_records, name="admin-patient-zip"),
    path("panel/appointments/", v.admin_appointments, name="admin-appointments"),
    path("panel/appointments/add/", v.admin_appointment_add, name="admin-appointment-add"),
    path("panel/appointments/<int:pk>/cancel/", v.cancel_appointment, name="admin-appointment-cancel"),
    path("panel/billing/", v.admin_billing, name="admin-billing"),
    path("panel/billing/<int:pk>/collect/", v.collect_payment, name="collect-payment"),
    path("panel/payments/", v.admin_payments, name="admin-payments"),
    path("panel/staff/", v.admin_staff, name="admin-staff"),
    path("panel/staff/add/", v.admin_staff_add, name="admin-staff-add"),
    path("panel/staff/<int:pk>/toggle/", v.admin_staff_toggle, name="admin-staff-toggle"),
    path("panel/staff/<int:pk>/delete/", v.admin_staff_delete, name="admin-staff-delete"),
    path("panel/records/", v.admin_records, name="admin-records"),
    path("panel/records/all.zip", v.download_all_records, name="admin-records-zip"),

    # doctor
    path("doctor/", v.doctor_dashboard, name="doctor-dashboard"),
    path("doctor/queue/", v.doctor_queue, name="doctor-queue"),
    path("doctor/queue/<int:pk>/start/", v.start_checkup, name="doctor-start"),
    path("doctor/checkup/new/", v.new_checkup, name="doctor-new-checkup"),
    path("doctor/checkup/<int:pk>/", v.doctor_visit_edit, name="doctor-visit-edit"),
    path("doctor/checkup/<int:pk>/delete/", v.doctor_visit_delete, name="doctor-visit-delete"),
    path("doctor/checkups/", v.doctor_visits, name="doctor-visits"),
    path("doctor/earnings/", v.doctor_earnings, name="doctor-earnings"),

    # patient
    path("patient/", v.patient_dashboard, name="patient-dashboard"),
    path("patient/book/", v.patient_book, name="patient-book"),
    path("patient/appointments/", v.patient_appointments, name="patient-appointments"),
    path("patient/appointments/<int:pk>/cancel/", v.patient_cancel, name="patient-cancel"),
    path("patient/records/", v.patient_records, name="patient-records"),
    path("patient/doctors/", v.patient_doctors, name="patient-doctors"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

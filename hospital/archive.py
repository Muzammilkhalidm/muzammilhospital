"""Stores patient records on disk and builds ZIP downloads."""
import csv
import io
import json
import re
import zipfile
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string


def _slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_") or "patient"


def patient_folder_name(patient):
    return f"{patient.code}_{_slug(patient.full_name)}"


def render_record_html(visit, show_fee=True):
    return render_to_string("shared/visit_print.html", {
        "visit": visit, "show_fee": show_fee, "standalone": True,
        "HOSPITAL_NAME": settings.HOSPITAL_NAME, "CURRENCY": settings.CURRENCY,
    })


def record_dict(visit):
    return {
        "visit_code": visit.code,
        "receipt_no": visit.receipt_no,
        "date": visit.created_at.strftime("%Y-%m-%d %H:%M"),
        "patient": {"id": visit.patient.code, "name": visit.patient_name, "age": visit.age,
                    "gender": visit.gender, "height_cm": visit.height_cm,
                    "weight_kg": str(visit.weight_kg) if visit.weight_kg is not None else None,
                    "blood_pressure": visit.blood_pressure, "temperature": visit.temperature, "pulse": visit.pulse},
        "doctor": {"name": visit.doctor.display_name, "specialization": visit.doctor.specialization,
                   "qualification": visit.doctor.qualification, "university": visit.doctor.university,
                   "registration_no": visit.doctor.license_no},
        "problems": visit.problem_list,
        "diagnosis": visit.diagnosis_list,
        "tests": visit.test_list,
        "advice": visit.advice_list,
        "medicines": [{"medicine": i.medicine, "dose": i.dose, "frequency": i.frequency,
                       "duration": i.duration, "instructions": i.instructions} for i in visit.items.all()],
        "referral": {"to": visit.referral_to, "reason": visit.referral_notes},
        "follow_up": visit.follow_up.isoformat() if visit.follow_up else None,
        "payment": {"charges": visit.fee, "method": visit.payment_method,
                    "paid_at": visit.paid_at.strftime("%Y-%m-%d %H:%M") if visit.paid_at else None,
                    "doctor_percent": visit.doctor_percent, "doctor_amount": visit.doctor_amount,
                    "hospital_amount": visit.hospital_amount},
    }


def save_snapshot(visit):
    """Write the paid record into media/patient_records/<patient>/ (called when payment is received)."""
    folder = Path(settings.MEDIA_ROOT) / "patient_records" / patient_folder_name(visit.patient)
    folder.mkdir(parents=True, exist_ok=True)
    base = f"{visit.receipt_no or visit.code}_{visit.code}"
    (folder / f"{base}.html").write_text(render_record_html(visit), encoding="utf-8")
    (folder / f"{base}.json").write_text(json.dumps(record_dict(visit), indent=2, ensure_ascii=False), encoding="utf-8")


def build_zip(visits, patients=None):
    """Return bytes of a ZIP with one folder per patient plus summary CSVs."""
    visits = list(visits.select_related("patient__user", "doctor__user").prefetch_related("items"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        pay_rows = [["Receipt", "Date", "Patient ID", "Patient", "Doctor", "Charges", "Method",
                     "Doctor %", "Doctor share", "Hospital share"]]
        patient_map = {}
        for v in visits:
            patient_map[v.patient_id] = v.patient
            folder = patient_folder_name(v.patient)
            base = f"{v.receipt_no or v.code}_{v.code}"
            z.writestr(f"{folder}/{base}.html", render_record_html(v))
            z.writestr(f"{folder}/{base}.json", json.dumps(record_dict(v), indent=2, ensure_ascii=False))
            pay_rows.append([v.receipt_no, v.paid_at.strftime("%Y-%m-%d %H:%M") if v.paid_at else "", v.patient.code,
                             v.patient_name, v.doctor.display_name, v.fee, v.payment_method,
                             v.doctor_percent, v.doctor_amount, v.hospital_amount])
        for p in (patients or []):
            patient_map.setdefault(p.pk, p)
        rows = [["Patient ID", "Name", "Phone", "Gender", "Age", "Address"]]
        for p in patient_map.values():
            rows.append([p.code, p.full_name, p.phone, p.gender, p.age, p.address])
        for name, data in (("patients.csv", rows), ("payments.csv", pay_rows)):
            s = io.StringIO()
            csv.writer(s).writerows(data)
            z.writestr(name, "﻿" + s.getvalue())
    return buf.getvalue()

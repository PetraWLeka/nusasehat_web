"""
NusaHealth Cloud — Patient Views (EMR)
CRUD operations with role-based access control.
"""

import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.decorators import admin_required, staff_or_admin_required
from core.models import AuditLog
from .forms import PatientForm, PatientStatusForm
from .models import Patient

logger = logging.getLogger("nusahealth")


@login_required
@staff_or_admin_required
def patient_list_view(request):
    """List all patients with search, filter, sort."""
    patients = Patient.objects.filter(is_deleted=False)

    # Search
    q = request.GET.get("q", "").strip()
    if q:
        patients = patients.filter(
            Q(full_name__icontains=q) |
            Q(nik__icontains=q) |
            Q(village__icontains=q)
        )

    # Sort
    sort = request.GET.get("sort", "-created_at")
    allowed_sorts = ["full_name", "-full_name", "-created_at", "created_at"]
    if sort in allowed_sorts:
        patients = patients.order_by(sort)

    context = {
        "patients": patients,
        "query": q,
        "sort": sort,
    }
    return render(request, "patients/patient_list.html", context)


@login_required
@staff_or_admin_required
def patient_detail_view(request, pk):
    """View patient details + consultation history."""
    patient = get_object_or_404(Patient, pk=pk, is_deleted=False)

    # Get consultation history
    from consultations.models import ConsultationSession
    from reports.models import DiseaseReport

    consultations = ConsultationSession.objects.filter(
        patient=patient
    ).order_by("-created_at")

    disease_reports = DiseaseReport.objects.filter(
        patient=patient
    ).order_by("-created_at")

    context = {
        "patient": patient,
        "consultations": consultations,
        "disease_reports": disease_reports,
    }
    return render(request, "patients/patient_detail.html", context)


@login_required
@staff_or_admin_required
def patient_create_view(request):
    """Register new patient."""
    if request.method == "POST":
        form = PatientForm(request.POST, request.FILES)
        if form.is_valid():
            patient = form.save(commit=False)
            patient.created_by = request.user
            patient.save()
            AuditLog.log(
                user=request.user,
                action=AuditLog.ActionType.CREATE,
                description=f"Registrasi pasien baru: {patient.full_name}",
                target_model="Patient",
                target_id=patient.pk,
                ip_address=getattr(request, "_audit_ip", None),
            )
            messages.success(request, f"Pasien {patient.full_name} berhasil didaftarkan.")
            return redirect("patients:detail", pk=patient.pk)
    else:
        form = PatientForm()

    return render(request, "patients/patient_form.html", {"form": form, "is_edit": False})


@login_required
@staff_or_admin_required
def patient_edit_view(request, pk):
    """Edit patient — owner or Admin only."""
    patient = get_object_or_404(Patient, pk=pk, is_deleted=False)

    # Staff can only edit their own patients
    if not request.user.is_admin and patient.created_by != request.user:
        return HttpResponseForbidden(
            "<h1>403 Forbidden</h1><p>Anda hanya bisa mengedit pasien yang Anda daftarkan.</p>"
        )

    if request.method == "POST":
        form = PatientForm(request.POST, request.FILES, instance=patient)
        if form.is_valid():
            form.save()
            AuditLog.log(
                user=request.user,
                action=AuditLog.ActionType.UPDATE,
                description=f"Mengedit pasien: {patient.full_name}",
                target_model="Patient",
                target_id=patient.pk,
                ip_address=getattr(request, "_audit_ip", None),
            )
            messages.success(request, f"Data pasien {patient.full_name} berhasil diperbarui.")
            return redirect("patients:detail", pk=patient.pk)
    else:
        form = PatientForm(instance=patient)

    return render(request, "patients/patient_form.html", {
        "form": form,
        "is_edit": True,
        "patient": patient,
    })


@admin_required
@require_POST
def patient_delete_view(request, pk):
    """Soft delete patient — Admin only."""
    patient = get_object_or_404(Patient, pk=pk)
    patient.is_deleted = True
    patient.save()

    AuditLog.log(
        user=request.user,
        action=AuditLog.ActionType.DELETE,
        description=f"Menghapus pasien: {patient.full_name}",
        target_model="Patient",
        target_id=patient.pk,
        ip_address=getattr(request, "_audit_ip", None),
    )

    messages.success(request, f"Pasien {patient.full_name} berhasil dihapus.")
    return redirect("patients:list")


@login_required
@require_POST
def patient_update_status_view(request, pk):
    """Quick status update."""
    patient = get_object_or_404(Patient, pk=pk, is_deleted=False)
    form = PatientStatusForm(request.POST, instance=patient)
    if form.is_valid():
        form.save()
        messages.success(request, f"Status pasien diperbarui ke {patient.get_status_display()}.")
    return redirect("patients:detail", pk=patient.pk)

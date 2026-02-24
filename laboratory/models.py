"""
NusaHealth Cloud — Laboratory AI Models
Visual inspection using MedGemma 1.5 4B multimodal.
"""

from django.db import models
from core.models import User
from patients.models import Patient
from consultations.models import ConsultationSession


class VisualInspection(models.Model):
    """Record of an AI visual inspection."""

    class InspectionType(models.TextChoices):
        # Radiology — trained on MIMIC-CXR, ChestImaGenome, CT-RATE, Knee X-ray
        CHEST_XRAY = "chest_xray", "Rontgen Dada (Chest X-Ray)"
        KNEE_XRAY = "knee_xray", "Rontgen Lutut (Knee X-Ray)"
        CT_SCAN = "ct_scan", "CT Scan"
        # Dermatology — trained on PAD-UFES-20, SCIN, ISIC, + 6 proprietary sets
        DERMATOLOGY = "dermatology", "Dermatologi (Kulit)"
        # Ophthalmology — trained on EyePACS fundus images
        OPHTHALMOLOGY = "ophthalmology", "Oftalmologi (Mata/Fundus)"
        # Histopathology — trained on CAMELYON, TCGA, + 4 proprietary sets
        HISTOPATHOLOGY = "histopathology", "Histopatologi"
        # Clinical lab reports — trained on EHR datasets 2-4
        LAB_REPORT = "lab_report", "Laporan Lab Klinis"

    inspection_type = models.CharField(max_length=20, choices=InspectionType.choices)
    patient = models.ForeignKey(
        Patient, on_delete=models.SET_NULL, null=True, blank=True, related_name="inspections"
    )
    consultation = models.ForeignKey(
        ConsultationSession, on_delete=models.SET_NULL, null=True, blank=True, related_name="inspections"
    )

    # Image
    image = models.ImageField(upload_to="inspections/%Y/%m/")
    image_gcs_path = models.CharField(max_length=500, blank=True)

    # AI result
    findings = models.TextField(blank=True)
    model_used = models.CharField(max_length=50, default="medgemma-4b")
    latency_ms = models.IntegerField(null=True, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)

    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "visual_inspection"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_inspection_type_display()} — {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def display_diagnosis(self):
        """Extract clean diagnosis text for display, even from truncated JSON."""
        import json as _json
        import re as _re

        # 1. From raw_response dict
        if self.raw_response and isinstance(self.raw_response, dict):
            diag = self.raw_response.get("diagnosis", "")
            if diag:
                return diag

        # 2. Try parsing from findings (might contain raw JSON)
        text = self.findings or ""
        text = text.strip()
        # Strip markdown code-block wrapper
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        if text.startswith("{"):
            try:
                d = _json.loads(text)
                if d.get("diagnosis"):
                    return d["diagnosis"]
            except (ValueError, TypeError):
                pass
            # Regex fallback for truncated JSON
            m = _re.search(r'"diagnosis"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            if m:
                return m.group(1).replace("\\n", " ")

        return ""

    @property
    def display_confidence(self):
        """Extract confidence value, even from truncated JSON."""
        import re as _re
        if self.raw_response and isinstance(self.raw_response, dict):
            conf = self.raw_response.get("confidence", 0)
            if conf and float(conf) != 0.7:  # 0.7 is fallback default
                return float(conf)
        text = self.findings or ""
        m = _re.search(r'"confidence"\s*:\s*([\d.]+)', text)
        if m:
            return float(m.group(1))
        return 0

    @classmethod
    def get_prompt_for_type(cls, inspection_type):
        """Return the medical analysis prompt for each inspection type.

        Each prompt requests structured JSON output including bounding box
        coordinates for regions of interest. Coordinates are normalized 0-1000
        (Gemma 3 / MedGemma spatial format: [ymin, xmin, ymax, xmax]).
        """
        bbox_instruction = (
            '\n\nFormat respons sebagai JSON:\n'
            '{\n'
            '  "diagnosis": "diagnosis utama",\n'
            '  "confidence": 0.0-1.0,\n'
            '  "findings": "deskripsi temuan lengkap",\n'
            '  "recommendations": "rekomendasi tindakan",\n'
            '  "regions": [\n'
            '    {\n'
            '      "label": "nama area/temuan",\n'
            '      "description": "deskripsi singkat",\n'
            '      "severity": "normal|perhatian|abnormal",\n'
            '      "bbox": [ymin, xmin, ymax, xmax]\n'
            '    }\n'
            '  ]\n'
            '}\n'
            'Koordinat bbox dalam skala 0-1000 relatif terhadap ukuran gambar. '
            'Pastikan setiap temuan klinis memiliki region yang sesuai.'
        )

        prompts = {
            cls.InspectionType.CHEST_XRAY: (
                "Sebagai radiolog, analisis rontgen dada ini. "
                "Lokalisasi fitur anatomis dan daftarkan potensi abnormalitas. "
                "Evaluasi cardiothoracic ratio, parenkim paru, dan sinus costofrenikus. "
                "Tandai setiap area abnormal dengan koordinat."
                + bbox_instruction
            ),
            cls.InspectionType.KNEE_XRAY: (
                "Sebagai radiolog orthopedi, analisis rontgen lutut ini. "
                "Evaluasi ruang sendi, alignment tulang, kepadatan tulang, "
                "dan tanda-tanda osteoarthritis, fraktur, atau kelainan lainnya. "
                "Tandai area abnormal."
                + bbox_instruction
            ),
            cls.InspectionType.CT_SCAN: (
                "Sebagai radiolog, analisis gambar CT scan ini. "
                "Identifikasi struktur anatomis, evaluasi organ yang terlihat, "
                "dan cari tanda-tanda patologi seperti massa, efusi, atau kelainan lainnya. "
                "Tandai setiap temuan abnormal."
                + bbox_instruction
            ),
            cls.InspectionType.DERMATOLOGY: (
                "Sebagai dermatolog, analisis gambar kulit ini. "
                "Identifikasi jenis lesi, distribusi, morfologi, dan batas-batasnya. "
                "Berikan differential diagnosis termasuk kemungkinan keganasan kulit, "
                "infeksi jamur, lepra, dermatitis, atau kondisi kulit lainnya. "
                "Tandai setiap lesi atau area abnormal."
                + bbox_instruction
            ),
            cls.InspectionType.OPHTHALMOLOGY: (
                "Sebagai oftalmolog, analisis gambar fundus/retina ini. "
                "Evaluasi diskus optik, makula, pembuluh darah retina, "
                "dan cari tanda-tanda retinopati diabetik, glaukoma, "
                "degenerasi makula, atau kelainan retina lainnya. "
                "Tandai area abnormal."
                + bbox_instruction
            ),
            cls.InspectionType.HISTOPATHOLOGY: (
                "Sebagai patolog, analisis gambar histopatologi ini. "
                "Identifikasi tipe jaringan, arsitektur sel, dan tanda-tanda "
                "keganasan atau patologi. Evaluasi diferensiasi sel, mitosis, "
                "nekrosis, dan invasi. Tandai area yang mencurigakan."
                + bbox_instruction
            ),
            cls.InspectionType.LAB_REPORT: (
                "Sebagai dokter patologi klinik, analisis laporan laboratorium ini. "
                "Baca dan ekstrak semua nilai pemeriksaan, identifikasi nilai abnormal, "
                "dan berikan interpretasi klinis. Format hasilnya dalam JSON:\n"
                '{\n'
                '  "diagnosis": "interpretasi keseluruhan",\n'
                '  "confidence": 0.0-1.0,\n'
                '  "findings": "deskripsi lengkap semua temuan lab",\n'
                '  "recommendations": "rekomendasi tindakan",\n'
                '  "lab_values": [\n'
                '    {"test": "nama tes", "value": "hasil", "unit": "satuan", '
                '"status": "normal|tinggi|rendah|kritis"}\n'
                '  ],\n'
                '  "regions": []\n'
                '}'
            ),
        }
        return prompts.get(inspection_type, "")

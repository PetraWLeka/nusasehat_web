"""
NusaHealth Cloud — Education Celery Tasks
Background AI generation of education materials.
"""

import json
import logging
import re

from celery import shared_task

logger = logging.getLogger("nusahealth")


def _parse_ai_response(raw_text):
    """Parse AI response into dict — handles fences, partial JSON, etc."""
    text = raw_text.strip()

    # Strip markdown fences
    fence = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if fence:
        text = fence.group(1).strip()

    # Try JSON parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass

    # Try to find JSON object in the text
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

    return None


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def generate_education_material(self, material_id):
    """Generate education content for a single disease using AI 4B.

    Dispatched by button click — not auto-generated.
    """
    try:
        from education.models import EducationMaterial
        from services.ai_service import AIService

        material = EducationMaterial.objects.get(pk=material_id)

        ai_service = AIService()
        result = ai_service.generate_education_material(
            disease_name=material.disease_name,
            disease_category=material.disease_category,
        )

        # result is a dict from ai_service (already attempted JSON parse)
        # But may still contain raw text — double-check
        if isinstance(result, str):
            parsed = _parse_ai_response(result)
            if parsed:
                result = parsed
            else:
                result = {"description": result}

        # If ai_service returned a dict with a single text blob, try re-parsing
        desc = result.get("description", "")
        if desc and not result.get("symptoms") and not result.get("prevention"):
            parsed = _parse_ai_response(desc)
            if parsed and parsed.get("symptoms"):
                result = parsed

        def _to_str(val):
            """Coerce AI output to string — handles list, dict, etc."""
            if isinstance(val, list):
                return "\n".join(f"- {item}" if not str(item).startswith("-") else str(item) for item in val)
            if isinstance(val, dict):
                return "\n".join(f"- {v}" for v in val.values())
            return str(val).strip() if val else ""

        material.description = _to_str(result.get("description", ""))
        material.symptoms = _to_str(result.get("symptoms", ""))
        material.prevention = _to_str(result.get("prevention", ""))
        material.when_to_visit = _to_str(result.get("when_to_visit", ""))
        material.save()

        logger.info(f"Education material generated: {material.disease_name}")
        return {"status": "success", "id": material_id}

    except EducationMaterial.DoesNotExist:
        logger.warning(f"Education material {material_id} not found")
        return {"status": "not_found", "id": material_id}
    except Exception as e:
        logger.error(f"Education material generation failed: {e}", exc_info=True)
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=1)
def generate_all_education_materials(self):
    """Generate education materials for all top illnesses from CSV.

    Can be triggered manually or scheduled via Beat.
    """
    try:
        from pathlib import Path
        from django.conf import settings
        from education.models import EducationMaterial

        import pandas as pd
        csv_path = Path(settings.BASE_DIR) / "data" / "illness_tracking.csv"
        if not csv_path.exists():
            logger.warning("No illness CSV found for education generation")
            return {"status": "no_data"}

        df = pd.read_csv(csv_path)
        df["illness"] = df["illness"].astype(str).str.strip().str.lower()
        df = df[df["illness"].str.len().between(1, 80)]
        df = df[df["illness"].str.match(r'^[a-z]')]
        if df.empty:
            return {"status": "no_data"}

        agg = df.groupby("illness")["count"].sum().sort_values(ascending=False).head(10)
        generated = 0

        for name, cnt in agg.items():
            material, created = EducationMaterial.objects.get_or_create(
                disease_category=name,
                defaults={
                    "disease_name": name.title(),
                    "case_count": int(cnt),
                },
            )
            if material.case_count != int(cnt):
                material.case_count = int(cnt)
                material.save(update_fields=["case_count"])

            if created or not material.description:
                generate_education_material.delay(material.pk)
                generated += 1

        logger.info(f"Triggered education generation for {generated} materials")
        return {"status": "success", "triggered": generated}

    except Exception as e:
        logger.error(f"Bulk education generation failed: {e}", exc_info=True)
        raise self.retry(exc=e)

"""
One-time management command to clean raw JSON from existing chat messages.
Usage:  python manage.py clean_chat_json
        python manage.py clean_chat_json --dry-run
"""

import json
import re

from django.core.management.base import BaseCommand

from consultations.models import ChatMessage


def _extract_response(text):
    """Extract 'response' field from JSON/truncated JSON."""
    if not isinstance(text, str) or not text.strip():
        return None
    t = text.strip()
    # Strip fences
    fence = re.search(r'```(?:json)?\s*([\s\S]*?)```', t)
    if fence:
        t = fence.group(1).strip()
    # Full parse
    if t.startswith("{"):
        try:
            parsed = json.loads(t)
            if isinstance(parsed, dict) and "response" in parsed:
                return parsed["response"]
        except (json.JSONDecodeError, TypeError):
            pass
    # Regex fallback
    if '"response"' in t:
        m = re.search(r'"response"\s*:\s*"((?:[^"\\]|\\.)*)"', t)
        if m:
            try:
                return json.loads('"' + m.group(1) + '"')
            except (json.JSONDecodeError, TypeError):
                return m.group(1)
    return None


class Command(BaseCommand):
    help = "Clean raw JSON artifacts from AI chat messages in the database."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show what would be cleaned without saving.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        ai_messages = ChatMessage.objects.exclude(sender_type="user")
        cleaned = 0
        total = ai_messages.count()

        for msg in ai_messages.iterator():
            extracted = _extract_response(msg.content)
            if extracted and extracted != msg.content:
                if dry_run:
                    self.stdout.write(f"  [DRY] Message {msg.pk}: {msg.content[:80]}... -> {extracted[:80]}...")
                else:
                    msg.content = extracted
                    msg.save(update_fields=["content"])
                cleaned += 1

        action = "Would clean" if dry_run else "Cleaned"
        self.stdout.write(self.style.SUCCESS(f"{action} {cleaned}/{total} AI messages."))

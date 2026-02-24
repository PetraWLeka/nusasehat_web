"""
NusaHealth Cloud — PII Masking Log Filter
Masks sensitive patient data (NIK, names) in log output.
"""

import logging
import re
from django.conf import settings


class PIIMaskingFilter(logging.Filter):
    """Filter that masks PII data in log records."""

    # Pattern for Indonesian NIK (16 digits)
    NIK_PATTERN = re.compile(r"\b\d{16}\b")
    # Pattern for phone numbers
    PHONE_PATTERN = re.compile(r"\b(?:\+62|62|0)\d{8,12}\b")

    def filter(self, record):
        if not getattr(settings, "ENABLE_PII_MASKING", True):
            return True

        if hasattr(record, "msg") and isinstance(record.msg, str):
            record.msg = self.NIK_PATTERN.sub("****NIK-MASKED****", record.msg)
            record.msg = self.PHONE_PATTERN.sub("****PHONE-MASKED****", record.msg)

        if hasattr(record, "args") and record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self._mask_value(v) for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(self._mask_value(a) for a in record.args)

        return True

    def _mask_value(self, value):
        if not isinstance(value, str):
            return value
        value = self.NIK_PATTERN.sub("****NIK-MASKED****", value)
        value = self.PHONE_PATTERN.sub("****PHONE-MASKED****", value)
        return value

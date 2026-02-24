"""
NusaHealth Cloud — AI Service Layer
Triple backend: Cloud Run (MedGemma 4B/27B via vLLM, default),
Vertex AI (MedGemma via google-genai), or OpenRouter (Gemma 3 27B).
Controlled by settings.AI_BACKEND ("cloud_run" | "vertex_ai" | "openrouter").

Cloud Run (default):
  - Two Cloud Run GPU services running vLLM with OpenAI-compatible API
  - 4B  = multimodal, fast triage (L4 GPU)
  - 27B = text-only, deep specialist (L4 GPU)
  - Auth via Google OIDC ID tokens (service account)
  - Scale-to-zero for cost savings

Vertex AI (alternative):
  - Uses google-genai SDK with vertexai=True
  - Auth via Application Default Credentials / service account

OpenRouter (fallback):
  - Gemma 3 27B free tier (single model, no escalation)
"""

import json
import logging
import re
import time
import base64
import threading
from io import BytesIO

import requests as http_requests

from django.conf import settings

try:
    from google import genai as google_genai
    from google.genai import types as genai_types
except ImportError:
    google_genai = None
    genai_types = None

logger = logging.getLogger("nusahealth")


class AIService:
    """Unified AI service — routes to Cloud Run, Vertex AI, or OpenRouter."""

    # Class-level OIDC token cache (shared across instances, thread-safe)
    _token_cache = {}      # {audience_url: (token_str, expiry_time)}
    _token_lock = threading.Lock()

    def __init__(self):
        self._backend = getattr(settings, "AI_BACKEND", "cloud_run")
        self._available = None  # None = unchecked
        self._genai_client = None  # Lazy-initialized for Vertex AI

    # ── Availability ─────────────────────────────────────────────────

    @property
    def is_available(self):
        if self._available is None:
            if not getattr(settings, "AI_ENABLED", False):
                self._available = False
            elif self._backend == "openrouter":
                self._available = bool(getattr(settings, "OPENROUTER_API_KEY", ""))
            elif self._backend == "cloud_run":
                url = getattr(settings, "CLOUD_RUN_4B_URL", "")
                self._available = bool(url) and url.startswith("https://")
            else:
                # Vertex AI: check project ID is set
                self._available = bool(getattr(settings, "GCP_PROJECT_ID", ""))
        return self._available

    # ── Cloud Run OIDC Authentication ────────────────────────────────

    def _get_oidc_token(self, audience_url):
        """Get a cached Google OIDC ID token for the Cloud Run audience.

        Tokens are cached for 50 minutes (they expire after 60 min).
        Thread-safe via a class-level lock.
        """
        now = time.time()

        with self._token_lock:
            cached = self._token_cache.get(audience_url)
            if cached and cached[1] > now:
                return cached[0]

        # Generate new token outside the lock (network call)
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests

        token = id_token.fetch_id_token(google_requests.Request(), audience_url)

        with self._token_lock:
            # Cache for 50 minutes
            self._token_cache[audience_url] = (token, now + 3000)

        return token

    def _cloud_run_chat(self, cloud_run_url, model_name, messages,
                        max_tokens=2048, temperature=0.3):
        """Call a Cloud Run vLLM service (OpenAI-compatible /v1/chat/completions).

        Args:
            cloud_run_url: base URL of the Cloud Run service
            model_name: HuggingFace model ID running in vLLM
            messages: list of {"role": ..., "content": ...}
            max_tokens: max output tokens
            temperature: sampling temperature

        Returns:
            str — the assistant's reply text
        """
        token = self._get_oidc_token(cloud_run_url)

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        body = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.8,
        }

        api_endpoint = f"{cloud_run_url.rstrip('/')}/v1/chat/completions"

        # Pre-truncate: MedGemma 4B context = 4096 tokens.
        # ~4 chars/token → keep total prompt under ~8000 chars input
        # to leave room for max_tokens output.
        MAX_INPUT_CHARS = 8000
        total_chars = sum(len(m["content"]) for m in body["messages"])
        if total_chars > MAX_INPUT_CHARS:
            # Shrink the longest user message to fit
            user_msgs = [m for m in body["messages"] if m["role"] == "user"]
            sys_chars = sum(len(m["content"]) for m in body["messages"] if m["role"] != "user")
            if user_msgs:
                budget = MAX_INPUT_CHARS - sys_chars
                longest = max(user_msgs, key=lambda m: len(m["content"]))
                if len(longest["content"]) > budget:
                    old_len = len(longest["content"])
                    longest["content"] = longest["content"][:max(500, budget)]
                    logger.info(
                        f"Pre-truncated prompt: {old_len} → {len(longest['content'])} chars "
                        f"(total was {total_chars}, target {MAX_INPUT_CHARS})"
                    )

        # Retry logic for cold starts, transient errors, and token overflow
        max_retries = 6
        for attempt in range(max_retries):
            try:
                resp = http_requests.post(
                    api_endpoint,
                    headers=headers,
                    json=body,
                    timeout=300,  # 5 min — Cloud Run cold start can take 2-3 min
                )

                if resp.status_code == 200:
                    break

                if resp.status_code == 429:
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(f"Cloud Run 429 rate limit. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                if resp.status_code == 400:
                    err_text = resp.text.lower()
                    is_token_err = ("max_tokens" in err_text or "context length" in err_text
                                    or "input tokens" in err_text or "maximum context" in err_text)
                    if is_token_err:
                        old_mt = body["max_tokens"]
                        if old_mt > 256:
                            # Step 1: halve max_tokens down to 256
                            body["max_tokens"] = max(256, old_mt // 2)
                            logger.warning(
                                f"Cloud Run 400 token overflow ({old_mt}). "
                                f"Reducing max_tokens to {body['max_tokens']} and retrying..."
                            )
                            continue
                        else:
                            # Step 2: max_tokens already at minimum — truncate input
                            user_msgs = [m for m in body["messages"] if m["role"] == "user"]
                            if user_msgs:
                                longest = max(user_msgs, key=lambda m: len(m["content"]))
                                old_len = len(longest["content"])
                                if old_len > 200:
                                    longest["content"] = longest["content"][:int(old_len * 0.6)]
                                    logger.warning(
                                        f"Cloud Run 400 input overflow ({old_len} chars). "
                                        f"Truncated to {len(longest['content'])} chars and retrying..."
                                    )
                                    continue
                            raise RuntimeError(
                                f"Cloud Run 400 input too long even after truncation: {resp.text[:300]}"
                            )

                if resp.status_code == 503:
                    # Cold start — service is booting
                    wait_time = 10 * (attempt + 1)
                    logger.info(f"Cloud Run 503 (cold start). Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    # Refresh token in case it's a new instance
                    token = self._get_oidc_token(cloud_run_url)
                    headers["Authorization"] = f"Bearer {token}"
                    continue

                error_detail = resp.text[:500]
                raise RuntimeError(
                    f"Cloud Run API error {resp.status_code}: {error_detail}"
                )

            except http_requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    wait_time = 15 * (attempt + 1)
                    logger.warning(f"Cloud Run timeout. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                raise RuntimeError("Cloud Run request timed out after retries")
        else:
            raise RuntimeError("Cloud Run API request failed after retries")

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(f"Cloud Run returned empty choices: {data}")

        raw_text = choices[0]["message"]["content"]
        return self._strip_thought_tokens(raw_text)

    # ── Thought-token stripping ──────────────────────────────────────

    @staticmethod
    def _strip_thought_tokens(text):
        """Strip MedGemma <unused94>thought ... </unused94> chain-of-thought tokens.

        MedGemma 4B outputs thinking in the format:
          <unused94>thought\n...chain of thought...<unused94>\nActual response
        We strip the thought block and return only the actual response.
        If no clean response follows the thought, we try to extract
        a JSON object from the thought text itself.
        """
        if not text or "<unused" not in text:
            return text

        # Pattern: <unusedNN>thought ... <unusedNN> ... actual response
        # Also handles: <unused94>thought\n...\n</unused94>\nresponse
        cleaned = re.sub(
            r"<unused\d+>\s*thought\s*\n.*?<unused\d+>",
            "",
            text,
            flags=re.DOTALL,
        ).strip()

        if cleaned:
            return cleaned

        # Fallback: the entire response was thought tokens.
        # Try to extract a JSON block from inside the thought.
        json_match = re.search(r"```json\s*\n(\{.*?\})\s*\n```", text, re.DOTALL)
        if json_match:
            return json_match.group(1)

        # Last resort: strip just the opening tag and return rest
        cleaned = re.sub(r"<unused\d+>\s*(?:thought)?\s*\n?", "", text).strip()
        return cleaned if cleaned else text

    # ── OpenRouter HTTP Call ─────────────────────────────────────────

    def _openrouter_chat(self, messages, max_tokens=2048, temperature=0.3, json_mode=False):
        """Call OpenRouter API (OpenAI-compatible chat completions).

        Args:
            messages: list of {"role": "system"|"user"|"assistant", "content": ...}
            max_tokens: max output tokens
            temperature: sampling temperature
            json_mode: if True, request JSON response format

        Returns:
            str — the assistant's reply text
        """
        api_key = settings.OPENROUTER_API_KEY
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": getattr(settings, "OPENROUTER_SITE_URL", ""),
            "X-Title": getattr(settings, "OPENROUTER_SITE_NAME", "NusaHealth"),
        }

        body = {
            "model": settings.OPENROUTER_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.8,
        }

        if json_mode:
            body["response_format"] = {"type": "json_object"}

        # Custom retry for 429 (rate limit)
        max_retries = 3
        for attempt in range(max_retries):
            resp = http_requests.post(
                settings.OPENROUTER_BASE_URL,
                headers=headers,
                json=body,
                timeout=60,
            )

            if resp.status_code == 200:
                break
            
            if resp.status_code == 429:
                wait_time = 2 ** (attempt + 1)
                logger.warning(f"OpenRouter 429 Rate Limit. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
                
            error_detail = resp.text[:500]
            raise RuntimeError(f"OpenRouter API error {resp.status_code}: {error_detail}")
        else:
            raise RuntimeError("OpenRouter API rate limit exceeded after retries.")

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(f"OpenRouter returned empty choices: {data}")

        return choices[0]["message"]["content"]

    # ── Vertex AI (google-genai SDK) ────────────────────────────────

    def _get_genai_client(self):
        """Lazy-initialize the google-genai client for Vertex AI."""
        if self._genai_client is None:
            if google_genai is None:
                raise RuntimeError(
                    "google-genai package not installed. "
                    "Run: pip install google-genai"
                )
            self._genai_client = google_genai.Client(
                vertexai=True,
                project=settings.GCP_PROJECT_ID,
                location=getattr(settings, "VERTEX_AI_LOCATION", "us-central1"),
            )
        return self._genai_client

    def _vertex_ai_chat(self, model_name, contents, system_instruction=None,
                        max_tokens=2048, temperature=0.3):
        """Call Vertex AI via google-genai SDK.

        Args:
            model_name: Vertex AI model ID (e.g. 'medgemma-4b-it')
            contents: string, list of Parts, or list of Content objects
            system_instruction: optional system prompt
            max_tokens: max output tokens
            temperature: sampling temperature

        Returns:
            str — the model's reply text
        """
        client = self._get_genai_client()

        config = genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=max_tokens,
            temperature=temperature,
            top_p=0.8,
        )

        # Retry logic for transient errors
        max_retries = 3
        last_error = None
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config,
                )
                if response.text:
                    return response.text
                # Handle blocked / empty responses
                finish = "unknown"
                if response.candidates:
                    finish = getattr(response.candidates[0], "finish_reason", "unknown")
                raise RuntimeError(
                    f"Vertex AI returned empty response. Finish reason: {finish}"
                )
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                if any(k in error_str for k in ("429", "503", "resource_exhausted", "unavailable", "deadline")):
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(f"Vertex AI transient error ({e}). Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                raise

        raise RuntimeError(f"Vertex AI request failed after {max_retries} retries: {last_error}")

    # ── Text Generation (triple backend) ─────────────────────────────

    def query_4b(self, prompt, system_instruction=None, max_tokens=2048):
        """Query frontline model (OpenRouter Gemma 3 27B · or · Vertex MedGemma 4B)."""
        return self._generate_text(
            model_tier="4b",
            prompt=prompt,
            system_instruction=system_instruction,
            max_tokens=max_tokens,
        )

    def query_27b(self, prompt, system_instruction=None, max_tokens=8192):
        """Query specialist model (OpenRouter Gemma 3 27B · or · Vertex MedGemma 27B).

        Default max_tokens=8192 to utilise the 27B model's full generation
        capability for deep analysis, specialist consultations, and reports.
        """
        return self._generate_text(
            model_tier="27b",
            prompt=prompt,
            system_instruction=system_instruction,
            max_tokens=max_tokens,
        )

    def _generate_text(self, model_tier, prompt, system_instruction=None, max_tokens=2048):
        """Route text generation to the active backend."""
        start_time = time.time()

        try:
            if self._backend == "openrouter":
                text = self._generate_text_openrouter(
                    prompt, system_instruction, max_tokens,
                )
            elif self._backend == "cloud_run":
                text = self._generate_text_cloud_run(
                    model_tier, prompt, system_instruction, max_tokens,
                )
            else:
                text = self._generate_text_vertex_ai(
                    model_tier, prompt, system_instruction, max_tokens,
                )

            latency = time.time() - start_time
            if self._backend == "openrouter":
                model_name = settings.OPENROUTER_MODEL
            elif self._backend == "cloud_run":
                model_name = f"cloud-run-{model_tier}"
            else:
                model_name = f"vertex-ai-{model_tier}"
            logger.info(
                f"AI [{model_name}] response: "
                f"{len(text)} chars, {latency:.2f}s"
            )
            return {
                "text": text,
                "latency": round(latency, 2),
                "model_tier": model_tier,
                "backend": self._backend,
                "success": True,
            }

        except Exception as e:
            latency = time.time() - start_time
            logger.error(f"AI [{self._backend}/{model_tier}] failed: {e}", exc_info=True)
            return {
                "text": "",
                "latency": round(latency, 2),
                "model_tier": model_tier,
                "backend": self._backend,
                "success": False,
                "error": str(e),
            }

    def _generate_text_openrouter(self, prompt, system_instruction, max_tokens):
        """Text generation via OpenRouter."""
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})
        return self._openrouter_chat(messages, max_tokens=max_tokens)

    def _generate_text_cloud_run(self, model_tier, prompt, system_instruction, max_tokens):
        """Text generation via Cloud Run vLLM (OpenAI-compatible).

        Routes to 4B (multimodal, triage) or 27B (text specialist) based
        on model_tier. Falls back to 4B if 27B URL is not configured.
        """
        if model_tier == "27b":
            url = getattr(settings, "CLOUD_RUN_27B_URL", "") or settings.CLOUD_RUN_4B_URL
            model = getattr(settings, "CLOUD_RUN_MODEL_27B", "") or settings.CLOUD_RUN_MODEL_4B
            if url == settings.CLOUD_RUN_4B_URL:
                logger.info("27B URL not configured — falling back to 4B")
        else:
            url = settings.CLOUD_RUN_4B_URL
            model = settings.CLOUD_RUN_MODEL_4B

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        return self._cloud_run_chat(url, model, messages, max_tokens=max_tokens)

    def _generate_text_vertex_ai(self, model_tier, prompt, system_instruction, max_tokens):
        """Text generation via Vertex AI (google-genai SDK)."""
        if model_tier == "4b":
            model = settings.VERTEX_AI_MODEL_4B
        else:
            model = getattr(settings, "VERTEX_AI_MODEL_27B", "") or settings.VERTEX_AI_MODEL_4B

        return self._vertex_ai_chat(
            model_name=model,
            contents=prompt,
            system_instruction=system_instruction,
            max_tokens=max_tokens,
        )

    # ── Image Analysis (triple backend) ───────────────────────────────

    def analyze_image(self, image_file, inspection_type, medical_prompt):
        """Analyze a medical image.

        Args:
            image_file: file-like object with .read() OR a filesystem path (str).
            inspection_type: e.g. "malaria", "chest_xray" etc.
            medical_prompt: the full prompt text to send.

        Returns dict with diagnosis, findings, confidence, recommendations,
        regions, latency, raw_response, success.
        """
        start_time = time.time()

        try:
            # Normalise image input: accept file objects or paths
            if isinstance(image_file, str):
                with open(image_file, "rb") as f:
                    image_bytes = f.read()
                content_type = "image/jpeg"
                if image_file.lower().endswith(".png"):
                    content_type = "image/png"
                elif image_file.lower().endswith(".webp"):
                    content_type = "image/webp"
            else:
                image_bytes = image_file.read()
                image_file.seek(0)
                content_type = getattr(image_file, "content_type", "image/jpeg")

            if self._backend == "openrouter":
                text = self._analyze_image_openrouter(
                    image_bytes, content_type, medical_prompt,
                )
            elif self._backend == "cloud_run":
                text = self._analyze_image_cloud_run(
                    image_bytes, content_type, medical_prompt,
                )
            else:
                text = self._analyze_image_vertex_ai(
                    image_bytes, content_type, medical_prompt,
                )

            latency = time.time() - start_time

            # Strip thought tokens before parsing
            text = self._strip_thought_tokens(text)

            result = self._parse_image_analysis(text, inspection_type)
            result["latency"] = round(latency, 2)
            result["raw_response"] = text
            result["success"] = True

            logger.info(f"Image analysis ({inspection_type}): {latency:.2f}s")
            return result

        except Exception as e:
            latency = time.time() - start_time
            logger.error(f"Image analysis failed: {e}", exc_info=True)
            return {
                "diagnosis": "Analisis gagal",
                "findings": str(e),
                "confidence": 0.0,
                "recommendations": "",
                "regions": [],
                "latency": round(latency, 2),
                "success": False,
                "error": str(e),
            }

    def _analyze_image_openrouter(self, image_bytes, content_type, medical_prompt):
        """Image analysis via OpenRouter multimodal (Gemma 3 27B vision)."""
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        data_uri = f"data:{content_type};base64,{b64}"

        system_msg = (
            "Anda adalah dokter spesialis yang menganalisis gambar medis. "
            "Berikan analisis dalam Bahasa Indonesia dengan format JSON terstruktur."
        )

        messages = [
            {"role": "system", "content": system_msg},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": medical_prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            },
        ]

        return self._openrouter_chat(messages, max_tokens=2048, temperature=0.2)

    def _analyze_image_cloud_run(self, image_bytes, content_type, medical_prompt):
        """Image analysis via Cloud Run vLLM (4B model is multimodal)."""
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        data_uri = f"data:{content_type};base64,{b64}"

        system_msg = (
            "Anda adalah dokter spesialis yang menganalisis gambar medis. "
            "Berikan analisis dalam Bahasa Indonesia dengan format JSON terstruktur."
        )

        messages = [
            {"role": "system", "content": system_msg},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": medical_prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            },
        ]

        return self._cloud_run_chat(
            settings.CLOUD_RUN_4B_URL,
            settings.CLOUD_RUN_MODEL_4B,
            messages,
            max_tokens=2048,
            temperature=0.2,
        )

    def _analyze_image_vertex_ai(self, image_bytes, content_type, medical_prompt):
        """Image analysis via Vertex AI (multimodal, google-genai SDK)."""
        system_msg = (
            "Anda adalah dokter spesialis yang menganalisis gambar medis. "
            "Berikan analisis dalam Bahasa Indonesia dengan format JSON terstruktur."
        )

        contents = [
            genai_types.Part.from_bytes(data=image_bytes, mime_type=content_type),
            genai_types.Part.from_text(text=medical_prompt),
        ]

        return self._vertex_ai_chat(
            model_name=settings.VERTEX_AI_MODEL_4B,
            contents=contents,
            system_instruction=system_msg,
            max_tokens=2048,
            temperature=0.2,
        )

    def _parse_image_analysis(self, text, inspection_type):
        """Parse AI image analysis response into structured data with regions."""

        def _build_result(data, fallback_text):
            return {
                "diagnosis": data.get("diagnosis", ""),
                "findings": data.get("findings", fallback_text),
                "confidence": float(data.get("confidence", 0.7)),
                "recommendations": data.get("recommendations", ""),
                "regions": self._validate_regions(data.get("regions", [])),
            }

        # Strip markdown code-block wrappers (```json ... ```)
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        # Try parsing cleaned text as JSON first
        try:
            data = json.loads(cleaned)
            return _build_result(data, text)
        except (json.JSONDecodeError, ValueError):
            pass

        # Try extracting JSON object from mixed text
        try:
            json_match = cleaned[cleaned.index("{"):cleaned.rindex("}") + 1]
            data = json.loads(json_match)
            return _build_result(data, text)
        except (json.JSONDecodeError, ValueError, IndexError):
            pass

        # Try with regex to handle malformed JSON (e.g. trailing commas)
        try:
            m = re.search(r'\{[\s\S]*\}', cleaned)
            if m:
                raw_json = m.group(0)
                # Remove trailing commas before } or ]
                raw_json = re.sub(r',\s*([}\]])', r'\1', raw_json)
                data = json.loads(raw_json)
                return _build_result(data, text)
        except (json.JSONDecodeError, ValueError):
            pass

        # Regex fallback: extract individual fields from truncated/malformed JSON
        def _regex_extract(key):
            """Extract a JSON string value by key using regex."""
            m = re.search(r'"' + key + r'"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned)
            if m:
                return m.group(1).replace("\\n", "\n").replace("\\t", "\t")
            return ""

        def _regex_extract_number(key, default=0):
            m = re.search(r'"' + key + r'"\s*:\s*([\d.]+)', cleaned)
            return float(m.group(1)) if m else default

        diagnosis = _regex_extract("diagnosis") or self._extract_field(text, ["diagnosis", "diagnosa"])
        findings_val = _regex_extract("findings")
        recommendations = _regex_extract("recommendations")
        confidence = _regex_extract_number("confidence", 0.7)

        # Try to extract recommendations array
        if not recommendations:
            m = re.search(r'"recommendations"\s*:\s*\[(.*?)\]', cleaned, re.DOTALL)
            if m:
                items = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
                recommendations = "\n".join(f"- {item}" for item in items)

        return {
            "diagnosis": diagnosis,
            "findings": findings_val or text,
            "confidence": confidence,
            "recommendations": recommendations or self._extract_field(text, ["rekomendasi", "recommendation"]),
            "regions": [],
        }

    @staticmethod
    def _validate_regions(regions):
        """Validate and sanitize bounding box regions from AI response."""
        if not isinstance(regions, list):
            return []

        valid = []
        for r in regions:
            if not isinstance(r, dict):
                continue
            bbox = r.get("bbox", [])
            if isinstance(bbox, list) and len(bbox) == 4:
                try:
                    ymin, xmin, ymax, xmax = [
                        max(0, min(1000, int(float(v)))) for v in bbox
                    ]
                    if ymin < ymax and xmin < xmax:
                        valid.append({
                            "label": str(r.get("label", "Temuan"))[:100],
                            "description": str(r.get("description", ""))[:300],
                            "severity": r.get("severity", "perhatian"),
                            "bbox": [ymin, xmin, ymax, xmax],
                        })
                except (ValueError, TypeError):
                    continue
        return valid

    # ── Consultation Support ─────────────────────────────────────────

    def direct_consultation(self, patient_context, message, chat_history=None, rag_context=None):
        """Single-call consultation — no triage/escalation split.

        Used when the backend has only one model (e.g. OpenRouter free tier)
        so we don't waste two API calls on the same model.
        """
        system_instruction = (
            "Anda adalah asisten medis AI senior di Puskesmas Indonesia. "
            "Berikan jawaban medis yang lengkap, akurat, dan dalam Bahasa Indonesia.\n\n"
            "Panduan:\n"
            "- Jawab langsung dan ringkas jika pertanyaan sederhana.\n"
            "- Untuk keluhan medis, berikan triase (hijau/kuning/merah), kemungkinan diagnosis, "
            "dan saran tindakan.\n"
            "- Jika serius, rekomendasikan rujukan ke dokter/RS.\n"
            "- Selalu gunakan Bahasa Indonesia yang mudah dipahami.\n"
            "- Ekstrak penyakit (illnesses) dalam 1-2 kata (misal: 'Malaria', 'ISPA'). Jika tidak ada penyakit atau hanya pertanyaan umum, kosongkan.\n"
            "- Ekstrak obat/barang medis yang dibutuhkan (items_needed) beserta jumlahnya.\n\n"
            "Format respons JSON:\n"
            '{"response": "...", "triage_level": "green|yellow|red", '
            '"confidence": 0.0-1.0, "suggested_actions": ["..."], '
            '"extracted_data": {"illnesses": [{"illness": "Nama Penyakit", "count": 1}], '
            '"items_needed": [{"item": "Nama Obat/Barang", "quantity": 1}]}}'
        )

        prompt_parts = []
        if patient_context:
            prompt_parts.append(f"--- Data Pasien ---\n{patient_context}\n")
        if rag_context:
            prompt_parts.append(f"--- Referensi Medis ---\n{rag_context}\n")
        if chat_history:
            prompt_parts.append(f"--- Riwayat Chat ---\n{chat_history}\n")
        prompt_parts.append(f"--- Pertanyaan ---\n{message}")

        result = self.query_27b(
            prompt="\n".join(prompt_parts),
            system_instruction=system_instruction,
            max_tokens=4096,
            json_mode=True,
        )

        if result["success"]:
            text = result["text"]
            parsed = None

            # Strip markdown code fences if present
            import re as _re
            fence_match = _re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
            if fence_match:
                text = fence_match.group(1).strip()

            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                pass

            if parsed is None:
                json_match = re.search(r'(\{[\s\S]*"response"[\s\S]*\})', text)
                if json_match:
                    try:
                        parsed = json.loads(json_match.group(1))
                    except (json.JSONDecodeError, ValueError):
                        pass

            if parsed and isinstance(parsed, dict) and "response" in parsed:
                result.update(parsed)
            else:
                result["response"] = text
                result["triage_level"] = "yellow"
                result["confidence"] = 0.5
                result["extracted_data"] = {}
                logger.warning(f"Direct JSON parse failed, using plain text. First 200 chars: {text[:200]}")

        return result

    def triage_consultation(self, patient_context, message, chat_history=None, rag_context=None):
        """Frontline triage for patient consultations."""
        system_instruction = (
            "Anda adalah asisten medis AI di Puskesmas Indonesia. "
            "Tugas Anda:\n"
            "1. Triase keluhan pasien (hijau/kuning/merah)\n"
            "2. Berikan respons medis awal dalam Bahasa Indonesia\n"
            "3. Tentukan tingkat kepercayaan (0.0 - 1.0)\n"
            "4. Sarankan tindakan yang diperlukan\n"
            "5. Ekstrak penyakit (illnesses) dalam 1-2 kata (misal: 'Malaria', 'ISPA'). Jika tidak ada penyakit atau hanya pertanyaan umum, kosongkan.\n"
            "6. Ekstrak obat/barang medis yang dibutuhkan (items_needed) beserta jumlahnya.\n\n"
            "Format respons JSON:\n"
            '{"response": "...", "triage_level": "green|yellow|red", '
            '"confidence": 0.0-1.0, "suggested_actions": ["..."], '
            '"needs_escalation": true/false, '
            '"extracted_data": {"symptoms": [], "duration": "", "severity": "", '
            '"illnesses": [{"illness": "Nama Penyakit", "count": 1}], '
            '"items_needed": [{"item": "Nama Obat/Barang", "quantity": 1}]}}'
        )

        prompt_parts = [f"--- Data Pasien ---\n{patient_context}\n"]
        if rag_context:
            prompt_parts.append(f"--- Referensi Medis ---\n{rag_context}\n")
        if chat_history:
            prompt_parts.append(f"--- Riwayat Chat ---\n{chat_history}\n")
        prompt_parts.append(f"--- Keluhan Pasien ---\n{message}")

        result = self.query_4b(
            prompt="\n".join(prompt_parts),
            system_instruction=system_instruction,
        )

        if result["success"]:
            text = result["text"]
            parsed = None

            # Strip markdown code fences if present
            import re as _re
            fence_match = _re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
            if fence_match:
                text = fence_match.group(1).strip()

            # 1. Direct JSON parse
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                pass

            # 2. Extract JSON object from mixed text (e.g., thought + JSON)
            if parsed is None:
                json_match = re.search(r'(\{[\s\S]*"response"[\s\S]*\})', text)
                if json_match:
                    try:
                        parsed = json.loads(json_match.group(1))
                    except (json.JSONDecodeError, ValueError):
                        pass

            if parsed and isinstance(parsed, dict) and "response" in parsed:
                result.update(parsed)
            else:
                # Fallback — use the cleaned text as the response
                result["response"] = text
                result["triage_level"] = "yellow"
                result["confidence"] = 0.5
                result["needs_escalation"] = False
                result["suggested_actions"] = []
                logger.warning(f"Triage JSON parse failed, using plain text. First 200 chars: {text[:200]}")

        return result

    def specialist_consultation(self, patient_context, message, triage_result,
                                chat_history=None, rag_context=None):
        """Specialist deep analysis for escalated cases (27B model)."""
        system_instruction = (
            "Anda adalah dokter spesialis senior dan konsultan klinis di Puskesmas Indonesia. "
            "Anda menerima kasus yang telah diescalasi karena memerlukan analisis mendalam.\n\n"
            "Tugas Anda:\n"
            "1. Analisis mendalam terhadap gejala, riwayat, dan data pasien\n"
            "2. Berikan diagnosis banding (differential diagnosis) dengan reasoning\n"
            "3. Rekomendasikan pemeriksaan penunjang yang diperlukan\n"
            "4. Susun rencana terapi lengkap termasuk dosis dan durasi obat\n"
            "5. Tentukan apakah perlu rujukan ke fasilitas yang lebih tinggi\n"
            "6. Berikan rencana follow-up yang spesifik\n"
            "7. Pertimbangkan faktor epidemiologi lokal Indonesia\n\n"
            "Gunakan Bahasa Indonesia yang jelas dan profesional.\n"
            "Format respons JSON:\n"
            '{"response": "analisis lengkap dan detail", '
            '"differential_diagnosis": ["diagnosis 1 — alasan", "diagnosis 2 — alasan"], '
            '"recommended_tests": ["tes 1", "tes 2"], '
            '"treatment_plan": "rencana terapi lengkap", '
            '"medications": [{"name": "...", "dosage": "...", "duration": "...", "notes": "..."}], '
            '"referral_needed": true/false, "referral_reason": "...", '
            '"confidence": 0.0-1.0, '
            '"follow_up": "rencana follow-up detail", '
            '"suggested_actions": ["tindakan 1", "tindakan 2"]}'
        )

        prompt_parts = [
            f"--- Data Pasien ---\n{patient_context}\n",
            f"--- Hasil Triase ---\n{json.dumps(triage_result, ensure_ascii=False)}\n",
        ]
        if rag_context:
            prompt_parts.append(f"--- Referensi Medis ---\n{rag_context}\n")
        if chat_history:
            prompt_parts.append(f"--- Riwayat Chat ---\n{chat_history}\n")
        prompt_parts.append(f"--- Keluhan Detail ---\n{message}")

        result = self.query_27b(
            prompt="\n".join(prompt_parts),
            system_instruction=system_instruction,
        )

        if result["success"]:
            try:
                parsed = json.loads(result["text"])
                result.update(parsed)
            except (json.JSONDecodeError, ValueError):
                result["response"] = result["text"]

        return result

    def generate_consultation_summary(self, patient_context, messages_context):
        """Generate consultation summary."""
        system_instruction = (
            "Buatkan ringkasan konsultasi medis yang komprehensif dalam Bahasa Indonesia.\n"
            "Format respons JSON:\n"
            '{"summary": "ringkasan konsultasi", '
            '"diagnosis": "nama diagnosis utama", '
            '"category": "kategori penyakit", '
            '"medications": "obat2 yang direkomendasikan", '
            '"supplies_used": "alat medis yang digunakan", '
            '"severity": "ringan|sedang|berat", '
            '"needs_followup": true/false, '
            '"follow_up_notes": "catatan follow up", '
            '"illnesses": ["nama penyakit 1-2 kata lowercase"], '
            '"items_needed": [{"item": "nama obat/barang lowercase", "quantity": 1}]}\n\n'
            "PENTING:\n"
            "- illnesses: daftar penyakit yang teridentifikasi, nama singkat 1-2 kata lowercase (contoh: [\"ispa\", \"diare\"]). "
            "Jika pasien tidak sakit atau hanya konsultasi umum, kosongkan array [].\n"
            "- items_needed: daftar obat/barang medis yang dibutuhkan, nama lowercase. "
            "Jika tidak ada obat yang dibutuhkan, kosongkan array []."
        )

        prompt = (
            f"--- Data Pasien ---\n{patient_context}\n\n"
            f"--- Riwayat Percakapan ---\n{messages_context}\n\n"
            "Buatkan ringkasan lengkap konsultasi ini."
        )

        result = self.query_27b(prompt=prompt, system_instruction=system_instruction)

        if result["success"]:
            try:
                parsed = json.loads(result["text"])
                result.update(parsed)
            except (json.JSONDecodeError, ValueError):
                result["summary"] = result["text"]

        return result

    # ── Village Reporting ────────────────────────────────────────────

    def generate_village_report(self, village_context, disease_stats, stunting_stats, period_info):
        """Generate comprehensive village health report."""
        system_instruction = (
            "Anda adalah epidemiolog senior. Buatkan laporan kesehatan desa yang komprehensif.\n"
            "Format JSON:\n"
            '{"title": "...", "executive_summary": "...", '
            '"disease_analysis": "...", "stunting_analysis": "...", '
            '"recommendations": "...", "resource_needs": "...", '
            '"outbreak_alerts": "..."}'
        )

        prompt = (
            f"--- Profil Desa ---\n{village_context}\n\n"
            f"--- Statistik Penyakit ---\n{disease_stats}\n\n"
            f"--- Statistik Stunting ---\n{stunting_stats}\n\n"
            f"--- Periode ---\n{period_info}\n\n"
            "Buatkan laporan kesehatan desa yang lengkap dan actionable."
        )

        result = self.query_27b(
            prompt=prompt,
            system_instruction=system_instruction,
            max_tokens=8192,
        )

        if result["success"]:
            try:
                parsed = json.loads(result["text"])
                result.update(parsed)
            except (json.JSONDecodeError, ValueError):
                result["executive_summary"] = result["text"]

        return result

    def generate_village_report_v2(self, report_data):
        """Generate comprehensive village health report with top items,
        illness analysis, solutions, and forecast projections.

        Args:
            report_data: dict with keys:
                period, village, disease_summary, top_illnesses,
                top_items_needed, forecast_projection,
                total_consultations, total_inspections,
                total_patients_served, stunting_rate
        """
        system_instruction = (
            "Anda adalah epidemiolog senior dan konsultan kesehatan masyarakat di Indonesia. "
            "Buatkan laporan kesehatan desa yang komprehensif dan actionable.\n\n"
            "Laporan WAJIB mencakup:\n"
            "1. Ringkasan Eksekutif — overview singkat kondisi kesehatan\n"
            "2. Analisis Penyakit — analisis mendalam masalah penyakit utama di wilayah ini. "
            "Jelaskan mengapa penyakit ini muncul dan faktor penyebabnya.\n"
            "3. Kebutuhan Logistik — obat, alat, dan barang kesehatan yang diperlukan\n"
            "4. Solusi & Rekomendasi — langkah konkret untuk mengatasi masalah. "
            "Termasuk pencegahan, edukasi masyarakat, dan penanganan.\n"
            "5. Proyeksi & Tren — berdasarkan data forecast, prediksi tren penyakit "
            "dan kebutuhan item untuk minggu/bulan ke depan\n"
            "6. Dampak & Estimasi — estimasi dampak jika rekomendasi dilaksanakan\n\n"
            "Format respons JSON:\n"
            '{"full_report": "... (laporan lengkap dalam markdown)", '
            '"executive_summary": "...", '
            '"disease_analysis": "... (analisis masalah penyakit)", '
            '"logistics_needs": "... (kebutuhan obat dan barang)", '
            '"recommendations": "... (solusi konkret)", '
            '"trend_projection": "... (proyeksi dan tren ke depan)", '
            '"impact_estimate": "... (estimasi dampak)"}'
        )

        prompt = (
            f"--- Profil Puskesmas ---\n{report_data.get('village', 'Puskesmas')}\n\n"
            f"--- Periode ---\n{report_data.get('period', '')}\n\n"
            f"--- Statistik Layanan ---\n"
            f"Total konsultasi: {report_data.get('total_consultations', 0)}\n"
            f"Total inspeksi visual: {report_data.get('total_inspections', 0)}\n"
            f"Pasien dilayani: {report_data.get('total_patients_served', 0)}\n"
            f"Stunting: {report_data.get('stunting_rate', 'N/A')}\n\n"
            f"--- Ringkasan Penyakit (dari DiseaseReport) ---\n"
            f"{json.dumps(report_data.get('disease_summary', {}), ensure_ascii=False)}\n\n"
            f"--- Top Penyakit (dari CSV Tracking) ---\n"
            f"{report_data.get('top_illnesses', 'Belum ada data.')}\n\n"
            f"--- Top Kebutuhan Obat/Barang (dari CSV Tracking) ---\n"
            f"{report_data.get('top_items_needed', 'Belum ada data.')}\n\n"
            f"--- Proyeksi Forecast LightGBM ---\n"
            f"{report_data.get('forecast_projection', 'Belum ada data.')}\n\n"
            "Buatkan laporan kesehatan desa lengkap yang mencakup analisis masalah, "
            "solusi konkret, dan proyeksi ke depan berdasarkan semua data di atas."
        )

        result = self.query_27b(
            prompt=prompt,
            system_instruction=system_instruction,
            max_tokens=8192,
        )

        if result["success"]:
            text = result["text"]
            parsed = None

            # Strip markdown code fences if present
            import re as _re
            fence_match = _re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
            if fence_match:
                text = fence_match.group(1).strip()

            # Strip chain-of-thought prefix (e.g. "thought ..." before JSON)
            thought_match = _re.search(r'(\{[\s\S]*"full_report"[\s\S]*\})\s*$', text)
            if thought_match:
                text = thought_match.group(1)

            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                pass

            if parsed is None:
                json_match = re.search(r'(\{[\s\S]*"full_report"[\s\S]*\})', text)
                if json_match:
                    try:
                        parsed = json.loads(json_match.group(1))
                    except (json.JSONDecodeError, ValueError):
                        pass

            if parsed and isinstance(parsed, dict):
                result.update(parsed)
            else:
                # Fallback: use the entire text as the full report
                result["full_report"] = text
                result["executive_summary"] = text[:500]
                logger.warning("Village report v2 JSON parse failed, using plain text.")

        return result

    # ── Nutrition ────────────────────────────────────────────────────

    def query_nutrition(self, message, village_context, chat_history=None):
        """Nutrition expert consultation."""
        system_instruction = (
            "Anda adalah ahli gizi masyarakat di Indonesia. "
            "Berikan saran nutrisi dan pertanian yang sesuai dengan kondisi desa.\n"
            "Jawab dalam Bahasa Indonesia yang mudah dipahami masyarakat."
        )

        prompt_parts = [f"--- Profil Desa ---\n{village_context}\n"]
        if chat_history:
            prompt_parts.append(f"--- Riwayat ---\n{chat_history}\n")
        prompt_parts.append(f"--- Pertanyaan ---\n{message}")

        return self.query_4b(
            prompt="\n".join(prompt_parts),
            system_instruction=system_instruction,
        )

    # ── Education Material ───────────────────────────────────────────

    def generate_education_material(self, disease_name, disease_category):
        """Generate disease prevention education material — concise public tutorial."""
        system_instruction = (
            "Kamu adalah petugas kesehatan desa yang membuat materi edukasi singkat.\n"
            "Tulis dalam Bahasa Indonesia sederhana yang mudah dipahami masyarakat.\n"
            "Gunakan format markdown (bullet points, bold) agar mudah dibaca.\n"
            "Jawab HANYA dalam format JSON berikut, tanpa teks tambahan:\n"
            '{"description": "penjelasan singkat penyakit (2-3 kalimat)", '
            '"symptoms": "gejala utama dalam bentuk daftar markdown", '
            '"prevention": "langkah pencegahan dalam bentuk daftar markdown", '
            '"when_to_visit": "kapan harus ke puskesmas dalam bentuk daftar markdown"}'
        )

        prompt = (
            f"Buatkan materi edukasi pencegahan untuk penyakit: {disease_name} "
            f"(kategori: {disease_category}).\n"
            "Materi ini untuk dibagikan petugas kesehatan ke masyarakat desa.\n"
            "Buat singkat, padat, dan mudah dipahami orang awam.\n"
            "Gunakan bullet points markdown (- item)."
        )

        result = self.query_4b(prompt=prompt, system_instruction=system_instruction)

        if result["success"]:
            text = result["text"].strip()

            # Strip markdown code fences
            fence = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
            if fence:
                text = fence.group(1).strip()

            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass

            # Try to extract JSON object from mixed text
            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict):
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    pass

            return {"description": text}

        return {"description": f"Materi untuk {disease_name} belum tersedia."}

    def generate_disease_recommendation(self, disease_name, case_count, trend, change_pct):
        """Generate a government-facing recommendation for a specific disease.

        Used by village reports. The recommendation targets puskesmas staff
        and local government — NOT the general public.

        Returns:
            str — recommendation text (1-3 sentences, actionable)
        """
        system_instruction = (
            "Kamu adalah epidemiolog yang memberi rekomendasi untuk puskesmas desa.\n"
            "Tulis rekomendasi singkat (2-3 kalimat) untuk petugas puskesmas & pemerintah desa.\n"
            "Fokus pada: program pencegahan, stok obat, koordinasi, skrining.\n"
            "Bahasa Indonesia formal. Langsung ke inti tanpa basa-basi."
        )

        trend_text = "stabil"
        if trend == "naik":
            trend_text = f"naik {change_pct}%"
        elif trend == "turun":
            trend_text = f"turun {change_pct}%"

        prompt = (
            f"Penyakit: {disease_name}\n"
            f"Jumlah kasus periode ini: {case_count}\n"
            f"Tren: {trend_text}\n\n"
            "Berikan rekomendasi singkat (2-3 kalimat) untuk puskesmas "
            "tentang langkah yang harus diambil."
        )

        result = self.query_27b(
            prompt=prompt,
            system_instruction=system_instruction,
            max_tokens=2048,
        )

        if result["success"]:
            text = result["text"].strip()
            # Strip fences if any
            fence = re.search(r'```(?:\w+)?\s*([\s\S]*?)```', text)
            if fence:
                text = fence.group(1).strip()
            # Strip JSON wrapper if model returned JSON
            if text.startswith("{"):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        text = parsed.get("recommendation", parsed.get("rekomendasi", text))
                except (json.JSONDecodeError, ValueError):
                    pass
            return text

        return ""

    # ── OCR Support (for library PDF extraction) ─────────────────────

    def ocr_image(self, image_bytes, mime_type="image/png"):
        """Extract text from an image via multimodal AI. Used by library OCR.

        Args:
            image_bytes: raw bytes of the image
            mime_type: MIME type of the image

        Returns:
            str — extracted text
        """
        prompt = (
            "Ekstrak semua teks dari gambar dokumen ini secara lengkap dan akurat. "
            "Pertahankan struktur paragraf dan format asli. "
            "Jika ada tulisan tangan, transkripsi sebaik mungkin. "
            "Jika ada tabel, pertahankan struktur kolom dan baris. "
            "Kembalikan hanya teks yang diekstrak, tanpa komentar tambahan."
        )

        if self._backend == "openrouter":
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            data_uri = f"data:{mime_type};base64,{b64}"
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ]
            return self._openrouter_chat(messages, max_tokens=4096, temperature=0.1)
        elif self._backend == "cloud_run":
            # Cloud Run 4B is multimodal — same OpenAI format
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            data_uri = f"data:{mime_type};base64,{b64}"
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ]
            return self._cloud_run_chat(
                settings.CLOUD_RUN_4B_URL,
                settings.CLOUD_RUN_MODEL_4B,
                messages,
                max_tokens=4096,
                temperature=0.1,
            )
        else:
            # Vertex AI — multimodal via google-genai
            contents = [
                genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                genai_types.Part.from_text(text=prompt),
            ]
            return self._vertex_ai_chat(
                model_name=settings.VERTEX_AI_MODEL_4B,
                contents=contents,
                max_tokens=4096,
                temperature=0.1,
            )

    # ── Health Check ─────────────────────────────────────────────────

    def check_health(self):
        """Check AI service health status — lightweight, no real API call."""
        if not getattr(settings, "AI_ENABLED", False):
            return {"status": "not_configured", "backend": self._backend}
        try:
            if self._backend == "openrouter":
                # Just verify the key is present — don't burn API quota
                if not getattr(settings, "OPENROUTER_API_KEY", ""):
                    return {"status": "not_configured", "backend": self._backend}
                return {
                    "status": "healthy",
                    "backend": self._backend,
                    "model": settings.OPENROUTER_MODEL,
                }
            elif self._backend == "cloud_run":
                # Cloud Run: verify URLs are configured
                url_4b = getattr(settings, "CLOUD_RUN_4B_URL", "")
                url_27b = getattr(settings, "CLOUD_RUN_27B_URL", "")
                if not url_4b:
                    return {"status": "not_configured", "backend": self._backend}
                return {
                    "status": "healthy",
                    "backend": self._backend,
                    "model": f"{settings.CLOUD_RUN_MODEL_4B} / {settings.CLOUD_RUN_MODEL_27B}",
                    "endpoints": {
                        "4b": url_4b,
                        "27b": url_27b or "(not configured — using 4B only)",
                    },
                }
            else:
                # Vertex AI: verify project is set
                project = getattr(settings, "GCP_PROJECT_ID", "")
                if not project:
                    return {"status": "not_configured", "backend": self._backend}
                model_4b = getattr(settings, "VERTEX_AI_MODEL_4B", "medgemma-4b-it")
                model_27b = getattr(settings, "VERTEX_AI_MODEL_27B", "medgemma-27b-text-it")
                return {
                    "status": "healthy",
                    "backend": self._backend,
                    "model": f"{model_4b} / {model_27b}",
                    "project": project,
                    "location": getattr(settings, "VERTEX_AI_LOCATION", "us-central1"),
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": self._backend,
                "error": str(e),
            }

    # ── Utilities ────────────────────────────────────────────────────

    @staticmethod
    def _extract_field(text, field_names):
        """Extract a field value from unstructured text."""
        lines = text.split("\n")
        for line in lines:
            lower = line.lower().strip()
            for name in field_names:
                if lower.startswith(name):
                    return line.split(":", 1)[-1].strip() if ":" in line else ""
        return ""

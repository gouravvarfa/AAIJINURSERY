"""Provider abstraction (section 33) -- Orders/Accounting/Delivery/Website
never talk to AiSensy directly; they only ever call WhatsAppService, which
talks to whichever MessageProvider is configured. Adding Twilio/WhatsApp
Cloud API/SMS/Email later means writing one more class here, nothing else
in the app changes.

AISENSY_API_KEY is read from the environment ONLY -- never hardcoded, never
logged, never returned in any API response.
"""
import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from app.communications.gate import MESSAGING_OFF_CODE, MESSAGING_OFF_MESSAGE, is_messaging_enabled, record_blocked


@dataclass
class ProviderResult:
    ok: bool
    provider_message_id: str = ""
    error_code: str = ""
    error_message: str = ""
    retryable: bool = False


class MessageProvider(ABC):
    @abstractmethod
    def send_template_message(
        self, mobile: str, campaign_name: str, template_params: list,
        variable_names: Optional[list] = None, language_code: Optional[str] = None,
    ) -> ProviderResult:
        """variable_names (optional): the named placeholder for each
        template_params value, in the same order (e.g. ["customer_name",
        "order_number"]) -- Meta's newer templates require NAMED body
        parameters ({{customer_name}}, not {{1}}), so a Cloud API provider
        needs this to build the correct payload. language_code (optional):
        the exact language the template was approved under on Meta (e.g.
        "en" vs "en_US" are DIFFERENT templates to Meta -- sending the
        wrong one fails with "template does not exist" even if the template
        is genuinely approved). Providers that only ever
        use positional params (AiSensy) simply ignore it."""
        ...

    @abstractmethod
    def test_connection(self) -> ProviderResult: ...

    def send_document_message(self, mobile: str, file_bytes: bytes, filename: str, caption: str = "") -> ProviderResult:
        """Send a PDF (or other document) as a WhatsApp document message.
        Default implementation: not supported -- a provider that can't do
        this (e.g. AiSensy, whose document-message API isn't verified/wired
        up yet) fails cleanly rather than silently dropping the document."""
        return ProviderResult(False, error_code="NOT_SUPPORTED", error_message="This provider does not support document messages")


class AiSensyProvider(MessageProvider):
    def __init__(self):
        self.api_key = os.environ.get("AISENSY_API_KEY", "")
        self.api_url = os.environ.get("AISENSY_API_URL", "https://backend.aisensy.com/campaign/t1/api/v2")
        self.timeout = float(os.environ.get("AISENSY_TIMEOUT", "15"))

    def _configured(self) -> bool:
        return bool(self.api_key and self.api_url)

    def _post(self, payload: dict):
        req = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return urllib.request.urlopen(req, timeout=self.timeout)

    def send_template_message(self, mobile: str, campaign_name: str, template_params: list, variable_names: Optional[list] = None, language_code: Optional[str] = None) -> ProviderResult:
        if not is_messaging_enabled():
            record_blocked()
            return ProviderResult(False, error_code=MESSAGING_OFF_CODE, error_message=MESSAGING_OFF_MESSAGE)
        if not self._configured():
            return ProviderResult(False, error_code="CONFIGURATION_ERROR", error_message="AISENSY_API_KEY/AISENSY_API_URL not configured")

        payload = {
            "apiKey": self.api_key,
            "campaignName": campaign_name,
            "destination": mobile,
            "userName": mobile,
            "templateParams": [str(p) for p in template_params],
        }
        try:
            with self._post(payload) as resp:
                body = resp.read().decode()
                status = resp.status
            if status in (200, 201):
                data = json.loads(body) if body else {}
                msg_id = str(data.get("submitted_message_id") or data.get("messageId") or "")
                return ProviderResult(True, provider_message_id=msg_id)
            return ProviderResult(False, error_code=f"HTTP_{status}", error_message="Unexpected AiSensy response", retryable=status >= 500)
        except urllib.error.HTTPError as exc:
            code, message = self._parse_aisensy_error(exc.read())
            if exc.code in (401, 403):
                return ProviderResult(False, error_code=code or "AUTHENTICATION_ERROR", error_message=message, retryable=False)
            if exc.code == 429:
                return ProviderResult(False, error_code=code or "RATE_LIMITED", error_message=message, retryable=True)
            return ProviderResult(False, error_code=code or f"HTTP_{exc.code}", error_message=message, retryable=exc.code >= 500)
        except urllib.error.URLError as exc:
            reason = str(exc.reason)
            code = "TIMEOUT" if "timed out" in reason.lower() else "PROVIDER_ERROR"
            return ProviderResult(False, error_code=code, error_message=reason, retryable=True)
        except Exception as exc:  # noqa: BLE001 - a WhatsApp failure must never propagate
            return ProviderResult(False, error_code="PROVIDER_ERROR", error_message=str(exc), retryable=True)

    @staticmethod
    def _parse_aisensy_error(raw_body: bytes) -> tuple[str, str]:
        """AiSensy errors look like {"name":"ERR400","errorCode":400,
        "errorMessage":"WABA is not verified"} -- surface the real
        errorCode/errorMessage instead of just the outer HTTP status."""
        try:
            data = json.loads(raw_body.decode(errors="ignore"))
            code = str(data.get("errorCode") or data.get("name") or "")
            message = data.get("errorMessage", "")
            if code or message:
                return code, message or "Unknown AiSensy error"
        except (ValueError, AttributeError):
            pass
        return "", raw_body.decode(errors="ignore")[:400]

    def test_connection(self) -> ProviderResult:
        """Best-effort connection test. AiSensy's v2 campaign endpoint has no
        separate health-check/ping route, so this sends a deliberately
        destination-less request to the real endpoint and classifies the
        response: an auth error surfaces as AUTHENTICATION_ERROR, and a
        validation error (400/422) after passing auth surfaces as CONNECTED
        (the key + URL were accepted; no message was actually sent since
        `destination` is empty). This does NOT fully guarantee a real send
        will succeed -- use "Send Test WhatsApp" against a real number for
        that -- but it never fabricates a CONNECTED result."""
        if not self.api_key:
            return ProviderResult(False, error_code="CONFIGURATION_ERROR", error_message="AISENSY_API_KEY is not set")
        if not self.api_url:
            return ProviderResult(False, error_code="CONFIGURATION_ERROR", error_message="AISENSY_API_URL is not set")
        try:
            with self._post({"apiKey": self.api_key, "campaignName": "__connection_test__", "destination": ""}) as resp:
                status = resp.status
            if status in (200, 201):
                return ProviderResult(True)
            return ProviderResult(False, error_code=f"HTTP_{status}", error_message="Unexpected response")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return ProviderResult(False, error_code="AUTHENTICATION_ERROR", error_message="AiSensy rejected the API key")
            if exc.code in (400, 422):
                return ProviderResult(True)  # reached validation past auth -- key + URL are good
            return ProviderResult(False, error_code=f"HTTP_{exc.code}", error_message="Unexpected AiSensy response")
        except urllib.error.URLError as exc:
            reason = str(exc.reason)
            code = "TIMEOUT" if "timed out" in reason.lower() else "PROVIDER_ERROR"
            return ProviderResult(False, error_code=code, error_message=reason)
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(False, error_code="PROVIDER_ERROR", error_message=str(exc))


class WhatsAppCloudAPIProvider(MessageProvider):
    """Meta's own WhatsApp Cloud API, used directly (no AiSensy in the
    middle) -- mainly for instant testing via a Meta test number, which can
    message up to 5 verified recipient numbers with zero business
    verification wait (unlike a real WABA on a BSP like AiSensy)."""

    def __init__(self):
        self.token = os.environ.get("WHATSAPP_CLOUD_API_TOKEN", "")
        self.phone_id = os.environ.get("WHATSAPP_CLOUD_API_PHONE_ID", "")
        self.api_version = os.environ.get("WHATSAPP_CLOUD_API_VERSION", "v20.0")
        self.timeout = float(os.environ.get("AISENSY_TIMEOUT", "15"))

    def _configured(self) -> bool:
        return bool(self.token and self.phone_id)

    def _url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}/{self.phone_id}/messages"

    def _post(self, payload: dict):
        req = urllib.request.Request(
            self._url(),
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"},
            method="POST",
        )
        return urllib.request.urlopen(req, timeout=self.timeout)

    @staticmethod
    def _parse_meta_error(raw_body: bytes) -> tuple[str, str]:
        """Extract Meta's own nested error code/message (e.g. 132001
        "Template name does not exist in the translation") instead of just
        the outer HTTP status -- this is what actually tells an admin WHY a
        send failed, not just that it failed."""
        try:
            data = json.loads(raw_body.decode(errors="ignore"))
            err = data.get("error", {})
            code = str(err.get("code", ""))
            message = err.get("error_data", {}).get("details") or err.get("message", "")
            if code or message:
                return code or "META_ERROR", message or "Unknown Meta error"
        except (ValueError, AttributeError):
            pass
        return "", raw_body.decode(errors="ignore")[:400]

    def send_template_message(self, mobile: str, campaign_name: str, template_params: list, variable_names: Optional[list] = None, language_code: Optional[str] = None) -> ProviderResult:
        if not is_messaging_enabled():
            record_blocked()
            return ProviderResult(False, error_code=MESSAGING_OFF_CODE, error_message=MESSAGING_OFF_MESSAGE)
        if not self._configured():
            return ProviderResult(False, error_code="CONFIGURATION_ERROR", error_message="WHATSAPP_CLOUD_API_TOKEN/WHATSAPP_CLOUD_API_PHONE_ID not configured")

        components = []
        if template_params:
            # Meta now requires NAMED body parameters ({{customer_name}},
            # not {{1}}) -- when the template's variable names are known,
            # tag each parameter with `parameter_name` to match. Falls back
            # to plain positional params if names weren't supplied (e.g. an
            # older numbered-placeholder template).
            if variable_names and len(variable_names) == len(template_params):
                parameters = [
                    {"type": "text", "parameter_name": name, "text": str(value)}
                    for name, value in zip(variable_names, template_params)
                ]
            else:
                parameters = [{"type": "text", "text": str(p)} for p in template_params]
            components.append({"type": "body", "parameters": parameters})
        payload = {
            "messaging_product": "whatsapp",
            "to": mobile.lstrip("+"),
            "type": "template",
            "template": {"name": campaign_name, "language": {"code": language_code or "en_US"}, "components": components},
        }
        try:
            with self._post(payload) as resp:
                body = resp.read().decode()
                status = resp.status
            if status in (200, 201):
                data = json.loads(body) if body else {}
                msg_id = str((data.get("messages") or [{}])[0].get("id", ""))
                return ProviderResult(True, provider_message_id=msg_id)
            return ProviderResult(False, error_code=f"HTTP_{status}", error_message="Unexpected Cloud API response", retryable=status >= 500)
        except urllib.error.HTTPError as exc:
            meta_code, meta_message = self._parse_meta_error(exc.read())
            if exc.code in (401, 403):
                return ProviderResult(False, error_code=meta_code or "AUTHENTICATION_ERROR", error_message=meta_message, retryable=False)
            if exc.code == 429:
                return ProviderResult(False, error_code=meta_code or "RATE_LIMITED", error_message=meta_message, retryable=True)
            # Template/config errors (unknown template, param mismatch, etc.)
            # always come back as 4xx and must NEVER be retried -- only a
            # genuine 5xx (Meta's own outage) is worth retrying.
            return ProviderResult(False, error_code=meta_code or f"HTTP_{exc.code}", error_message=meta_message, retryable=exc.code >= 500)
        except urllib.error.URLError as exc:
            reason = str(exc.reason)
            code = "TIMEOUT" if "timed out" in reason.lower() else "PROVIDER_ERROR"
            return ProviderResult(False, error_code=code, error_message=reason, retryable=True)
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(False, error_code="PROVIDER_ERROR", error_message=str(exc), retryable=True)

    def test_connection(self) -> ProviderResult:
        if not self.token:
            return ProviderResult(False, error_code="CONFIGURATION_ERROR", error_message="WHATSAPP_CLOUD_API_TOKEN is not set")
        if not self.phone_id:
            return ProviderResult(False, error_code="CONFIGURATION_ERROR", error_message="WHATSAPP_CLOUD_API_PHONE_ID is not set")
        try:
            req = urllib.request.Request(
                f"https://graph.facebook.com/{self.api_version}/{self.phone_id}",
                headers={"Authorization": f"Bearer {self.token}"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status = resp.status
            return ProviderResult(status == 200)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return ProviderResult(False, error_code="AUTHENTICATION_ERROR", error_message="Meta rejected the access token")
            return ProviderResult(False, error_code=f"HTTP_{exc.code}", error_message="Unexpected Meta response")
        except urllib.error.URLError as exc:
            reason = str(exc.reason)
            code = "TIMEOUT" if "timed out" in reason.lower() else "PROVIDER_ERROR"
            return ProviderResult(False, error_code=code, error_message=reason)
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(False, error_code="PROVIDER_ERROR", error_message=str(exc))

    def _upload_media(self, file_bytes: bytes, filename: str, mime_type: str) -> tuple[str, ProviderResult]:
        """Step 1 of sending a document: upload the file bytes to Meta's
        media endpoint (multipart/form-data, built by hand since this
        project has no `requests` dependency) and get back a media id."""
        boundary = "----WhatsAppMediaBoundary7d91f4"
        parts = []
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"messaging_product\"\r\n\r\nwhatsapp\r\n")
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"type\"\r\n\r\n{mime_type}\r\n")
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: {mime_type}\r\n\r\n")
        body = "".join(parts).encode() + file_bytes + f"\r\n--{boundary}--\r\n".encode()

        try:
            req = urllib.request.Request(
                f"https://graph.facebook.com/{self.api_version}/{self.phone_id}/media",
                data=body,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
            media_id = data.get("id", "")
            if not media_id:
                return "", ProviderResult(False, error_code="MEDIA_UPLOAD_ERROR", error_message="Meta did not return a media id")
            return media_id, ProviderResult(True)
        except urllib.error.HTTPError as exc:
            code, message = self._parse_meta_error(exc.read())
            return "", ProviderResult(False, error_code=code or f"HTTP_{exc.code}", error_message=message, retryable=exc.code >= 500)
        except urllib.error.URLError as exc:
            reason = str(exc.reason)
            code = "TIMEOUT" if "timed out" in reason.lower() else "PROVIDER_ERROR"
            return "", ProviderResult(False, error_code=code, error_message=reason, retryable=True)
        except Exception as exc:  # noqa: BLE001
            return "", ProviderResult(False, error_code="PROVIDER_ERROR", error_message=str(exc), retryable=True)

    def send_document_message(self, mobile: str, file_bytes: bytes, filename: str, caption: str = "") -> ProviderResult:
        if not is_messaging_enabled():
            record_blocked()
            return ProviderResult(False, error_code=MESSAGING_OFF_CODE, error_message=MESSAGING_OFF_MESSAGE)
        if not self._configured():
            return ProviderResult(False, error_code="CONFIGURATION_ERROR", error_message="WHATSAPP_CLOUD_API_TOKEN/WHATSAPP_CLOUD_API_PHONE_ID not configured")

        media_id, upload_result = self._upload_media(file_bytes, filename, "application/pdf")
        if not upload_result.ok:
            return upload_result

        payload = {
            "messaging_product": "whatsapp",
            "to": mobile.lstrip("+"),
            "type": "document",
            "document": {"id": media_id, "filename": filename, "caption": caption} if caption else {"id": media_id, "filename": filename},
        }
        try:
            with self._post(payload) as resp:
                body = resp.read().decode()
                status = resp.status
            if status in (200, 201):
                data = json.loads(body) if body else {}
                msg_id = str((data.get("messages") or [{}])[0].get("id", ""))
                return ProviderResult(True, provider_message_id=msg_id)
            return ProviderResult(False, error_code=f"HTTP_{status}", error_message="Unexpected Cloud API response", retryable=status >= 500)
        except urllib.error.HTTPError as exc:
            code, message = self._parse_meta_error(exc.read())
            return ProviderResult(False, error_code=code or f"HTTP_{exc.code}", error_message=message, retryable=exc.code >= 500)
        except urllib.error.URLError as exc:
            reason = str(exc.reason)
            code = "TIMEOUT" if "timed out" in reason.lower() else "PROVIDER_ERROR"
            return ProviderResult(False, error_code=code, error_message=reason, retryable=True)
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(False, error_code="PROVIDER_ERROR", error_message=str(exc), retryable=True)


_provider_instance: Optional[MessageProvider] = None


def get_provider_name() -> str:
    return os.environ.get("WHATSAPP_PROVIDER", "aisensy").lower()


def get_provider() -> MessageProvider:
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = WhatsAppCloudAPIProvider() if get_provider_name() == "cloud_api" else AiSensyProvider()
    return _provider_instance

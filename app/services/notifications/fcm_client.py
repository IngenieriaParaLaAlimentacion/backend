import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import httpx
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials

_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_TRANSIENT_HTTP = frozenset({401, 403, 408, 429, 500, 502, 503, 504})
_PERMANENT_TOKEN_CODES = frozenset({"UNREGISTERED", "SENDER_ID_MISMATCH"})


class FcmOutcome(StrEnum):
    """Action the dispatcher must take after one FCM request."""

    SUCCESS = "success"
    PERMANENT_TOKEN = "permanent_token"
    PERMANENT_MESSAGE = "permanent_message"
    TRANSIENT = "transient"


@dataclass(frozen=True)
class FcmResult:
    """Classified provider result without retaining provider diagnostics."""

    outcome: FcmOutcome


class FcmClient:
    """Send visible push notifications through FCM HTTP v1."""

    def __init__(
        self,
        *,
        project_id: str,
        client_email: str,
        private_key: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.project_id = project_id
        self.timeout_seconds = timeout_seconds
        self._http_client: httpx.AsyncClient | None = None
        self._refresh_lock = asyncio.Lock()
        self.credentials = Credentials.from_service_account_info(
            {
                # This is a credential-schema discriminator, not a secret value.
                "type": "service_account",  # nosemgrep
                "project_id": project_id,
                "client_email": client_email,
                "private_key": private_key.replace("\\n", "\n"),
                "token_uri": "https://oauth2.googleapis.com/token",
            },
            scopes=[_SCOPE],
        )

    async def _access_token(self) -> str:
        if not self.credentials.valid:
            async with self._refresh_lock:
                if not self.credentials.valid:
                    await asyncio.to_thread(self.credentials.refresh, Request())
        assert self.credentials.token is not None
        return self.credentials.token

    async def start(self) -> None:
        """Open the bounded-run connection pool and validate credentials."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.timeout_seconds)
        await self._access_token()

    async def aclose(self) -> None:
        """Close the bounded-run connection pool."""
        if self._http_client is not None:
            client = self._http_client
            self._http_client = None
            await client.aclose()

    @staticmethod
    def _fcm_error_code(body: Mapping) -> str | None:
        error = body.get("error")
        if not isinstance(error, Mapping):
            return None
        details = error.get("details", [])
        if not isinstance(details, list):
            return None
        for detail in details:
            if isinstance(detail, Mapping) and detail.get("errorCode"):
                return str(detail["errorCode"])
        return None

    @staticmethod
    def _invalid_token_field(body: Mapping) -> bool:
        error = body.get("error")
        if not isinstance(error, Mapping):
            return False
        details = error.get("details", [])
        if not isinstance(details, list):
            return False
        for detail in details:
            if not isinstance(detail, Mapping):
                continue
            violations = detail.get("fieldViolations", [])
            if not isinstance(violations, list):
                continue
            for violation in violations:
                if isinstance(violation, Mapping) and str(
                    violation.get("field", "")
                ).endswith("message.token"):
                    return True
        return False

    async def send(
        self,
        *,
        token: str,
        title: str,
        body: str,
        data: dict[str, str],
        collapse_key: str,
    ) -> FcmResult:
        """Send one visible notification and classify its terminality."""
        try:
            if self._http_client is None:
                await self.start()
            access_token = await self._access_token()
            assert self._http_client is not None
            response = await self._http_client.post(
                "https://fcm.googleapis.com/v1/projects/"
                f"{self.project_id}/messages:send",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "message": {
                        "token": token,
                        "notification": {"title": title, "body": body},
                        "data": data,
                        "android": {
                            "collapse_key": collapse_key,
                            "notification": {
                                "channel_id": "stale_establishments",
                                "tag": collapse_key,
                            },
                        },
                        "apns": {"headers": {"apns-collapse-id": collapse_key}},
                    }
                },
            )
        except (GoogleAuthError, httpx.HTTPError, TimeoutError, OSError):
            return FcmResult(FcmOutcome.TRANSIENT)

        if 200 <= response.status_code < 300:
            return FcmResult(FcmOutcome.SUCCESS)
        try:
            response_body = response.json()
        except ValueError:
            response_body = {}
        if not isinstance(response_body, Mapping):
            response_body = {}
        error_code = self._fcm_error_code(response_body)
        if error_code in _PERMANENT_TOKEN_CODES:
            return FcmResult(FcmOutcome.PERMANENT_TOKEN)
        if error_code == "INVALID_ARGUMENT" and self._invalid_token_field(
            response_body
        ):
            return FcmResult(FcmOutcome.PERMANENT_TOKEN)
        if response.status_code in _TRANSIENT_HTTP:
            return FcmResult(FcmOutcome.TRANSIENT)
        return FcmResult(FcmOutcome.PERMANENT_MESSAGE)

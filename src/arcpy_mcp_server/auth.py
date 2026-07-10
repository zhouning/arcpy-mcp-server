import hashlib
import hmac
import time

from fastmcp.server.auth import AccessToken, TokenVerifier


class StaticBearerVerifier(TokenVerifier):
    def __init__(self, expected_token: str, base_url: str):
        super().__init__(base_url=base_url)
        self._expected = expected_token.encode("utf-8")

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token.encode("utf-8"), self._expected):
            return None
        return AccessToken(
            token=token,
            client_id="codex-macos",
            scopes=[],
            claims={"auth_method": "static_bearer"},
        )


class ArtifactSigner:
    def __init__(self, key: bytes):
        self._key = key

    def sign(self, operation: str, artifact_id: str, expires_at: int) -> str:
        payload = f"{operation}:{artifact_id}:{expires_at}".encode()
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def verify(
        self,
        operation: str,
        artifact_id: str,
        expires_at: int,
        signature: str,
    ) -> bool:
        if expires_at < int(time.time()):
            return False
        expected = self.sign(operation, artifact_id, expires_at)
        return hmac.compare_digest(expected, signature)

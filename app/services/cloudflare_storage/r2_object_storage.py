import aioboto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config.settings import settings
from app.core.interfaces.object_storage import IObjectStorage
from app.exceptions.domain_exceptions import ObjectStorageError


class R2ObjectStorage(IObjectStorage):
    """Object storage backed by Cloudflare R2, via its S3-compatible API.

    R2 speaks the same wire protocol as S3, so the standard S3 client works
    against it unmodified -- only the endpoint URL and region differ from
    AWS. A fresh client is opened per call, matching how ``UnitOfWork`` opens
    a fresh DB session per request rather than pooling one at import time.
    """

    def __init__(self) -> None:
        self._session = aioboto3.Session()

    async def save(self, *, key: str, content_type: str, data: bytes) -> None:
        try:
            async with self._session.client(
                "s3",
                endpoint_url=settings.storage_endpoint_url,
                aws_access_key_id=settings.storage_access_key_id,
                aws_secret_access_key=settings.storage_secret_access_key,
                region_name=settings.storage_region,
            ) as s3:
                await s3.put_object(
                    Bucket=settings.storage_bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageError(key, str(exc)) from exc

"""Cloudflare R2 (S3-compatible) object storage backed by boto3.

R2 speaks the S3 API, so the standard boto3 ``s3`` client works as long
as we point it at the R2 endpoint URL and use SigV4. The ``region_name``
must literally be ``"auto"`` for R2 — R2's region is server-determined
and boto3 needs *some* string to compute the signature.

Costs are tracked at the consumer level (see end-of-backfill log line in
M2 PR-G); this module just exposes the primitives.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import boto3
import structlog
from botocore.client import Config as BotoConfig

from puckbunny.storage.base import ObjectMetadata

if TYPE_CHECKING:
    from collections.abc import Iterator

    from puckbunny.config import Settings


@dataclass(frozen=True)
class R2Credentials:
    """Credentials + endpoint coordinates for one R2 bucket."""

    account_id: str
    access_key_id: str
    secret_access_key: str
    endpoint_url: str
    bucket: str
    region: str = "auto"

    @classmethod
    def from_settings(cls, settings: Settings) -> R2Credentials:
        return cls(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            endpoint_url=settings.r2_endpoint_url,
            bucket=settings.r2_bucket,
            region=settings.r2_region,
        )


class R2ObjectStorage:
    """``ObjectStorage`` implementation backed by Cloudflare R2 via boto3.

    A single instance is bound to one bucket. Construct one per-process
    and reuse it; boto3 manages its own connection pool internally.
    """

    def __init__(self, credentials: R2Credentials) -> None:
        self._credentials = credentials
        self._bucket = credentials.bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=credentials.endpoint_url,
            aws_access_key_id=credentials.access_key_id,
            aws_secret_access_key=credentials.secret_access_key,
            region_name=credentials.region,
            config=BotoConfig(
                signature_version="s3v4",
                # Boto's "standard" mode does adaptive backoff on 5xx and
                # throttling responses — a useful belt-and-braces under
                # the higher-level tenacity retry in the HTTP client.
                retries={"max_attempts": 5, "mode": "standard"},
            ),
        )
        self._log = structlog.get_logger(__name__).bind(bucket=self._bucket)

    @classmethod
    def from_settings(cls, settings: Settings) -> R2ObjectStorage:
        return cls(R2Credentials.from_settings(settings))

    # --- ObjectStorage Protocol ---

    def put_object(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        kwargs: dict[str, object] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": body,
        }
        if content_type is not None:
            kwargs["ContentType"] = content_type
        self._client.put_object(**kwargs)
        self._log.info("r2_put_object", key=key, size_bytes=len(body))

    def get_object(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        body: bytes = resp["Body"].read()
        return body

    def head_object(self, key: str) -> ObjectMetadata:
        resp = self._client.head_object(Bucket=self._bucket, Key=key)
        return ObjectMetadata(
            key=key,
            size_bytes=int(resp["ContentLength"]),
            etag=str(resp.get("ETag", "")).strip('"'),
            content_type=resp.get("ContentType"),
        )

    def list_objects(self, prefix: str) -> Iterator[str]:
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []) or []:
                yield obj["Key"]

    def delete_object(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

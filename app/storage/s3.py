import aioboto3
from botocore.exceptions import ClientError
from app.config import settings


async def upload_file(data: bytes, filename: str, content_type: str = "image/jpeg") -> str:
    if not settings.S3_BUCKET:
        raise RuntimeError("S3_BUCKET not configured")

    session = aioboto3.Session(
        aws_access_key_id=settings.S3_ACCESS_KEY or None,
        aws_secret_access_key=settings.S3_SECRET_KEY or None,
        region_name=settings.S3_REGION or None,
    )

    kwargs = {}
    if settings.S3_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL

    async with session.client("s3", **kwargs) as s3:
        try:
            await s3.put_object(
                Bucket=settings.S3_BUCKET,
                Key=filename,
                Body=data,
                ContentType=content_type,
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "Unknown")
            raise RuntimeError(f"S3 upload failed for {filename} (ClientError {code}): {e}") from e
        except Exception as e:
            raise RuntimeError(f"S3 upload failed for {filename}: {e}") from e

    if settings.S3_PUBLIC_URL:
        return f"{settings.S3_PUBLIC_URL.rstrip('/')}/{filename}"
    if settings.S3_ENDPOINT_URL:
        return f"{settings.S3_ENDPOINT_URL.rstrip('/')}/{settings.S3_BUCKET}/{filename}"
    return f"https://{settings.S3_BUCKET}.s3.amazonaws.com/{filename}"

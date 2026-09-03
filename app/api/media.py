"""Загрузка картинок из админки — файлом, а не только ссылкой.

Картинки приветствий до сих пор добавляли ссылкой на уже загруженное во ВК фото:
чтобы поставить новую, её сначала надо было куда-то выложить. Здесь файл кладётся
на наш же сервер (см. app.storage.local) и сразу получает адрес, который читают и
браузер админки, и модель, и ВК при перезаливке.
"""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.auth.dependencies import require_role
from app.config import settings
from app.db.models import User
from app.storage.local import safe_extension, save_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/media", tags=["media"])


@router.post("/upload")
async def upload_media(
    file: UploadFile,
    current_user: User = Depends(require_role("admin", "curator")),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Файл пустой")

    limit = settings.MEDIA_MAX_UPLOAD_MB * 1024 * 1024
    if len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"Файл больше {settings.MEDIA_MAX_UPLOAD_MB} МБ",
        )

    ext = safe_extension(file.filename)
    # «bin» — всё, что не в белом списке хранилища. Такой файл ВК не примет как
    # вложение, а в приветствии он бесполезен, поэтому отказываем сразу.
    if ext == "bin":
        raise HTTPException(
            status_code=400,
            detail=(
                "Не тот тип файла: картинка (jpg, png, gif, webp, heic), "
                "видео (mp4, mov), pdf или аудио (mp3, m4a, ogg)"
            ),
        )

    url = await save_file(data, f"greeting/{uuid.uuid4().hex}.{ext}")
    logger.info(
        "media uploaded | user=%s | file=%r | bytes=%d | url=%s",
        current_user.email, file.filename, len(data), url,
    )
    return {"url": url}

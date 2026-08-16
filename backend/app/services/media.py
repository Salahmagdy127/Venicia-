"""تخزين صور الميدان — Content-addressed photo storage.

الصورة بتتخزّن **باسم بصمتها** مش باسم عشوائي:

    media/1/2026/08/9f/9f3a…c1.jpg

يعني لو نفس الصورة اترفعت مرتين — والتليفون بيعيد الرفع لما الشبكة
تقطع في النص — الملف بيتكتب مكانه ومبيتكرّرش على القرص. وبصمة الملف
بتبقى جزء من السجل، فأي تعديل على الصورة بعدين بيبان.

المصغّرة اختيارية: لو Pillow متركّبة بنعملها، ولو لأ التطبيق بيشتغل
عادي بالصورة الأصلية. مبنخليش رفع الصور يقع على اعتمادية اختيارية.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.core.config import settings

try:  # pragma: no cover - الاعتمادية اختيارية
    from PIL import Image

    HAS_PILLOW = True
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    HAS_PILLOW = False

#: أطول ضلع في المصغّرة — كفاية لشبكة صور في شاشة تليفون
THUMB_MAX = 320

#: أقصى حجم للصورة الواحدة. التليفون بيصغّر قبل ما يبعت، والحد ده
#: بيحمي القرص لو حد بعت من غير تصغير.
MAX_BYTES = 6 * 1024 * 1024

ALLOWED_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class MediaError(Exception):
    def __init__(self, message_ar: str, message_en: str, code: str = "media_error"):
        super().__init__(message_en)
        self.message_ar = message_ar
        self.message_en = message_en
        self.code = code


def root() -> Path:
    path = Path(settings.MEDIA_ROOT)
    path.mkdir(parents=True, exist_ok=True)
    return path


class StoredPhoto:
    """نتيجة التخزين — المسارات نسبية عشان نقل المجلد ميكسرش الروابط."""

    __slots__ = ("sha256", "path", "thumb_path", "byte_size", "width", "height", "reused")

    def __init__(
        self,
        sha256: str,
        path: str,
        thumb_path: str | None,
        byte_size: int,
        width: int | None,
        height: int | None,
        reused: bool,
    ) -> None:
        self.sha256 = sha256
        self.path = path
        self.thumb_path = thumb_path
        self.byte_size = byte_size
        self.width = width
        self.height = height
        self.reused = reused


def store(
    data: bytes,
    *,
    property_id: int,
    year: int,
    month: int,
    content_type: str = "image/jpeg",
) -> StoredPhoto:
    """يكتب الصورة ويرجّع مسارها النسبي وبصمتها."""
    if not data:
        raise MediaError("الصورة فاضية", "Empty image", "empty")
    if len(data) > MAX_BYTES:
        raise MediaError(
            f"الصورة أكبر من {MAX_BYTES // (1024 * 1024)} ميجا",
            f"Image exceeds {MAX_BYTES // (1024 * 1024)}MB",
            "too_large",
        )
    normalized = (content_type or "").split(";")[0].strip().lower()
    if normalized not in ALLOWED_TYPES:
        raise MediaError(
            "نوع الملف مش صورة مدعومة",
            "Unsupported image type",
            "bad_type",
        )

    digest = hashlib.sha256(data).hexdigest()
    extension = EXTENSIONS[normalized]
    relative = Path(str(property_id)) / f"{year:04d}" / f"{month:02d}" / digest[:2]
    directory = root() / relative
    directory.mkdir(parents=True, exist_ok=True)

    target = directory / f"{digest}{extension}"
    reused = target.exists()
    if not reused:
        # كتابة مؤقتة وبعدين نقل: لو العملية اتقطعت في النص، مفيش ملف
        # نص مكتوب بيتحسب إنه موجود في المرة الجاية.
        staging = directory / f".{digest}{extension}.part"
        staging.write_bytes(data)
        staging.replace(target)

    width = height = None
    thumb_relative: str | None = None
    if HAS_PILLOW:
        thumb_target = directory / f"{digest}_t.jpg"
        try:
            with Image.open(target) as image:  # type: ignore[union-attr]
                width, height = image.size
                if not thumb_target.exists():
                    thumbnail = image.convert("RGB")
                    thumbnail.thumbnail((THUMB_MAX, THUMB_MAX))
                    thumbnail.save(thumb_target, "JPEG", quality=78, optimize=True)
            thumb_relative = (relative / thumb_target.name).as_posix()
        except Exception:  # pragma: no cover - صورة تالفة متوقّفش الرفع
            thumb_relative = None

    return StoredPhoto(
        sha256=digest,
        path=(relative / target.name).as_posix(),
        thumb_path=thumb_relative,
        byte_size=len(data),
        width=width,
        height=height,
        reused=reused,
    )


def resolve(relative_path: str) -> Path:
    """يحوّل المسار النسبي لمسار كامل — مع منع الخروج من مجلد الوسائط."""
    base = root().resolve()
    candidate = (base / relative_path).resolve()
    if not candidate.is_relative_to(base):
        raise MediaError("مسار غير صالح", "Invalid path", "bad_path")
    if not candidate.is_file():
        raise MediaError("الصورة غير موجودة", "Photo not found", "not_found")
    return candidate

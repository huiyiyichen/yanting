"""附件（图片）处理。

约束（工程规范第 13.3 节、前端规范第 5.3 节）：
- 仅 JPEG / PNG / WebP，每张不超过 5MB；
- **后端再次校验实际类型与可解码性**，不能只信扩展名或前端限制；
- 只保存到 `data/runtime` 下的系统生成路径；不保存原始文件名，避免目录穿越；
- 文档内 URL、扩展名都不能触发任意远程下载；
- 知识导入、附件与聊天内容**均不授予工具权限**。
"""

from __future__ import annotations

import hashlib
import io
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.errors import ValidationRejected

# Pillow 用于真实解码校验：只信 magic bytes 不足以排除损坏文件
try:  # pragma: no cover - 导入失败会在校验时报错
    from PIL import Image, UnidentifiedImageError
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]

    class UnidentifiedImageError(Exception):  # type: ignore[no-redef]
        pass


# Pillow 的格式名 -> MIME
FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}

ALLOWED_MIMES = frozenset(FORMAT_TO_MIME.values())

# 图片魔数：先用廉价检查快速排除明显伪造，再用 Pillow 解码确认
MAGIC_NUMBERS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)


@dataclass(frozen=True, slots=True)
class StoredAttachment:
    attachment_id: str
    mime_type: str
    byte_size: int
    stored_path: str
    sha256: str
    width: int
    height: int


def _detect_magic(data: bytes) -> str | None:
    for prefix, mime in MAGIC_NUMBERS:
        if data.startswith(prefix):
            return mime
    # WebP：RIFF....WEBP
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_and_store_image(
    *,
    data: bytes,
    declared_mime: str | None,
    settings: Settings,
    conversation_id: str,
) -> StoredAttachment:
    """校验并落盘一张图片。任何不合法输入都抛 `ValidationRejected`。"""

    if not data:
        raise ValidationRejected("图片内容为空")
    if len(data) > settings.image_max_bytes:
        raise ValidationRejected(
            f"图片超过大小上限（{settings.image_max_bytes // (1024 * 1024)}MB）",
            detail=f"实际 {len(data)} 字节",
        )

    magic_mime = _detect_magic(data)
    if magic_mime is None:
        raise ValidationRejected(
            "无法识别的图片格式",
            detail="仅支持 JPEG / PNG / WebP；扩展名不作为判断依据",
        )

    if magic_mime not in settings.allowed_image_mimes:
        raise ValidationRejected(
            f"不支持的图片类型：{magic_mime}",
            detail=f"允许的类型：{settings.allowed_image_mimes}",
        )

    if declared_mime and declared_mime not in settings.allowed_image_mimes:
        raise ValidationRejected(
            f"声明的内容类型不被允许：{declared_mime}",
            detail="前端限制不能替代后端校验",
        )

    if Image is None:
        raise ValidationRejected("服务端缺少图片解码能力（Pillow 未安装）")

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()  # 校验完整性
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            actual_format = (image.format or "").upper()
    except UnidentifiedImageError as exc:
        raise ValidationRejected("图片无法解码，可能已损坏", detail=str(exc)[:200]) from exc
    except Exception as exc:
        raise ValidationRejected(
            "图片校验失败", detail=f"{type(exc).__name__}: {str(exc)[:200]}"
        ) from exc

    resolved_mime = FORMAT_TO_MIME.get(actual_format)
    if resolved_mime is None:
        raise ValidationRejected(
            f"解码得到的格式不受支持：{actual_format or 'unknown'}",
            detail="实际解码格式与允许列表不符",
        )
    if resolved_mime not in settings.allowed_image_mimes:
        raise ValidationRejected(f"不支持的图片类型：{resolved_mime}")

    digest = hashlib.sha256(data).hexdigest()
    attachment_id = f"att-{uuid.uuid4().hex[:12]}"

    # 路径由系统生成：不含用户文件名，避免目录穿越与信息泄露
    target_dir = settings.runtime_path / "attachments" / conversation_id
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[resolved_mime]
    target = target_dir / f"{attachment_id}{suffix}"
    target.write_bytes(data)

    return StoredAttachment(
        attachment_id=attachment_id,
        mime_type=resolved_mime,
        byte_size=len(data),
        stored_path=str(target),
        sha256=digest,
        width=width,
        height=height,
    )


def to_data_url(data: bytes, mime_type: str) -> str:
    """把图片编码成 data URL 供多模态模型使用（不产生外部请求）。"""

    import base64

    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def read_stored(path: str) -> bytes:
    return Path(path).read_bytes()

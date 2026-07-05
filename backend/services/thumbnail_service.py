from pathlib import Path
from datetime import datetime

from PIL import Image, ImageOps

try:
    from pi_heif import register_heif_opener

    register_heif_opener(thumbnails=False)
except ImportError:
    # Standard JPEG/PNG thumbnails remain available in minimal environments.
    pass

from backend import config
from backend.db.database import connection


def generate_thumbnail(asset_id: str, user_id: int, source: Path) -> str | None:
    root = (config.DATA_ROOT / "Thumbnails" / str(user_id)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / f"{asset_id}.jpg").resolve()
    if root not in target.parents:
        raise ValueError("缩略图路径越界")
    try:
        with Image.open(source) as image:
            exif_datetime = _exif_datetime(image)
            image = ImageOps.exif_transpose(image)
            width, height = image.size
            image.thumbnail((480, 480), Image.Resampling.LANCZOS)
            if image.mode != "RGB":
                if "A" in image.getbands():
                    background = Image.new("RGB", image.size, "white")
                    background.paste(image, mask=image.getchannel("A"))
                    image = background
                else:
                    image = image.convert("RGB")
            image.save(target, "JPEG", quality=82, optimize=True)
    except (OSError, ValueError):
        target.unlink(missing_ok=True)
        return None
    with connection() as conn:
        conn.execute(
            "UPDATE assets SET thumbnail_storage_path=?,thumbnail_url=?,exif_datetime=?,width=?,height=? "
            "WHERE id=? AND user_id=?",
            (str(target), f"/api/assets/{asset_id}/thumbnail", exif_datetime, width, height, asset_id, user_id),
        )
    return str(target)


def _exif_datetime(image: Image.Image) -> str | None:
    try:
        exif = image.getexif()
        raw = exif.get(36867) or exif.get(36868) or exif.get(306)
        if not raw:
            return None
        return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S").isoformat()
    except (AttributeError, TypeError, ValueError, OSError):
        return None


def remove_thumbnail(path: str | None, user_id: int):
    if not path:
        return
    root = (config.DATA_ROOT / "Thumbnails" / str(user_id)).resolve()
    target = Path(path).resolve()
    if root in target.parents:
        target.unlink(missing_ok=True)

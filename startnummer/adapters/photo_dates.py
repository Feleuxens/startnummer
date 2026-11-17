"""Read camera timestamps without retaining other EXIF fields."""

from datetime import datetime
from email.utils import parsedate_to_datetime
from struct import error as StructError

from PIL import ExifTags, Image


def modified_time(value: str | None) -> datetime | None:
    """Read a server's Last-Modified date without substituting download time."""
    if not value:
        return None
    try:
        result = parsedate_to_datetime(value)
        return result if result.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def capture_time(image: Image.Image) -> datetime | None:
    """Return DateTimeOriginal as camera-local time, including burst subseconds."""
    try:
        exif = image.getexif()
        details = exif.get_ifd(ExifTags.IFD.Exif)
        value = details.get(ExifTags.Base.DateTimeOriginal) or exif.get(ExifTags.Base.DateTimeOriginal)
        if isinstance(value, bytes):
            value = value.decode("ascii")
        if not isinstance(value, str):
            return None
        result = datetime.strptime(value.strip(" \0"), "%Y:%m:%d %H:%M:%S")
        fraction = details.get(ExifTags.Base.SubsecTimeOriginal) or exif.get(ExifTags.Base.SubsecTimeOriginal)
        if isinstance(fraction, bytes):
            fraction = fraction.decode("ascii")
        if isinstance(fraction, str) and fraction.strip(" \0").isdecimal():
            result = result.replace(microsecond=int(fraction.strip(" \0")[:6].ljust(6, "0")))
        return result
    except (AttributeError, IndexError, KeyError, OSError, StructError, SyntaxError, TypeError, ValueError):
        return None

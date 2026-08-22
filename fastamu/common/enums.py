from enum import StrEnum


class FaStrEnum(StrEnum):
    """A `StrEnum` that also carries the label a person should read.

    The wire value and the display text are two different things, and keeping
    them in two places is how a client ends up shipping its own copy of your
    vocabulary — one that drifts the moment a member is added::

        class Status(FaStrEnum):
            PENDING = ("pending", "در انتظار")

        Status.PENDING == "pending"   # still a str, still the wire value
        Status.PENDING.fa             # "در انتظار"

    A member declared with a bare value keeps the value as its own label, so
    the second element is optional.
    """

    fa: str

    def __new__(cls, value: str, fa: str = "") -> "FaStrEnum":
        member = str.__new__(cls, value)
        member._value_ = value
        member.fa = fa or value
        return member


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class MediaType(StrEnum):
    EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    PDF = "application/pdf"
    JSON = "application/json"
    XML = "application/xml"
    HTML = "text/html"
    TEXT = "text/plain"
    CSV = "text/csv"
    OCTET_STREAM = "application/octet-stream"
    ZIP = "application/zip"
    GZIP = "application/gzip"
    PNG = "image/png"
    JPEG = "image/jpeg"
    JPG = "image/jpg"
    GIF = "image/gif"
    SVG = "image/svg+xml"
    TIFF = "image/tiff"
    BMP = "image/bmp"
    WEBP = "image/webp"
    AVIF = "image/avif"
    MP4 = "video/mp4"
    MOV = "video/quicktime"
    MKV = "video/x-matroska"
    FLV = "video/x-flv"
    AVI = "video/x-msvideo"
    WMV = "video/x-ms-wmv"
    MP3 = "audio/mpeg"
    WAV = "audio/wav"
    OGG = "audio/ogg"
    AAC = "audio/aac"
    FLAC = "audio/flac"
    WMA = "audio/x-ms-wma"
    M4A = "audio/x-m4a"
    AMR = "audio/amr"
    MPG = "audio/mpeg"


class HTTPMethod(StrEnum):
    POST = "POST"
    PUT = "PUT"
    GET = "GET"
    DELETE = "DELETE"
    PATCH = "PATCH"


class FilterType(StrEnum):
    SLIDER = "slider"
    CHECKBOX = "checkbox"
    RADIO = "radio"

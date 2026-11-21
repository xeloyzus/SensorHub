"""Generate a scannable dashboard link without an external QR service."""

from functools import lru_cache
from io import BytesIO

from fastapi import APIRouter, Request, Response
import qrcode

from ..core.config import settings
from .system import dashboard_url

router = APIRouter(include_in_schema=False)


@lru_cache(maxsize=64)
def dashboard_qr(target: str) -> bytes:
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    code.add_data(target)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@router.get("/qr/dashboard.png")
async def qr_code(request: Request):
    target = dashboard_url(request)
    # The canonical origin is stable, so its PNG can be cached by clients and
    # proxies. A request-derived fallback origin varies with the Host header,
    # so it must never be shared from a cache (or the unbounded variety of
    # forged hosts would thrash the LRU cache too).
    if settings.public_base_url and target.startswith(settings.public_base_url):
        cache_control = "public, max-age=86400"
    else:
        cache_control = "private, no-store"
    return Response(
        dashboard_qr(target), media_type="image/png",
        headers={"Cache-Control": cache_control, "X-Content-Type-Options": "nosniff"},
    )

"""Generate a scannable dashboard link without an external QR service."""

from functools import lru_cache
from io import BytesIO

from fastapi import APIRouter, Request, Response
import qrcode

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
    return Response(
        dashboard_qr(dashboard_url(request)), media_type="image/png",
        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
    )

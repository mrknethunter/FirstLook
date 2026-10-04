"""QR and printable carriers generated only for the patient owner."""

from __future__ import annotations

from io import BytesIO
from typing import Literal

import segno
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.lib.utils import ImageReader  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

DOMAIN = "firstlook-hy-demo.duckdns.org"
CarrierKind = Literal[
    "qr.svg", "qr.png", "wallpaper-1170.png", "wallpaper-1080.png", "cards.pdf", "nfc.txt"
]


def _qr(url: str) -> segno.QRCode:
    """Keep the published QR at correction level M even for short payloads."""
    return segno.make_qr(url, error="m", boost_error=False)


def qr_svg(url: str) -> bytes:
    qr = _qr(url)
    scale, border = 6, 4
    size = len(qr.matrix)
    width = (size + 2 * border) * scale
    height = width + 76
    rectangles = []
    for y, row in enumerate(qr.matrix):
        for x, dark in enumerate(row):
            if dark:
                rectangles.append(
                    f'<rect x="{(x + border) * scale}" y="{(y + border) * scale + 50}" '
                    f'width="{scale}" height="{scale}"/>'
                )
    markup = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Emergency scan QR code">'
        f'<rect width="{width}" height="{height}" fill="#fff"/>'
        f'<rect x="2" y="2" width="{width - 4}" height="{height - 4}" '
        'fill="none" stroke="#bd1f2d" stroke-width="4"/>'
        f'<text x="{width // 2}" y="30" text-anchor="middle" font-family="sans-serif" '
        'font-size="18" font-weight="bold" fill="#bd1f2d">EMERGENCY - SCAN ME</text>'
        f'<g fill="#111">{"".join(rectangles)}</g>'
        f'<text x="{width // 2}" y="{height - 12}" text-anchor="middle" '
        f'font-family="sans-serif" font-size="12">{DOMAIN}</text>'
        "</svg>"
    )
    return markup.encode("utf-8")


def qr_png(url: str, *, scale: int = 10) -> bytes:
    image = BytesIO()
    _qr(url).save(image, kind="png", scale=scale, border=4, dark="#111111", light="white")
    return image.getvalue()


def wallpaper_png(url: str, width: int, height: int) -> bytes:
    if (width, height) not in {(1170, 2532), (1080, 2400)}:
        raise ValueError("unsupported wallpaper size")
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 260), fill="#bd1f2d")
    title_font = ImageFont.load_default(size=66)
    body_font = ImageFont.load_default(size=38)
    draw.text((width // 2, 145), "EMERGENCY - SCAN ME", anchor="mm", font=title_font, fill="white")
    qr_image = Image.open(BytesIO(qr_png(url, scale=14))).convert("RGB")
    side = min(width - 100, 900)
    qr_image = qr_image.resize((side, side), Image.Resampling.NEAREST)
    image.paste(qr_image, ((width - side) // 2, (height - side) // 2))
    draw.text((width // 2, height - 300), DOMAIN, anchor="mm", font=body_font, fill="#111111")
    draw.text(
        (width // 2, height - 225),
        "Synthetic demo profile",
        anchor="mm",
        font=body_font,
        fill="#444444",
    )
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def cards_pdf(url: str) -> bytes:
    """A4 sheet with wallet card, stickers and a bracelet label."""
    output = BytesIO()
    page = canvas.Canvas(output, pagesize=A4)
    width, height = A4
    qr_image = ImageReader(BytesIO(qr_png(url, scale=12)))

    def carrier(x: float, y: float, w: float, h: float, qr_side: float) -> None:
        page.setStrokeColorRGB(0.74, 0.12, 0.18)
        page.setLineWidth(2)
        page.rect(x, y, w, h)
        page.setFillColorRGB(0.74, 0.12, 0.18)
        page.setFont("Helvetica-Bold", 12)
        page.drawCentredString(x + w / 2, y + h - 24, "EMERGENCY - SCAN ME")
        page.drawImage(
            qr_image,
            x + (w - qr_side) / 2,
            y + (h - qr_side) / 2 - 5,
            width=qr_side,
            height=qr_side,
        )
        page.setFillColorRGB(0.1, 0.1, 0.1)
        page.setFont("Helvetica", 8)
        page.drawCentredString(x + w / 2, y + 12, DOMAIN)

    carrier(45, height - 305, 250, 245, 170)
    carrier(330, height - 240, 215, 180, 120)
    carrier(330, height - 455, 215, 180, 120)
    carrier(45, height - 445, 250, 95, 64)
    page.setFont("Helvetica", 9)
    page.drawString(45, 42, "FirstLook synthetic demo carrier - patient-owned emergency profile")
    page.showPage()
    page.save()
    return output.getvalue()


def render_carrier(url: str, kind: CarrierKind) -> tuple[bytes, str]:
    if kind == "qr.svg":
        return qr_svg(url), "image/svg+xml"
    if kind == "qr.png":
        return qr_png(url), "image/png"
    if kind == "wallpaper-1170.png":
        return wallpaper_png(url, 1170, 2532), "image/png"
    if kind == "wallpaper-1080.png":
        return wallpaper_png(url, 1080, 2400), "image/png"
    if kind == "cards.pdf":
        return cards_pdf(url), "application/pdf"
    if kind == "nfc.txt":
        return url.encode("utf-8"), "text/plain; charset=utf-8"
    raise ValueError("unsupported carrier")

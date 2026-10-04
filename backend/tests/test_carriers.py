from io import BytesIO

from firstlook.sharing.carriers import _qr, render_carrier
from PIL import Image

URL = "https://firstlook-hy-demo.duckdns.org/s#shlink:/synthetic-test-payload"


def test_carriers_use_qr_ecc_m_and_show_domain() -> None:
    assert _qr(URL).error == "M"
    svg, media_type = render_carrier(URL, "qr.svg")
    assert media_type == "image/svg+xml"
    assert b"EMERGENCY - SCAN ME" in svg
    assert b"firstlook-hy-demo.duckdns.org" in svg
    assert URL.encode() not in svg


def test_wallpaper_and_pdf_have_expected_formats() -> None:
    wallpaper, media_type = render_carrier(URL, "wallpaper-1080.png")
    assert media_type == "image/png"
    assert Image.open(BytesIO(wallpaper)).size == (1080, 2400)
    document, media_type = render_carrier(URL, "cards.pdf")
    assert media_type == "application/pdf"
    assert document.startswith(b"%PDF-")

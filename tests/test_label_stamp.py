"""Tester för tack-rad + recensions-QR på DHL-etiketter."""

import io

import pytest

from src.printing.label_stamp import stamp_review_footer

REVIEW_URL = "https://g.page/r/EXEMPEL/review"


def _fake_label(pages: int = 1) -> bytes:
    """Minimal etikett-PDF i DHL-format (105×210 mm)."""
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(105 * mm, 210 * mm))
    for i in range(pages):
        c.setFont("Helvetica", 10)
        c.drawString(20, 500, f"DHL PAKET — kolli {i + 1}")
        c.showPage()
    c.save()
    return buf.getvalue()


def _config(**label_stamp) -> dict:
    return {
        "label_stamp": {"enabled": True, "review_url": REVIEW_URL, **label_stamp},
        "smtp": {},
    }


def test_disabled_returns_original():
    label = _fake_label()
    assert stamp_review_footer(label, {"label_stamp": {"enabled": False}}) is label
    assert stamp_review_footer(label, {}) is label


def test_missing_url_returns_original():
    label = _fake_label()
    cfg = {"label_stamp": {"enabled": True}, "smtp": {}}
    assert stamp_review_footer(label, cfg) is label


def test_url_fallback_to_smtp_google_review_url():
    label = _fake_label()
    cfg = {
        "label_stamp": {"enabled": True},
        "smtp": {"google_review_url": REVIEW_URL},
    }
    stamped = stamp_review_footer(label, cfg)
    assert stamped != label
    assert stamped.startswith(b"%PDF")


def test_stamps_all_pages_and_preserves_page_count():
    from pypdf import PdfReader

    label = _fake_label(pages=3)
    stamped = stamp_review_footer(label, _config())
    reader = PdfReader(io.BytesIO(stamped))
    assert len(reader.pages) == 3
    # Overlayn ger varje sida mer innehåll än originalet
    orig = PdfReader(io.BytesIO(label))
    for i in range(3):
        assert len(stamped) > len(label)
        assert float(reader.pages[i].mediabox.width) == pytest.approx(
            float(orig.pages[i].mediabox.width)
        )


def test_star_fallback_without_logo():
    label = _fake_label()
    stamped = stamp_review_footer(label, _config(logo=False))
    assert stamped != label
    assert stamped.startswith(b"%PDF")


def test_corrupt_pdf_returns_original():
    junk = b"detta ar inte en pdf"
    assert stamp_review_footer(junk, _config()) is junk

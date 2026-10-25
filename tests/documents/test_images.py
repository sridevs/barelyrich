from io import BytesIO
import logging
from unittest.mock import MagicMock, Mock

import pytest

from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_page import StatementPage
from src.agents.statement_agent import TransformersStatementAgent
from src.agents.response import StatementParsingError
from src.service.statements import StatementImportService
from src.documents.reader import StatementDocumentReader
from src.documents.images import StatementPdf
from src.documents import images

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = ImageDraw = None


def fictional_pdf(page_count=1, width=600, height=800):
    pdfium = pytest.importorskip("pypdfium2")
    output = BytesIO()
    with pdfium.PdfDocument.new() as document:
        for _ in range(page_count):
            document.new_page(width, height).close()
        document.save(output)
    return output.getvalue()


def test_pdf_images_are_bounded_and_attached_in_page_order():

    document = StatementDocumentReader().read("fictional.pdf", fictional_pdf(page_count=2))
    assert [page.number for page in document.pages] == [1, 2]
    for page in document.pages:
        assert len(page.image) <= 2_000_000
        with Image.open(BytesIO(page.image)) as image:
            assert image.format == "JPEG"
            assert max(image.size) <= 1600
        assert page.text == ""


def test_scanned_pdf_is_accepted_without_extracting_text(monkeypatch):
    output = BytesIO()
    with Image.new("RGB", (600, 800), "white") as scan:
        ImageDraw.Draw(scan).text(
            (40, 40), "Fictional Savings Account\nClosing balance: SGD 1,234.50",
            fill="black",
        )
        scan.save(output, format="PDF")
    pytest.importorskip("pypdfium2")

    def forbid_text_extraction(*arguments, **keywords):
        pytest.fail("PDF text extraction must not be used.")

    monkeypatch.setattr("pypdfium2.PdfPage.get_textpage", forbid_text_extraction)
    document = StatementDocumentReader().read("scan.pdf", output.getvalue())
    assert len(document.pages) == 1
    image_bytes = document.page(1).image
    assert image_bytes is not None and image_bytes.startswith(b"\xff\xd8")


def test_renderer_rejects_excessive_pages_and_corrupt_pdf():
    with pytest.raises(ValueError, match="at most 16 pages"):
        StatementDocumentReader().read("large.pdf", fictional_pdf(page_count=17))
    with pytest.raises(ValueError, match="Unable to render"):
        StatementPdf(b"not a pdf").render()


def test_renderer_accepts_sixteen_pages():
    rendered_images = StatementPdf(fictional_pdf(page_count=16, width=60, height=80)).render()
    assert len(rendered_images) == 16


def test_renderer_scales_large_page_before_allocating_bitmap():

    rendered_images = StatementPdf(fictional_pdf(width=12000, height=16000)).render()
    with Image.open(BytesIO(rendered_images[0])) as image:
        assert image.size == (1200, 1600)


@pytest.mark.parametrize("dimensions", [(0, 800), (float("nan"), 800)])
def test_renderer_rejects_invalid_dimensions_and_closes_page(dimensions):
    page = Mock()
    page.get_size.return_value = dimensions
    document = MagicMock()
    document.__getitem__.return_value = page
    with pytest.raises(ValueError, match="dimensions"):
        images._render_page(document, 0)
    page.close.assert_called_once()
    page.render.assert_not_called()


def test_renderer_rejects_oversized_image_and_closes_native_resources():
    document = MagicMock()
    page = document.__getitem__.return_value
    page.get_size.return_value = (600, 800)
    bitmap = page.render.return_value
    rgb_image = bitmap.to_pil.return_value.__enter__.return_value.convert.return_value.__enter__.return_value
    rgb_image.save.side_effect = lambda output, **options: output.write(b"x" * 2_000_001)
    with pytest.raises(ValueError, match="2 MB"):
        images._render_page(document, 0)
    bitmap.close.assert_called_once()
    page.close.assert_called_once()


def test_missing_rendering_dependency_has_install_instructions(monkeypatch):
    monkeypatch.setattr("src.documents.images.pdfium", None)
    with pytest.raises(ValueError, match="statements.*extra"):
        StatementPdf(b"pdf").render()


def test_missing_text_dependency_has_install_instructions(monkeypatch):
    monkeypatch.setattr("src.documents.images.pdfium", None)
    with pytest.raises(ValueError, match="statements.*extra"):
        StatementPdf(b"pdf").text()


def test_text_reader_rejects_corrupt_and_oversized_page_counts():
    with pytest.raises(ValueError, match="Unable to read"):
        StatementPdf(b"not a PDF").text()
    with pytest.raises(ValueError, match="at most 16 pages"):
        StatementPdf(fictional_pdf(page_count=17)).text()


def test_text_reader_closes_native_resources_when_text_limit_is_exceeded(monkeypatch):
    pdfium = pytest.importorskip("pypdfium2")
    document = MagicMock()
    document.__len__.return_value = 1
    page = document.__getitem__.return_value
    text_page = page.get_textpage.return_value
    text_page.count_chars.return_value = 256_001
    monkeypatch.setattr(pdfium, "PdfDocument", lambda *args, **kwargs: document)
    document.__enter__.return_value = document
    with pytest.raises(ValueError, match="256,000-character limit"):
        StatementPdf(b"pdf").text()
    text_page.get_text_bounded.assert_not_called()
    text_page.close.assert_called_once()
    page.close.assert_called_once()
    document.__exit__.assert_called_once()


def test_text_reader_preserves_password_error(monkeypatch):
    pdfium = pytest.importorskip("pypdfium2")
    monkeypatch.setattr("pypdfium2.PdfDocument", Mock(side_effect=pdfium.PdfiumError(
        "Failed to load document", err_code=pdfium.raw.FPDF_ERR_PASSWORD,
    )))
    with pytest.raises(ValueError, match="requires an opening password"):
        StatementDocumentReader(prefer_text=True).read("protected.pdf", b"pdf")


def test_password_protected_pdf_has_explicit_error(monkeypatch):
    pdfium = pytest.importorskip("pypdfium2")
    protected_document = Mock(side_effect=pdfium.PdfiumError(
        "Failed to load document", err_code=pdfium.raw.FPDF_ERR_PASSWORD,
    ))
    monkeypatch.setattr("pypdfium2.PdfDocument", protected_document)
    with pytest.raises(ValueError, match="requires an opening password"):
        StatementDocumentReader().read("protected.pdf", b"protected PDF")
    protected_document.assert_called_once_with(b"protected PDF", password="")


def test_missing_pillow_has_install_instructions(monkeypatch):
    content = fictional_pdf()

    def missing_pillow(document, index):
        raise ImportError("Pillow not installed")

    monkeypatch.setattr(images, "_render_page", missing_pillow)
    with pytest.raises(ValueError, match="Pillow"):
        StatementPdf(content).render()


@pytest.mark.parametrize("image", [b"", "not bytes", b"x" * 2_000_001])
def test_page_rejects_invalid_or_oversized_image(image):
    with pytest.raises(ValueError, match="image"):
        StatementPage(1, image)


def test_agent_sends_images_and_page_mapping_without_logging_source(caplog):
    document = StatementDocument((
        StatementPage(1, b"first image"),
        StatementPage(3, b"third image"),
    ))
    runtime = Mock()
    runtime.generate.return_value = '{"balances":[]}'
    with caplog.at_level(logging.INFO), pytest.raises(StatementParsingError):
        TransformersStatementAgent(runtime).parse(document)
    passed_document, prompt = runtime.generate.call_args.args
    assert [page.image for page in passed_document.pages] == [b"first image", b"third image"]
    assert "Page metadata: [1, 3]" in prompt
    assert "pages=2" in caplog.text
    assert "private statement text" not in caplog.text
    assert "first image" not in caplog.text


def test_document_processing_timing_does_not_log_source(caplog):
    reader = Mock()
    reader.read.return_value = StatementDocument((StatementPage(1, b"page image"),))
    agent = Mock()
    with caplog.at_level(logging.INFO):
        StatementImportService(reader, agent).preview("private.pdf", b"private")
    assert "document processing completed" in caplog.text
    assert "private" not in caplog.text

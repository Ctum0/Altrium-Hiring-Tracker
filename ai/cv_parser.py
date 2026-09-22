"""Extract raw text from uploaded CV files (PDF / DOCX)."""
import io
import logging

logger = logging.getLogger(__name__)


def extract_text(uploaded_file) -> str:
    """Return raw text from a PDF or DOCX file object."""
    name = (uploaded_file.name or '').lower()
    data = uploaded_file.read()
    if name.endswith('.pdf'):
        return _clean(_from_pdf(data))
    if name.endswith('.docx'):
        return _clean(_from_docx(data))
    # Fallback: try to read as text
    try:
        return _clean(data.decode('utf-8', errors='replace'))
    except Exception:
        return ''


def _clean(text):
    """Normalize extraction artifacts.

    pdfminer emits a raw form-feed (\\x0c) page separator that renders as
    a junk glyph in the CV-text overlay (CV audit BUG D). Replace with a
    newline and collapse the surrounding blank lines.
    """
    if not text:
        return text
    return text.replace('\x0c', '\n').replace('\n\n\n', '\n\n').strip()


def _from_pdf(data: bytes) -> str:
    try:
        from pdfminer.high_level import extract_text as pdf_extract
        text = pdf_extract(io.BytesIO(data))
    except Exception as exc:
        logger.error('PDF extraction failed: %s', exc)
        text = ''
    if len(text.strip()) >= 30:
        return text
    # Near-empty text layer: likely a scanned/image-based PDF. Try OCR as a
    # fallback; in environments without pytesseract/pdf2image (or the
    # tesseract binary) this degrades gracefully to the short text above.
    ocr_text = _ocr_pdf(data)
    return ocr_text if ocr_text else text


def _ocr_pdf(data: bytes) -> str:
    """OCR the first pages of a PDF via pdf2image + pytesseract.

    Returns '' on any failure (missing module, missing tesseract binary,
    undecodable PDF) so callers keep the pre-OCR behavior.
    """
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except ImportError as exc:
        logger.info('OCR fallback unavailable (%s); using text layer as-is', exc)
        return ''
    try:
        # Cap at 5 pages @ 200dpi: OCR is CPU-heavy and CVs rarely exceed
        # a couple of pages; this bounds worst-case runtime implicitly.
        images = convert_from_bytes(data, dpi=200, first_page=1, last_page=5)
        pages = [pytesseract.image_to_string(img) for img in images]
    except Exception as exc:
        logger.warning('OCR fallback failed: %s', exc)
        return ''
    text = '\n'.join(pages).strip()
    if text:
        logger.info('OCR fallback extracted %d characters from scanned PDF', len(text))
    return text


def _from_docx(data: bytes) -> str:
    try:
        import docx
        document = docx.Document(io.BytesIO(data))
        parts = [p.text for p in document.paragraphs if p.text.strip()]
        for table in document.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(' | '.join(cells))
        return '\n'.join(parts)
    except Exception as exc:
        logger.error('DOCX extraction failed: %s', exc)
        return ''

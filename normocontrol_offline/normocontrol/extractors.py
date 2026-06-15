from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from zipfile import BadZipFile, ZipFile


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
ODT_TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
W = f"{{{W_NS}}}"
ODT_TEXT = f"{{{ODT_TEXT_NS}}}"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
SUPPORTED_EXTENSIONS = {
    ".docx",
    ".odt",
    ".pdf",
    ".txt",
    ".md",
    ".doc",
    *IMAGE_EXTENSIONS,
}


class ExtractionError(RuntimeError):
    pass


@dataclass(slots=True)
class Annotation:
    paragraph_index: int
    kind: str
    text: str


@dataclass(slots=True)
class ExtractedDocument:
    text: str
    paragraphs: list[str]
    annotations: list[Annotation] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def iter_supported_files(source: Path):
    if source.is_file():
        candidates = [source]
    else:
        candidates = sorted(source.rglob("*"))
    for path in candidates:
        if not path.is_file() or path.name.startswith(".~lock."):
            continue
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def extract_document(path: Path) -> ExtractedDocument:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix == ".odt":
        return _extract_odt(path)
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix in {".txt", ".md"}:
        return _extract_text(path)
    if suffix == ".doc":
        return _extract_legacy_doc(path)
    if suffix in IMAGE_EXTENSIONS:
        return _extract_image(path)
    raise ExtractionError(f"Формат {suffix or '<без расширения>'} не поддерживается")


def _run_text(run: ET.Element) -> str:
    chunks: list[str] = []
    for node in run.iter():
        if node.tag == W + "t":
            chunks.append(node.text or "")
        elif node.tag == W + "tab":
            chunks.append("\t")
        elif node.tag in {W + "br", W + "cr"}:
            chunks.append("\n")
    return "".join(chunks)


def _annotation_kinds(run: ET.Element) -> list[str]:
    properties = run.find(W + "rPr")
    if properties is None:
        return []
    kinds: list[str] = []
    highlight = properties.find(W + "highlight")
    if highlight is not None and highlight.attrib.get(W + "val", "yellow") != "none":
        kinds.append("highlight")
    if properties.find(W + "i") is not None:
        kinds.append("italic")
    underline = properties.find(W + "u")
    if underline is not None and underline.attrib.get(W + "val", "single") != "none":
        kinds.append("underline")
    return kinds


def _extract_docx(path: Path) -> ExtractedDocument:
    paragraphs: list[str] = []
    annotations: list[Annotation] = []
    try:
        with ZipFile(path) as archive:
            names = [
                name
                for name in archive.namelist()
                if re.fullmatch(
                    r"word/(?:document|header\d+|footer\d+|footnotes|endnotes|comments)\.xml",
                    name,
                )
            ]
            names.sort(key=lambda name: (name != "word/document.xml", name))
            for part_name in names:
                root = ET.fromstring(archive.read(part_name))
                for paragraph in root.iter(W + "p"):
                    paragraph_index = len(paragraphs)
                    text_chunks: list[str] = []
                    for run in paragraph.iter(W + "r"):
                        run_text = _run_text(run)
                        text_chunks.append(run_text)
                        for kind in _annotation_kinds(run):
                            if run_text.strip():
                                annotations.append(
                                    Annotation(paragraph_index, kind, run_text.strip())
                                )
                    text = "".join(text_chunks).strip()
                    if text:
                        if (
                            paragraph.find(".//" + W + "drawing") is not None
                            or paragraph.find(".//" + W + "pict") is not None
                        ):
                            annotations.append(
                                Annotation(paragraph_index, "drawing_mark", text)
                            )
                        paragraphs.append(text)
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        raise ExtractionError(f"Не удалось разобрать DOCX: {exc}") from exc
    return ExtractedDocument(
        text="\n".join(paragraphs),
        paragraphs=paragraphs,
        annotations=annotations,
        metadata={"format": "docx"},
    )


def _extract_odt(path: Path) -> ExtractedDocument:
    try:
        with ZipFile(path) as archive:
            root = ET.fromstring(archive.read("content.xml"))
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        raise ExtractionError(f"Не удалось разобрать ODT: {exc}") from exc
    paragraphs: list[str] = []
    for tag in (ODT_TEXT + "p", ODT_TEXT + "h"):
        for paragraph in root.iter(tag):
            text = "".join(paragraph.itertext()).strip()
            if text:
                paragraphs.append(text)
    return ExtractedDocument(
        text="\n".join(paragraphs),
        paragraphs=paragraphs,
        metadata={"format": "odt"},
    )


def _extract_pdf(path: Path) -> ExtractedDocument:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ExtractionError(
            "Для PDF установите зависимость: python -m pip install pypdf"
        ) from exc
    try:
        reader = PdfReader(str(path))
        page_texts: list[str] = []
        for page_index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            page_texts.append(text)
        useful_pages = {
            re.sub(r"\s+", " ", text).strip() for text in page_texts if len(text.strip()) > 80
        }
        average_length = sum(len(text) for text in page_texts) / max(len(page_texts), 1)
        if average_length < 180 or len(useful_pages) <= max(2, len(page_texts) // 20):
            return _ocr_pdf(path)
        paragraphs: list[str] = []
        for text in page_texts:
            for block in re.split(r"\n\s*\n|\n(?=\d+(?:\.\d+)*\s)", text):
                clean = " ".join(block.split())
                if clean:
                    paragraphs.append(clean)
    except Exception as exc:
        raise ExtractionError(f"Не удалось извлечь текст PDF: {exc}") from exc
    return ExtractedDocument(
        text="\n".join(paragraphs),
        paragraphs=paragraphs,
        metadata={"format": "pdf", "pages": str(len(reader.pages))},
    )


def _tesseract_text(image_path: Path) -> str:
    tesseract = shutil.which("tesseract")
    if not tesseract:
        raise ExtractionError(
            "Для сканов установите Tesseract OCR с русским языком"
        )
    result = subprocess.run(
        [tesseract, str(image_path), "stdout", "-l", "rus+eng", "--psm", "6"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise ExtractionError(f"OCR завершился с ошибкой: {error}")
    return result.stdout.decode("utf-8", errors="replace")


def _ocr_pdf(path: Path) -> ExtractedDocument:
    try:
        import fitz
    except ImportError as exc:
        raise ExtractionError("Для OCR PDF установите PyMuPDF") from exc
    paragraphs: list[str] = []
    page_count = 0
    with tempfile.TemporaryDirectory() as directory:
        document = fitz.open(path)
        matrix = fitz.Matrix(2.2, 2.2)
        for page_index, page in enumerate(document, start=1):
            page_count = page_index
            image_path = Path(directory) / f"page-{page_index:04d}.png"
            page.get_pixmap(matrix=matrix, alpha=False).save(image_path)
            text = _tesseract_text(image_path)
            for line in text.splitlines():
                clean = " ".join(line.split())
                if clean:
                    paragraphs.append(f"[стр. {page_index}] {clean}")
    return ExtractedDocument(
        text="\n".join(paragraphs),
        paragraphs=paragraphs,
        metadata={"format": "pdf", "pages": str(page_count), "ocr": "tesseract"},
    )


def _extract_image(path: Path) -> ExtractedDocument:
    text = _tesseract_text(path)
    paragraphs = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    return ExtractedDocument(
        text="\n".join(paragraphs),
        paragraphs=paragraphs,
        metadata={"format": path.suffix.lower().lstrip("."), "ocr": "tesseract"},
    )


def _extract_text(path: Path) -> ExtractedDocument:
    raw = path.read_bytes()
    for encoding in ("utf-8", "cp1251", "utf-16"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    return ExtractedDocument(
        text="\n".join(paragraphs),
        paragraphs=paragraphs,
        metadata={"format": path.suffix.lower().lstrip(".")},
    )


def _extract_legacy_doc(path: Path) -> ExtractedDocument:
    textutil = shutil.which("textutil")
    if textutil:
        result = subprocess.run(
            [textutil, "-convert", "txt", "-stdout", str(path)],
            capture_output=True,
            check=False,
        )
        null_ratio = result.stdout.count(b"\x00") / max(len(result.stdout), 1)
        if result.returncode == 0 and null_ratio < 0.01:
            text = result.stdout.decode("utf-8", errors="replace")
            paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
            return ExtractedDocument(
                text="\n".join(paragraphs),
                paragraphs=paragraphs,
                metadata={"format": "doc", "converter": "textutil"},
            )

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        with tempfile.TemporaryDirectory() as output:
            result = subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--convert-to",
                    "txt:Text",
                    "--outdir",
                    output,
                    str(path),
                ],
                capture_output=True,
                check=False,
            )
            converted = Path(output) / f"{path.stem}.txt"
            if result.returncode == 0 and converted.exists():
                return _extract_text(converted)
    raise ExtractionError(
        "Старый DOC требует LibreOffice; рекомендуется сохранить его как DOCX"
    )

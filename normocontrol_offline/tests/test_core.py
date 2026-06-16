from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from normocontrol.corrections import apply_reference_mappings, preview_reference_mappings
from normocontrol.corrections import replace_in_docx
from normocontrol.db import Database
from normocontrol.extractors import extract_document
from normocontrol.references import find_references
from normocontrol.service import add_mapping, import_source


DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Ссылка ГОСТ Р 2.105-2019.</w:t></w:r></w:p>
    <w:p><w:r><w:rPr><w:i/><w:u w:val="single"/></w:rPr><w:t>исправить</w:t></w:r></w:p>
  </w:body>
</w:document>
"""

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
</Types>
"""


def make_docx(path: Path) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("word/document.xml", DOCUMENT_XML)


class CoreTests(unittest.TestCase):
    def test_docx_extraction_and_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.docx"
            make_docx(path)
            result = extract_document(path)
        self.assertEqual(result.paragraphs[0], "Ссылка ГОСТ Р 2.105-2019.")
        self.assertEqual({item.kind for item in result.annotations}, {"italic", "underline"})

    def test_reference_extraction(self) -> None:
        references = find_references("Применяется ГОСТ Р 2.105-2019 и НП-001-15.")
        self.assertEqual(
            {item.canonical for item in references},
            {"ГОСТ Р 2.105-2019", "НП-001-15"},
        )
        self.assertNotIn("НП-001-15.", {item.raw for item in references})

    def test_safe_docx_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.docx"
            target = Path(directory) / "target.docx"
            make_docx(source)
            count = replace_in_docx(
                source, target, [("ГОСТ Р 2.105-2019", "ГОСТ Р 2.105-2025")]
            )
            result = extract_document(target)
        self.assertEqual(count, 1)
        self.assertIn("ГОСТ Р 2.105-2025", result.text)

    def test_corrections_require_confirmation_and_write_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.docx"
            output = root / "corrected"
            make_docx(source)
            db = Database(root / "base.sqlite3")
            import_source(db, source, "document")
            add_mapping(db, "ГОСТ Р 2.105-2019", "ГОСТ Р 2.105-2025")

            preview = preview_reference_mappings(db)
            self.assertEqual(preview["documents"], 1)
            self.assertEqual(preview["replacements"], 1)
            with self.assertRaises(PermissionError):
                apply_reference_mappings(db, output)

            result = apply_reference_mappings(db, output, confirmed=True)
            report = Path(result["report"])
            self.assertEqual(result["changed_files"], 1)
            self.assertEqual(result["replacements"], 1)
            self.assertTrue(report.exists())
            self.assertIn("ГОСТ Р 2.105-2025", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

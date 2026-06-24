from __future__ import annotations

import csv
import posixpath
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

SUPPORTED_SOURCE_FILE_TYPES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".xlsx"}
MAX_SOURCE_CHARS = 8000
MAX_TABLE_ROWS = 40
MAX_TABLE_COLUMNS = 12

SPREADSHEET_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
REL_ID_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def build_source_context(
    *,
    website_urls: list[str] | None = None,
    source_files: list[Path] | None = None,
) -> tuple[list[str], list[str]]:
    """Return source references and bounded notes for business discovery context."""
    source_documents: list[str] = []
    notes: list[str] = []

    for raw_url in _normalize_items(website_urls):
        url = _normalize_url(raw_url)
        source_documents.append(url)
        notes.append(
            "Fuente web declarada: "
            f"{url}\n"
            "Uso esperado: revisar propuesta de valor, productos, segmentos, "
            "lenguaje comercial y formularios antes de cerrar el diseno CRM."
        )

    for path in source_files or []:
        if not path.exists():
            raise ValueError(f"Source file not found: {path}")
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_SOURCE_FILE_TYPES:
            supported = ", ".join(sorted(SUPPORTED_SOURCE_FILE_TYPES))
            raise ValueError(f"Unsupported source file type {suffix}. Supported: {supported}")
        source_documents.append(str(path))
        notes.append(f"Archivo de proceso aportado: {path}\n{_read_source_file(path)}")

    return source_documents, notes


def _normalize_items(items: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for item in items or []:
        for part in item.replace(";", ",").split(","):
            value = part.strip()
            if value:
                normalized.append(value)
    return normalized


def _normalize_url(raw_url: str) -> str:
    value = raw_url.strip()
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    if not parsed.netloc:
        raise ValueError(f"Invalid website URL: {raw_url}")
    return value


def _read_source_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        return _clip(path.read_text(encoding="utf-8", errors="replace"))
    if suffix in {".csv", ".tsv"}:
        return _read_delimited_table(path, delimiter="\t" if suffix == ".tsv" else ",")
    if suffix == ".xlsx":
        return _read_xlsx(path)
    raise ValueError(f"Unsupported source file type: {suffix}")


def _read_delimited_table(path: Path, *, delimiter: str) -> str:
    rows: list[list[str]] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        for row in reader:
            rows.append([cell.strip() for cell in row[:MAX_TABLE_COLUMNS]])
            if len(rows) >= MAX_TABLE_ROWS:
                break
    return _table_preview(rows, title=f"Vista previa tabular ({path.name})")


def _read_xlsx(path: Path) -> str:
    with zipfile.ZipFile(path) as workbook:
        shared_strings = _shared_strings(workbook)
        sheets = _workbook_sheets(workbook)
        previews: list[str] = []
        for sheet_name, sheet_path in sheets[:5]:
            if sheet_path not in workbook.namelist():
                continue
            rows = _worksheet_rows(workbook, sheet_path, shared_strings)
            previews.append(_table_preview(rows, title=f"Hoja: {sheet_name}"))
        return "\n\n".join(previews) if previews else "No pude extraer filas visibles del XLSX."


def _shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []
    root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("main:si", SPREADSHEET_NS):
        values.append(
            "".join(text.text or "" for text in item.findall(".//main:t", SPREADSHEET_NS))
        )
    return values


def _workbook_sheets(workbook: zipfile.ZipFile) -> list[tuple[str, str]]:
    root = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
    rel_root = ElementTree.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    rels = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rel_root.findall("rel:Relationship", SPREADSHEET_NS)
        if "Id" in rel.attrib and "Target" in rel.attrib
    }
    sheets: list[tuple[str, str]] = []
    for sheet in root.findall("main:sheets/main:sheet", SPREADSHEET_NS):
        rel_id = sheet.attrib.get(REL_ID_ATTR, "")
        target = rels.get(rel_id)
        if not target:
            continue
        sheet_path = target if target.startswith("xl/") else posixpath.normpath(f"xl/{target}")
        sheets.append((sheet.attrib.get("name", rel_id), sheet_path))
    return sheets


def _worksheet_rows(
    workbook: zipfile.ZipFile, sheet_path: str, shared_strings: list[str]
) -> list[list[str]]:
    root = ElementTree.fromstring(workbook.read(sheet_path))
    rows: list[list[str]] = []
    for row in root.findall(".//main:sheetData/main:row", SPREADSHEET_NS):
        values: list[str] = []
        for cell in row.findall("main:c", SPREADSHEET_NS)[:MAX_TABLE_COLUMNS]:
            values.append(_cell_value(cell, shared_strings))
        rows.append(values)
        if len(rows) >= MAX_TABLE_ROWS:
            break
    return rows


def _cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value_node = cell.find("main:v", SPREADSHEET_NS)
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//main:t", SPREADSHEET_NS))
    if value_node is None or value_node.text is None:
        return ""
    value = value_node.text
    if cell_type == "s":
        try:
            return shared_strings[int(value)]
        except (IndexError, ValueError):
            return value
    return value


def _table_preview(rows: list[list[str]], *, title: str) -> str:
    if not rows:
        return f"{title}\nSin filas visibles."
    rendered = [title]
    for row in rows:
        rendered.append("- " + " | ".join(cell for cell in row if cell))
    return _clip("\n".join(rendered))


def _clip(text: str, *, limit: int = MAX_SOURCE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[contenido truncado para mantener el contexto manejable]"

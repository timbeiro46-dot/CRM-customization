from __future__ import annotations

import zipfile

from crm_agent.source_context import build_source_context


def test_build_source_context_reads_xlsx_preview(tmp_path) -> None:
    workbook_path = tmp_path / "proceso.xlsx"
    _write_minimal_xlsx(workbook_path)

    source_documents, notes = build_source_context(
        website_urls=["example.com"],
        source_files=[workbook_path],
    )

    joined_notes = "\n".join(notes)
    assert "https://example.com" in source_documents
    assert str(workbook_path) in source_documents
    assert "Fuente web declarada" in joined_notes
    assert "Hoja: Proceso" in joined_notes
    assert "Etapa | Entrada | Salida" in joined_notes
    assert "Lead | Formulario web | Calificado" in joined_notes


def _write_minimal_xlsx(path) -> None:
    with zipfile.ZipFile(path, "w") as workbook:
        workbook.writestr(
            "xl/workbook.xml",
            """
            <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
              xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
              <sheets>
                <sheet name="Proceso" sheetId="1" r:id="rId1"/>
              </sheets>
            </workbook>
            """,
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            """
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1"
                Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
                Target="worksheets/sheet1.xml"/>
            </Relationships>
            """,
        )
        workbook.writestr(
            "xl/worksheets/sheet1.xml",
            """
            <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <sheetData>
                <row r="1">
                  <c r="A1" t="inlineStr"><is><t>Etapa</t></is></c>
                  <c r="B1" t="inlineStr"><is><t>Entrada</t></is></c>
                  <c r="C1" t="inlineStr"><is><t>Salida</t></is></c>
                </row>
                <row r="2">
                  <c r="A2" t="inlineStr"><is><t>Lead</t></is></c>
                  <c r="B2" t="inlineStr"><is><t>Formulario web</t></is></c>
                  <c r="C2" t="inlineStr"><is><t>Calificado</t></is></c>
                </row>
              </sheetData>
            </worksheet>
            """,
        )

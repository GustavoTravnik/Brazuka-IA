# Skill: Document Generation (PDF e DOCX)

**Role:** Geração de documentos PDF e DOCX a partir de conteúdo estruturado.  
**Ativação:** Sempre que precisar produzir um arquivo PDF ou DOCX para o usuário.

---

## 1. BIBLIOTECAS DISPONÍVEIS

| Biblioteca | Uso |
|---|---|
| `python-docx` | Criar e editar arquivos `.docx` |
| `weasyprint` | Converter HTML → PDF (suporte a CSS paginado, tabelas, fontes) |
| `markdown` | Converter Markdown → HTML (intermediário para PDF) |
| `reportlab` | PDF programático com controle fino de layout (tabelas complexas, gráficos) |
| `LibreOffice` (CLI) | Converter `.docx` → `.pdf` quando o DOCX já existe |

---

## 2. FLUXO DE DECISÃO

```
Preciso gerar um documento
│
├─ PDF?
│   ├─ Conteúdo é texto/markdown/tabelas simples → weasyprint (Markdown → HTML → PDF)
│   └─ Layout complexo, gráficos, posicionamento fino  → reportlab
│
└─ DOCX?
    ├─ Documento novo                                  → python-docx
    └─ Já tenho o DOCX e preciso de PDF também         → libreoffice --headless --convert-to pdf
```

---

## 3. GERAÇÃO DE PDF — WEASYPRINT (PADRÃO)

### Fluxo: Markdown → HTML → PDF

```python
import markdown
from weasyprint import HTML

def gerar_pdf(conteudo_md: str, caminho_saida: str) -> None:
    html_body = markdown.markdown(
        conteudo_md,
        extensions=["tables", "fenced_code"]
    )
    html_completo = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{
    size: A4;
    margin: 2.5cm;
    @bottom-center {{
      content: "Página " counter(page) " de " counter(pages);
      font-size: 9pt;
      color: #888;
    }}
  }}
  body      {{ font-family: Arial, sans-serif; font-size: 11pt; color: #222; line-height: 1.6; }}
  h1        {{ color: #1a237e; border-bottom: 2px solid #1a237e; padding-bottom: 6px; }}
  h2        {{ color: #283593; margin-top: 24px; }}
  h3        {{ color: #37474f; }}
  table     {{ border-collapse: collapse; width: 100%; margin: 14px 0; }}
  th        {{ background: #1a237e; color: white; padding: 8px 10px; text-align: left; }}
  td        {{ border: 1px solid #ccc; padding: 8px 10px; }}
  tr:nth-child(even) td {{ background: #f5f5f5; }}
  code      {{ background: #f0f0f0; padding: 2px 5px; border-radius: 3px; font-size: 10pt; font-family: monospace; }}
  pre       {{ background: #f0f0f0; padding: 14px; border-radius: 4px; overflow: auto; }}
  pre code  {{ background: none; padding: 0; }}
  blockquote {{ border-left: 4px solid #1a237e; margin: 0; padding: 4px 16px; color: #555; }}
</style>
</head>
<body>{html_body}</body>
</html>"""

    HTML(string=html_completo).write_pdf(caminho_saida)
```

### Parâmetros de página comuns

```python
# Paisagem
"@page { size: A4 landscape; margin: 2cm; }"

# Quebra de página forçada no Markdown via HTML inline
"<div style='page-break-before: always'></div>"

# CSS para evitar quebra no meio de uma tabela
"table { page-break-inside: avoid; }"
```

---

## 4. GERAÇÃO DE PDF — REPORTLAB (LAYOUT COMPLEXO)

Use apenas quando weasyprint não for suficiente: posicionamento absoluto, gráficos de barras, cabeçalhos fixos por página.

```python
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors

def gerar_pdf_reportlab(caminho_saida: str) -> None:
    doc = SimpleDocTemplate(caminho_saida, pagesize=A4,
                            leftMargin=2.5*cm, rightMargin=2.5*cm,
                            topMargin=2.5*cm, bottomMargin=2.5*cm)
    styles = getSampleStyleSheet()
    elementos = []

    # Título
    elementos.append(Paragraph("Relatório", styles["Title"]))
    elementos.append(Spacer(1, 0.5*cm))

    # Parágrafo
    elementos.append(Paragraph("Conteúdo do relatório.", styles["Normal"]))
    elementos.append(Spacer(1, 0.4*cm))

    # Tabela
    dados = [["Coluna A", "Coluna B", "Coluna C"],
             ["Valor 1",  "Valor 2",  "Valor 3"]]
    tabela = Table(dados, hAlign="LEFT")
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID",       (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("PADDING",    (0, 0), (-1, -1), 6),
    ]))
    elementos.append(tabela)

    doc.build(elementos)
```

---

## 5. GERAÇÃO DE DOCX — PYTHON-DOCX

```python
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

def gerar_docx(caminho_saida: str) -> None:
    doc = Document()

    # Título centralizado
    titulo = doc.add_heading("Título do Documento", level=0)
    titulo.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Seção
    doc.add_heading("Seção 1", level=1)

    # Parágrafo com formatação inline
    p = doc.add_paragraph()
    p.add_run("Texto normal e ")
    p.add_run("texto em negrito").bold = True
    p.add_run(" e ")
    p.add_run("itálico").italic = True

    # Lista com marcadores
    doc.add_heading("Lista", level=2)
    for item in ["Item A", "Item B", "Item C"]:
        doc.add_paragraph(item, style="List Bullet")

    # Lista numerada
    for item in ["Passo 1", "Passo 2", "Passo 3"]:
        doc.add_paragraph(item, style="List Number")

    # Tabela
    doc.add_heading("Tabela", level=2)
    tabela = doc.add_table(rows=1, cols=3)
    tabela.style = "Table Grid"

    cabecalho = tabela.rows[0].cells
    cabecalho[0].text = "Coluna A"
    cabecalho[1].text = "Coluna B"
    cabecalho[2].text = "Coluna C"

    linha = tabela.add_row().cells
    linha[0].text = "Valor 1"
    linha[1].text = "Valor 2"
    linha[2].text = "Valor 3"

    # Quebra de página
    doc.add_page_break()

    doc.save(caminho_saida)
```

### Formatação de células da tabela

```python
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# Cor de fundo em uma célula
def set_cell_bg(cell, hex_color: str):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    shd.set(qn("w:val"), "clear")
    tc_pr.append(shd)

# Uso
set_cell_bg(tabela.rows[0].cells[0], "1a237e")
```

---

## 6. DOCX → PDF VIA LIBREOFFICE

Quando o arquivo DOCX já existe e o usuário também precisa do PDF:

```bash
libreoffice --headless --convert-to pdf /caminho/arquivo.docx --outdir /caminho/saida/
```

```python
import subprocess

def docx_para_pdf(caminho_docx: str, diretorio_saida: str) -> None:
    subprocess.run(
        ["libreoffice", "--headless", "--convert-to", "pdf",
         caminho_docx, "--outdir", diretorio_saida],
        check=True,
        capture_output=True
    )
```

---

## 7. TEMPLATES PRONTOS

### Relatório de Sprint

```python
def relatorio_sprint(sprint: str, metricas: dict, destaques: list[str]) -> str:
    """Retorna Markdown pronto para gerar PDF via weasyprint."""
    itens = "\n".join(f"- {d}" for d in destaques)
    linhas = "\n".join(f"| {k} | {v} |" for k, v in metricas.items())
    return f"""# Relatório de Sprint — {sprint}

| Métrica | Valor |
|---|---|
{linhas}

## Destaques

{itens}
"""
```

### Documento técnico com capa

```python
def capa_html(titulo: str, subtitulo: str, data: str) -> str:
    return f"""
<div style="text-align:center; margin-top: 120px;">
  <h1 style="font-size: 28pt; color: #1a237e;">{titulo}</h1>
  <p style="font-size: 14pt; color: #555;">{subtitulo}</p>
  <p style="font-size: 10pt; color: #888; margin-top: 60px;">{data}</p>
</div>
<div style="page-break-before: always"></div>
"""
```

---

## 8. CHECKLIST DE GERAÇÃO

Antes de gerar qualquer documento, confirme:

- [ ] Qual formato de saída? PDF ou DOCX (ou ambos)?
- [ ] O conteúdo é texto/tabelas simples? → `weasyprint`
- [ ] O conteúdo exige layout fino ou gráficos? → `reportlab`
- [ ] O usuário pediu DOCX e também PDF? → gerar DOCX com `python-docx`, converter com LibreOffice
- [ ] O caminho de saída está definido? (preferir `/tmp/` ou diretório do projeto)
- [ ] Confirmei que o arquivo foi gerado verificando o tamanho com `os.path.getsize()`?

---

## 9. TRATAMENTO DE ERROS COMUNS

| Erro | Causa | Solução |
|---|---|---|
| `ModuleNotFoundError` | Biblioteca não instalada | `pip install python-docx weasyprint markdown reportlab` |
| PDF gerado com 0 bytes | HTML inválido ou vazio | Verificar se `html_body` não está vazio antes de chamar `write_pdf` |
| Tabela cortada no DOCX | Células sem texto | Garantir que `cell.text` nunca seja `None` |
| LibreOffice trava | Processo anterior não encerrou | `pkill -f soffice` antes de executar |
| Fonte não encontrada no weasyprint | Fonte customizada ausente | Usar fontes web-safe: Arial, Helvetica, Georgia, monospace |
| Caracteres especiais corrompidos | Encoding errado | Sempre incluir `<meta charset="utf-8">` no HTML |

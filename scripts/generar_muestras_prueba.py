#!/usr/bin/env python3
"""
Script para generar archivos de prueba para Captura y Homologación:
1. factura_prueba_F001-00000456.xml (UBL 2.1 estándar SUNAT con RUCs válidos y cuadre matemático exacto)
2. factura_prueba_F001-00000456.pdf (PDF vectorial estilizado y legible para el visor y OCR)
"""
import os
import shutil
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Frame, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm

BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_PRUEBAS = BASE_DIR / "docs" / "pruebas"
DOCS_PRUEBAS.mkdir(parents=True, exist_ok=True)

XML_CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:UBLVersionID>2.1</cbc:UBLVersionID>
  <cbc:CustomizationID>2.0</cbc:CustomizationID>
  <cbc:ID>F001-00000456</cbc:ID>
  <cbc:IssueDate>2026-02-15</cbc:IssueDate>
  <cbc:IssueTime>10:30:00</cbc:IssueTime>
  <cbc:InvoiceTypeCode listID="0101">01</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>PEN</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyIdentification>
        <cbc:ID schemeID="6">20601234565</cbc:ID>
      </cac:PartyIdentification>
      <cac:PartyLegalEntity>
        <cbc:RegistrationName>DISTRIBUIDORA INDUSTRIAL DEL PERU S.A.C.</cbc:RegistrationName>
      </cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyIdentification>
        <cbc:ID schemeID="6">20100070970</cbc:ID>
      </cac:PartyIdentification>
      <cac:PartyLegalEntity>
        <cbc:RegistrationName>EMPRESA PILOTO ASESCON S.A.C.</cbc:RegistrationName>
      </cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="PEN">270.90</cbc:TaxAmount>
    <cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="PEN">1505.00</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="PEN">270.90</cbc:TaxAmount>
      <cac:TaxCategory>
        <cbc:ID>S</cbc:ID>
        <cbc:Percent>18.00</cbc:Percent>
        <cbc:TaxExemptionReasonCode>10</cbc:TaxExemptionReasonCode>
        <cac:TaxScheme>
          <cbc:ID>1000</cbc:ID>
          <cbc:Name>IGV</cbc:Name>
          <cbc:TaxTypeCode>VAT</cbc:TaxTypeCode>
        </cac:TaxScheme>
      </cac:TaxCategory>
    </cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="PEN">1505.00</cbc:LineExtensionAmount>
    <cbc:TaxInclusiveAmount currencyID="PEN">1775.90</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="PEN">1775.90</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="NIU">50.00</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="PEN">925.00</cbc:LineExtensionAmount>
    <cac:PricingReference>
      <cac:AlternativeConditionPrice>
        <cbc:PriceAmount currencyID="PEN">21.83</cbc:PriceAmount>
        <cbc:PriceTypeCode>01</cbc:PriceTypeCode>
      </cac:AlternativeConditionPrice>
    </cac:PricingReference>
    <cac:TaxTotal>
      <cbc:TaxAmount currencyID="PEN">166.50</cbc:TaxAmount>
      <cac:TaxSubtotal>
        <cbc:TaxableAmount currencyID="PEN">925.00</cbc:TaxableAmount>
        <cbc:TaxAmount currencyID="PEN">166.50</cbc:TaxAmount>
        <cac:TaxCategory>
          <cbc:Percent>18.00</cbc:Percent>
          <cbc:TaxExemptionReasonCode>10</cbc:TaxExemptionReasonCode>
          <cac:TaxScheme>
            <cbc:ID>1000</cbc:ID>
            <cbc:Name>IGV</cbc:Name>
            <cbc:TaxTypeCode>VAT</cbc:TaxTypeCode>
          </cac:TaxScheme>
        </cac:TaxCategory>
      </cac:TaxSubtotal>
    </cac:TaxTotal>
    <cac:Item>
      <cbc:Description>PAPEL BOND 75GR A4 ATLAS MILL</cbc:Description>
      <cac:SellersItemIdentification>
        <cbc:ID>PROD-001</cbc:ID>
      </cac:SellersItemIdentification>
    </cac:Item>
    <cac:Price>
      <cbc:PriceAmount currencyID="PEN">18.50</cbc:PriceAmount>
    </cac:Price>
  </cac:InvoiceLine>
  <cac:InvoiceLine>
    <cbc:ID>2</cbc:ID>
    <cbc:InvoicedQuantity unitCode="NIU">4.00</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="PEN">580.00</cbc:LineExtensionAmount>
    <cac:PricingReference>
      <cac:AlternativeConditionPrice>
        <cbc:PriceAmount currencyID="PEN">171.10</cbc:PriceAmount>
        <cbc:PriceTypeCode>01</cbc:PriceTypeCode>
      </cac:AlternativeConditionPrice>
    </cac:PricingReference>
    <cac:TaxTotal>
      <cbc:TaxAmount currencyID="PEN">104.40</cbc:TaxAmount>
      <cac:TaxSubtotal>
        <cbc:TaxableAmount currencyID="PEN">580.00</cbc:TaxableAmount>
        <cbc:TaxAmount currencyID="PEN">104.40</cbc:TaxAmount>
        <cac:TaxCategory>
          <cbc:Percent>18.00</cbc:Percent>
          <cbc:TaxExemptionReasonCode>10</cbc:TaxExemptionReasonCode>
          <cac:TaxScheme>
            <cbc:ID>1000</cbc:ID>
            <cbc:Name>IGV</cbc:Name>
            <cbc:TaxTypeCode>VAT</cbc:TaxTypeCode>
          </cac:TaxScheme>
        </cac:TaxCategory>
      </cac:TaxSubtotal>
    </cac:TaxTotal>
    <cac:Item>
      <cbc:Description>TONER HP LASERJET NEGRO CF283A</cbc:Description>
      <cac:SellersItemIdentification>
        <cbc:ID>PROD-002</cbc:ID>
      </cac:SellersItemIdentification>
    </cac:Item>
    <cac:Price>
      <cbc:PriceAmount currencyID="PEN">145.00</cbc:PriceAmount>
    </cac:Price>
  </cac:InvoiceLine>
</Invoice>
"""

def generar_xml():
    xml_path = DOCS_PRUEBAS / "factura_prueba_F001-00000456.xml"
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(XML_CONTENT.strip())
    print(f"XML generado en: {xml_path}")
    
    # Copia en raíz para acceso directo
    shutil.copy(xml_path, BASE_DIR / "factura_prueba.xml")
    print(f"XML copiado a: {BASE_DIR / 'factura_prueba.xml'}")

def generar_pdf():
    pdf_path = DOCS_PRUEBAS / "factura_prueba_F001-00000456.pdf"
    
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    
    styles = getSampleStyleSheet()
    
    # Estilos personalizados
    titulo_emisor = ParagraphStyle(
        'TituloEmisor',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#1E293B'),
    )
    
    datos_emisor = ParagraphStyle(
        'DatosEmisor',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor('#475569'),
    )
    
    ruc_box_title = ParagraphStyle(
        'RucBoxTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        alignment=1, # Centrado
        textColor=colors.HexColor('#0F172A'),
    )
    
    ruc_box_num = ParagraphStyle(
        'RucBoxNum',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=15,
        alignment=1,
        textColor=colors.HexColor('#1E3A8A'),
    )
    
    label_style = ParagraphStyle(
        'LabelStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#1E293B'),
    )
    
    val_style = ParagraphStyle(
        'ValStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#334155'),
    )

    story = []

    # 1. Cabecera Emisor + Caja RUC
    col_emisor = [
        Paragraph("DISTRIBUIDORA INDUSTRIAL DEL PERU S.A.C.", titulo_emisor),
        Spacer(1, 4),
        Paragraph("Venta de suministros, útiles y artículos de oficina y computo", datos_emisor),
        Paragraph("Av. Argentina 2450, Lima, Perú", datos_emisor),
        Paragraph("Teléfono: (01) 456-7890 | Email: ventas@distribuidoraindustrial.pe", datos_emisor),
        Paragraph("Web: www.distribuidoraindustrial.pe", datos_emisor),
    ]

    col_ruc = [
        Spacer(1, 6),
        Paragraph("R.U.C. 20601234565", ruc_box_title),
        Spacer(1, 4),
        Paragraph("FACTURA ELECTRÓNICA", ruc_box_title),
        Spacer(1, 4),
        Paragraph("F001-00000456", ruc_box_num),
        Spacer(1, 6),
    ]

    t_ruc = Table([[col_ruc]], colWidths=[200])
    t_ruc.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 1.5, colors.HexColor('#1E3A8A')),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
    ]))

    header_table = Table([[col_emisor, t_ruc]], colWidths=[330, 210])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 14))

    # 2. Datos del Cliente / Adquiriente
    datos_cliente = [
        [
            Paragraph("Señor(es):", label_style),
            Paragraph("EMPRESA PILOTO ASESCON S.A.C.", val_style),
            Paragraph("Fecha Emisión:", label_style),
            Paragraph("15/02/2026", val_style),
        ],
        [
            Paragraph("R.U.C.:", label_style),
            Paragraph("20100070970", val_style),
            Paragraph("Moneda:", label_style),
            Paragraph("SOLES (PEN)", val_style),
        ],
        [
            Paragraph("Dirección:", label_style),
            Paragraph("Av. Los Frutales 123, Ate, Lima", val_style),
            Paragraph("Condición Pago:", label_style),
            Paragraph("Contado", val_style),
        ],
    ]
    t_cliente = Table(datos_cliente, colWidths=[65, 260, 85, 130])
    t_cliente.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 0.75, colors.HexColor('#CBD5E1')),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_cliente)
    story.append(Spacer(1, 14))

    # 3. Tabla de Productos / Ítems
    th_style = ParagraphStyle(
        'THStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        alignment=1,
        textColor=colors.white,
    )
    td_center = ParagraphStyle('TDC', parent=val_style, alignment=1)
    td_right = ParagraphStyle('TDR', parent=val_style, alignment=2)
    td_left = ParagraphStyle('TDL', parent=val_style, alignment=0)

    items_data = [
        [
            Paragraph("ÍTEM", th_style),
            Paragraph("CÓDIGO", th_style),
            Paragraph("DESCRIPCIÓN", th_style),
            Paragraph("UND", th_style),
            Paragraph("CANTIDAD", th_style),
            Paragraph("P. UNIT.", th_style),
            Paragraph("VALOR VENTA", th_style),
        ],
        [
            Paragraph("1", td_center),
            Paragraph("PROD-001", td_center),
            Paragraph("PAPEL BOND 75GR A4 ATLAS MILL (Millar)", td_left),
            Paragraph("NIU", td_center),
            Paragraph("50.00", td_right),
            Paragraph("18.50", td_right),
            Paragraph("925.00", td_right),
        ],
        [
            Paragraph("2", td_center),
            Paragraph("PROD-002", td_center),
            Paragraph("TONER HP LASERJET NEGRO CF283A", td_left),
            Paragraph("NIU", td_center),
            Paragraph("4.00", td_right),
            Paragraph("145.00", td_right),
            Paragraph("580.00", td_right),
        ],
    ]

    t_items = Table(items_data, colWidths=[30, 65, 230, 40, 55, 60, 60])
    t_items.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E293B')),
        ('BOX', (0,0), (-1,-1), 0.75, colors.HexColor('#94A3B8')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t_items)
    story.append(Spacer(1, 10))

    # 4. Totales e Importe en Letras
    son_letras = Paragraph(
        "<strong>SON:</strong> MIL SETECIENTOS SETENTA Y CINCO CON 90/100 SOLES",
        label_style
    )

    totales_data = [
        [Paragraph("Op. Gravada:", label_style), Paragraph("S/ 1,505.00", td_right)],
        [Paragraph("I.G.V. (18%):", label_style), Paragraph("S/ 270.90", td_right)],
        [Paragraph("<strong>TOTAL A PAGAR:</strong>", label_style), Paragraph("<strong>S/ 1,775.90</strong>", td_right)],
    ]
    t_totales = Table(totales_data, colWidths=[90, 85])
    t_totales.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 0.75, colors.HexColor('#CBD5E1')),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('BACKGROUND', (0,2), (-1,2), colors.HexColor('#E0E7FF')), # Resaltar total
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]))

    t_pie = Table([[son_letras, t_totales]], colWidths=[365, 175])
    t_pie.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
    ]))
    story.append(t_pie)
    story.append(Spacer(1, 20))

    # 5. Pie de página legal SUNAT
    pie_legal = ParagraphStyle(
        'PieLegal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7,
        leading=9.5,
        alignment=1,
        textColor=colors.HexColor('#64748B'),
    )
    story.append(Paragraph(
        "Representación impresa de la FACTURA ELECTRÓNICA generada según normativa SUNAT UBL 2.1.<br/>"
        "Autorizado mediante Resolución de Superintendencia N° 034-005-0005315/SUNAT.<br/>"
        "Hash SHA-256 de control: c8a3f9e2b1d4a7c5e8f0b3d6a9c2e5f8b1d4a7c0",
        pie_legal
    ))

    doc.build(story)
    print(f"PDF generado en: {pdf_path}")
    
    # Copia en raíz para acceso directo
    shutil.copy(pdf_path, BASE_DIR / "factura_prueba.pdf")
    print(f"PDF copiado a: {BASE_DIR / 'factura_prueba.pdf'}")

if __name__ == '__main__':
    generar_xml()
    generar_pdf()
    print("Muestras de prueba generadas exitosamente.")


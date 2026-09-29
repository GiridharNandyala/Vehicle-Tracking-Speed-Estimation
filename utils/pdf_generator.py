import io
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def generate_pdf_report(summary_stats: dict, logs_df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    
    # Page width = 612 pt. Margins 36 pt split both sides = 540 pt printable width
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=letter,
        rightMargin=36, 
        leftMargin=36, 
        topMargin=36, 
        bottomMargin=36
    )
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#1E293B'),
        spaceAfter=12
    )
    
    cell_style = ParagraphStyle(
        'CellStyle',
        parent=styles['Normal'],
        fontSize=6.5,
        leading=7.5,
        wordWrap='CJK'
    )
    
    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        fontSize=6.5,
        leading=7.5,
        textColor=colors.white,
        fontName='Helvetica-Bold'
    )

    elements = []

    # Title
    elements.append(Paragraph("Traffic Analytics Executive Report", title_style))
    elements.append(Spacer(1, 10))

    # Summary Table
    summary_data = [["Metric", "Value"]]
    for k, v in summary_stats.items():
        summary_data.append([str(k), str(v)])
        
    t_summary = Table(summary_data, colWidths=[180, 360])
    t_summary.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F172A')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F8FAFC')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
    ]))
    elements.append(t_summary)
    elements.append(Spacer(1, 15))

    # Logs Table
    if not logs_df.empty:
        elements.append(Paragraph("Recent Detection Logs", styles['Heading2']))
        elements.append(Spacer(1, 8))
        
        # Limit rows and round float values to 2 decimals
        df_preview = logs_df.head(15).copy()
        for col in df_preview.select_dtypes(include=['float', 'float64']).columns:
            df_preview[col] = df_preview[col].round(2)

        # Header Row
        logs_data = [[Paragraph(str(col), header_style) for col in df_preview.columns]]
        
        # Data Rows wrapped in Paragraph for auto text-wrapping
        for _, row in df_preview.iterrows():
            formatted_row = [Paragraph(str(val), cell_style) for val in row.values]
            logs_data.append(formatted_row)
            
        # Dynamically calculate column width within 540 pt printable page boundary
        num_cols = len(df_preview.columns)
        col_width = 540 / num_cols if num_cols > 0 else 60
        
        t_logs = Table(logs_data, colWidths=[col_width] * num_cols)
        t_logs.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#334155')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(t_logs)

    # Build PDF
    doc.build(elements)
    
    # Extract bytes from buffer
    pdf_bytes = buffer.getvalue()
    buffer.close()
    
    return pdf_bytes
import io
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def generate_pdf_report(summary_stats: dict, logs_df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
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
    
    normal_style = styles['Normal']
    elements = []

    # Title
    elements.append(Paragraph("Traffic Analytics Executive Report", title_style))
    elements.append(Spacer(1, 10))

    # Summary Table
    summary_data = [["Metric", "Value"]]
    for k, v in summary_stats.items():
        summary_data.append([str(k), str(v)])
        
    t_summary = Table(summary_data, colWidths=[200, 300])
    t_summary.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F172A')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F8FAFC')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
    ]))
    elements.append(t_summary)
    elements.append(Spacer(1, 20))

    # Logs Table
    if not logs_df.empty:
        elements.append(Paragraph("Recent Detection Logs", styles['Heading2']))
        elements.append(Spacer(1, 8))
        
        # Limit rows to fit nicely
        df_preview = logs_df.head(15)
        
        logs_data = [list(df_preview.columns)]
        for _, row in df_preview.iterrows():
            logs_data.append([str(val) for val in row.values])
            
        t_logs = Table(logs_data)
        t_logs.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#334155')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(t_logs)

    # Build PDF
    doc.build(elements)
    
    # Extract bytes from buffer
    pdf_bytes = buffer.getvalue()
    buffer.close()
    
    return pdf_bytes
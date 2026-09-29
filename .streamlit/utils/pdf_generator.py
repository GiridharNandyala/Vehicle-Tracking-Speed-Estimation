"""
utils/pdf_generator.py
PDF Executive Summary Generator using ReportLab
"""

import io
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

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
    elements = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#161b22'),
        spaceAfter=12
    )
    
    elements.append(Paragraph("🚦 Traffic Flow & Executive Analytics Report", title_style))
    elements.append(Spacer(1, 10))

    summary_data = [
        ["Metric", "Value"],
        ["Total Vehicles Captured", str(summary_stats.get('total', 0))],
        ["Speeding Violations", str(summary_stats.get('speeding', 0))],
        ["Average Speed (km/h)", f"{summary_stats.get('avg_speed', 0) or 0:.1f}"],
        ["Peak Speed Recorded (km/h)", f"{summary_stats.get('max_speed', 0) or 0:.1f}"],
        ["Inbound (IN) Count", str(summary_stats.get('total_in', 0))],
        ["Outbound (OUT) Count", str(summary_stats.get('total_out', 0))]
    ]

    t_summary = Table(summary_data, colWidths=[200, 200])
    t_summary.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#21262d')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('GRID', (0,0), (-1,-1), 1, colors.HexColor('#d0d7de')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(t_summary)
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("Recent Vehicle Log Sample", styles['Heading2']))
    elements.append(Spacer(1, 8))

    if not logs_df.empty:
        sample_df = logs_df.head(10)[['id', 'vehicle_type', 'speed_kmh', 'direction', 'is_speeding']]
        table_content = [["ID", "Class", "Speed (km/h)", "Direction", "Speeding?"]]
        for _, r in sample_df.iterrows():
            table_content.append([
                str(r.get('id', '')),
                str(r.get('vehicle_type', '')),
                f"{r.get('speed_kmh', 0):.1f}" if pd.notnull(r.get('speed_kmh')) else "N/A",
                str(r.get('direction', '')),
                "YES" if r.get('is_speeding') else "NO"
            ])
        t_logs = Table(table_content, colWidths=[50, 100, 100, 100, 90])
        t_logs.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#58a6ff')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#d0d7de')),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        elements.append(t_logs)

    doc.build(elements)
    pdf_val = buffer.getvalue()
    buffer.close()
    return pdf_val
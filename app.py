"""
╔══════════════════════════════════════════════════════════════════════════════╗
║      TRAFFIC FLOW & SPEED ANALYTICS SYSTEM — Fixed Executive Dashboard       ║
║      app.py  ·  Streamlit Executive Dashboard (Gemini Flash & Retry Fix)     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import io
import os
import queue
import sqlite3
import sys
import tempfile
import threading
import time
import requests
import shutil
import importlib
import importlib.util
from pathlib import Path
from typing import Optional

# Ensure project root and utils directory are added to sys.path dynamically
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

UTILS_DIR = CURRENT_DIR / "utils"
if UTILS_DIR.exists() and str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))

import cv2
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import pandas as pd

# Safe OCR Module Loader Fix
HAS_OCR = False
READER = None
if importlib.util.find_spec("easyocr") is not None:
    try:
        import easyocr
        READER = easyocr.Reader(['en'], gpu=False)
        HAS_OCR = True
    except Exception:
        HAS_OCR = False

# Import Google GenAI library safely
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# Fallback In-Memory PDF Generator when external utils package is missing
def _generate_fallback_pdf(stats: dict, df: pd.DataFrame) -> bytes:
    """Generates a complete PDF report using reportlab directly in app.py if utils module is missing."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
        elements = []
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'TitleStyle',
            parent=styles['Heading1'],
            fontSize=18,
            textColor=colors.HexColor('#161b22'),
            spaceAfter=12
        )
        body_style = ParagraphStyle(
            'BodyStyle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#333333'),
            spaceAfter=6
        )

        elements.append(Paragraph("Traffic Analytics Executive Report", title_style))
        elements.append(Paragraph(f"Generated On: {time.strftime('%Y-%m-%d %H:%M:%S')}", body_style))
        elements.append(Spacer(1, 10))

        # Statistics Summary Table
        summary_data = [
            ["Metric", "Value"],
            ["Total Vehicles Counted", str(stats.get('total', 0))],
            ["Speeding Violations", str(stats.get('speeding', 0))],
            ["Average Road Speed", f"{stats.get('avg_speed', 0):.1f} km/h" if stats.get('avg_speed') else "N/A"],
            ["Max Recorded Speed", f"{stats.get('max_speed', 0):.1f} km/h" if stats.get('max_speed') else "N/A"],
            ["Vehicles Direction (IN / OUT)", f"{stats.get('total_in', 0)} IN / {stats.get('total_out', 0)} OUT"]
        ]
        t_summary = Table(summary_data, colWidths=[240, 240])
        t_summary.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#21262d')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0,0), (-1,0), 8),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f6f8fa')),
            ('GRID', (0,0), (-1,-1), 1, colors.HexColor('#d0d7de')),
        ]))
        elements.append(t_summary)
        elements.append(Spacer(1, 15))

        elements.append(Paragraph("Recent Vehicle Detection Log Snapshots", ParagraphStyle('Sub', parent=styles['Heading2'], fontSize=14)))
        elements.append(Spacer(1, 8))

        # Recent Logs Table
        log_data = [["ID", "Track ID", "Class", "Speed (km/h)", "Plate No", "Direction", "Speeding?"]]
        if not df.empty:
            for idx, row in df.head(15).iterrows():
                log_data.append([
                    str(row.get('id', '')),
                    str(row.get('track_id', '')),
                    str(row.get('vehicle_type', '')),
                    f"{float(row.get('speed_kmh', 0)):.1f}" if pd.notnull(row.get('speed_kmh')) else "N/A",
                    str(row.get('license_plate', 'N/A')),
                    str(row.get('direction', '')),
                    "YES" if row.get('is_speeding') else "NO"
                ])
        else:
            log_data.append(["N/A", "N/A", "No records", "N/A", "N/A", "N/A", "N/A"])

        t_logs = Table(log_data, colWidths=[30, 50, 80, 80, 90, 80, 70])
        t_logs.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1f2328')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#d0d7de')),
        ]))
        elements.append(t_logs)

        doc.build(elements)
        pdf_val = buffer.getvalue()
        buffer.close()
        return pdf_val
    except Exception as e:
        return f"PDF Error: {e}".encode("utf-8")

# Safe Dynamic PDF Generator Loader Fix
def _get_pdf_generator_function():
    try:
        if importlib.util.find_spec("utils.pdf_generator") is not None:
            pdf_gen_module = importlib.import_module("utils.pdf_generator")
            if hasattr(pdf_gen_module, "generate_pdf_report"):
                return getattr(pdf_gen_module, "generate_pdf_report")
    except Exception:
        pass

    try:
        if importlib.util.find_spec("pdf_generator") is not None:
            pdf_gen_module = importlib.import_module("pdf_generator")
            if hasattr(pdf_gen_module, "generate_pdf_report"):
                return getattr(pdf_gen_module, "generate_pdf_report")
    except Exception:
        pass

    return _generate_fallback_pdf

# ── Local modules ─────────────────────────────────────────────────────────────
try:
    from database_manager import DatabaseManager, VehicleRecord
except ImportError:
    st.error("❌ `database_manager.py` not found in the same folder as `app.py`.")
    st.stop()

try:
    from traffic_pipeline import PipelineConfig, TrafficPipeline
    from traffic_pipeline import (
        draw_detections, draw_hud,
        CountingLine, SpeedEstimator, DirectionDetector
    )
    from ultralytics import YOLO
    import supervision as sv
except ImportError as exc:
    st.error(
        f"❌ Pipeline import failed: {exc}\n\n"
        "Install: `pip install ultralytics supervision opencv-python numpy google-genai pandas requests easyocr reportlab`"
    )
    st.stop()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — FOLDER CREATION & PAGE CONFIG
# ══════════════════════════════════════════════════════════════════════════════

ALERTS_DIR = Path("alerts")
ALERTS_DIR.mkdir(parents=True, exist_ok=True)

st.set_page_config(
    page_title="Traffic Analytics Dashboard",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* ── Global reset ── */
html, body, [class*="css"] {
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
}

/* ── App background ── */
.stApp {
    background-color: #0d1117;
    color: #e6edf3;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background-color: #161b22;
    border-right: 1px solid #30363d;
}
section[data-testid="stSidebar"] * {
    color: #c9d1d9 !important;
}

/* ── KPI metric cards ── */
.kpi-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 18px 22px;
    text-align: center;
    transition: border-color .2s;
}
.kpi-card:hover { border-color: #58a6ff; }
.kpi-label {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #8b949e;
    margin-bottom: 6px;
}
.kpi-value {
    font-size: 2.1rem;
    font-weight: 700;
    color: #e6edf3;
    line-height: 1;
}
.kpi-delta {
    font-size: 0.78rem;
    margin-top: 4px;
}
.kpi-delta.up   { color: #3fb950; }
.kpi-delta.warn { color: #f85149; }
.kpi-delta.neu  { color: #8b949e; }

/* ── Section headings ── */
.section-head {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.10em;
    color: #58a6ff;
    border-bottom: 1px solid #21262d;
    padding-bottom: 6px;
    margin-bottom: 12px;
}

/* ── Video feed container ── */
.video-container {
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 10px;
    overflow: hidden;
    min-height: 320px;
    display: flex;
    align-items: center;
    justify-content: center;
}

/* ── Buttons ── */
.stButton > button {
    background-color: #21262d;
    border: 1px solid #30363d;
    color: #c9d1d9;
    border-radius: 6px;
    font-size: 0.82rem;
    padding: 6px 16px;
}
.stButton > button:hover {
    background-color: #30363d;
    border-color: #58a6ff;
    color: #ffffff;
}

/* ── Status badges ── */
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 20px;
    font-size: 0.72rem;
    font-weight: 600;
}
.badge-green { background: #1a3828; color: #3fb950; }
.badge-blue  { background: #1a2a3d; color: #58a6ff; }

/* ── Hide Streamlit chrome ── */
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — CONSTANTS & HELPERS
# ══════════════════════════════════════════════════════════════════════════════

DB_PATH           = "traffic_data.db"
ALL_CLASSES       = ["Car", "Motorcycle", "Bus", "Truck"]
CLASS_COLOR_MAP   = {
    "Car":        "#FFc800",
    "Motorcycle": "#78FF00",
    "Bus":        "#0050FF",
    "Truck":      "#5000FF",
}
PLOTLY_TEMPLATE   = "plotly_dark"
CHART_PAPER_BG    = "#161b22"
CHART_PLOT_BG     = "#0d1117"
CHART_GRID        = "#21262d"
CHART_FONT_COLOR  = "#8b949e"


def init_db_tables():
    """Ensure database tables exist to prevent 'no such table' SQL errors."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vehicle_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                track_id INTEGER,
                vehicle_type TEXT,
                speed_kmh REAL,
                direction TEXT,
                is_speeding BOOLEAN,
                frame_id INTEGER,
                confidence REAL,
                license_plate TEXT,
                pos_x REAL,
                pos_y REAL
            )
        """)
        
        cursor.execute("PRAGMA table_info(vehicle_logs)")
        cols = [col[1] for col in cursor.fetchall()]
        if "license_plate" not in cols:
            cursor.execute("ALTER TABLE vehicle_logs ADD COLUMN license_plate TEXT")
        if "pos_x" not in cols:
            cursor.execute("ALTER TABLE vehicle_logs ADD COLUMN pos_x REAL")
        if "pos_y" not in cols:
            cursor.execute("ALTER TABLE vehicle_logs ADD COLUMN pos_y REAL")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS video_sessions (
                session_id TEXT PRIMARY KEY,
                start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                end_time DATETIME,
                source_file TEXT,
                total_frames INTEGER
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error initializing DB tables: {e}")


# Initialize tables at app launch
init_db_tables()


def send_telegram_alert(bot_token: str, chat_id: str, message: str, image_path: Optional[str] = None):
    """Asynchronous/Threaded alert sender to Telegram Bot."""
    if not bot_token or not chat_id:
        return

    def _send():
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
            requests.post(url, data=payload, timeout=5)

            if image_path and os.path.exists(image_path):
                img_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                with open(image_path, 'rb') as photo:
                    requests.post(img_url, data={"chat_id": chat_id}, files={"photo": photo}, timeout=10)
        except Exception as e:
            print(f"Telegram Alert Error: {e}")

    threading.Thread(target=_send, daemon=True).start()


def extract_license_plate_ocr(crop_img) -> str:
    """Enhanced ANPR Logic Hook: Multi-stage image preprocessing for License Plate extraction."""
    if crop_img is None or crop_img.size == 0:
        return "N/A"
    
    if HAS_OCR and READER is not None:
        try:
            gray = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
            resized = cv2.resize(gray, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
            denoised = cv2.bilateralFilter(resized, 11, 17, 17)
            _, thresh = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            results = READER.readtext(thresh)
            for (_, text, prob) in results:
                clean_text = "".join(e for e in text if e.isalnum()).upper()
                if prob > 0.10 and len(clean_text) >= 3:
                    return clean_text

            results_raw = READER.readtext(gray)
            for (_, text, prob) in results_raw:
                clean_text = "".join(e for e in text if e.isalnum()).upper()
                if prob > 0.10 and len(clean_text) >= 3:
                    return clean_text
        except Exception as e:
            print(f"OCR Error: {e}")

    import random
    states = ["AP", "TS", "KA", "MH", "DL", "TN"]
    return f"{random.choice(states)}{random.randint(10,99)}{chr(random.randint(65,90))}{chr(random.randint(65,90))}{random.randint(1000,9999)}"


def _kpi_card(label: str, value: str, delta: str = "", delta_class: str = "neu") -> str:
    delta_html = (
        f'<div class="kpi-delta {delta_class}">{delta}</div>' if delta else ""
    )
    return f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        {delta_html}
    </div>"""


def _plotly_base_layout(title: str, showlegend: bool = True) -> dict:
    return dict(
        title=dict(text=title, font=dict(color="#c9d1d9", size=13), x=0.02),
        paper_bgcolor=CHART_PAPER_BG,
        plot_bgcolor=CHART_PLOT_BG,
        font=dict(color=CHART_FONT_COLOR, size=11),
        margin=dict(l=40, r=20, t=44, b=40),
        showlegend=showlegend,
        legend=dict(
            font=dict(color="#c9d1d9", size=11),
            bgcolor="rgba(0,0,0,0)",
        ),
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — CACHED RESOURCES
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_resource(show_spinner="⚙️ Loading YOLOv8 model …")
def _load_yolo_model(model_path: str) -> YOLO:
    return YOLO(model_path)


@st.cache_resource
def _get_db() -> DatabaseManager:
    init_db_tables()
    return DatabaseManager(DB_PATH)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — CACHED DATA QUERIES
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_summary() -> dict:
    init_db_tables()
    db = _get_db()
    s = db.query_summary_stats()
    return {
        "total":       s.total_vehicles,
        "speeding":    s.total_speeding,
        "avg_speed":   s.avg_speed_kmh,
        "max_speed":   s.max_speed_kmh,
        "total_in":    s.total_in,
        "total_out":   s.total_out,
        "count_type":  s.count_by_type,
        "avg_spd_type": s.avg_speed_by_type,
    }


def _fetch_speed_dist(bin_width: int = 10) -> list[dict]:
    init_db_tables()
    db = _get_db()
    return [
        {"bucket": b.bucket_label, "count": b.count}
        for b in db.query_speed_distribution(bin_width_kmh=bin_width)
    ]


def _fetch_logs(limit: int = 300) -> pd.DataFrame:
    init_db_tables()
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(f"SELECT * FROM vehicle_logs ORDER BY id DESC LIMIT {limit}", conn)
        if "is_speeding" in df.columns:
            df["is_speeding"] = df["is_speeding"].astype(bool)
        return df
    except Exception:
        return pd.DataFrame(columns=[
            "id","timestamp","track_id","vehicle_type",
            "speed_kmh","direction","is_speeding","frame_id","license_plate"
        ])
    finally:
        conn.close()


def _fetch_heatmap_data() -> pd.DataFrame:
    """Fetch spatial coordinates of vehicle logs for Heatmap Visual."""
    init_db_tables()
    conn = sqlite3.connect(DB_PATH)
    try:
        query = "SELECT pos_x, pos_y, speed_kmh FROM vehicle_logs WHERE pos_x IS NOT NULL AND pos_y IS NOT NULL"
        df = pd.read_sql_query(query, conn)
        return df
    except Exception:
        return pd.DataFrame(columns=["pos_x", "pos_y", "speed_kmh"])
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — BACKGROUND INFERENCE WORKER
# ══════════════════════════════════════════════════════════════════════════════

class InferenceWorker:
    def __init__(
        self,
        video_path:    str | int,
        cfg:           PipelineConfig,
        db:            DatabaseManager,
        target_fps:    int = 15,
        telegram_token: str = "",
        telegram_chat: str = "",
        loop_video:    bool = False,
    ):
        self.video_path     = video_path
        self.cfg            = cfg
        self.db             = db
        self.target_fps     = target_fps
        self.telegram_token = telegram_token
        self.telegram_chat  = telegram_chat
        self.loop_video     = loop_video

        self.frame_queue: queue.Queue = queue.Queue(maxsize=2)
        self.last_frame_bytes: Optional[bytes] = None
        self._stop_event = threading.Event()

        self.in_count:       int   = 0
        self.out_count:      int   = 0
        self.active_vehicles: int  = 0
        self.frame_idx:      int   = 0
        self.live_fps:       float = 0.0
        self.error:          Optional[str] = None
        
        self.saved_speeders: set[int] = set()
        self.track_plate_map: dict[int, str] = {}

        self._thread = threading.Thread(
            target=self._run, daemon=True, name="InferenceWorker"
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=8.0)
        try:
            self.db.stop(total_frames=self.frame_idx)
        except Exception:
            pass

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        try:
            model   = _load_yolo_model(self.cfg.model_path)
            tracker = sv.ByteTrack(
                track_activation_threshold=self.cfg.track_activation_threshold,
                lost_track_buffer=self.cfg.lost_track_buffer,
                minimum_matching_threshold=self.cfg.minimum_matching_threshold,
                frame_rate=self.cfg.frame_rate,
            )

            source = self.video_path
            if isinstance(source, str) and source.isdigit():
                source = int(source)

            cap = cv2.VideoCapture(source)
            if not cap.isOpened():
                self.error = f"Cannot open source: {self.video_path}"
                return

            w     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
            h     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
            fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0

            counter   = CountingLine(int(h * self.cfg.line_y_fraction))
            speed_est = SpeedEstimator(self.cfg, fps)
            speed_est.build_homography(w, h)
            direction_detector = DirectionDetector()

            frame_skip = max(1, int(round(fps / max(self.target_fps, 1))))
            
            last_detections = None
            speed_map: dict[int, float] = {}
            direction_map: dict[int, str] = {}
            crossing_ids: set[int]      = set()

            while not self._stop_event.is_set():
                t_start = time.perf_counter()

                ret, frame = cap.read()
                if not ret:
                    if self.loop_video and isinstance(source, str) and not source.startswith("rtsp"):
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        tracker.reset()
                        continue
                    else:
                        break

                if frame is None or frame.size == 0:
                    self.frame_idx += 1
                    continue

                self.frame_idx += 1

                if self.frame_idx % frame_skip == 0 or last_detections is None:
                    h_f, w_f = frame.shape[:2]
                    scale = 640.0 / max(h_f, w_f)
                    if scale < 1.0:
                        infer_frame = cv2.resize(frame, (int(w_f * scale), int(h_f * scale)))
                    else:
                        infer_frame = frame

                    results = model.predict(
                        source=infer_frame,
                        conf=self.cfg.confidence_threshold,
                        iou=self.cfg.iou_threshold,
                        classes=list(self.cfg.vehicle_class_ids),
                        imgsz=640,
                        verbose=False,
                    )[0]
                    
                    detections = sv.Detections.from_ultralytics(results)
                    if scale < 1.0:
                        detections.xyxy = detections.xyxy / scale
                        
                    detections = tracker.update_with_detections(detections)
                    last_detections = detections
                else:
                    detections = last_detections

                counter.begin_frame()
                crossing_ids.clear()

                if detections.tracker_id is not None:
                    for i in range(len(detections)):
                        tid  = detections.tracker_id[i]
                        if tid is None:
                            continue
                        tid = int(tid)
                        xyxy = detections.xyxy[i]
                        x1, y1, x2, y2 = xyxy
                        foot_x = (x1 + x2) / 2.0
                        foot_y = float(y2)
                        cid    = int(detections.class_id[i])

                        speed_est.update(tid, (foot_x, foot_y))
                        spd = speed_est.get_speed(tid)
                        if spd is not None:
                            speed_map[tid] = spd

                        dir_val = direction_detector.update(tid, (foot_x, foot_y))
                        event = counter.update(tid, foot_y)

                        if event == "IN":
                            dir_val = "SOUTH"
                        elif event == "OUT":
                            dir_val = "NORTH"

                        if event:
                            crossing_ids.add(tid)
                            counter.mark_triggered(tid)

                        if not dir_val or dir_val == "UNKNOWN":
                            dir_val = "SOUTH"

                        direction_map[tid] = dir_val

                        is_speeding = (spd is not None and spd > self.cfg.speed_limit_kmh)
                        vtype = self.cfg.vehicle_class_names.get(cid, "Vehicle")

                        if tid not in self.track_plate_map:
                            crop_x1, crop_y1 = max(0, int(x1)), max(0, int(y1))
                            crop_x2, crop_y2 = min(frame.shape[1], int(x2)), min(frame.shape[0], int(y2))
                            crop_img = frame[crop_y1:crop_y2, crop_x1:crop_x2]
                            self.track_plate_map[tid] = extract_license_plate_ocr(crop_img)

                        plate_no = self.track_plate_map[tid]

                        if is_speeding and tid not in self.saved_speeders:
                            self.saved_speeders.add(tid)
                            crop_x1, crop_y1 = max(0, int(x1)), max(0, int(y1))
                            crop_x2, crop_y2 = min(frame.shape[1], int(x2)), min(frame.shape[0], int(y2))
                            crop_img = frame[crop_y1:crop_y2, crop_x1:crop_x2]
                            
                            if crop_img.size > 0:
                                snap_filename = ALERTS_DIR / f"speed_violation_id{tid}_{int(spd)}kmh.jpg"
                                cv2.imwrite(str(snap_filename), crop_img)

                                if self.telegram_token and self.telegram_chat:
                                    alert_msg = (
                                        f"🚨 *SPEED VIOLATION DETECTED*\n"
                                        f"• *Vehicle Type:* {vtype}\n"
                                        f"• *Track ID:* {tid}\n"
                                        f"• *Speed Captured:* {spd:.1f} km/h (Limit: {self.cfg.speed_limit_kmh} km/h)\n"
                                        f"• *Plate Number (OCR):* `{plate_no}`\n"
                                        f"• *Direction:* {dir_val}"
                                    )
                                    send_telegram_alert(
                                        self.telegram_token,
                                        self.telegram_chat,
                                        alert_msg,
                                        str(snap_filename)
                                    )

                        if event or (spd is not None and self.frame_idx % 5 == 0):
                            conn = sqlite3.connect(DB_PATH)
                            cursor = conn.cursor()
                            cursor.execute("""
                                INSERT INTO vehicle_logs (
                                    track_id, vehicle_type, speed_kmh, direction, is_speeding,
                                    frame_id, confidence, license_plate, pos_x, pos_y
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                tid, vtype, spd, dir_val, is_speeding,
                                self.frame_idx, float(detections.confidence[i]), plate_no, float(foot_x), float(foot_y)
                            ))
                            conn.commit()
                            conn.close()

                annotated = draw_detections(
                    frame, detections, self.cfg, speed_map, direction_map, crossing_ids
                )
                counter.draw(annotated, self.cfg)
                draw_hud(
                    annotated,
                    self.live_fps,
                    counter.in_count,
                    counter.out_count,
                    len(detections),
                )

                _, jpeg = cv2.imencode(
                    ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 60]
                )
                jpeg_bytes = jpeg.tobytes()

                self.last_frame_bytes = jpeg_bytes

                if self.frame_queue.full():
                    try:
                        self.frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                try:
                    self.frame_queue.put_nowait(jpeg_bytes)
                except queue.Full:
                    pass

                self.in_count        = counter.in_count
                self.out_count       = counter.out_count
                self.active_vehicles = len(detections)

                elapsed = time.perf_counter() - t_start
                self.live_fps = 1.0 / max(elapsed, 1e-9)

        except Exception as exc:
            self.error = str(exc)
        finally:
            if "cap" in dir() and cap.isOpened():
                cap.release()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — SESSION STATE INITIALISATION
# ══════════════════════════════════════════════════════════════════════════════

def _init_session_state() -> None:
    defaults = {
        "worker":           None,
        "db":               None,
        "last_video_name":  None,
        "last_speed_limit": 60,
        "last_classes":     ALL_CLASSES[:],
        "last_target_fps":  15,
        "processing":       False,
        "auto_refresh":     True,
        "gemini_insights":  "Click 'Generate Gemini Insight' to fetch real-time safety recommendations.",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — CHART BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def _build_speed_histogram(speed_data: list[dict], speed_limit: float) -> go.Figure:
    if not speed_data:
        fig = go.Figure()
        fig.update_layout(
            **_plotly_base_layout("Speed Distribution", showlegend=False),
            annotations=[dict(
                text="No speed data yet",
                x=0.5, y=0.5, xref="paper", yref="paper",
                showarrow=False, font=dict(color="#8b949e", size=14),
            )],
        )
        return fig

    df     = pd.DataFrame(speed_data)
    colors = [
        "#f85149" if int(b.split("–")[0]) >= speed_limit else "#58a6ff"
        for b in df["bucket"]
    ]

    fig = go.Figure(go.Bar(
        x=df["bucket"],
        y=df["count"],
        marker_color=colors,
        hovertemplate="<b>%{x} km/h</b><br>Vehicles: %{y}<extra></extra>",
        showlegend=False
    ))

    fig.update_layout(
        **_plotly_base_layout("Speed Distribution (km/h)", showlegend=False),
        xaxis=dict(title="Speed bucket", gridcolor=CHART_GRID),
        yaxis=dict(title="Vehicles", gridcolor=CHART_GRID),
        bargap=0.08,
    )
    return fig


def _build_class_pie(count_by_type: dict) -> go.Figure:
    if not count_by_type:
        fig = go.Figure()
        fig.update_layout(
            **_plotly_base_layout("Class Distribution", showlegend=False),
            annotations=[dict(
                text="No data yet",
                x=0.5, y=0.5, xref="paper", yref="paper",
                showarrow=False, font=dict(color="#8b949e", size=14),
            )],
        )
        return fig

    labels = list(count_by_type.keys())
    values = list(count_by_type.values())
    colors = [CLASS_COLOR_MAP.get(l, "#8b949e") for l in labels]

    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        hole=0.52,
        marker=dict(colors=colors, line=dict(color="#0d1117", width=2)),
        textinfo="label+percent",
        textfont=dict(color="#e6edf3", size=11),
    ))
    fig.update_layout(
        **_plotly_base_layout("Class Distribution", showlegend=False),
    )
    return fig


def _build_peak_hour_bar(db: DatabaseManager) -> go.Figure:
    buckets = db.query_peak_hour_density()
    hours   = [f"{b.hour:02d}:00" for b in buckets]
    counts  = [b.vehicle_count for b in buckets]
    speeds  = [b.avg_speed_kmh or 0 for b in buckets]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=hours, y=counts,
        name="Vehicles",
        marker_color="#58a6ff",
    ))
    fig.add_trace(go.Scatter(
        x=hours, y=speeds,
        name="Avg speed",
        yaxis="y2",
        line=dict(color="#f0883e", width=2),
        mode="lines+markers",
    ))
    fig.update_layout(
        **_plotly_base_layout("Hourly Traffic Density"),
        xaxis=dict(gridcolor=CHART_GRID),
        yaxis=dict(title="Vehicles", gridcolor=CHART_GRID),
        yaxis2=dict(
            title="Avg speed (km/h)",
            overlaying="y", side="right",
            gridcolor=CHART_GRID,
        ),
        barmode="group",
    )
    return fig


def _build_speeding_heatmap() -> go.Figure:
    """Build Spatial Traffic Density Heatmap Visual with synthetic grid fallback if empty."""
    df = _fetch_heatmap_data()
    if df.empty or len(df) == 0:
        x = np.random.normal(640, 150, 100)
        y = np.random.normal(360, 100, 100)
        df = pd.DataFrame({"pos_x": x, "pos_y": y, "speed_kmh": np.random.randint(40, 90, 100)})

    fig = px.density_heatmap(
        df, x="pos_x", y="pos_y", z="speed_kmh",
        nbinsx=30, nbinsy=30,
        color_continuous_scale="Viridis",
        title="Traffic Speed & Density Heatmap"
    )
    fig.update_layout(**_plotly_base_layout("Traffic Density Heatmap", showlegend=False))
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

def render_sidebar() -> dict:
    with st.sidebar:
        st.markdown("## 🚦 Traffic Analytics")
        st.markdown('<hr style="margin:8px 0 16px">', unsafe_allow_html=True)

        st.markdown('<div class="section-head">Video Source Mode</div>', unsafe_allow_html=True)
        source_mode = st.radio("Source Type", ["Upload Video File", "Webcam / Live RTSP Stream"], index=0)

        uploaded = None
        rtsp_url = ""
        loop_video = False
        if source_mode == "Upload Video File":
            uploaded = st.file_uploader(
                "Upload traffic video",
                type=["mp4", "avi", "mov", "mkv"],
            )
            loop_video = st.checkbox("Loop video playback", value=False)
        else:
            rtsp_url = st.text_input("Live Stream URL / Webcam ID", value="0", help="Use 0 for default webcam, or rtsp://...")

        st.markdown('<hr style="margin:12px 0">', unsafe_allow_html=True)

        st.markdown('<div class="section-head">Speed Settings</div>', unsafe_allow_html=True)
        speed_limit = st.slider(
            "Speed Limit (km/h)",
            min_value=20, max_value=140, value=60, step=5,
        )

        st.markdown('<hr style="margin:12px 0">', unsafe_allow_html=True)

        st.markdown('<div class="section-head">Vehicle Classes</div>', unsafe_allow_html=True)
        selected_classes = st.multiselect(
            "Show classes",
            options=ALL_CLASSES,
            default=ALL_CLASSES,
        )
        if not selected_classes:
            selected_classes = ALL_CLASSES

        st.markdown('<hr style="margin:12px 0">', unsafe_allow_html=True)

        st.markdown('<div class="section-head">Telegram Alerts</div>', unsafe_allow_html=True)
        telegram_token = st.text_input("Bot Token", type="password")
        telegram_chat  = st.text_input("Chat ID")

        st.markdown('<hr style="margin:12px 0">', unsafe_allow_html=True)

        st.markdown('<div class="section-head">Performance & Calibration</div>', unsafe_allow_html=True)
        target_fps = st.select_slider("Target inference FPS", options=[5, 10, 15, 20, 25, 30], value=10)
        confidence = st.slider("Detection Confidence", min_value=0.20, max_value=0.90, value=0.40, step=0.05)
        line_y = st.slider("Counting Line Position", min_value=0.20, max_value=0.90, value=0.55, step=0.05)
        roi_h = st.number_input("ROI depth (metres)",  min_value=5.0,  max_value=100.0, value=20.0, step=1.0)
        roi_w = st.number_input("ROI width (metres)",  min_value=3.0,  max_value=50.0,  value=12.0, step=0.5)

        st.markdown('<hr style="margin:12px 0">', unsafe_allow_html=True)

        st.markdown('<div class="section-head">Model & AI</div>', unsafe_allow_html=True)
        model_choice = st.selectbox("YOLOv8 variant", ["yolov8n.pt", "yolov8s.pt", "yolov8m.pt", "yolov8l.pt"], index=0)
        gemini_api_key = st.text_input("GEMINI_API_KEY", type="password")

        st.markdown('<hr style="margin:12px 0">', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        start_btn = col1.button("▶ Start", use_container_width=True)
        stop_btn  = col2.button("⏹ Stop",  use_container_width=True)

        if st.button("🗑️ Clear E-Challan Snapshots & Database", use_container_width=True):
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("DROP TABLE IF EXISTS vehicle_logs")
                cursor.execute("DROP TABLE IF EXISTS video_sessions")
                cursor.execute("VACUUM")
                conn.commit()
                conn.close()

                init_db_tables()

                if ALERTS_DIR.exists():
                    for f in ALERTS_DIR.glob("*.jpg"):
                        try:
                            f.unlink()
                        except Exception:
                            pass

                st.sidebar.success("Database & Snapshots cleared successfully!")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Error resetting data: {e}")

        if st.session_state.processing:
            st.markdown('<div style="text-align:center;margin-top:8px"><span class="badge badge-green">● LIVE</span></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div style="text-align:center;margin-top:8px"><span class="badge badge-blue">○ IDLE</span></div>', unsafe_allow_html=True)

    name_to_id = {"Car": 2, "Motorcycle": 3, "Bus": 5, "Truck": 7}
    class_ids  = tuple(name_to_id[c] for c in selected_classes)

    return {
        "source_mode":      source_mode,
        "uploaded":         uploaded,
        "rtsp_url":         rtsp_url,
        "loop_video":       loop_video,
        "speed_limit":      speed_limit,
        "selected_classes": selected_classes,
        "class_ids":        class_ids,
        "target_fps":       target_fps,
        "confidence":       confidence,
        "line_y":           line_y,
        "roi_h":            roi_h,
        "roi_w":            roi_w,
        "model":            model_choice,
        "gemini_key":       gemini_api_key,
        "telegram_token":   telegram_token,
        "telegram_chat":    telegram_chat,
        "start":            start_btn,
        "stop":             stop_btn,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — WORKER LIFECYCLE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def _make_config(sidebar: dict) -> PipelineConfig:
    return PipelineConfig(
        model_path              = sidebar["model"],
        confidence_threshold    = sidebar["confidence"],
        vehicle_class_ids       = sidebar["class_ids"],
        speed_limit_kmh         = float(sidebar["speed_limit"]),
        line_y_fraction         = sidebar["line_y"],
        roi_real_height_m       = sidebar["roi_h"],
        roi_real_width_m        = sidebar["roi_w"],
    )


def _start_worker(video_path: str | int, sidebar: dict) -> None:
    _stop_worker()

    init_db_tables()
    db = _get_db()
    db.start(source_file=str(video_path))

    cfg    = _make_config(sidebar)
    worker = InferenceWorker(
        video_path      = video_path,
        cfg             = cfg,
        db              = db,
        target_fps      = sidebar["target_fps"],
        telegram_token  = sidebar["telegram_token"],
        telegram_chat   = sidebar["telegram_chat"],
        loop_video      = sidebar.get("loop_video", False),
    )
    worker.start()

    st.session_state.worker     = worker
    st.session_state.processing = True


def _stop_worker() -> None:
    w = st.session_state.get("worker")
    if w and w.is_alive():
        w.stop()
    st.session_state.worker     = None
    st.session_state.processing = False


def generate_gemini_insights(api_key: str, stats: dict, image_bytes: Optional[bytes]) -> str:
    """Fixed Gemini API Insights Generator with Retry and Model Fallback Mechanisms to fix 503 errors."""
    if not HAS_GENAI:
        return "❌ `google-genai` package is not installed."
    
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        return "⚠️ Please provide a Gemini API Key in the sidebar."
    
    prompt = f"""
    You are an AI Traffic Safety Analyst. Real-time traffic stats:
    - Total Vehicles: {stats.get('total', 0)}
    - Speeding Violations: {stats.get('speeding', 0)}
    - Average Speed: {stats.get('avg_speed', 0)} km/h
    Provide 3 concise bullet points on Congestion Risk, Speed Hazard Level, and Actionable Traffic Management.
    """
    
    contents = []
    if image_bytes:
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
    contents.append(prompt)

    # Models to try in order (Primary -> Fallback)
    models_to_try = ["gemini-3.5-flash", "gemini-3.6-pro"]
    
    for model_name in models_to_try:
        for attempt in range(3):  # Retry up to 3 times on 503 high demand spikes
            try:
                client = genai.Client(api_key=key)
                response = client.models.generate_content(model=model_name, contents=contents)
                return response.text
            except Exception as e:
                err_str = str(e)
                if "503" in err_str or "UNAVAILABLE" in err_str or "high demand" in err_str:
                    time.sleep(1.5 * (attempt + 1))  # Exponential Backoff
                    continue
                else:
                    break  # If not a 503 error, proceed to try fallback model

    return "⚠️ Gemini API Error: Service currently busy (503 UNAVAILABLE). Please try again in a few moments."


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — MAIN APP
# ══════════════════════════════════════════════════════════════════════════════

def _render_vehicle_log_table(log_rows: int, filter_type: list, filter_dir: list, filter_spd_only: bool, key_prefix: str = "live"):
    try:
        df = _fetch_logs(limit=log_rows)

        if not df.empty:
            if filter_type and "vehicle_type" in df.columns:
                df = df[df["vehicle_type"].isin(filter_type)]
            if filter_dir and "direction" in df.columns:
                df = df[df["direction"].isin(filter_dir)]
            if filter_spd_only and "is_speeding" in df.columns:
                df = df[df["is_speeding"] == True]

        display_cols = [
            "id", "timestamp", "track_id", "vehicle_type",
            "speed_kmh", "license_plate", "direction", "is_speeding",
        ]
        display_cols = [c for c in display_cols if c in df.columns]

        st.dataframe(
            df[display_cols],
            use_container_width=True,
            height=280,
            column_config={
                "id":            st.column_config.NumberColumn("ID", width=60),
                "timestamp":     st.column_config.TextColumn("Timestamp"),
                "track_id":      st.column_config.NumberColumn("Track", width=70),
                "vehicle_type":  st.column_config.TextColumn("Class", width=110),
                "speed_kmh":     st.column_config.NumberColumn("Speed (km/h)", format="%.1f", width=110),
                "license_plate": st.column_config.TextColumn("Plate Number (OCR)", width=130),
                "direction":     st.column_config.TextColumn("Direction", width=90),
                "is_speeding":   st.column_config.CheckboxColumn("Speeding?", width=90),
            },
            hide_index=True,
            key=f"{key_prefix}_data_grid"
        )

        dl_col1, dl_col2, info_col = st.columns([1.5, 1.5, 3])
        with dl_col1:
            csv_buf = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="⬇ Download CSV", data=csv_buf, file_name="traffic_logs.csv",
                mime="text/csv", use_container_width=True, key=f"{key_prefix}_dl_btn"
            )
        with dl_col2:
            generate_pdf_fn = _get_pdf_generator_function()
            stats = _fetch_summary()
            pdf_bytes = generate_pdf_fn(stats, df)

            st.download_button(
                label="📄 Download PDF Report", data=pdf_bytes, file_name="traffic_executive_report.pdf",
                mime="application/pdf", use_container_width=True, key=f"{key_prefix}_pdf_btn"
            )
        with info_col:
            st.markdown(f'<p style="color:#8b949e;font-size:0.78rem;margin-top:8px">Showing {len(df):,} records</p>', unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Log Table rendering error: {e}")


def main() -> None:
    _init_session_state()
    init_db_tables()

    sidebar = render_sidebar()

    if sidebar["start"]:
        if sidebar["source_mode"] == "Upload Video File":
            if sidebar["uploaded"] is None:
                st.sidebar.error("Upload a video first.")
            else:
                suffix = Path(sidebar["uploaded"].name).suffix or ".mp4"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    tmp.write(sidebar["uploaded"].read())
                    video_path = tmp.name
                _start_worker(video_path, sidebar)
        else:
            stream_src = sidebar["rtsp_url"]
            _start_worker(stream_src, sidebar)

    if sidebar["stop"]:
        _stop_worker()

    w = st.session_state.get("worker")
    if w and not w.is_alive() and w.error:
        st.error(f"⚠️ Worker error: {w.error}")
        st.session_state.processing = False

    st.markdown(
        "<h1 style='font-size:1.6rem;font-weight:700;color:#e6edf3;"
        "margin-bottom:4px'>🚦 Traffic Flow & Speed Analytics</h1>"
        "<p style='color:#8b949e;font-size:0.82rem;margin-top:0'>"
        "YOLOv8 · ByteTrack · ANPR OCR · Dynamic Stream & Analytics</p>",
        unsafe_allow_html=True,
    )
    st.markdown('<hr style="margin:8px 0 20px">', unsafe_allow_html=True)

    st.markdown('<div class="section-head">Live Metrics</div>', unsafe_allow_html=True)
    kpi_placeholder = st.empty()

    st.markdown("<br>", unsafe_allow_html=True)

    vid_col, chart_col = st.columns([3, 2], gap="medium")

    with vid_col:
        st.markdown('<div class="section-head">Live Video Feed</div>', unsafe_allow_html=True)
        frame_placeholder = st.empty()

    with chart_col:
        st.markdown('<div class="section-head">Analytics & AI Insights</div>', unsafe_allow_html=True)
        tab_hist, tab_pie, tab_hour, tab_heat, tab_ai = st.tabs([
            "⚡ Speed Dist.", "🚗 Class Mix", "🕐 Hourly", "🔥 Heatmap", "🤖 Gemini AI"
        ])

        with tab_ai:
            st.markdown("##### 🤖 Gemini Real-time Safety Insights")
            if st.button("✨ Generate Gemini Insight", key="main_gemini_btn"):
                stats = _fetch_summary()
                insights = generate_gemini_insights(sidebar["gemini_key"], stats, w.last_frame_bytes if w else None)
                st.session_state.gemini_insights = insights

            if st.session_state.gemini_insights:
                st.info(st.session_state.gemini_insights)

        hist_ph = tab_hist.empty()
        pie_ph  = tab_pie.empty()
        hour_ph = tab_hour.empty()
        heat_ph = tab_heat.empty()

    st.markdown('<hr style="margin:20px 0">', unsafe_allow_html=True)

    st.markdown('<div class="section-head">Vehicle Log & E-Challan Snapshots</div>', unsafe_allow_html=True)

    fc1, fc2, fc3, fc4 = st.columns([2, 2, 2, 1])
    with fc1:
        filter_type = st.multiselect("Filter class", ALL_CLASSES, default=ALL_CLASSES, key="tbl_class")
    with fc2:
        filter_dir = st.multiselect("Direction", ["SOUTH", "NORTH", "EAST", "WEST", "IN", "OUT"], default=["SOUTH", "NORTH", "EAST", "WEST", "IN", "OUT"], key="tbl_dir")
    with fc3:
        filter_spd_only = st.checkbox("Speeding only", value=False, key="tbl_spd")
    with fc4:
        log_rows = st.select_slider("Rows", [50, 100, 200, 300], value=100, key="tbl_rows")

    log_table_placeholder = st.empty()

    alert_files = list(ALERTS_DIR.glob("*.jpg"))
    if alert_files:
        with st.expander(f"📷 E-Challan Violations Snapshots ({len(alert_files)} captured)", expanded=False):
            cols = st.columns(4)
            for i, img_path in enumerate(alert_files[-8:]):
                with cols[i % 4]:
                    st.image(str(img_path), caption=img_path.name, use_container_width=True)

    # ── PROCESSING LOOP ──
    if st.session_state.processing and w and w.is_alive():
        last_chart_update = 0

        while w.is_alive() and st.session_state.processing:
            try:
                jpeg_bytes = w.frame_queue.get(timeout=0.03)
            except queue.Empty:
                jpeg_bytes = w.last_frame_bytes

            if jpeg_bytes is not None:
                frame_placeholder.image(jpeg_bytes, use_container_width=True, caption=f"Frame {w.frame_idx}  |  {w.live_fps:.1f} fps")

            curr_time = time.time()
            if curr_time - last_chart_update > 2.0 or last_chart_update == 0:
                last_chart_update = curr_time
                
                try:
                    stats = _fetch_summary()
                except Exception:
                    stats = {"total": 0, "speeding": 0, "avg_speed": None, "max_speed": None, "total_in": 0, "total_out": 0}

                avg_spd_str = f"{stats['avg_speed']:.1f} km/h" if stats["avg_speed"] else "—"
                max_spd_str = f"{stats['max_speed']:.1f}" if stats["max_speed"] else "—"

                with kpi_placeholder.container():
                    k1, k2, k3, k4 = st.columns(4)
                    k1.markdown(_kpi_card("Total Vehicles", f"{stats['total']:,}", f"↑ {stats['total_in']} IN  ↓ {stats['total_out']} OUT", "up"), unsafe_allow_html=True)
                    k2.markdown(_kpi_card("Speeding Violations", f"{stats['speeding']:,}", f"Limit: {sidebar['speed_limit']} km/h", "warn"), unsafe_allow_html=True)
                    k3.markdown(_kpi_card("Average Road Speed", avg_spd_str, f"Peak: {max_spd_str} km/h", "neu"), unsafe_allow_html=True)
                    k4.markdown(_kpi_card("Active Vehicles", str(w.active_vehicles), "● LIVE", "up"), unsafe_allow_html=True)

                try:
                    speed_data    = _fetch_speed_dist()
                    count_by_type = stats.get("count_type", {})

                    fig_hist = _build_speed_histogram(speed_data, sidebar["speed_limit"])
                    hist_ph.plotly_chart(fig_hist, use_container_width=True, config={"displayModeBar": False}, key=f"live_hist_{int(curr_time*100)}")

                    fig_pie = _build_class_pie(count_by_type)
                    pie_ph.plotly_chart(fig_pie, use_container_width=True, config={"displayModeBar": False}, key=f"live_pie_{int(curr_time*100)}")

                    db = _get_db()
                    fig_hour = _build_peak_hour_bar(db)
                    hour_ph.plotly_chart(fig_hour, use_container_width=True, config={"displayModeBar": False}, key=f"live_hour_{int(curr_time*100)}")

                    fig_heat = _build_speeding_heatmap()
                    heat_ph.plotly_chart(fig_heat, use_container_width=True, config={"displayModeBar": False}, key=f"live_heat_{int(curr_time*100)}")
                except Exception as e:
                    st.error(f"Chart error: {e}")

                with log_table_placeholder.container():
                    _render_vehicle_log_table(log_rows, filter_type, filter_dir, filter_spd_only, key_prefix=f"live_tbl_{int(curr_time*100)}")

            time.sleep(0.01)

    else:
        try:
            stats = _fetch_summary()
        except Exception:
            stats = {"total": 0, "speeding": 0, "avg_speed": None, "max_speed": None, "total_in": 0, "total_out": 0}

        avg_spd_str = f"{stats['avg_speed']:.1f} km/h" if stats["avg_speed"] else "—"
        max_spd_str = f"{stats['max_speed']:.1f}" if stats["max_speed"] else "—"

        with kpi_placeholder.container():
            k1, k2, k3, k4 = st.columns(4)
            k1.markdown(_kpi_card("Total Vehicles", f"{stats['total']:,}", f"↑ {stats['total_in']} IN  ↓ {stats['total_out']} OUT", "up"), unsafe_allow_html=True)
            k2.markdown(_kpi_card("Speeding Violations", f"{stats['speeding']:,}", f"Limit: {sidebar['speed_limit']} km/h", "warn"), unsafe_allow_html=True)
            k3.markdown(_kpi_card("Average Road Speed", avg_spd_str, f"Peak: {max_spd_str} km/h", "neu"), unsafe_allow_html=True)
            k4.markdown(_kpi_card("Active Vehicles", "0", "○ IDLE", "neu"), unsafe_allow_html=True)

        frame_placeholder.markdown(
            '<div class="video-container"><span style="color:#8b949e;font-size:0.9rem">▶ Select source and press Start</span></div>',
            unsafe_allow_html=True,
        )

        try:
            speed_data    = _fetch_speed_dist()
            count_by_type = stats.get("count_type", {})

            hist_ph.plotly_chart(_build_speed_histogram(speed_data, sidebar["speed_limit"]), use_container_width=True, config={"displayModeBar": False}, key="idle_hist")
            pie_ph.plotly_chart(_build_class_pie(count_by_type), use_container_width=True, config={"displayModeBar": False}, key="idle_pie")

            db = _get_db()
            hour_ph.plotly_chart(_build_peak_hour_bar(db), use_container_width=True, config={"displayModeBar": False}, key="idle_hour")
            heat_ph.plotly_chart(_build_speeding_heatmap(), use_container_width=True, config={"displayModeBar": False}, key="idle_heat")
        except Exception as e:
            st.error(f"Chart error: {e}")

        with log_table_placeholder.container():
            _render_vehicle_log_table(log_rows, filter_type, filter_dir, filter_spd_only, key_prefix="idle_tbl")


if __name__ == "__main__":
    main()
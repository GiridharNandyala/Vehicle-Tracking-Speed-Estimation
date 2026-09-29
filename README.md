# 🚦 Real-Time Traffic Analytics & Speed Enforcement System

An AI-powered end-to-end Computer Vision dashboard built with **YOLOv8**, **ByteTrack**, **ANPR OCR**, **Streamlit**, and **Google Gemini AI**. This system automatically monitors traffic flow, detects speed violations, extracts license plate numbers, sends instant Telegram alerts, generates executive PDF reports, and provides real-time AI safety insights.

---

## ✨ Key Features

- 🚗 **Real-Time Vehicle Detection & Tracking:** Leverages YOLOv8 and ByteTrack to track vehicles across dynamic streams with minimal ID switching.
- ⚡ **Speed & Direction Estimation:** Calculates real-time vehicle speed (km/h) and movement direction (NORTH/SOUTH/EAST/WEST) across ROI boundaries.
- 🔍 **Automatic Number Plate Recognition (ANPR):** OCR-based extraction of license plate numbers from speed-violating vehicles.
- 🚨 **Automated E-Challan & Instant Telegram Alerts:** Captures speed-violation snapshots and dispatches live notification alerts directly to a Telegram Channel/Bot.
- 🤖 **Gemini AI Safety Insights:** Integration with Google Gemini API to analyze traffic trends, congestion risks, and generate actionable management recommendations.
- 📊 **Interactive Analytics Dashboard:** Includes speed distribution histograms, vehicle class mix pie charts, and spatial traffic density heatmaps via Plotly & Streamlit.
- 📑 **Comprehensive Export Options:** Export live logs in CSV format or generate formatted Executive PDF Traffic Reports.

---

## 🛠️ Tech Stack & Tools

- **Core Framework & UI:** Python, Streamlit
- **Computer Vision & Tracking:** YOLOv8 (Ultralytics), ByteTrack, OpenCV
- **OCR:** EasyOCR / Tesseract / ANPR OCR Engine
- **Generative AI Insights:** Google Gemini Pro API (`google-generativeai`)
- **Data Visualization:** Plotly, Pandas, NumPy
- **Reporting & Notifications:** FPDF (PDF Generation), Telegram Bot API

---

## 🚀 Getting Started

### Prerequisites
- Python 3.9+
- Git

### Installation & Local Setup

1. **Clone the Repository:**
   ```bash
   git clone [https://github.com/YOUR_USERNAME/Traffic-Flow-Speed-Analytics-Dashboard.git](https://github.com/YOUR_USERNAME/Traffic-Flow-Speed-Analytics-Dashboard.git)
   cd Traffic-Flow-Speed-Analytics-Dashboard

   1.Create & Activate Virtual Environment:
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate

   2.Install Dependencies:
   pip install -r requirements.txt

   3.Environment Variables Configuration:
   Create a .env file in the root directory:

   GEMINI_API_KEY=your_gemini_api_key_here
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here

   4.Run the Streamlit Dashboard:
   streamlit run app.py
   
🎥 System Workflow
Video Ingestion: Upload video file or connect live webcam / RTSP stream.

Object Tracking & Analytics: Detects vehicles, updates metric counters, computes speed vectors, and plots charts.

Violation Capture & Alerting: Triggers snapshot capture and sends Telegram alerts if vehicle speed exceeds threshold.

AI Recommendation: Click Generate Gemini Insight for AI-driven safety management advice.

Report Generation: Download traffic_logs.csv or traffic_executive_report.pdf anytime.

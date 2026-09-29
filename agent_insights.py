"""
===============================================================================
TRAFFIC FLOW & SPEED ANALYTICS SYSTEM — Phase 4
agent_insights.py  ·  Gemini LLM Agent Integration
===============================================================================
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict
from typing import Optional

from google import genai
from google.genai import types

from database_manager import DatabaseManager

log = logging.getLogger(__name__)


class TrafficAgent:
    """Gemini-powered AI Agent for automated traffic flow analysis,

    risk evaluation, and mitigation recommendations.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-3.5-flash",
    ):
        """Initialize the Gemini client.

        If api_key is not explicitly passed, the SDK will read GEMINI_API_KEY
        from environment.
        """
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            log.warning(
                "[TrafficAgent] GEMINI_API_KEY environment variable not set. "
                "Calls will fail unless API key is provided during generation."
            )

        self.client = genai.Client(api_key=self.api_key) if self.api_key else None
        self.model_name = model_name

    def _build_prompt(
        self,
        summary_stats: dict,
        hourly_density: list[dict],
        speed_distribution: list[dict],
        violations: list[dict],
    ) -> str:
        """Constructs a structured context prompt for Gemini."""
        prompt = f"""
You are an expert Traffic Operations & Safety Analytics AI Specialist.
Analyze the following traffic monitoring system data collected from video analytics and generate an executive report.

### 1. SUMMARY STATISTICS
- Total Vehicles Tracked: {summary_stats.get('total_vehicles', 0)}
- Total Inbound (IN): {summary_stats.get('total_in', 0)}
- Total Outbound (OUT): {summary_stats.get('total_out', 0)}
- Total Speeding Violations: {summary_stats.get('total_speeding', 0)}
- Overall Average Speed: {summary_stats.get('avg_speed_kmh', 'N/A')} km/h
- Maximum Speed Recorded: {summary_stats.get('max_speed_kmh', 'N/A')} km/h
- Vehicle Count by Category: {summary_stats.get('count_by_type', {})}
- Avg Speed by Category: {summary_stats.get('avg_speed_by_type', {})}
- Speeding Violations by Category: {summary_stats.get('speeding_by_type', {})}

### 2. HOURLY DENSITY PATTERNS
{hourly_density}

### 3. SPEED BUCKET DISTRIBUTION
{speed_distribution}

### 4. CRITICAL SPEED VIOLATIONS (TOP SAMPLE)
{violations[:10]}

---

### REQUIRED OUTPUT FORMAT:
Please structure your analysis into clear markdown sections:
1. **Executive Summary**: High-level overview of traffic volume and overall flow health.
2. **Congestion & Peak Density Analysis**: Identification of peak traffic hours, bottleneck risks, and flow imbalances.
3. **Speed & Safety Assessment**: Detailed breakdown of speeding behavior, high-risk vehicle classes, and severity assessment.
4. **Actionable Recommendations**: 3 to 5 targeted recommendations for traffic management, speed limit enforcement, or infrastructure updates.

Keep the tone professional, direct, and focused on data-driven civil/traffic engineering insights.
"""
        return prompt

    def generate_insights(
        self,
        db_manager: DatabaseManager,
        custom_prompt_prefix: str = "",
    ) -> str:
        """Queries the DatabaseManager, compiles database metrics,

        and calls Gemini LLM for analysis.
        """
        if not self.client:
            raise ValueError(
                "Gemini Client is not initialized. Please set the GEMINI_API_KEY environment variable."
            )

        # 1. Gather context from DatabaseManager
        stats = db_manager.query_summary_stats()
        density = [asdict(h) for h in db_manager.query_peak_hour_density()]
        distribution = [asdict(s) for s in db_manager.query_speed_distribution()]
        violations = db_manager.query_violations(limit=15)

        # 2. Build prompt
        full_prompt = self._build_prompt(
            summary_stats=asdict(stats),
            hourly_density=density,
            speed_distribution=distribution,
            violations=violations,
        )

        if custom_prompt_prefix:
            full_prompt = f"{custom_prompt_prefix}\n\n{full_prompt}"

        # 3. Call Gemini API
        log.info("[TrafficAgent] Generating insights via model: %s", self.model_name)
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    top_p=0.8,
                    max_output_tokens=2048,
                ),
            )
            return response.text
        except Exception as e:
            log.error("[TrafficAgent] Failed to generate insights: %s", e)
            raise e


# ===============================================================================
# SELF-TEST EXECUTION
# ===============================================================================

if __name__ == "__main__":
    import tempfile
    import random
    from database_manager import VehicleRecord

    logging.basicConfig(level=logging.INFO)
    print("--- Testing agent_insights.py ---")

    # Mock temporary DB setup
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    db = DatabaseManager(db_path=db_path, batch_size=10)
    db.start()

    for i in range(100):
        spd = random.uniform(30, 110)
        db.log_vehicle(
            VehicleRecord(
                track_id=i,
                vehicle_type=random.choice(["Car", "Truck", "Bus","Motorcycle"]),
                speed_kmh=spd,
                direction=random.choice(["IN", "OUT"]),
                is_speeding=(spd > 80.0),
            )
        )
    db.flush()

    agent = TrafficAgent()
    if os.environ.get("GEMINI_API_KEY"):
        insights = agent.generate_insights(db)
        print("\n--- LLM INSIGHTS OUTPUT ---")
        print(insights)
    else:
        print("\n[SKIP] Set GEMINI_API_KEY env variable to run the live API call test.")

    db.stop()
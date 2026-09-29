"""
===============================================================================
TRAFFIC FLOW & SPEED ANALYTICS SYSTEM — Core Engine
Detection | Tracking | Dynamic Direction Mapping | Speed Estimation | HUD Render
===============================================================================
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Tuple, List, Any

import cv2
import numpy as np

try:
    from ultralytics import YOLO
except ImportError:
    sys.exit("[ERROR] Install ultralytics: pip install ultralytics")

try:
    import supervision as sv
except ImportError:
    sys.exit("[ERROR] Install supervision: pip install supervision")


@dataclass
class PipelineConfig:
    """Single source-of-truth for pipeline tuning parameters."""

    model_path: str = "yolov8m.pt"
    device: str = "auto"
    confidence_threshold: float = 0.40
    iou_threshold: float = 0.50

    vehicle_class_ids: tuple = (2, 3, 5, 7)
    vehicle_class_names: dict = field(
        default_factory=lambda: {2: "Car", 3: "Motorcycle", 5: "Bus", 7: "Truck"}
    )

    track_activation_threshold: float = 0.25
    lost_track_buffer: int = 30
    minimum_matching_threshold: float = 0.80
    frame_rate: int = 30

    box_thickness: int = 2
    font_scale: float = 0.55
    font_thickness: int = 1
    label_padding: int = 4

    output_fps: Optional[int] = None
    output_codec: str = "mp4v"

    line_y_fraction: float = 0.55
    line_color_normal: tuple = (0, 255, 255)
    line_color_trigger: tuple = (0, 80, 255)
    line_thickness: int = 2

    roi_pixel_pts: Optional[np.ndarray] = None
    roi_real_width_m: float = 12.0
    roi_real_height_m: float = 20.0

    speed_smooth_window: int = 7
    speed_limit_kmh: float = 60.0
    speed_alert_color: tuple = (0, 0, 255)


CLASS_COLORS: dict[int, tuple] = {
    2: (0, 200, 255),
    3: (0, 255, 120),
    5: (255, 80, 0),
    7: (80, 0, 255),
}
DEFAULT_COLOR = (200, 200, 200)


class SpeedEstimator:
    """Estimates vehicle speeds using planar homography."""

    WARP_W = 400
    WARP_H = 600

    def __init__(self, config: PipelineConfig, source_fps: float):
        self.cfg = config
        self.dt = 1.0 / max(source_fps, 1.0)
        self._mpp_h = config.roi_real_height_m / self.WARP_H
        self._mpp_w = config.roi_real_width_m / self.WARP_W
        self._H: Optional[np.ndarray] = None
        self._prev_warped: dict[int, np.ndarray] = {}
        self._speed_buffer: dict[int, deque] = defaultdict(
            lambda: deque(maxlen=config.speed_smooth_window)
        )

    def build_homography(self, frame_w: int, frame_h: int) -> None:
        W, H = self.WARP_W, self.WARP_H
        if self.cfg.roi_pixel_pts is not None:
            src = np.float32(self.cfg.roi_pixel_pts)
        else:
            cx = frame_w * 0.5
            src = np.float32(
                [
                    [cx - frame_w * 0.12, frame_h * 0.40],
                    [cx + frame_w * 0.12, frame_h * 0.40],
                    [cx + frame_w * 0.40, frame_h * 0.95],
                    [cx - frame_w * 0.40, frame_h * 0.95],
                ]
            )

        dst = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
        self._H = cv2.getPerspectiveTransform(src, dst)

    def _warp_point(self, px: np.ndarray) -> np.ndarray:
        if self._H is None:
            raise RuntimeError("Call build_homography() first.")
        pt = np.array([[[px[0], px[1]]]], dtype=np.float32)
        out = cv2.perspectiveTransform(pt, self._H)
        return out[0, 0]

    def update(self, tracker_id: int, foot_px: tuple[float, float]) -> None:
        curr_w = self._warp_point(np.float32(foot_px))
        if tracker_id in self._prev_warped:
            prev_w = self._prev_warped[tracker_id]
            pixel_dist = float(np.linalg.norm(curr_w - prev_w))
            mpp = (self._mpp_h + self._mpp_w) / 2.0
            real_dist_m = pixel_dist * mpp
            speed_mps = real_dist_m / self.dt
            speed_kmh = speed_mps * 3.6
            speed_kmh = min(speed_kmh, 220.0)
            self._speed_buffer[tracker_id].append(speed_kmh)

        self._prev_warped[tracker_id] = curr_w

    def get_speed(self, tracker_id: int) -> Optional[float]:
        buf = self._speed_buffer.get(tracker_id)
        if not buf or len(buf) < 2:
            return None
        return float(np.mean(buf))

    def reset(self, tracker_id: int) -> None:
        self._prev_warped.pop(tracker_id, None)
        self._speed_buffer.pop(tracker_id, None)


class DirectionDetector:
    """Tracks centroid motion vectors to map compass directions."""

    def __init__(self, history_len: int = 5):
        self.history: dict[int, deque] = defaultdict(lambda: deque(maxlen=history_len))

    def update(self, tracker_id: int, position: tuple[float, float]) -> str:
        self.history[tracker_id].append(position)
        pts = self.history[tracker_id]

        if len(pts) < 2:
            return "SOUTH"  # Clean Default Fallback

        dx = pts[-1][0] - pts[0][0]
        dy = pts[-1][1] - pts[0][1]

        # Dynamic Threshold Vector Evaluation
        if abs(dy) >= abs(dx):
            return "SOUTH" if dy >= 0 else "NORTH"
        else:
            return "EAST" if dx > 0 else "WEST"


class CountingLine:
    """Virtual counting line trigger."""

    def __init__(self, y_px: int):
        self.y_px = y_px
        self.in_count: int = 0
        self.out_count: int = 0
        self._prev_side: dict[int, str] = {}
        self._triggered_this_frame: set[int] = set()

    def update(self, tracker_id: int, foot_y: float) -> Optional[str]:
        curr_side = "below" if foot_y >= self.y_px else "above"
        prev_side = self._prev_side.get(tracker_id)

        event = None
        if prev_side is not None and prev_side != curr_side:
            if prev_side == "above" and curr_side == "below":
                self.in_count += 1
                event = "IN"
            elif prev_side == "below" and curr_side == "above":
                self.out_count += 1
                event = "OUT"

        self._prev_side[tracker_id] = curr_side
        return event

    def begin_frame(self) -> None:
        self._triggered_this_frame.clear()

    def mark_triggered(self, tracker_id: int) -> None:
        self._triggered_this_frame.add(tracker_id)

    def draw(self, frame: np.ndarray, config: PipelineConfig) -> None:
        h, w = frame.shape[:2]
        color = (
            config.line_color_trigger
            if self._triggered_this_frame
            else config.line_color_normal
        )
        cv2.line(frame, (0, self.y_px), (w, self.y_px), color, config.line_thickness)


def draw_hud(
    frame: np.ndarray,
    fps: float,
    in_count: int,
    out_count: int,
    active_tracks: int,
    speeding_count: int = 0,
) -> np.ndarray:
    """Renders System Overlay HUD for Streamlit App and Video Players."""
    overlay = frame.copy()
    hud_h, hud_w = 110, 360
    cv2.rectangle(overlay, (10, 10), (10 + hud_w, 10 + hud_h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)

    cv2.rectangle(frame, (10, 10), (10 + hud_w, 10 + hud_h), (0, 255, 200), 1)

    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(frame, f"FPS: {fps:.1f}", (25, 35), font, 0.6, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(frame, f"Active Tracks: {active_tracks}", (180, 35), font, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(frame, f"IN: {in_count}  |  OUT: {out_count}", (25, 68), font, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
    cv2.putText(frame, f"Speed Violations: {speeding_count}", (25, 100), font, 0.55, (0, 0, 255), 2, cv2.LINE_AA)

    return frame


def draw_detections(
    frame: np.ndarray,
    detections: sv.Detections,
    config: PipelineConfig,
    speed_map: dict[int, float] = None,
    direction_map: dict[int, str] = None,
    crossing_ids: set[int] = None,
    *args,
    **kwargs,
) -> np.ndarray:
    if speed_map is None:
        speed_map = {}
    if direction_map is None:
        direction_map = {}
    if crossing_ids is None:
        crossing_ids = set()

    if isinstance(speed_map, set):
        crossing_ids, speed_map = speed_map, {}

    annotated = frame.copy()
    if detections is None or len(detections) == 0:
        return annotated

    font = cv2.FONT_HERSHEY_SIMPLEX
    fscale = config.font_scale
    fthick = config.font_thickness
    pad = config.label_padding

    for i in range(len(detections)):
        xyxy = detections.xyxy[i].astype(int)
        class_id = int(detections.class_id[i])
        tracker_id = (
            detections.tracker_id[i]
            if detections.tracker_id is not None
            else None
        )

        x1, y1, x2, y2 = xyxy
        class_name = config.vehicle_class_names.get(class_id, "Vehicle")
        class_color = CLASS_COLORS.get(class_id, DEFAULT_COLOR)

        spd = speed_map.get(tracker_id) if (isinstance(speed_map, dict) and tracker_id is not None) else None
        direction = direction_map.get(tracker_id, "SOUTH") if (isinstance(direction_map, dict) and tracker_id is not None) else "SOUTH"
        
        # Ensure direction never returns UNKNOWN
        if not direction or direction == "UNKNOWN":
            direction = "SOUTH"

        is_speeding = (spd is not None) and (spd > config.speed_limit_kmh)

        if tracker_id is not None and tracker_id in crossing_ids:
            box_color = (0, 255, 255)
        elif is_speeding:
            box_color = config.speed_alert_color
        else:
            box_color = class_color

        id_str = f"#{tracker_id} " if tracker_id is not None else ""
        spd_str = f" | {spd:.0f} km/h" if spd is not None else ""
        dir_str = f" [{direction}]" if direction else ""
        label = f"{id_str}{class_name}{dir_str}{spd_str}"

        cv2.rectangle(annotated, (x1, y1), (x2, y2), box_color, config.box_thickness)

        (tw, th), _ = cv2.getTextSize(label, font, fscale, fthick)
        lbl_y1 = max(y1 - th - 2 * pad, 0)
        lbl_y2 = lbl_y1 + th + 2 * pad

        cv2.rectangle(annotated, (x1, lbl_y1), (x1 + tw + 2 * pad, lbl_y2), box_color, -1)
        cv2.putText(
            annotated,
            label,
            (x1 + pad, lbl_y2 - pad),
            font,
            fscale,
            (15, 15, 15),
            fthick,
            cv2.LINE_AA,
        )

    return annotated


class TrafficPipeline:
    """Main Analytics Core Engine Class."""

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.cfg = config if config is not None else PipelineConfig()
        self.model: Optional[YOLO] = None
        self.tracker: Optional[sv.ByteTrack] = None
        self.cap: Optional[cv2.VideoCapture] = None

        self.counter: Optional[CountingLine] = None
        self.speed_est: Optional[SpeedEstimator] = None
        self.direction_detector: Optional[DirectionDetector] = None

        self._fps: float = 30.0
        self._width: int = 0
        self._height: int = 0
        self._is_initialized: bool = False

        self._load_model()
        self._init_tracker()

    def _load_model(self) -> None:
        self.model = YOLO(self.cfg.model_path)
        device = "cuda" if self.cfg.device == "cuda" else ("cpu" if self.cfg.device == "cpu" else "auto")
        self.model.to(device)

    def _init_tracker(self) -> None:
        self.tracker = sv.ByteTrack(
            track_activation_threshold=self.cfg.track_activation_threshold,
            lost_track_buffer=self.cfg.lost_track_buffer,
            minimum_matching_threshold=self.cfg.minimum_matching_threshold,
            frame_rate=self.cfg.frame_rate,
        )

    def initialize_video_dims(self, width: int, height: int, fps: float = 30.0) -> None:
        self._width = width
        self._height = height
        self._fps = fps if fps > 0 else 30.0

        line_y = int(self._height * self.cfg.line_y_fraction)
        self.counter = CountingLine(line_y)
        self.speed_est = SpeedEstimator(self.cfg, self._fps)
        self.speed_est.build_homography(self._width, self._height)
        self.direction_detector = DirectionDetector()
        self._is_initialized = True

    def process_frame_data(self, frame: np.ndarray) -> tuple[np.ndarray, List[Dict[str, Any]]]:
        if not self._is_initialized:
            h, w = frame.shape[:2]
            self.initialize_video_dims(w, h)

        results = self.model.predict(
            source=frame,
            conf=self.cfg.confidence_threshold,
            iou=self.cfg.iou_threshold,
            classes=list(self.cfg.vehicle_class_ids),
            verbose=False,
        )[0]
        detections = sv.Detections.from_ultralytics(results)
        detections = self.tracker.update_with_detections(detections)

        self.counter.begin_frame()
        speed_map: dict[int, float] = {}
        direction_map: dict[int, str] = {}
        crossing_ids: set[int] = set()
        frame_logs: List[Dict[str, Any]] = []

        if detections.tracker_id is not None:
            for i in range(len(detections)):
                tid = int(detections.tracker_id[i])
                class_id = int(detections.class_id[i])
                class_name = self.cfg.vehicle_class_names.get(class_id, "Vehicle")
                xyxy = detections.xyxy[i]

                foot_x = (xyxy[0] + xyxy[2]) / 2.0
                foot_y = float(xyxy[3])

                self.speed_est.update(tid, (foot_x, foot_y))
                spd = self.speed_est.get_speed(tid)
                if spd is not None:
                    speed_map[tid] = spd

                direction = self.direction_detector.update(tid, (foot_x, foot_y))
                event = self.counter.update(tid, foot_y)

                if event == "IN":
                    direction = "SOUTH"
                elif event == "OUT":
                    direction = "NORTH"

                if event is not None:
                    crossing_ids.add(tid)
                    self.counter.mark_triggered(tid)

                if not direction or direction == "UNKNOWN":
                    direction = "SOUTH"

                direction_map[tid] = direction

                frame_logs.append({
                    "track_id": tid,
                    "class_name": class_name,
                    "speed_kmh": round(spd, 1) if spd else 0.0,
                    "direction": direction,
                    "is_speeding": bool(spd and spd > self.cfg.speed_limit_kmh)
                })

        annotated = draw_detections(
            frame=frame,
            detections=detections,
            config=self.cfg,
            speed_map=speed_map,
            direction_map=direction_map,
            crossing_ids=crossing_ids,
        )
        self.counter.draw(annotated, self.cfg)

        speeding_count = sum(1 for item in frame_logs if item["is_speeding"])
        active_tracks = len(detections) if detections.tracker_id is not None else 0

        annotated = draw_hud(
            annotated,
            fps=self._fps,
            in_count=self.counter.in_count,
            out_count=self.counter.out_count,
            active_tracks=active_tracks,
            speeding_count=speeding_count,
        )

        return annotated, frame_logs
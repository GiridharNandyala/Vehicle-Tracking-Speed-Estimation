"""
===============================================================================
TRAFFIC FLOW & SPEED ANALYTICS SYSTEM — Phase 3
database_manager.py  ·  SQLite Persistence Layer
===============================================================================
"""

from __future__ import annotations

import csv
import logging
import queue
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

log = logging.getLogger(__name__)


# ===============================================================================
# SECTION 1 — DATA TRANSFER OBJECTS
# ===============================================================================

@dataclass
class VehicleRecord:
    """One observation of a tracked vehicle, passed to DatabaseManager.log_vehicle()."""
    track_id:     int
    vehicle_type: str
    speed_kmh:    Optional[float] = None
    direction:    str             = "UNKNOWN"
    is_speeding:  bool            = False
    timestamp:    str             = field(default_factory=lambda:
                                    datetime.now(timezone.utc).isoformat())
    frame_id:     Optional[int]   = None
    confidence:   Optional[float] = None


@dataclass(frozen=True)
class SummaryStats:
    """Return type for query_summary_stats()."""
    total_vehicles:         int
    total_in:               int
    total_out:              int
    total_speeding:         int
    avg_speed_kmh:          Optional[float]
    max_speed_kmh:          Optional[float]
    count_by_type:          dict
    avg_speed_by_type:      dict
    speeding_by_type:       dict


@dataclass(frozen=True)
class HourBucket:
    """One row from query_peak_hour_density()."""
    hour:          int
    vehicle_count: int
    avg_speed_kmh: Optional[float]
    speeding_count: int


@dataclass(frozen=True)
class SpeedBucket:
    """One row from query_speed_distribution()."""
    bucket_label:  str
    count:         int


# ===============================================================================
# SECTION 2 — SCHEMA DDL
# ===============================================================================

_DDL_VEHICLE_LOGS = """
CREATE TABLE IF NOT EXISTS vehicle_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT    NOT NULL,
    track_id     INTEGER NOT NULL,
    frame_id     INTEGER,
    vehicle_type TEXT    NOT NULL,
    confidence   REAL,
    speed_kmh    REAL,
    direction    TEXT    NOT NULL DEFAULT 'UNKNOWN',
    is_speeding  INTEGER NOT NULL DEFAULT 0
);
"""

_DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_vl_timestamp   ON vehicle_logs (timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_vl_type        ON vehicle_logs (vehicle_type);",
    "CREATE INDEX IF NOT EXISTS idx_vl_speeding    ON vehicle_logs (is_speeding) WHERE is_speeding = 1;",
    "CREATE INDEX IF NOT EXISTS idx_vl_track       ON vehicle_logs (track_id, timestamp);",
]

_DDL_SESSIONS = """
CREATE TABLE IF NOT EXISTS processing_sessions (
    session_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT    NOT NULL,
    ended_at     TEXT,
    source_file  TEXT,
    total_frames INTEGER,
    notes        TEXT
);
"""

_DDL_SUMMARY_VIEW = """
CREATE VIEW IF NOT EXISTS v_hourly_summary AS
SELECT
    CAST(substr(timestamp, 12, 2) AS INTEGER) AS hour,
    COUNT(*)                        AS vehicle_count,
    ROUND(AVG(speed_kmh), 2)        AS avg_speed_kmh,
    SUM(is_speeding)                AS speeding_count
FROM vehicle_logs
WHERE speed_kmh IS NOT NULL
GROUP BY hour
ORDER BY hour;
"""


# ===============================================================================
# SECTION 3 — DATABASE MANAGER
# ===============================================================================

_STOP_SENTINEL = object()
_DEFAULT_BATCH_SIZE = 64
_DEFAULT_FLUSH_INTERVAL = 1.0


class DatabaseManager:
    """Thread-safe SQLite persistence layer for the Traffic Analytics System."""

    def __init__(
        self,
        db_path:         str   = "traffic_data.db",
        batch_size:      int   = _DEFAULT_BATCH_SIZE,
        flush_interval:  float = _DEFAULT_FLUSH_INTERVAL,
        queue_maxsize:   int   = 4096,
    ):
        self._db_path = Path(db_path)
        self._batch_size = batch_size
        self._flush_interval = flush_interval

        self._write_queue: queue.Queue = queue.Queue(maxsize=queue_maxsize)
        self._writer_thread: Optional[threading.Thread] = None
        self._running = False

        self._rows_written: int = 0
        self._batches_committed: int = 0
        self._queue_drops: int = 0
        self._session_id: Optional[int] = None

        self._init_schema()
        log.info("[DB] Initialised → %s", self._db_path.resolve())

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA cache_size = -65536;")
        conn.execute("PRAGMA temp_store = MEMORY;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_schema(self) -> None:
        conn = self._get_connection()
        try:
            conn.execute(_DDL_VEHICLE_LOGS)
            conn.execute(_DDL_SESSIONS)
            conn.execute(_DDL_SUMMARY_VIEW)
            for idx_sql in _DDL_INDEXES:
                conn.execute(idx_sql)
            conn.commit()
            log.debug("[DB] Schema ready.")
        finally:
            conn.close()

    def _open_session(
        self,
        conn: sqlite3.Connection,
        source_file: Optional[str] = None,
    ) -> int:
        cur = conn.execute(
            "INSERT INTO processing_sessions (started_at, source_file) VALUES (?,?)",
            (datetime.now(timezone.utc).isoformat(), source_file),
        )
        conn.commit()
        return cur.lastrowid

    def _close_session(
        self,
        conn: sqlite3.Connection,
        session_id: int,
        total_frames: Optional[int] = None,
    ) -> None:
        conn.execute(
            "UPDATE processing_sessions SET ended_at=?, total_frames=? WHERE session_id=?",
            (datetime.now(timezone.utc).isoformat(), total_frames, session_id),
        )
        conn.commit()

    def start(self, source_file: Optional[str] = None) -> None:
        if self._running:
            log.warning("[DB] start() called twice — ignoring.")
            return

        self._running = True
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            args=(source_file,),
            name="DB-Writer",
            daemon=True,
        )
        self._writer_thread.start()
        log.info("[DB] Writer thread started (batch=%d, flush=%.1fs).",
                 self._batch_size, self._flush_interval)

    def stop(self, total_frames: Optional[int] = None) -> None:
        if not self._running:
            return

        self._running = False
        self._write_queue.put(_STOP_SENTINEL)

        if self._writer_thread:
            self._writer_thread.join(timeout=10.0)
            if self._writer_thread.is_alive():
                log.warning("[DB] Writer thread did not stop within 10s — data may be incomplete.")

        conn = self._get_connection()
        try:
            if self._session_id is not None:
                self._close_session(conn, self._session_id, total_frames)
            conn.execute("PRAGMA optimize;")
            conn.commit()
        finally:
            conn.close()

        log.info(
            "[DB] Shutdown complete. rows_written=%d, batches=%d, drops=%d",
            self._rows_written, self._batches_committed, self._queue_drops,
        )

    def log_vehicle(self, record: VehicleRecord) -> None:
        try:
            self._write_queue.put_nowait(record)
        except queue.Full:
            self._queue_drops += 1
            if self._queue_drops % 100 == 1:
                log.warning(
                    "[DB] Queue full — dropped record (total drops: %d).",
                    self._queue_drops,
                )

    def flush(self) -> None:
        self._write_queue.join()

    def _writer_loop(self, source_file: Optional[str]) -> None:
        conn = self._get_connection()
        try:
            self._session_id = self._open_session(conn, source_file)
            batch: list[VehicleRecord] = []
            deadline = time.monotonic() + self._flush_interval

            while True:
                timeout = max(deadline - time.monotonic(), 0.001)

                try:
                    item = self._write_queue.get(timeout=timeout)
                except queue.Empty:
                    if batch:
                        self._batch_insert(conn, batch)
                        batch.clear()
                    deadline = time.monotonic() + self._flush_interval
                    continue

                if item is _STOP_SENTINEL:
                    self._write_queue.task_done()
                    if batch:
                        self._batch_insert(conn, batch)
                    break

                batch.append(item)
                self._write_queue.task_done()

                if len(batch) >= self._batch_size:
                    self._batch_insert(conn, batch)
                    batch.clear()
                    deadline = time.monotonic() + self._flush_interval

        except Exception as exc:
            log.error("[DB] Writer thread crashed: %s", exc, exc_info=True)
        finally:
            conn.close()

    _INSERT_SQL = """
        INSERT INTO vehicle_logs
            (timestamp, track_id, frame_id, vehicle_type, confidence,
             speed_kmh, direction, is_speeding)
        VALUES
            (:timestamp, :track_id, :frame_id, :vehicle_type, :confidence,
             :speed_kmh, :direction, :is_speeding)
    """

    def _batch_insert(
        self,
        conn: sqlite3.Connection,
        batch: list[VehicleRecord],
    ) -> None:
        params = [asdict(r) for r in batch]

        try:
            conn.executemany(self._INSERT_SQL, params)
            conn.commit()
            self._rows_written += len(batch)
            self._batches_committed += 1
            log.debug("[DB] Batch committed: %d rows (total: %d).",
                      len(batch), self._rows_written)

        except sqlite3.Error as bulk_err:
            log.warning(
                "[DB] Batch INSERT failed (%s) — retrying row-by-row.", bulk_err
            )
            conn.rollback()
            saved = 0
            for p in params:
                try:
                    conn.execute(self._INSERT_SQL, p)
                    saved += 1
                except sqlite3.Error as row_err:
                    log.error("[DB] Row dropped: %s | record=%s", row_err, p)
            try:
                conn.commit()
                self._rows_written += saved
                self._batches_committed += 1
            except sqlite3.Error as commit_err:
                log.error("[DB] Commit failed after row-by-row retry: %s", commit_err)
                conn.rollback()

    # ===============================================================================
    # SECTION 4 — ANALYTICS QUERIES
    # ===============================================================================

    @contextmanager
    def _read_conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._get_connection()
        try:
            yield conn
        finally:
            conn.close()

    def query_summary_stats(self) -> SummaryStats:
        with self._read_conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*)                                   AS total_vehicles,
                    SUM(CASE WHEN direction='IN'  THEN 1 ELSE 0 END) AS total_in,
                    SUM(CASE WHEN direction='OUT' THEN 1 ELSE 0 END) AS total_out,
                    SUM(is_speeding)                           AS total_speeding,
                    ROUND(AVG(speed_kmh), 2)                   AS avg_speed_kmh,
                    ROUND(MAX(speed_kmh), 2)                   AS max_speed_kmh
                FROM vehicle_logs
            """).fetchone()

            class_rows = conn.execute("""
                SELECT
                    vehicle_type,
                    COUNT(*)                     AS cnt,
                    ROUND(AVG(speed_kmh), 2)     AS avg_spd,
                    SUM(is_speeding)             AS spd_violations
                FROM vehicle_logs
                GROUP BY vehicle_type
                ORDER BY cnt DESC
            """).fetchall()

        count_by_type = {r["vehicle_type"]: r["cnt"] for r in class_rows}
        avg_speed_by_type = {r["vehicle_type"]: r["avg_spd"] for r in class_rows}
        speeding_by_type = {r["vehicle_type"]: r["spd_violations"] for r in class_rows}

        return SummaryStats(
            total_vehicles=row["total_vehicles"] or 0,
            total_in=row["total_in"] or 0,
            total_out=row["total_out"] or 0,
            total_speeding=row["total_speeding"] or 0,
            avg_speed_kmh=row["avg_speed_kmh"],
            max_speed_kmh=row["max_speed_kmh"],
            count_by_type=count_by_type,
            avg_speed_by_type=avg_speed_by_type,
            speeding_by_type=speeding_by_type,
        )

    def query_peak_hour_density(self) -> list[HourBucket]:
        with self._read_conn() as conn:
            rows = conn.execute("""
                SELECT
                    CAST(substr(timestamp, 12, 2) AS INTEGER) AS hour,
                    COUNT(*)                    AS vehicle_count,
                    ROUND(AVG(speed_kmh), 2)    AS avg_speed_kmh,
                    SUM(is_speeding)            AS speeding_count
                FROM vehicle_logs
                GROUP BY hour
                ORDER BY hour
            """).fetchall()

        by_hour = {r["hour"]: r for r in rows if r["hour"] is not None}

        return [
            HourBucket(
                hour=h,
                vehicle_count=by_hour[h]["vehicle_count"] if h in by_hour else 0,
                avg_speed_kmh=by_hour[h]["avg_speed_kmh"] if h in by_hour else None,
                speeding_count=by_hour[h]["speeding_count"] if h in by_hour else 0,
            )
            for h in range(24)
        ]

    def query_recent_logs(self, n: int = 50) -> list[dict]:
        with self._read_conn() as conn:
            rows = conn.execute("""
                SELECT id, timestamp, track_id, vehicle_type,
                       ROUND(speed_kmh, 1) AS speed_kmh,
                       direction, is_speeding, frame_id
                FROM vehicle_logs
                ORDER BY id DESC
                LIMIT ?
            """, (n,)).fetchall()

        return [dict(r) for r in rows]

    def query_speed_distribution(
        self,
        bin_width_kmh: int = 10,
        max_speed_kmh: int = 150,
    ) -> list[SpeedBucket]:
        with self._read_conn() as conn:
            rows = conn.execute("""
                SELECT
                    (CAST(speed_kmh / :w AS INTEGER) * :w)      AS bin_floor,
                    COUNT(*)                                     AS cnt
                FROM vehicle_logs
                WHERE speed_kmh IS NOT NULL
                  AND speed_kmh <= :max
                GROUP BY bin_floor
                ORDER BY bin_floor
            """, {"w": bin_width_kmh, "max": max_speed_kmh}).fetchall()

        return [
            SpeedBucket(
                bucket_label=f"{r['bin_floor']}–{r['bin_floor'] + bin_width_kmh}",
                count=r["cnt"],
            )
            for r in rows
        ]

    def query_violations(
        self,
        min_speed_kmh: Optional[float] = None,
        limit: int = 200,
    ) -> list[dict]:
        where_speed = f"AND speed_kmh >= {min_speed_kmh}" if min_speed_kmh else ""
        with self._read_conn() as conn:
            rows = conn.execute(f"""
                SELECT id, timestamp, track_id, vehicle_type,
                       ROUND(speed_kmh, 1) AS speed_kmh,
                       direction, frame_id
                FROM vehicle_logs
                WHERE is_speeding = 1
                  {where_speed}
                ORDER BY speed_kmh DESC
                LIMIT {limit}
            """).fetchall()
        return [dict(r) for r in rows]

    def export_csv(self, output_path: str = "vehicle_logs_export.csv") -> int:
        output = Path(output_path)
        _CHUNK = 1000

        with self._read_conn() as conn:
            cur = conn.execute("""
                SELECT id, timestamp, track_id, frame_id, vehicle_type,
                       confidence, speed_kmh, direction, is_speeding
                FROM vehicle_logs
                ORDER BY id
            """)

            columns = [desc[0] for desc in cur.description]
            rows_written = 0

            with open(output, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(columns)

                while True:
                    chunk = cur.fetchmany(_CHUNK)
                    if not chunk:
                        break
                    writer.writerows(chunk)
                    rows_written += len(chunk)

        log.info("[DB] Exported %d rows → %s", rows_written, output.resolve())
        return rows_written

    def __repr__(self) -> str:
        return (
            f"DatabaseManager(db='{self._db_path}', "
            f"rows_written={self._rows_written}, "
            f"queue_size={self._write_queue.qsize()})"
        )


# ===============================================================================
# SECTION 5 — SELF-TEST EXECUTION
# ===============================================================================

def _self_test() -> None:
    import random
    import tempfile

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    VEHICLE_TYPES = ["Car", "Motorcycle", "Bus", "Truck"]
    DIRECTIONS = ["IN", "OUT"]
    SPEED_LIMIT = 60.0
    N_RECORDS = 500

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    print(f"\n{'═'*60}")
    print("  DatabaseManager — self-test")
    print(f"  DB path: {db_path}")
    print(f"{'═'*60}\n")

    db = DatabaseManager(db_path=db_path, batch_size=50, flush_interval=0.5)
    db.start(source_file="self_test_video.mp4")

    t0 = time.perf_counter()
    for i in range(N_RECORDS):
        vtype = random.choice(VEHICLE_TYPES)
        speed = round(random.uniform(20, 110), 2)
        record = VehicleRecord(
            track_id=random.randint(1, 80),
            vehicle_type=vtype,
            speed_kmh=speed,
            direction=random.choice(DIRECTIONS),
            is_speeding=speed > SPEED_LIMIT,
            frame_id=i * 3,
            confidence=round(random.uniform(0.55, 0.99), 3),
        )
        db.log_vehicle(record)
    elapsed_enqueue = time.perf_counter() - t0
    print(f"  Enqueued {N_RECORDS} records in {elapsed_enqueue*1000:.1f} ms "
          f"({N_RECORDS/elapsed_enqueue:,.0f} records/sec)")

    db.flush()

    stats = db.query_summary_stats()
    print(f"\n  ── Summary Stats ──────────────────────────────────")
    print(f"  Total vehicles   : {stats.total_vehicles}")
    print(f"  Total IN         : {stats.total_in}")
    print(f"  Total OUT        : {stats.total_out}")
    print(f"  Speeding         : {stats.total_speeding}")
    print(f"  Avg speed        : {stats.avg_speed_kmh} km/h")
    print(f"  Max speed        : {stats.max_speed_kmh} km/h")
    print(f"  Count by type    : {stats.count_by_type}")

    density = db.query_peak_hour_density()
    non_zero = [b for b in density if b.vehicle_count > 0]
    print(f"\n  ── Peak-Hour Density (non-zero hours) ─────────────")
    for b in non_zero:
        bar = "█" * min(b.vehicle_count, 40)
        print(f"  {b.hour:02d}:00  {bar:<40}  {b.vehicle_count:>4} vehicles")

    dist = db.query_speed_distribution()
    print(f"\n  ── Speed Distribution ─────────────────────────────")
    for b in dist:
        bar = "▪" * min(b.count, 30)
        print(f"  {b.bucket_label:<10}  {bar:<30}  {b.count}")

    recent = db.query_recent_logs(5)
    print(f"\n  ── 5 Most Recent Logs ─────────────────────────────")
    for r in recent:
        print(f"  {r}")

    violations = db.query_violations(min_speed_kmh=80.0, limit=5)
    print(f"\n  ── Top Violations (≥80 km/h, top 5) ──────────────")
    for v in violations:
        print(f"  {v}")

    csv_path = db_path.replace(".db", "_export.csv")
    n = db.export_csv(csv_path)
    print(f"\n  ── CSV Export ─────────────────────────────────────")
    print(f"  Wrote {n} rows → {csv_path}")

    db.stop(total_frames=N_RECORDS * 3)
    print(f"\n  {db}")
    print(f"\n{'═'*60}")
    print("  Self-test PASSED ✓")
    print(f"{'═'*60}\n")


if __name__ == "__main__":
    _self_test()
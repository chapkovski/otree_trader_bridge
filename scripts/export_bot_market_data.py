#!/usr/bin/env python3
import csv
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _resolve_export_backend_and_target():
    db_url = str(os.getenv("DATABASE_URL", "")).strip()
    if db_url:
        if db_url.startswith("postgresql+psycopg2://"):
            return "postgres", db_url.replace("postgresql+psycopg2://", "postgresql://", 1)
        if db_url.startswith("postgres://"):
            return "postgres", "postgresql://" + db_url[len("postgres://") :]
        if db_url.startswith("postgresql://"):
            return "postgres", db_url
        if db_url.startswith("sqlite:///"):
            return "sqlite", db_url[len("sqlite:///") :]
    return "sqlite", str((ROOT / "db.sqlite3").resolve())


def _fetch_rows(sql_query):
    backend, target = _resolve_export_backend_and_target()
    if backend == "sqlite":
        with sqlite3.connect(target) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            try:
                cur.execute(sql_query)
            except sqlite3.OperationalError:
                return []
            return cur.fetchall()

    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(target)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql_query)
            return cur.fetchall()
    finally:
        conn.close()


def _parse_json_object(raw):
    try:
        parsed = json.loads(str(raw or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _timestamped_output_dir():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = ROOT / f"_bots_{ts}"
    output_dir.mkdir(parents=True, exist_ok=False)
    return output_dir


def _write_csv(path: Path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def _simulated_sessions():
    rows = _fetch_rows(
        """
        SELECT trading_session_uuid, payload_json, response_json, created_ts
        FROM trading_platform_sessions
        ORDER BY id ASC
        """
    )
    sessions = []
    for row in rows:
        payload = _parse_json_object(row["payload_json"])
        if not bool(payload.get("is_simulated", False)):
            continue
        sessions.append(row)
    return sessions


def _simulated_session_ids(sessions):
    return {str(row["trading_session_uuid"] or "") for row in sessions}


def _sessions_csv_rows(sessions):
    rows = [["trading_session_uuid", "is_simulated", "payload_json", "response_json", "created_ts"]]
    for row in sessions:
        rows.append(
            [
                str(row["trading_session_uuid"] or ""),
                True,
                str(row["payload_json"] or ""),
                str(row["response_json"] or ""),
                row["created_ts"],
            ]
        )
    return rows


def _export_table(sql_query, session_ids, is_simulated_position=1):
    rows = _fetch_rows(sql_query)
    if not rows:
        return []
    header = list(rows[0].keys())
    body = []
    for row in rows:
        session_uuid = str(row["trading_session_uuid"] or "")
        if session_uuid not in session_ids:
            continue
        values = [row[key] for key in header]
        if is_simulated_position is not None:
            values.insert(is_simulated_position, True)
        body.append(values)
    if is_simulated_position is not None:
        header = header[:is_simulated_position] + ["is_simulated"] + header[is_simulated_position:]
    return [header, *body]


def _write_note(path: Path, text: str):
    path.write_text(text, encoding="utf-8")


def main():
    sessions = _simulated_sessions()
    output_dir = _timestamped_output_dir()
    _write_csv(output_dir / "sessions.csv", _sessions_csv_rows(sessions))
    session_ids = _simulated_session_ids(sessions)
    if not sessions:
        _write_note(
            output_dir / "README.txt",
            "No simulated trading sessions were found in the configured persistence database. "
            "This usually means trading-platform SQL persistence is not enabled for the current local DB target.\n",
        )

    mbo_rows = _export_table(
        """
        SELECT trading_session_uuid,
               event_seq,
               event_ts,
               record_kind,
               event_type,
               side,
               order_id,
               trader_uuid,
               price,
               size,
               size_delta,
               size_resting_after,
               status_after,
               match_id,
               contra_order_id,
               bid_order_id,
               ask_order_id,
               bid_trader_uuid,
               ask_trader_uuid,
               event_json,
               created_ts
        FROM trading_platform_mbo_events
        ORDER BY id ASC
        """,
        session_ids=session_ids,
    )
    _write_csv(
        output_dir / "mbo.csv",
        mbo_rows
        or [[
            "trading_session_uuid",
            "is_simulated",
            "event_seq",
            "event_ts",
            "record_kind",
            "event_type",
            "side",
            "order_id",
            "trader_uuid",
            "price",
            "size",
            "size_delta",
            "size_resting_after",
            "status_after",
            "match_id",
            "contra_order_id",
            "bid_order_id",
            "ask_order_id",
            "bid_trader_uuid",
            "ask_trader_uuid",
            "event_json",
            "created_ts",
        ]],
    )

    mbp1_rows = _export_table(
        """
        SELECT trading_session_uuid,
               event_seq,
               event_ts,
               source_mbo_event_seq,
               source_order_id,
               source_event_type,
               best_bid_px,
               best_bid_sz,
               best_bid_ct,
               best_ask_px,
               best_ask_sz,
               best_ask_ct,
               spread,
               midpoint,
               created_ts
        FROM trading_platform_mbp1_events
        ORDER BY id ASC
        """,
        session_ids=session_ids,
    )
    _write_csv(
        output_dir / "mbp1.csv",
        mbp1_rows
        or [[
            "trading_session_uuid",
            "is_simulated",
            "event_seq",
            "event_ts",
            "source_mbo_event_seq",
            "source_order_id",
            "source_event_type",
            "best_bid_px",
            "best_bid_sz",
            "best_bid_ct",
            "best_ask_px",
            "best_ask_sz",
            "best_ask_ct",
            "spread",
            "midpoint",
            "created_ts",
        ]],
    )

    print(output_dir)


if __name__ == "__main__":
    main()

import csv
import os
import time
from datetime import datetime
from typing import Dict, Any

OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")
METRICS_FILE = os.path.join(OUTPUTS_DIR, "evaluation_metrics.csv")

# In-memory store for session metrics
session_metrics: Dict[str, Dict[str, Any]] = {}

def _ensure_session(session_id: str):
    if session_id not in session_metrics:
        session_metrics[session_id] = {
            "session_id": session_id,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_latency_sec": 0.0,
            "total_completion_tokens": 0,
            "total_llm_calls": 0,
            "json_validity_rate": 0.0,
            "json_attempts": 0,
            "json_successes": 0,
            "raw_text_length": 0,
            "final_text_length": 0,
            "compression_ratio": 0.0,
            "status": "in_progress"
        }

def log_llm_call(session_id: str, latency_sec: float, completion_tokens: int):
    _ensure_session(session_id)
    session_metrics[session_id]["total_latency_sec"] += latency_sec
    session_metrics[session_id]["total_completion_tokens"] += completion_tokens
    session_metrics[session_id]["total_llm_calls"] += 1

def log_json_attempt(session_id: str, success: bool):
    _ensure_session(session_id)
    session_metrics[session_id]["json_attempts"] += 1
    if success:
        session_metrics[session_id]["json_successes"] += 1

def set_compression_stats(session_id: str, raw_length: int, final_length: int):
    _ensure_session(session_id)
    session_metrics[session_id]["raw_text_length"] = raw_length
    session_metrics[session_id]["final_text_length"] = final_length
    if raw_length > 0:
        session_metrics[session_id]["compression_ratio"] = final_length / raw_length

def finalize_metrics(session_id: str, status: str = "completed"):
    if session_id not in session_metrics:
        return
        
    metrics = session_metrics[session_id]
    metrics["status"] = status
    
    # Calculate validity rate
    if metrics["json_attempts"] > 0:
        metrics["json_validity_rate"] = metrics["json_successes"] / metrics["json_attempts"]
        
    # Calculate throughput
    metrics["tokens_per_sec"] = 0.0
    if metrics["total_latency_sec"] > 0:
        metrics["tokens_per_sec"] = metrics["total_completion_tokens"] / metrics["total_latency_sec"]
        
    # Save to CSV
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    file_exists = os.path.isfile(METRICS_FILE)
    
    fieldnames = [
        "session_id", "date", "status", 
        "total_latency_sec", "total_llm_calls", 
        "total_completion_tokens", "tokens_per_sec", 
        "json_attempts", "json_successes", "json_validity_rate", 
        "raw_text_length", "final_text_length", "compression_ratio"
    ]
    
    try:
        with open(METRICS_FILE, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(metrics)
    except Exception as e:
        print(f"Failed to write metrics to CSV: {e}")
        
    # Cleanup memory
    del session_metrics[session_id]

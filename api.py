import json
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict
from functools import lru_cache
import secrets
import os

client_configs = {}
API_KEYS = {}

db_path = "/tmp/classifier.db" if os.environ.get("VERCEL") else "classifier.db"


def init_db():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS classifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT NOT NULL,
            company TEXT NOT NULL,
            score INTEGER,
            tier TEXT,
            confidence TEXT,
            recommended_action TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_hash TEXT UNIQUE NOT NULL,
            label TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS client_configs (
            client_id TEXT PRIMARY KEY,
            config_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


init_db()


def load_configs():
    global client_configs, API_KEYS
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT client_id, config_json FROM client_configs")
    for row in c.fetchall():
        client_configs[row[0]] = json.loads(row[1])
    c.execute("SELECT key_hash FROM api_keys")
    for row in c.fetchall():
        API_KEYS[row[0]] = True
    conn.close()


load_configs()


def verify_api_key(headers: dict) -> str:
    auth = headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise Exception("Missing or invalid Authorization header")
    key = auth[7:]
    if key not in API_KEYS:
        raise Exception("Invalid API key")
    return key


def classify_lead(client_config: dict, lead: dict) -> dict:
    from classifier import classify_lead as _classify
    return _classify(client_config, lead)


def handler(event, context):
    path = event.get("path", "/")
    method = event.get("httpMethod", "GET")
    headers = event.get("headers", {})
    body = event.get("body", "")

    try:
        verify_api_key(headers)
    except Exception as e:
        return {
            "statusCode": 401,
            "body": json.dumps({"detail": str(e)})
        }

    if path == "/health":
        return {"statusCode": 200, "body": json.dumps({"status": "healthy", "clients": len(client_configs)})}

    if method == "POST" and path == "/classify":
        try:
            data = json.loads(body)
        except:
            return {"statusCode": 400, "body": json.dumps({"detail": "Invalid JSON"})}

        client_config = data.get("client_config")
        client_id = data.get("client_id")
        lead = data.get("lead")

        if not lead:
            return {"statusCode": 400, "body": json.dumps({"detail": "Missing lead"})}

        if client_config:
            config = client_config
        elif client_id and client_id in client_configs:
            config = client_configs[client_id]
        else:
            return {"statusCode": 400, "body": json.dumps({"detail": "Provide client_config or valid client_id"})}

        result = classify_lead(config, lead)

        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("""
            INSERT INTO classifications (client_id, company, score, tier, confidence, recommended_action)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (result["client_id"], result["company"], result["score"], result["tier"],
              result["confidence"], result["recommended_action"]))
        conn.commit()
        conn.close()

        return {"statusCode": 200, "body": json.dumps(result)}

    if method == "POST" and path == "/admin/client-configs":
        try:
            data = json.loads(body)
        except:
            return {"statusCode": 400, "body": json.dumps({"detail": "Invalid JSON"})}

        client_id = data.get("client_id")
        config = data.get("config")

        if not client_id or not config:
            return {"statusCode": 400, "body": json.dumps({"detail": "Missing client_id or config"})}

        client_configs[client_id] = config
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO client_configs (client_id, config_json, updated_at)
            VALUES (?, ?, ?)
        """, (client_id, json.dumps(config), datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

        return {"statusCode": 200, "body": json.dumps({"status": "saved", "client_id": client_id})}

    if method == "GET" and path.startswith("/admin/classifications"):
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("""
            SELECT client_id, company, score, tier, confidence, recommended_action, created_at
            FROM classifications ORDER BY created_at DESC LIMIT 50
        """)
        rows = c.fetchall()
        conn.close()
        results = [{"client_id": r[0], "company": r[1], "score": r[2], "tier": r[3],
                    "confidence": r[4], "action": r[5], "created_at": r[6]} for r in rows]
        return {"statusCode": 200, "body": json.dumps(results)}

    return {"statusCode": 404, "body": json.dumps({"detail": "Not found"})}
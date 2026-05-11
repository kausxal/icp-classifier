import json
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict
import secrets
import os
import requests
from classifier import classify_lead as _classify

client_configs = {}
API_KEYS = {}

db_path = "classifier.db"

APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY", "")
HUBSPOT_API_KEY = os.environ.get("HUBSPOT_API_KEY", "")


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
    c.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT NOT NULL,
            source TEXT,
            source_id TEXT,
            company TEXT,
            domain TEXT,
            industry TEXT,
            headcount INTEGER,
            funding_stage TEXT,
            hq_country TEXT,
            hq_region TEXT,
            tech_stack TEXT,
            job_signals TEXT,
            email TEXT,
            first_name TEXT,
            last_name TEXT,
            title TEXT,
            score INTEGER,
            tier TEXT,
            confidence TEXT,
            recommended_action TEXT,
            pushed_to_hubspot INTEGER DEFAULT 0,
            hubspot_contact_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS routing_config (
            client_id TEXT PRIMARY KEY,
            route_to_db INTEGER DEFAULT 1,
            route_to_hubspot INTEGER DEFAULT 0,
            hubspot_pipeline TEXT,
            hubspot_stage TEXT,
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


def parse_headcount(hc_str: str) -> Optional[int]:
    if not hc_str:
        return None
    hc_str = str(hc_str).replace(",", "").replace(" ", "")
    if hc_str.isdigit():
        return int(hc_str)
    if "-" in hc_str:
        parts = hc_str.split("-")
        return int(parts[0]) if parts[0].isdigit() else None
    return None


def push_to_hubspot(lead: dict, hubspot_config: dict) -> Optional[str]:
    if not HUBSPOT_API_KEY:
        return None

    url = "https://api.hubapi.com/crm/v3/objects/contacts"
    headers = {"Authorization": f"Bearer {HUBSPOT_API_KEY}", "Content-Type": "application/json"}

    properties = {
        "email": lead.get("email", ""),
        "firstname": lead.get("first_name", ""),
        "lastname": lead.get("last_name", ""),
        "jobtitle": lead.get("title", ""),
        "company": lead.get("company", ""),
        "icp_score": str(lead.get("score", "")),
        "icp_tier": lead.get("tier", ""),
        "icp_confidence": lead.get("confidence", ""),
    }

    if hubspot_config.get("pipeline"):
        properties["pipeline"] = hubspot_config["pipeline"]
    if hubspot_config.get("stage"):
        properties["dealstage"] = hubspot_config["stage"]

    try:
        resp = requests.post(url, headers=headers, json={"properties": properties}, timeout=10)
        if resp.status_code in [200, 201]:
            data = resp.json()
            return data.get("id")
    except:
        pass
    return None


def save_lead(client_id: str, lead_data: dict, classification: dict, source: str = "api", source_id: str = "") -> int:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        INSERT INTO leads (
            client_id, source, source_id, company, domain, industry, headcount,
            funding_stage, hq_country, hq_region, tech_stack, job_signals,
            email, first_name, last_name, title, score, tier, confidence, recommended_action
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        client_id, source, source_id, lead_data.get("company"), lead_data.get("domain"),
        lead_data.get("industry"), lead_data.get("headcount"), lead_data.get("funding_stage"),
        lead_data.get("hq_country"), lead_data.get("hq_region"),
        json.dumps(lead_data.get("tech_stack", [])), json.dumps(lead_data.get("job_signals", [])),
        lead_data.get("email"), lead_data.get("first_name"), lead_data.get("last_name"),
        lead_data.get("title"), classification.get("score"), classification.get("tier"),
        classification.get("confidence"), classification.get("recommended_action")
    ))
    lead_id = c.lastrowid
    conn.commit()
    conn.close()
    return lead_id


def route_lead(client_id: str, lead_data: dict, classification: dict):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        SELECT route_to_db, route_to_hubspot, hubspot_pipeline, hubspot_stage
        FROM routing_config WHERE client_id = ?
    """, (client_id,))
    row = c.fetchone()
    conn.close()

    routing = {"route_to_db": True, "route_to_hubspot": False}
    hubspot_config = {}

    if row:
        routing = {"route_to_db": bool(row[0]), "route_to_hubspot": bool(row[1])}
        hubspot_config = {"pipeline": row[2], "stage": row[3]}

    lead_id = None
    hubspot_id = None

    if routing["route_to_db"]:
        lead_id = save_lead(client_id, lead_data, classification)

    if routing["route_to_hubspot"]:
        hubspot_id = push_to_hubspot({**lead_data, **classification}, hubspot_config)
        if hubspot_id and lead_id:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("UPDATE leads SET pushed_to_hubspot = 1, hubspot_contact_id = ? WHERE id = ?",
                      (hubspot_id, lead_id))
            conn.commit()
            conn.close()

    return {"lead_id": lead_id, "hubspot_contact_id": hubspot_id}


def handler(event, context):
    path = event.get("path", "/")
    method = event.get("httpMethod", "GET")
    headers = event.get("headers", {})
    body = event.get("body", "")

    try:
        verify_api_key(headers)
    except Exception as e:
        return {"statusCode": 401, "body": json.dumps({"detail": str(e)})}

    if path == "/health":
        return {"statusCode": 200, "body": json.dumps({"status": "healthy", "clients": len(client_configs)})}

    if method == "POST" and path == "/webhook/apollo":
        try:
            payload = json.loads(body)
        except:
            return {"statusCode": 400, "body": json.dumps({"detail": "Invalid JSON"})}

        person_id = payload.get("person", {}).get("id")
        client_id = payload.get("client_id")

        if not client_id or client_id not in client_configs:
            return {"statusCode": 400, "body": json.dumps({"detail": "Invalid client_id"})}

        contact_data = payload.get("contact", {})
        lead = {
            "company": contact_data.get("company_name"),
            "domain": contact_data.get("domain"),
            "industry": contact_data.get("industry"),
            "headcount": parse_headcount(contact_data.get("employee_count")),
            "funding_stage": contact_data.get("funding_stage"),
            "hq_country": contact_data.get("country_code"),
            "hq_region": contact_data.get("state"),
            "tech_stack": contact_data.get("tech", []),
            "job_signals": [contact_data.get("title")] if contact_data.get("title") else [],
            "email": contact_data.get("email"),
            "first_name": contact_data.get("first_name"),
            "last_name": contact_data.get("last_name"),
            "title": contact_data.get("title"),
            "is_competitor": contact_data.get("is_competitor", False)
        }

        result = _classify(client_configs[client_id], lead)

        route_result = route_lead(client_id, lead, result)

        result["lead_id"] = route_result["lead_id"]
        result["hubspot_contact_id"] = route_result["hubspot_contact_id"]

        return {"statusCode": 200, "body": json.dumps(result)}

    if method == "POST" and path == "/classify":
        try:
            data = json.loads(body)
        except:
            return {"statusCode": 400, "body": json.dumps({"detail": "Invalid JSON"})}

        client_config = data.get("client_config")
        client_id = data.get("client_id")
        lead = data.get("lead")
        route = data.get("route", {})

        if not lead:
            return {"statusCode": 400, "body": json.dumps({"detail": "Missing lead"})}

        if client_config:
            config = client_config
        elif client_id and client_id in client_configs:
            config = client_configs[client_id]
        else:
            return {"statusCode": 400, "body": json.dumps({"detail": "Provide client_config or valid client_id"})}

        result = _classify(config, lead)

        if route.get("save_to_db", True):
            route_result = route_lead(client_id or config.get("client_id", "unknown"), lead, result)
            result["lead_id"] = route_result["lead_id"]
            result["hubspot_contact_id"] = route_result["hubspot_contact_id"]

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

    if method == "POST" and path == "/admin/routing":
        try:
            data = json.loads(body)
        except:
            return {"statusCode": 400, "body": json.dumps({"detail": "Invalid JSON"})}

        client_id = data.get("client_id")
        route_to_db = data.get("route_to_db", True)
        route_to_hubspot = data.get("route_to_hubspot", False)
        hubspot_pipeline = data.get("hubspot_pipeline", "")
        hubspot_stage = data.get("hubspot_stage", "")

        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO routing_config 
            (client_id, route_to_db, route_to_hubspot, hubspot_pipeline, hubspot_stage, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (client_id, int(route_to_db), int(route_to_hubspot), hubspot_pipeline, hubspot_stage, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

        return {"statusCode": 200, "body": json.dumps({"status": "saved", "client_id": client_id})}

    if method == "GET" and path == "/admin/leads":
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("""
            SELECT id, client_id, company, email, score, tier, confidence, 
                   recommended_action, pushed_to_hubspot, hubspot_contact_id, created_at
            FROM leads ORDER BY created_at DESC LIMIT 100
        """)
        rows = c.fetchall()
        conn.close()
        results = [{
            "id": r[0], "client_id": r[1], "company": r[2], "email": r[3], "score": r[4],
            "tier": r[5], "confidence": r[6], "action": r[7], "hubspot_pushed": bool(r[8]),
            "hubspot_id": r[9], "created_at": r[10]
        } for r in rows]
        return {"statusCode": 200, "body": json.dumps(results)}

    if method == "GET" and path.startswith("/admin/leads/"):
        lead_id = path.split("/")[-1]
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return {"statusCode": 404, "body": json.dumps({"detail": "Lead not found"})}
        return {"statusCode": 200, "body": json.dumps({"id": row[0], "client_id": row[1], "data": {
            "company": row[3], "domain": row[4], "industry": row[5], "headcount": row[6],
            "funding_stage": row[7], "hq_country": row[8], "tech_stack": json.loads(row[10] or "[]"),
            "job_signals": json.loads(row[11] or "[]"), "email": row[12], "first_name": row[13],
            "last_name": row[14], "title": row[15]
        }, "classification": {"score": row[16], "tier": row[17], "confidence": row[18], "action": row[19]}})}

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
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import secrets
import os
import requests
from classifier import classify_lead as _classify

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse
from typing import Optional

app = FastAPI(title="ICP Classifier")

client_configs = {}
API_KEYS = {}
integrations = {}

db_path = "classifier.db"

APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY", "")
HUBSPOT_API_KEY = os.environ.get("HUBSPOT_API_KEY", "")
SALESFORCE_INSTANCE_URL = os.environ.get("SALESFORCE_INSTANCE_URL", "")
SALESFORCE_ACCESS_TOKEN = os.environ.get("SALESFORCE_ACCESS_TOKEN", "")


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
            phone TEXT,
            score INTEGER,
            tier TEXT,
            confidence TEXT,
            recommended_action TEXT,
            signal_breakdown TEXT,
            reasons TEXT,
            pushed_to_hubspot INTEGER DEFAULT 0,
            hubspot_contact_id TEXT,
            pushed_to_salesforce INTEGER DEFAULT 0,
            salesforce_contact_id TEXT,
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
            route_to_salesforce INTEGER DEFAULT 0,
            salesforce_account_id TEXT,
            salesforce_contact_owner_id TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS integrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'disconnected',
            config_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details TEXT,
            lead_id TEXT,
            client_id TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS batch_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            total_records INTEGER,
            processed INTEGER,
            succeeded INTEGER,
            failed INTEGER,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


init_db()


def load_configs():
    global client_configs, API_KEYS, integrations
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT client_id, config_json FROM client_configs")
    for row in c.fetchall():
        client_configs[row[0]] = json.loads(row[1])
    c.execute("SELECT key_hash FROM api_keys")
    for row in c.fetchall():
        API_KEYS[row[0]] = True
    c.execute("SELECT name, status, config_json FROM integrations")
    for row in c.fetchall():
        integrations[row[0]] = {"status": row[1], "config": json.loads(row[2]) if row[2] else {}}
    conn.close()


load_configs()


def log_activity(action: str, details: str = "", lead_id: str = "", client_id: str = "", status: str = "success"):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        INSERT INTO activity_logs (action, details, lead_id, client_id, status)
        VALUES (?, ?, ?, ?, ?)
    """, (action, details, lead_id, client_id, status))
    conn.commit()
    conn.close()


def verify_api_key(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization format")
    key = authorization[7:]
    if key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")
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
        log_activity("hubspot_push", "HubSpot API key not configured", status="failed")
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
            log_activity("hubspot_push", f"Pushed lead to HubSpot: {lead.get('email')}", status="success")
            return resp.json().get("id")
        else:
            log_activity("hubspot_push", f"HubSpot error: {resp.text}", status="failed")
    except Exception as e:
        log_activity("hubspot_push", f"HubSpot exception: {str(e)}", status="failed")
    return None


def push_to_salesforce(lead: dict, salesforce_config: dict) -> Optional[str]:
    if not SALESFORCE_INSTANCE_URL or not SALESFORCE_ACCESS_TOKEN:
        log_activity("salesforce_push", "Salesforce not configured", status="failed")
        return None
    url = f"{SALESFORCE_INSTANCE_URL}/services/data/v59.0/sobjects/Contact"
    headers = {"Authorization": f"Bearer {SALESFORCE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    contact_data = {
        "FirstName": lead.get("first_name", ""),
        "LastName": lead.get("last_name", ""),
        "Email": lead.get("email", ""),
        "Title": lead.get("title", ""),
        "AccountId": salesforce_config.get("account_id", ""),
        "OwnerId": salesforce_config.get("contact_owner_id", ""),
        "ICP_Score__c": lead.get("score", ""),
        "ICP_Tier__c": lead.get("tier", ""),
        "ICP_Confidence__c": lead.get("confidence", ""),
    }
    try:
        resp = requests.post(url, headers=headers, json=contact_data, timeout=10)
        if resp.status_code in [200, 201]:
            log_activity("salesforce_push", f"Pushed lead to Salesforce: {lead.get('email')}", status="success")
            return resp.json().get("id")
        else:
            log_activity("salesforce_push", f"Salesforce error: {resp.text}", status="failed")
    except Exception as e:
        log_activity("salesforce_push", f"Salesforce exception: {str(e)}", status="failed")
    return None


def save_lead(client_id: str, lead_data: dict, classification: dict, source: str = "api", source_id: str = "") -> int:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        INSERT INTO leads (
            client_id, source, source_id, company, domain, industry, headcount,
            funding_stage, hq_country, hq_region, tech_stack, job_signals,
            email, first_name, last_name, title, phone, score, tier, confidence, 
            recommended_action, signal_breakdown, reasons
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        client_id, source, source_id, lead_data.get("company"), lead_data.get("domain"),
        lead_data.get("industry"), lead_data.get("headcount"), lead_data.get("funding_stage"),
        lead_data.get("hq_country"), lead_data.get("hq_region"),
        json.dumps(lead_data.get("tech_stack", [])), json.dumps(lead_data.get("job_signals", [])),
        lead_data.get("email"), lead_data.get("first_name"), lead_data.get("last_name"),
        lead_data.get("title"), lead_data.get("phone"), classification.get("score"), 
        classification.get("tier"), classification.get("confidence"),
        classification.get("recommended_action"), json.dumps(classification.get("signal_breakdown", {})),
        json.dumps(classification.get("reasons", []))
    ))
    lead_id = c.lastrowid
    conn.commit()
    conn.close()
    log_activity("lead_saved", f"Saved lead: {lead_data.get('company')}", str(lead_id), client_id)
    return lead_id


def route_lead(client_id: str, lead_data: dict, classification: dict):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        SELECT route_to_db, route_to_hubspot, hubspot_pipeline, hubspot_stage,
               route_to_salesforce, salesforce_account_id, salesforce_contact_owner_id
        FROM routing_config WHERE client_id = ?
    """, (client_id,))
    row = c.fetchone()
    conn.close()

    routing = {"route_to_db": True, "route_to_hubspot": False, "route_to_salesforce": False}
    hubspot_config = {}
    salesforce_config = {}

    if row:
        routing = {"route_to_db": bool(row[0]), "route_to_hubspot": bool(row[1]), "route_to_salesforce": bool(row[4])}
        hubspot_config = {"pipeline": row[2], "stage": row[3]}
        salesforce_config = {"account_id": row[5], "contact_owner_id": row[6]}

    lead_id = None
    hubspot_id = None
    salesforce_id = None

    if routing["route_to_db"]:
        lead_id = save_lead(client_id, lead_data, classification)

    if routing["route_to_hubspot"]:
        hubspot_id = push_to_hubspot({**lead_data, **classification}, hubspot_config)

    if routing["route_to_salesforce"]:
        salesforce_id = push_to_salesforce({**lead_data, **classification}, salesforce_config)

    if lead_id and (hubspot_id or salesforce_id):
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        updates = []
        params = []
        if hubspot_id:
            updates.append("pushed_to_hubspot = 1, hubspot_contact_id = ?")
            params.append(hubspot_id)
        if salesforce_id:
            updates.append("pushed_to_salesforce = 1, salesforce_contact_id = ?")
            params.append(salesforce_id)
        params.append(lead_id)
        c.execute(f"UPDATE leads SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        conn.close()

    return {"lead_id": lead_id, "hubspot_contact_id": hubspot_id, "salesforce_contact_id": salesforce_id}


def get_dashboard_stats():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM leads")
    total_leads = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM leads WHERE tier = 'Tier 1'")
    tier1 = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM leads WHERE tier = 'Tier 2'")
    tier2 = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM leads WHERE tier = 'Not ICP'")
    not_icp = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM leads WHERE pushed_to_hubspot = 1")
    hubspot_pushed = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM leads WHERE pushed_to_salesforce = 1")
    salesforce_pushed = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM leads WHERE created_at >= date('now', '-7 days')")
    last_7_days = c.fetchone()[0]
    c.execute("SELECT tier, COUNT(*) as count FROM leads GROUP BY tier")
    tier_dist = c.fetchall()
    c.execute("SELECT client_id, COUNT(*) as count FROM leads GROUP BY client_id ORDER BY count DESC LIMIT 5")
    top_clients = c.fetchall()
    conn.close()
    return {
        "total_leads": total_leads, "tier1": tier1, "tier2": tier2, "not_icp": not_icp,
        "hubspot_pushed": hubspot_pushed, "salesforce_pushed": salesforce_pushed,
        "last_7_days": last_7_days,
        "tier_dist": [{"tier": r[0], "count": r[1]} for r in tier_dist],
        "top_clients": [{"client_id": r[0], "count": r[1]} for r in top_clients]
    }


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ICP Classifier Admin</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-gray-100">
    <div class="flex h-screen">
        <div class="w-64 bg-gray-900 text-white p-5">
            <h1 class="text-2xl font-bold mb-8"><i class="fas fa-layer-group mr-2"></i>ICP Classifier</h1>
            <nav class="space-y-2">
                <a href="/admin" class="block py-3 px-4 rounded hover:bg-gray-800"><i class="fas fa-chart-pie mr-2"></i>Dashboard</a>
                <a href="/admin/leads" class="block py-3 px-4 rounded hover:bg-gray-800"><i class="fas fa-users mr-2"></i>Leads</a>
                <a href="/admin/clients" class="block py-3 px-4 rounded hover:bg-gray-800"><i class="fas fa-building mr-2"></i>Clients</a>
                <a href="/admin/integrations" class="block py-3 px-4 rounded hover:bg-gray-800"><i class="fas fa-plug mr-2"></i>Integrations</a>
                <a href="/admin/import" class="block py-3 px-4 rounded hover:bg-gray-800"><i class="fas fa-file-import mr-2"></i>Import</a>
                <a href="/admin/logs" class="block py-3 px-4 rounded hover:bg-gray-800"><i class="fas fa-history mr-2"></i>Logs</a>
            </nav>
        </div>
        <div class="flex-1 overflow-auto p-8">
            {{content}}
        </div>
    </div>
</body>
</html>
"""


def render_page(title: str, content: str) -> HTMLResponse:
    return HTMLResponse(content=HTML_TEMPLATE.replace("{{content}}", f'<h1 class="text-3xl font-bold mb-6">{title}</h1>' + content))


@app.get("/health")
def health_check():
    return {"status": "healthy", "clients": len(client_configs)}


@app.get("/admin")
def dashboard():
    stats = get_dashboard_stats()
    content = f"""
    <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
        <div class="bg-white p-6 rounded-lg shadow">
            <div class="text-gray-500 text-sm">Total Leads</div>
            <div class="text-3xl font-bold">{stats['total_leads']}</div>
            <div class="text-green-500 text-sm mt-2">{stats['last_7_days']} this week</div>
        </div>
        <div class="bg-white p-6 rounded-lg shadow">
            <div class="text-gray-500 text-sm">Tier 1 Leads</div>
            <div class="text-3xl font-bold text-green-600">{stats['tier1']}</div>
        </div>
        <div class="bg-white p-6 rounded-lg shadow">
            <div class="text-gray-500 text-sm">Tier 2 Leads</div>
            <div class="text-3xl font-bold text-yellow-600">{stats['tier2']}</div>
        </div>
        <div class="bg-white p-6 rounded-lg shadow">
            <div class="text-gray-500 text-sm">Pushed to CRM</div>
            <div class="text-3xl font-bold">{stats['hubspot_pushed'] + stats['salesforce_pushed']}</div>
        </div>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div class="bg-white p-6 rounded-lg shadow">
            <h3 class="text-lg font-bold mb-4">Tier Distribution</h3>
    """
    for t in stats["tier_dist"]:
        pct = (t["count"] / stats["total_leads"] * 100) if stats["total_leads"] > 0 else 0
        content += f"""
            <div class="mb-3">
                <div class="flex justify-between text-sm"><span>{t['tier']}</span><span>{t['count']} ({pct:.1f}%)</span></div>
                <div class="w-full bg-gray-200 rounded-full h-2 mt-1"><div class="bg-purple-600 h-2 rounded-full" style="width: {pct}%"></div></div>
            </div>"""
    content += """
        </div>
        <div class="bg-white p-6 rounded-lg shadow">
            <h3 class="text-lg font-bold mb-4">Top Clients</h3>
    """
    for c in stats["top_clients"]:
        content += f'<div class="flex justify-between p-2 bg-gray-50 rounded mb-2"><span>{c["client_id"]}</span><span class="font-bold">{c["count"]}</span></div>'
    content += "</div></div>"
    return render_page("Dashboard", content)


@app.get("/admin/leads")
def leads_page(page: int = 1, search: str = "", tier: str = ""):
    offset = (page - 1) * 20
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    query = "SELECT id, client_id, company, email, first_name, last_name, title, score, tier, confidence, recommended_action, pushed_to_hubspot, pushed_to_salesforce, created_at FROM leads WHERE 1=1"
    params = []
    if search:
        query += " AND (company LIKE ? OR email LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    if tier:
        query += " AND tier = ?"
        params.append(tier)
    query += " ORDER BY created_at DESC LIMIT 20 OFFSET ?"
    params.append(offset)
    c.execute(query, params)
    rows = c.fetchall()
    c.execute("SELECT COUNT(*) FROM leads")
    total = c.fetchone()[0]
    conn.close()
    content = f"""
    <div class="mb-4 flex gap-4">
        <input type="text" id="search" placeholder="Search company or email..." class="px-4 py-2 border rounded-lg w-64" value="{search}">
        <select id="tierFilter" class="px-4 py-2 border rounded-lg">
            <option value="">All Tiers</option>
            <option value="Tier 1" {'selected' if tier=='Tier 1' else ''}>Tier 1</option>
            <option value="Tier 2" {'selected' if tier=='Tier 2' else ''}>Tier 2</option>
            <option value="Not ICP" {'selected' if tier=='Not ICP' else ''}>Not ICP</option>
        </select>
    </div>
    <div class="bg-white rounded-lg shadow overflow-hidden">
        <table class="w-full">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-6 py-3 text-left">Company</th>
                    <th class="px-6 py-3 text-left">Contact</th>
                    <th class="px-6 py-3 text-left">Tier</th>
                    <th class="px-6 py-3 text-left">Score</th>
                    <th class="px-6 py-3 text-left">Action</th>
                    <th class="px-6 py-3 text-left">CRM</th>
                </tr>
            </thead>
            <tbody>"""
    for r in rows:
        hubspot_icon = '<i class="fab fa-hubspot text-orange-500"></i>' if r[11] else '<span class="text-gray-300">-</span>'
        sf_icon = '<i class="fab fa-salesforce text-blue-500"></i>' if r[12] else '<span class="text-gray-300">-</span>'
        tier_class = "bg-green-100 text-green-800" if r[8] == "Tier 1" else ("bg-yellow-100 text-yellow-800" if r[8] == "Tier 2" else "bg-gray-100 text-gray-800")
        content += f"""<tr class="border-t hover:bg-gray-50">
            <td class="px-6 py-4">{r[2]}</td>
            <td class="px-6 py-4">{r[4] or ''} {r[5] or ''}<br><span class="text-gray-500 text-sm">{r[6] or ''}</span></td>
            <td class="px-6 py-4"><span class="px-2 py-1 rounded text-sm {tier_class}">{r[8]}</span></td>
            <td class="px-6 py-4">{r[7]}</td>
            <td class="px-6 py-4">{r[10]}</td>
            <td class="px-6 py-4">{hubspot_icon} {sf_icon}</td>
        </tr>"""
    content += f"""
            </tbody>
        </table>
    </div>
    <div class="mt-4 text-gray-600">Total leads: {total}</div>
    """
    return render_page("Leads", content)


@app.get("/admin/clients")
def clients_page():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT client_id, config_json, updated_at FROM client_configs")
    rows = c.fetchall()
    conn.close()
    content = '<div class="mb-4"><button class="px-4 py-2 bg-purple-600 text-white rounded-lg">+ Add Client</button></div><div class="grid grid-cols-1 md:grid-cols-2 gap-6">'
    for r in rows:
        config = json.loads(r[1])
        content += f"""<div class="bg-white p-6 rounded-lg shadow">
            <h3 class="text-xl font-bold">{r[0]}</h3>
            <p class="text-gray-500 text-sm">Updated: {r[2][:10]}</p>
            <div class="mt-4 grid grid-cols-2 gap-2 text-sm">
                <div><span class="text-gray-500">Industries:</span> {len(config.get('target_industries', []))}</div>
                <div><span class="text-gray-500">T1 Threshold:</span> {config.get('t1_threshold', 70)}</div>
            </div>
        </div>"""
    content += "</div>"
    return render_page("Clients", content)


@app.get("/admin/integrations")
def integrations_page():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT name, status FROM integrations")
    rows = c.fetchall()
    conn.close()
    status_map = {r[0]: r[1] for r in rows}
    content = """
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div class="bg-white p-6 rounded-lg shadow">
            <div class="flex items-center justify-between mb-4">
                <h3 class="text-xl font-bold"><i class="fab fa-apollo text-2xl mr-2"></i>Apollo</h3>
                <span class="px-3 py-1 rounded-full text-sm bg-green-100 text-green-800">""" + status_map.get("apollo", "disconnected") + """</span>
            </div>
            <button class="w-full py-2 bg-purple-600 text-white rounded-lg">Configure</button>
        </div>
        <div class="bg-white p-6 rounded-lg shadow">
            <div class="flex items-center justify-between mb-4">
                <h3 class="text-xl font-bold"><i class="fab fa-hubspot text-2xl mr-2" style="color:#ff7a59"></i>HubSpot</h3>
                <span class="px-3 py-1 rounded-full text-sm bg-green-100 text-green-800">""" + status_map.get("hubspot", "disconnected") + """</span>
            </div>
            <button class="w-full py-2 bg-purple-600 text-white rounded-lg">Configure</button>
        </div>
        <div class="bg-white p-6 rounded-lg shadow">
            <div class="flex items-center justify-between mb-4">
                <h3 class="text-xl font-bold"><i class="fab fa-salesforce text-2xl mr-2" style="color:#00a1e0"></i>Salesforce</h3>
                <span class="px-3 py-1 rounded-full text-sm bg-green-100 text-green-800">""" + status_map.get("salesforce", "disconnected") + """</span>
            </div>
            <button class="w-full py-2 bg-purple-600 text-white rounded-lg">Configure</button>
        </div>
    </div>"""
    return render_page("Integrations", content)


@app.get("/admin/import")
def import_page():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT client_id FROM client_configs")
    clients = [r[0] for r in c.fetchall()]
    conn.close()
    options = "".join([f'<option value="{c}">{c}</option>' for c in clients])
    content = f"""
    <div class="bg-white p-8 rounded-lg shadow">
        <h3 class="text-xl font-bold mb-4">Import Leads from Apollo</h3>
        <form class="space-y-4">
            <div><label class="block text-sm font-medium mb-2">Select Client</label>
            <select class="w-full px-4 py-2 border rounded-lg">{options}</select></div>
            <div><label class="block text-sm font-medium mb-2">Upload CSV</label>
            <input type="file" accept=".csv" class="w-full px-4 py-2 border rounded-lg"></div>
            <button type="button" class="px-6 py-2 bg-purple-600 text-white rounded-lg">Import & Classify</button>
        </form>
    </div>"""
    return render_page("Import Leads", content)


@app.get("/admin/logs")
def logs_page():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT action, details, lead_id, client_id, status, created_at FROM activity_logs ORDER BY created_at DESC LIMIT 100")
    rows = c.fetchall()
    conn.close()
    content = """
    <div class="bg-white rounded-lg shadow overflow-hidden">
        <table class="w-full">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-6 py-3 text-left">Action</th>
                    <th class="px-6 py-3 text-left">Details</th>
                    <th class="px-6 py-3 text-left">Status</th>
                    <th class="px-6 py-3 text-left">Time</th>
                </tr>
            </thead>
            <tbody>"""
    for r in rows:
        status_class = "text-green-600" if r[4] == "success" else "text-red-600"
        content += f"""<tr class="border-t">
            <td class="px-6 py-4 font-medium">{r[0]}</td>
            <td class="px-6 py-4 text-gray-600">{r[1]}</td>
            <td class="px-6 py-4 {status_class}">{r[4]}</td>
            <td class="px-6 py-4 text-gray-500">{r[5]}</td>
        </tr>"""
    content += "</tbody></table></div>"
    return render_page("Activity Logs", content)


@app.post("/classify")
def classify(request: dict, authorization: Optional[str] = Header(None)):
    verify_api_key(authorization)
    client_config = request.get("client_config")
    client_id = request.get("client_id")
    lead = request.get("lead")
    if not lead:
        raise HTTPException(status_code=400, detail="Missing lead")
    if client_config:
        config = client_config
    elif client_id and client_id in client_configs:
        config = client_configs[client_id]
    else:
        raise HTTPException(status_code=400, detail="Provide client_config or valid client_id")
    result = _classify(config, lead)
    if request.get("route", {}).get("save_to_db", True):
        route_result = route_lead(client_id or config.get("client_id", "unknown"), lead, result)
        result["lead_id"] = route_result["lead_id"]
        result["hubspot_contact_id"] = route_result["hubspot_contact_id"]
        result["salesforce_contact_id"] = route_result["salesforce_contact_id"]
    return result


@app.post("/admin/api-keys")
def create_api_key(data: dict, authorization: Optional[str] = Header(None)):
    verify_api_key(authorization)
    key = secrets.token_urlsafe(32)
    API_KEYS[key] = True
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("INSERT INTO api_keys (key_hash, label) VALUES (?, ?)", (key, data.get("label", "unnamed")))
    conn.commit()
    conn.close()
    return {"api_key": key, "label": data.get("label", "unnamed")}


@app.post("/admin/client-configs")
def save_client_config(data: dict, authorization: Optional[str] = Header(None)):
    verify_api_key(authorization)
    client_id = data.get("client_id")
    config = data.get("config")
    if not client_id or not config:
        raise HTTPException(status_code=400, detail="Missing client_id or config")
    client_configs[client_id] = config
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO client_configs (client_id, config_json, updated_at) VALUES (?, ?, ?)",
              (client_id, json.dumps(config), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    log_activity("config_updated", f"Updated config for {client_id}", client_id=client_id)
    return {"status": "saved", "client_id": client_id}


@app.get("/admin/client-configs/{client_id}")
def get_client_config(client_id: str, authorization: Optional[str] = Header(None)):
    verify_api_key(authorization)
    if client_id not in client_configs:
        raise HTTPException(status_code=404, detail="Client not found")
    return client_configs[client_id]


@app.post("/admin/routing")
def save_routing(data: dict, authorization: Optional[str] = Header(None)):
    verify_api_key(authorization)
    client_id = data.get("client_id")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO routing_config 
        (client_id, route_to_db, route_to_hubspot, hubspot_pipeline, hubspot_stage, 
         route_to_salesforce, salesforce_account_id, salesforce_contact_owner_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (client_id, int(data.get("route_to_db", True)), int(data.get("route_to_hubspot", False)),
         data.get("hubspot_pipeline", ""), data.get("hubspot_stage", ""),
         int(data.get("route_to_salesforce", False)), data.get("salesforce_account_id", ""),
         data.get("salesforce_contact_owner_id", ""), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    log_activity("routing_updated", f"Updated routing for {client_id}", client_id=client_id)
    return {"status": "saved", "client_id": client_id}


@app.get("/admin/stats")
def get_stats(authorization: Optional[str] = Header(None)):
    verify_api_key(authorization)
    return get_dashboard_stats()


@app.get("/admin/leads-api")
def leads_api(authorization: Optional[str] = Header(None)):
    verify_api_key(authorization)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, client_id, company, email, score, tier, confidence, action, hubspot, salesforce, created_at FROM (SELECT l.id, l.client_id, l.company, l.email, l.score, l.tier, l.confidence, l.recommended_action as action, l.pushed_to_hubspot as hubspot, l.pushed_to_salesforce as salesforce, l.created_at FROM leads ORDER BY l.created_at DESC LIMIT 100)")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "client_id": r[1], "company": r[2], "email": r[3], "score": r[4], "tier": r[5], "confidence": r[6], "action": r[7], "hubspot": bool(r[8]), "salesforce": bool(r[9]), "created_at": r[10]} for r in rows]


@app.get("/admin/lead/{lead_id}")
def get_lead(lead_id: str, authorization: Optional[str] = Header(None)):
    verify_api_key(authorization)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"id": row[0], "client_id": row[1], "data": {"company": row[3], "domain": row[4], "industry": row[5], "headcount": row[6], "funding_stage": row[7], "hq_country": row[8], "tech_stack": json.loads(row[10] or "[]"), "job_signals": json.loads(row[11] or "[]"), "email": row[12], "first_name": row[13], "last_name": row[14], "title": row[15]}, "classification": {"score": row[17], "tier": row[18], "confidence": row[19], "action": row[20], "signal_breakdown": json.loads(row[21] or "{}"), "reasons": json.loads(row[22] or "[]")}, "integrations": {"hubspot_id": row[24], "salesforce_id": row[26]}}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
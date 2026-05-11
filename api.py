import json
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import secrets
import os
import requests
from classifier import classify_lead as _classify
import hashlib

from fastapi import FastAPI, HTTPException, Header, Request, Response, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI(title="ICP Classifier")
app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32))

client_configs = {}
API_KEYS = {}
integrations = {}

db_path = "classifier.db"

APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY", "")
HUBSPOT_API_KEY = os.environ.get("HUBSPOT_API_KEY", "")
SALESFORCE_INSTANCE_URL = os.environ.get("SALESFORCE_INSTANCE_URL", "")
SALESFORCE_ACCESS_TOKEN = os.environ.get("SALESFORCE_ACCESS_TOKEN", "")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

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
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("SELECT COUNT(*) FROM admin_users")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO admin_users (username, password_hash) VALUES (?, ?)", 
                  ("admin", hash_password("admin123")))
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


def verify_session(request: Request) -> bool:
    return request.session.get("authenticated", False)


def log_activity(action: str, details: str = "", lead_id: str = "", client_id: str = "", status: str = "success"):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("INSERT INTO activity_logs (action, details, lead_id, client_id, status) VALUES (?, ?, ?, ?, ?)",
              (action, details, lead_id, client_id, status))
    conn.commit()
    conn.close()


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
        log_activity("hubspot_push", "HubSpot not configured", status="failed")
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
    try:
        resp = requests.post(url, headers=headers, json={"properties": properties}, timeout=10)
        if resp.status_code in [200, 201]:
            log_activity("hubspot_push", f"Pushed: {lead.get('email')}", status="success")
            return resp.json().get("id")
        log_activity("hubspot_push", f"Error: {resp.text}", status="failed")
    except Exception as e:
        log_activity("hubspot_push", str(e), status="failed")
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
        "ICP_Score__c": str(lead.get("score", "")),
        "ICP_Tier__c": lead.get("tier", ""),
    }
    try:
        resp = requests.post(url, headers=headers, json=contact_data, timeout=10)
        if resp.status_code in [200, 201]:
            log_activity("salesforce_push", f"Pushed: {lead.get('email')}", status="success")
            return resp.json().get("id")
        log_activity("salesforce_push", f"Error: {resp.text}", status="failed")
    except Exception as e:
        log_activity("salesforce_push", str(e), status="failed")
    return None


def save_lead(client_id: str, lead_data: dict, classification: dict) -> int:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""INSERT INTO leads (client_id, company, domain, industry, headcount, funding_stage, hq_country, hq_region, tech_stack, job_signals, email, first_name, last_name, title, phone, score, tier, confidence, recommended_action, signal_breakdown, reasons) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (client_id, lead_data.get("company"), lead_data.get("domain"), lead_data.get("industry"), lead_data.get("headcount"), lead_data.get("funding_stage"), lead_data.get("hq_country"), lead_data.get("hq_region"), json.dumps(lead_data.get("tech_stack", [])), json.dumps(lead_data.get("job_signals", [])), lead_data.get("email"), lead_data.get("first_name"), lead_data.get("last_name"), lead_data.get("title"), lead_data.get("phone"), classification.get("score"), classification.get("tier"), classification.get("confidence"), classification.get("recommended_action"), json.dumps(classification.get("signal_breakdown", {})), json.dumps(classification.get("reasons", []))))
    lead_id = c.lastrowid
    conn.commit()
    conn.close()
    log_activity("lead_saved", f"Saved: {lead_data.get('company')}", str(lead_id), client_id)
    return lead_id


def route_lead(client_id: str, lead_data: dict, classification: dict):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT route_to_db, route_to_hubspot, hubspot_pipeline, hubspot_stage, route_to_salesforce, salesforce_account_id FROM routing_config WHERE client_id = ?", (client_id,))
    row = c.fetchone()
    conn.close()
    routing = {"route_to_db": True, "route_to_hubspot": False, "route_to_salesforce": False}
    hubspot_cfg, sf_cfg = {}, {}
    if row:
        routing = {"route_to_db": bool(row[0]), "route_to_hubspot": bool(row[1]), "route_to_salesforce": bool(row[4])}
        hubspot_cfg = {"pipeline": row[2], "stage": row[3]}
        sf_cfg = {"account_id": row[5]}
    lead_id = save_lead(client_id, lead_data, classification) if routing["route_to_db"] else None
    hubspot_id = push_to_hubspot({**lead_data, **classification}, hubspot_cfg) if routing["route_to_hubspot"] else None
    sf_id = push_to_salesforce({**lead_data, **classification}, sf_cfg) if routing["route_to_salesforce"] else None
    if lead_id and (hubspot_id or sf_id):
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        updates, params = [], []
        if hubspot_id:
            updates.append("pushed_to_hubspot=1, hubspot_contact_id=?")
            params.append(hubspot_id)
        if sf_id:
            updates.append("pushed_to_salesforce=1, salesforce_contact_id=?")
            params.append(sf_id)
        params.append(lead_id)
        c.execute(f"UPDATE leads SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        conn.close()
    return {"lead_id": lead_id, "hubspot_contact_id": hubspot_id, "salesforce_contact_id": sf_id}


def get_dashboard_stats():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM leads")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM leads WHERE tier = 'Tier 1'")
    tier1 = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM leads WHERE tier = 'Tier 2'")
    tier2 = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM leads WHERE tier = 'Not ICP'")
    not_icp = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM leads WHERE pushed_to_hubspot = 1")
    hubspot = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM leads WHERE pushed_to_salesforce = 1")
    salesforce = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM leads WHERE created_at >= date('now', '-7 days')")
    week = c.fetchone()[0]
    c.execute("SELECT tier, COUNT(*) FROM leads GROUP BY tier")
    tier_dist = c.fetchall()
    c.execute("SELECT client_id, COUNT(*) FROM leads GROUP BY client_id ORDER BY COUNT(*) DESC LIMIT 5")
    top_clients = c.fetchall()
    conn.close()
    return {"total_leads": total, "tier1": tier1, "tier2": tier2, "not_icp": not_icp, "hubspot_pushed": hubspot, "salesforce_pushed": salesforce, "last_7_days": week, "tier_dist": [{"tier": r[0], "count": r[1]} for r in tier_dist], "top_clients": [{"client_id": r[0], "count": r[1]} for r in top_clients]}


LOGIN_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - ICP Classifier</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gradient-to-br from-purple-600 to-indigo-700 min-h-screen flex items-center justify-center">
    <div class="bg-white rounded-2xl shadow-2xl p-8 w-96">
        <h1 class="text-3xl font-bold text-center mb-8 text-gray-800">ICP Classifier</h1>
        <form method="post">
            <div class="mb-4">
                <label class="block text-gray-700 text-sm font-bold mb-2">Username</label>
                <input type="text" name="username" class="w-full px-4 py-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500" required>
            </div>
            <div class="mb-6">
                <label class="block text-gray-700 text-sm font-bold mb-2">Password</label>
                <input type="password" name="password" class="w-full px-4 py-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500" required>
            </div>
            <button type="submit" class="w-full bg-purple-600 text-white py-3 rounded-lg font-bold hover:bg-purple-700 transition">Login</button>
        </form>
        {% if error %}
        <div class="mt-4 p-3 bg-red-100 text-red-700 rounded-lg text-center">{{error}}</div>
        {% endif %}
    </div>
</body>
</html>
"""

ADMIN_TEMPLATE = """
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
            <div class="mb-6 pb-4 border-b border-gray-700">
                <div class="text-sm text-gray-400">Logged in as</div>
                <div class="font-bold">Admin</div>
            </div>
            <nav class="space-y-2">
                <a href="/admin/dashboard" class="block py-3 px-4 rounded hover:bg-gray-800 {% if page == 'dashboard' %}bg-purple-700{% endif %}"><i class="fas fa-chart-pie mr-2"></i>Dashboard</a>
                <a href="/admin/leads" class="block py-3 px-4 rounded hover:bg-gray-800 {% if page == 'leads' %}bg-purple-700{% endif %}"><i class="fas fa-users mr-2"></i>Leads</a>
                <a href="/admin/clients" class="block py-3 px-4 rounded hover:bg-gray-800 {% if page == 'clients' %}bg-purple-700{% endif %}"><i class="fas fa-building mr-2"></i>Clients</a>
                <a href="/admin/integrations" class="block py-3 px-4 rounded hover:bg-gray-800 {% if page == 'integrations' %}bg-purple-700{% endif %}"><i class="fas fa-plug mr-2"></i>Integrations</a>
                <a href="/admin/logs" class="block py-3 px-4 rounded hover:bg-gray-800 {% if page == 'logs' %}bg-purple-700{% endif %}"><i class="fas fa-history mr-2"></i>Activity Logs</a>
                <a href="/admin/settings" class="block py-3 px-4 rounded hover:bg-gray-800 {% if page == 'settings' %}bg-purple-700{% endif %}"><i class="fas fa-cog mr-2"></i>Settings</a>
            </nav>
            <div class="mt-auto pt-4 border-t border-gray-700">
                <a href="/admin/logout" class="block py-2 px-4 rounded text-red-400 hover:bg-gray-800"><i class="fas fa-sign-out-alt mr-2"></i>Logout</a>
            </div>
        </div>
        <div class="flex-1 overflow-auto p-8">
            {{content}}
        </div>
    </div>
</body>
</html>
"""

def render_admin(page: str, content: str) -> HTMLResponse:
    return HTMLResponse(content=ADMIN_TEMPLATE.replace("{{content}}", f'<h1 class="text-3xl font-bold mb-6">{page.title()}</h1>' + content).replace("{{page}}", page))


@app.get("/")
def root():
    return {"message": "ICP Classifier API", "docs": "/docs", "admin": "/admin/login"}


@app.get("/health")
def health_check():
    return {"status": "healthy", "clients": len(client_configs)}


@app.get("/admin/login")
def login_page(error: str = ""):
    return HTMLResponse(content=LOGIN_PAGE.replace("{{error}}", error))


@app.post("/admin/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT password_hash FROM admin_users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    if row and row[0] == hash_password(password):
        request.session["authenticated"] = True
        request.session["username"] = username
        return HTMLResponse(content='<script>window.location.href="/admin/dashboard";</script>')
    return HTMLResponse(content=LOGIN_PAGE.replace("{{error}}", "Invalid username or password"))


@app.get("/admin/logout")
def logout(request: Request):
    request.session.clear()
    return HTMLResponse(content='<script>window.location.href="/admin/login";</script>')


@app.get("/admin/dashboard")
def dashboard(request: Request):
    if not verify_session(request):
        return HTMLResponse(content='<script>window.location.href="/admin/login";</script>')
    stats = get_dashboard_stats()
    content = f"""
    <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
        <div class="bg-white p-6 rounded-lg shadow">
            <div class="text-gray-500 text-sm">Total Leads</div>
            <div class="text-3xl font-bold">{stats['total_leads']}</div>
            <div class="text-green-500 text-sm mt-2">{stats['last_7_days']} this week</div>
        </div>
        <div class="bg-white p-6 rounded-lg shadow">
            <div class="text-gray-500 text-sm">Tier 1 (Hot)</div>
            <div class="text-3xl font-bold text-green-600">{stats['tier1']}</div>
        </div>
        <div class="bg-white p-6 rounded-lg shadow">
            <div class="text-gray-500 text-sm">Tier 2 (Warm)</div>
            <div class="text-3xl font-bold text-yellow-600">{stats['tier2']}</div>
        </div>
        <div class="bg-white p-6 rounded-lg shadow">
            <div class="text-gray-500 text-sm">CRM Pushed</div>
            <div class="text-3xl font-bold">{stats['hubspot_pushed'] + stats['salesforce_pushed']}</div>
        </div>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div class="bg-white p-6 rounded-lg shadow">
            <h3 class="text-lg font-bold mb-4">Tier Distribution</h3>
    """
    for t in stats["tier_dist"]:
        pct = (t["count"] / stats["total_leads"] * 100) if stats["total_leads"] > 0 else 0
        content += f'<div class="mb-3"><div class="flex justify-between text-sm"><span>{t["tier"]}</span><span>{t["count"]} ({pct:.1f}%)</span></div><div class="w-full bg-gray-200 rounded-full h-2 mt-1"><div class="bg-purple-600 h-2 rounded-full" style="width:{pct}%"></div></div></div>'
    content += "</div><div class='bg-white p-6 rounded-lg shadow'><h3 class='text-lg font-bold mb-4'>Top Clients</h3>"
    for c in stats["top_clients"]:
        content += f'<div class="flex justify-between p-2 bg-gray-50 rounded mb-2"><span>{c["client_id"]}</span><span class="font-bold">{c["count"]}</span></div>'
    content += "</div></div>"
    return render_admin("dashboard", content)


@app.get("/admin/leads")
def leads(request: Request, search: str = "", tier: str = ""):
    if not verify_session(request):
        return HTMLResponse(content='<script>window.location.href="/admin/login";</script>')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    query = "SELECT id, client_id, company, email, first_name, last_name, title, score, tier, confidence, recommended_action, pushed_to_hubspot, pushed_to_salesforce FROM leads WHERE 1=1"
    params = []
    if search:
        query += " AND (company LIKE ? OR email LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    if tier:
        query += " AND tier = ?"
        params.append(tier)
    query += " ORDER BY id DESC LIMIT 50"
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    content = f"""
    <div class="mb-4 flex gap-4">
        <input type="text" id="search" placeholder="Search..." class="px-4 py-2 border rounded-lg" value="{search}">
        <select id="tier" class="px-4 py-2 border rounded-lg">
            <option value="">All</option>
            <option value="Tier 1" {'selected' if tier=='Tier 1' else ''}>Tier 1</option>
            <option value="Tier 2" {'selected' if tier=='Tier 2' else ''}>Tier 2</option>
            <option value="Not ICP" {'selected' if tier=='Not ICP' else ''}>Not ICP</option>
        </select>
    </div>
    <div class="bg-white rounded-lg shadow overflow-x">
        <table class="w-full">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-4 py-3 text-left">Company</th>
                    <th class="px-4 py-3 text-left">Contact</th>
                    <th class="px-4 py-3 text-left">Tier</th>
                    <th class="px-4 py-3 text-left">Score</th>
                    <th class="px-4 py-3 text-left">Action</th>
                    <th class="px-4 py-3 text-left">CRM</th>
                </tr>
            </thead>
            <tbody>"""
    for r in rows:
        hubspot = '<i class="fab fa-hubspot text-orange-500"></i>' if r[11] else '-'
        sf = '<i class="fab fa-salesforce text-blue-500"></i>' if r[12] else '-'
        tier_cls = "bg-green-100 text-green-800" if r[8] == "Tier 1" else ("bg-yellow-100 text-yellow-800" if r[8] == "Tier 2" else "bg-gray-100 text-gray-800")
        content += f"""<tr class="border-t">
            <td class="px-4 py-3">{r[2]}</td>
            <td class="px-4 py-3">{r[4] or ''} {r[5] or ''}<br><span class="text-gray-500 text-sm">{r[6] or ''}</span></td>
            <td class="px-4 py-3"><span class="px-2 py-1 rounded text-sm {tier_cls}">{r[8]}</span></td>
            <td class="px-4 py-3">{r[7]}</td>
            <td class="px-4 py-3">{r[10]}</td>
            <td class="px-4 py-3">{hubspot} {sf}</td>
        </tr>"""
    content += "</tbody></table></div>"
    return render_admin("leads", content)


@app.get("/admin/clients")
def clients(request: Request):
    if not verify_session(request):
        return HTMLResponse(content='<script>window.location.href="/admin/login";</script>')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT client_id, config_json, updated_at FROM client_configs")
    rows = c.fetchall()
    c.execute("SELECT client_id, route_to_hubspot, route_to_salesforce FROM routing_config")
    routing = {r[0]: {"hubspot": r[1], "salesforce": r[2]} for r in c.fetchall()}
    conn.close()
    content = '<div class="grid grid-cols-1 md:grid-cols-2 gap-6">'
    for r in rows:
        config = json.loads(r[1])
        rt = routing.get(r[0], {"hubspot": 0, "salesforce": 0})
        content += f"""<div class="bg-white p-6 rounded-lg shadow">
            <div class="flex justify-between items-start">
                <h3 class="text-xl font-bold">{r[0]}</h3>
                <span class="text-gray-400 text-sm">{r[2][:10]}</span>
            </div>
            <div class="mt-4 space-y-2 text-sm">
                <div><span class="text-gray-500">Industries:</span> {', '.join(config.get('target_industries', []))}</div>
                <div><span class="text-gray-500">Headcount:</span> {config.get('hc_min', 0)} - {config.get('hc_max', 0)}</div>
                <div><span class="text-gray-500">T1 Threshold:</span> {config.get('t1_threshold', 70)}</div>
                <div><span class="text-gray-500">HubSpot:</span> {'<i class="fas fa-check text-green-500"></i>' if rt['hubspot'] else '<i class="fas fa-times text-red-400"></i>'}</div>
                <div><span class="text-gray-500">Salesforce:</span> {'<i class="fas fa-check text-green-500"></i>' if rt['salesforce'] else '<i class="fas fa-times text-red-400"></i>'}</div>
            </div>
        </div>"""
    content += "</div>"
    return render_admin("clients", content)


@app.get("/admin/integrations")
def integrations(request: Request):
    if not verify_session(request):
        return HTMLResponse(content='<script>window.location.href="/admin/login";</script>')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT name, status, config_json FROM integrations")
    rows = c.fetchall()
    conn.close()
    status = {r[0]: {"status": r[1], "config": json.loads(r[2]) if r[2] else {}} for r in rows}
    apollo_st = status.get("apollo", {}).get("status", "disconnected")
    hubspot_st = status.get("hubspot", {}).get("status", "disconnected")
    sf_st = status.get("salesforce", {}).get("status", "disconnected")
    content = f"""
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div class="bg-white p-6 rounded-lg shadow">
            <div class="flex items-center justify-between mb-4">
                <h3 class="text-xl font-bold"><i class="fas fa-database mr-2"></i>Apollo</h3>
                <span class="px-3 py-1 rounded-full text-sm {'bg-green-100 text-green-800' if apollo_st=='connected' else 'bg-gray-100 text-gray-600'}">{apollo_st}</span>
            </div>
            <p class="text-gray-600 text-sm mb-4">Lead enrichment and webhook integration</p>
            <div class="text-sm">
                <div class="flex justify-between py-2 border-b"><span>API Key</span><span class="text-green-500">{'Configured' if APOLLO_API_KEY else 'Missing'}</span></div>
            </div>
        </div>
        <div class="bg-white p-6 rounded-lg shadow">
            <div class="flex items-center justify-between mb-4">
                <h3 class="text-xl font-bold"><i class="fab fa-hubspot mr-2" style="color:#ff7a59"></i>HubSpot</h3>
                <span class="px-3 py-1 rounded-full text-sm {'bg-green-100 text-green-800' if hubspot_st=='connected' else 'bg-gray-100 text-gray-600'}">{hubspot_st}</span>
            </div>
            <p class="text-gray-600 text-sm mb-4">Push leads to HubSpot contacts</p>
            <div class="text-sm">
                <div class="flex justify-between py-2 border-b"><span>API Key</span><span class="text-green-500">{'Configured' if HUBSPOT_API_KEY else 'Missing'}</span></div>
            </div>
        </div>
        <div class="bg-white p-6 rounded-lg shadow">
            <div class="flex items-center justify-between mb-4">
                <h3 class="text-xl font-bold"><i class="fab fa-salesforce mr-2" style="color:#00a1e0"></i>Salesforce</h3>
                <span class="px-3 py-1 rounded-full text-sm {'bg-green-100 text-green-800' if sf_st=='connected' else 'bg-gray-100 text-gray-600'}">{sf_st}</span>
            </div>
            <p class="text-gray-600 text-sm mb-4">Push leads to Salesforce contacts</p>
            <div class="text-sm">
                <div class="flex justify-between py-2 border-b"><span>Instance URL</span><span class="text-green-500">{'Configured' if SALESFORCE_INSTANCE_URL else 'Missing'}</span></div>
                <div class="flex justify-between py-2 border-b"><span>Access Token</span><span class="text-green-500">{'Configured' if SALESFORCE_ACCESS_TOKEN else 'Missing'}</span></div>
            </div>
        </div>
    </div>"""
    return render_admin("integrations", content)


@app.get("/admin/logs")
def logs(request: Request):
    if not verify_session(request):
        return HTMLResponse(content='<script>window.location.href="/admin/login";</script>')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT action, details, lead_id, client_id, status, created_at FROM activity_logs ORDER BY created_at DESC LIMIT 100")
    rows = c.fetchall()
    conn.close()
    content = '<div class="bg-white rounded-lg shadow overflow-x"><table class="w-full"><thead class="bg-gray-50"><tr><th class="px-4 py-3 text-left">Action</th><th class="px-4 py-3 text-left">Details</th><th class="px-4 py-3 text-left">Lead</th><th class="px-4 py-3 text-left">Client</th><th class="px-4 py-3 text-left">Status</th><th class="px-4 py-3 text-left">Time</th></tr></thead><tbody>'
    for r in rows:
        status_cls = "text-green-600" if r[4] == "success" else "text-red-600"
        content += f"""<tr class="border-t">
            <td class="px-4 py-3 font-medium">{r[0]}</td>
            <td class="px-4 py-3 text-gray-600">{r[1] or '-'}</td>
            <td class="px-4 py-3">{r[2] or '-'}</td>
            <td class="px-4 py-3">{r[3] or '-'}</td>
            <td class="px-4 py-3 {status_cls}">{r[4]}</td>
            <td class="px-4 py-3 text-gray-500">{r[5]}</td>
        </tr>"""
    content += "</tbody></table></div>"
    return render_admin("logs", content)


@app.get("/admin/settings")
def settings(request: Request):
    if not verify_session(request):
        return HTMLResponse(content='<script>window.location.href="/admin/login";</script>')
    content = """
    <div class="bg-white rounded-lg shadow p-6 mb-6">
        <h3 class="text-lg font-bold mb-4">Change Password</h3>
        <form method="post" action="/admin/settings/password" class="space-y-4">
            <div>
                <label class="block text-sm font-medium mb-2">Current Password</label>
                <input type="password" name="current_password" class="w-full px-4 py-2 border rounded-lg" required>
            </div>
            <div>
                <label class="block text-sm font-medium mb-2">New Password</label>
                <input type="password" name="new_password" class="w-full px-4 py-2 border rounded-lg" required>
            </div>
            <div>
                <label class="block text-sm font-medium mb-2">Confirm New Password</label>
                <input type="password" name="confirm_password" class="w-full px-4 py-2 border rounded-lg" required>
            </div>
            <button type="submit" class="px-6 py-2 bg-purple-600 text-white rounded-lg">Update Password</button>
        </form>
    </div>
    <div class="bg-white rounded-lg shadow p-6 mb-6">
        <h3 class="text-lg font-bold mb-4">API Keys</h3>
        <p class="text-gray-600 text-sm mb-4">Manage API keys for external integrations</p>
        <a href="#" class="px-4 py-2 bg-green-600 text-white rounded-lg inline-block">Generate New API Key</a>
    </div>
    <div class="bg-white rounded-lg shadow p-6">
        <h3 class="text-lg font-bold mb-4">Environment Variables</h3>
        <div class="space-y-3">
            <div class="flex justify-between items-center py-2 border-b">
                <span class="font-medium">APOLLO_API_KEY</span>
                <span class="text-green-500">""" + ("Configured" if APOLLO_API_KEY else "Not Set") + """</span>
            </div>
            <div class="flex justify-between items-center py-2 border-b">
                <span class="font-medium">HUBSPOT_API_KEY</span>
                <span class="text-green-500">""" + ("Configured" if HUBSPOT_API_KEY else "Not Set") + """</span>
            </div>
            <div class="flex justify-between items-center py-2 border-b">
                <span class="font-medium">SALESFORCE_INSTANCE_URL</span>
                <span class="text-green-500">""" + ("Configured" if SALESFORCE_INSTANCE_URL else "Not Set") + """</span>
            </div>
            <div class="flex justify-between items-center py-2 border-b">
                <span class="font-medium">SALESFORCE_ACCESS_TOKEN</span>
                <span class="text-green-500">""" + ("Configured" if SALESFORCE_ACCESS_TOKEN else "Not Set") + """</span>
            </div>
        </div>
    </div>
    """
    return render_admin("settings", content)


@app.post("/admin/settings/password")
def change_password(request: Request, current_password: str = Form(...), new_password: str = Form(...), confirm_password: str = Form(...)):
    if not verify_session(request):
        return HTMLResponse(content='<script>window.location.href="/admin/login";</script>')
    
    username = request.session.get("username", "admin")
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT password_hash FROM admin_users WHERE username = ?", (username,))
    row = c.fetchone()
    
    if not row or row[0] != hash_password(current_password):
        conn.close()
        return HTMLResponse(content='<script>alert("Current password is incorrect"); window.location.href="/admin/settings";</script>')
    
    if new_password != confirm_password:
        conn.close()
        return HTMLResponse(content='<script>alert("New passwords do not match"); window.location.href="/admin/settings";</script>')
    
    if len(new_password) < 6:
        conn.close()
        return HTMLResponse(content='<script>alert("Password must be at least 6 characters"); window.location.href="/admin/settings";</script>')
    
    c.execute("UPDATE admin_users SET password_hash = ? WHERE username = ?", (hash_password(new_password), username))
    conn.commit()
    conn.close()
    
    log_activity("password_changed", f"Password changed for {username}")
    return HTMLResponse(content='<script>alert("Password updated successfully"); window.location.href="/admin/settings";</script>')


@app.post("/classify")
def classify(request: dict):
    client_id = request.get("client_id")
    lead = request.get("lead")
    if not lead:
        raise HTTPException(status_code=400, detail="Missing lead")
    if client_id and client_id in client_configs:
        config = client_configs[client_id]
    else:
        raise HTTPException(status_code=400, detail="Invalid client_id")
    result = _classify(config, lead)
    if request.get("route", {}).get("save_to_db", True):
        route_result = route_lead(client_id, lead, result)
        result["lead_id"] = route_result["lead_id"]
        result["hubspot_contact_id"] = route_result["hubspot_contact_id"]
    return result


@app.post("/admin/api-keys")
def create_api_key(data: dict):
    key = secrets.token_urlsafe(32)
    API_KEYS[key] = True
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("INSERT INTO api_keys (key_hash, label) VALUES (?, ?)", (key, data.get("label", "unnamed")))
    conn.commit()
    conn.close()
    return {"api_key": key}


@app.post("/admin/client-configs")
def save_client_config(data: dict):
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
    log_activity("config_updated", f"Updated: {client_id}", client_id=client_id)
    return {"status": "saved", "client_id": client_id}


@app.post("/admin/routing")
def save_routing(data: dict):
    client_id = data.get("client_id")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO routing_config (client_id, route_to_db, route_to_hubspot, hubspot_pipeline, hubspot_stage, route_to_salesforce, salesforce_account_id, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (client_id, int(data.get("route_to_db", 1)), int(data.get("route_to_hubspot", 0)), data.get("hubspot_pipeline", ""), data.get("hubspot_stage", ""), int(data.get("route_to_salesforce", 0)), data.get("salesforce_account_id", ""), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    log_activity("routing_updated", f"Updated: {client_id}", client_id=client_id)
    return {"status": "saved"}


@app.get("/admin/stats")
def get_stats():
    return get_dashboard_stats()


@app.get("/admin/leads-api")
def leads_api():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, client_id, company, email, score, tier, confidence, recommended_action FROM leads ORDER BY id DESC LIMIT 100")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "client_id": r[1], "company": r[2], "email": r[3], "score": r[4], "tier": r[5], "confidence": r[6], "action": r[7]} for r in rows]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
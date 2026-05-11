# ICP Classifier

### Intelligent Lead Scoring & Routing System for GTM Agencies

---

## What Is This?

The ICP Classifier is an automated lead scoring system that evaluates incoming leads against each client's Ideal Customer Profile (ICP). It sits between your lead sources (Apollo, Clay, manual uploads) and your CRM (HubSpot, Salesforce), automatically scoring, tiering, and routing leads based on rules you define.

Think of it as a **smart filter** that every lead passes through before reaching your sales team.

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌─────────────┐
│   Apollo    │────▶│ ICP Classifier│────▶│  Database   │     │  HubSpot    │
│   (Leads)   │     │   (Scoring)   │     │  (Storage)  │     │  Salesforce │
└─────────────┘     └──────────────┘     └──────────────┘     └─────────────┘
                           │
                           │ TIER 1 (Hot) ──────▶ Route to AE
                           │ TIER 2 (Warm) ────▶ Nurture Sequence
                           │ NOT ICP ──────────▶ Discard/Enrich
```

---

## Why Use This?

| Problem | Solution |
|---------|----------|
| Manual lead review takes hours | Auto-score every lead in seconds |
| Inconsistent scoring across team | Same criteria, same rules, every time |
| No visibility into lead quality | Dashboard shows tier distribution |
| CRM fields not populated | Auto-push with ICP score, tier, confidence |
| Don't know why leads score low | Signal breakdown shows exactly what matched |

---

## How It Works

### 1. Lead Comes In

Leads can enter the system from multiple sources:

```
┌─────────────────────────────────────────────────────────┐
│                    LEAD SOURCES                          │
├─────────────────┬─────────────────┬───────────────────────┤
│   Apollo CSV    │   Apollo        │   Direct API         │
│   Export        │   Webhook       │   Call               │
└─────────────────┴─────────────────┴───────────────────────┘
```

### 2. System Scores the Lead

The classifier evaluates each lead across 6 weighted signals:

```
┌─────────────────────────────────────────────────────────────┐
│                     SCORING ENGINE                          │
│                                                              │
│  INDUSTRY (30%)   ████████████████████                      │
│  HEADCOUNT (20%)  ████████████                               │
│  FUNDING (15%)    ████████                                   │
│  GEOGRAPHY (15%)  ████████                                   │
│  TECH STACK (15%) ████████                                   │
│  JOB SIGNALS (5%) ██                                         │
│                                                              │
│  TOTAL SCORE: 85/100                                        │
└─────────────────────────────────────────────────────────────┘
```

#### Scoring Rules

| Signal | Full Points | Half Points | Zero Points |
|--------|-------------|-------------|-------------|
| **Industry** | Exact/semantic match | Adjacent (e.g., "B2B SaaS" → "SaaS") | No match |
| **Headcount** | Within min-max range | Within 20% outside range | Far outside |
| **Funding** | Matches target stages | — | No match |
| **Geography** | HQ in target geo | — | No match |
| **Tech Stack** | 2+ tech matches | 1 tech match | 0 matches |
| **Job Signals** | Keywords match | Has signals, no keyword | No signals |

### 3. Disqualification Check (Before Scoring)

If any hard rule fails, lead is immediately disqualified:

```
┌────────────────────────────────────────┐
│         DISQUALIFICATION RULES         │
├────────────────────────────────────────┤
│ ❌ Industry in disqualified list       │
│ ❌ Headcount below hard floor          │
│ ❌ is_competitor = true                │
│ ❌ Domain in blocklist                 │
└────────────────────────────────────────┘
        │
        ▼
   TIER: "Disqualified"
   ACTION: discard
```

### 4. Tier Assignment

Based on score and configured thresholds:

```
        0              40              70             100
        │──────────────│──────────────│─────────────▶
                     T2             T1
        ┌─────────────┬──────────────┬──────────────┐
        │  Not ICP   │    Tier 2    │   Tier 1     │
        │  (Discard/ │  (Nurture)   │  (Route to   │
        │  Enrich)   │              │    AE)       │
        └─────────────┴──────────────┴──────────────┘
```

### 5. Routing

Leads are routed based on client configuration:

```
┌─────────────────────────────────────────────────────────────┐
│                    ROUTING OPTIONS                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   DATABASE           Always save to local SQLite            │
│   ─────────────────────────────────────────────             │
│   HUBSPOT            Push as Contact with custom fields:   │
│                      - icp_score__c                         │
│                      - icp_tier__c                          │
│                      - icp_confidence__c                    │
│   ─────────────────────────────────────────────             │
│   SALESFORCE         Push as Contact with custom fields:   │
│                      - ICP_Score__c                          │
│                      - ICP_Tier__c                          │
│                      - ICP_Confidence__c                    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## What You Get Back

Every classification returns detailed information:

```json
{
  "client_id": "acme_co",
  "company": "Notion",
  "score": 85,
  "tier": "Tier 1",
  "confidence": "high",
  "signal_breakdown": {
    "industry": { "score": 30, "max": 30, "matched": true },
    "headcount": { "score": 20, "max": 20, "matched": true },
    "funding": { "score": 15, "max": 15, "matched": true },
    "geo": { "score": 15, "max": 15, "matched": true },
    "tech": { "score": 5, "max": 15, "matched": true },
    "signals": { "score": 0, "max": 5, "matched": false }
  },
  "signal_gaps": {
    "tech": false,
    "funding": false,
    "signals": true
  },
  "reasons": [
    "Industry matched: SaaS",
    "Headcount in range: 400",
    "Funding stage matched: Series C+",
    "Geography matched: US"
  ],
  "recommended_action": "route_to_ae",
  "slack_alert": true,
  "sequence_id": "seq_t1_outbound_v3"
}
```

---

## Recommended Actions Matrix

| Tier | Confidence | Action | What It Means |
|------|------------|--------|---------------|
| Tier 1 | High | `route_to_ae` | Best fit - send directly to sales |
| Tier 1 | Medium/Low | `enrich_first` | Good fit but need more data |
| Tier 2 | Any | `enroll_sequence` | Worth nurturing |
| Not ICP | Has Gaps | `enrich_first` | Don't give up yet, try to get more info |
| Not ICP | No Gaps | `discard` | Not a good fit |
| Disqualified | Any | `discard` | Failed hard rules |

---

## Features

### Core Capabilities

- **Weighted Signal Scoring** - Customizable weights for each signal type
- **Tier Assignment** - Automatic sorting into Tier 1, Tier 2, Not ICP, Disqualified
- **Confidence Scoring** - High/Medium/Low based on data completeness
- **Disqualification Rules** - Hard overrides that bypass scoring
- **Signal Breakdown** - See exactly what matched and what didn't

### Integrations

- **Apollo** - Webhook for real-time classification, CSV import for batch processing
- **HubSpot** - Push contacts with ICP custom fields
- **Salesforce** - Push contacts with ICP custom fields

### Admin Dashboard

- **Dashboard** - Overview of leads, tiers, CRM pushes, weekly trends
- **Leads** - Searchable, filterable list of all classified leads
- **Clients** - Manage ICP configurations for each client
- **Integrations** - Connect/disconnect Apollo, HubSpot, Salesforce
- **Import** - Upload Apollo CSV exports for batch classification
- **Activity Logs** - Full audit trail of all actions

---

## Quick Start

### 1. Deploy to Vercel

```
GitHub Repo: https://github.com/kausxal/icp-classifier
```

Connect the repo to Vercel - it will auto-deploy.

### 2. Add Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `APOLLO_API_KEY` | Optional | For auto-enrichment from Apollo |
| `HUBSPOT_API_KEY` | Optional | For pushing to HubSpot |
| `SALESFORCE_INSTANCE_URL` | Optional | For Salesforce (e.g., https://yourinstance.salesforce.com) |
| `SALESFORCE_ACCESS_TOKEN` | Optional | Salesforce OAuth access token |

### 3. Create an API Key

```bash
curl -X POST https://your-vercel-url.com/admin/api-keys \
  -H "Content-Type: application/json" \
  -d '{"label": "production"}'
```

### 4. Configure a Client

```bash
curl -X POST https://your-vercel-url.com/admin/client-configs \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "acme_co",
    "target_industries": ["SaaS", "MarTech", "Fintech"],
    "hc_min": 50,
    "hc_max": 500,
    "hard_hc_floor": 10,
    "target_funding_stages": ["Series A", "Series B", "Series C+"],
    "target_geos": ["US", "EU"],
    "target_tech": ["HubSpot", "Salesforce", "Segment"],
    "signal_keywords": ["Hiring SDRs", "VP Marketing", "Head of Revenue", "RevOps"],
    "disqualified_industries": ["Gambling", "Crypto"],
    "blocklist_domains": ["competitor.com"],
    "t1_threshold": 70,
    "t2_threshold": 40,
    "weights": {
      "industry": 30,
      "headcount": 20,
      "funding": 15,
      "geo": 15,
      "tech": 15,
      "signals": 5
    },
    "tier_sequences": {
      "Tier 1": "seq_t1_outbound_v3",
      "Tier 2": "seq_t2_nurture_v1"
    }
  }'
```

### 5. Set Up Routing

```bash
curl -X POST https://your-vercel-url.com/admin/routing \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "acme_co",
    "route_to_db": true,
    "route_to_hubspot": true,
    "hubspot_pipeline": "default",
    "hubspot_stage": "appointmentscheduled",
    "route_to_salesforce": false
  }'
```

### 6. Import Leads

1. Export leads from Apollo as CSV
2. Go to `/admin/import` in the browser
3. Upload CSV and select client
4. System classifies all leads in batch

---

## API Endpoints

### Main Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | System health check |
| `POST` | `/classify` | Classify a single lead |
| `POST` | `/webhook/apollo` | Apollo webhook handler |

### Admin Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/admin/api-keys` | Create API key |
| `POST` | `/admin/client-configs` | Save client ICP config |
| `GET` | `/admin/client-configs/{id}` | Get client config |
| `POST` | `/admin/routing` | Configure lead routing |
| `GET` | `/admin/leads` | List all leads |
| `GET` | `/admin/leads/{id}` | Get lead details |
| `GET` | `/admin/stats` | Dashboard statistics |
| `GET` | `/admin/logs` | Activity logs |

---

## Typical Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                        DAILY WORKFLOW                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. EXPORT        Export leads from Apollo                      │
│       │                                                            │
│       ▼                                                            │
│  2. IMPORT        Upload CSV to /admin/import                    │
│       │                                                            │
│       ▼                                                            │
│  3. CLASSIFY      System scores all leads against ICP            │
│       │           • 80 become Tier 1 (Hot)                       │
│       │           • 150 become Tier 2 (Warm)                    │
│       │           • 270 become Not ICP                          │
│       │                                                            │
│       ▼                                                            │
│  4. ROUTE         Based on routing config:                       │
│       │           • Tier 1 → HubSpot/Salesforce                  │
│       │           • All → Database                               │
│       │                                                            │
│       ▼                                                            │
│  5. REVIEW        Check Dashboard for:                           │
│                   • Total leads processed                        │
│                   • Tier distribution                           │
│                   • CRM push status                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Example Response

A Tier 1 lead that routed to HubSpot:

```json
{
  "client_id": "tech_startup",
  "company": "Linear",
  "score": 92,
  "tier": "Tier 1",
  "confidence": "high",
  "signal_breakdown": {
    "industry": { "score": 30, "max": 30, "matched": true },
    "headcount": { "score": 20, "max": 20, "matched": true },
    "funding": { "score": 15, "max": 15, "matched": true },
    "geo": { "score": 15, "max": 15, "matched": true },
    "tech": { "score": 10, "max": 15, "matched": true },
    "signals": { "score": 2, "max": 5, "matched": true }
  },
  "signal_gaps": { "tech": false, "funding": false, "signals": false },
  "reasons": [
    "Industry matched: SaaS",
    "Headcount in range: 50",
    "Funding stage matched: Series A",
    "Geography matched: US",
    "Tech stack matched: 2 technologies",
    "Job signals matched keywords"
  ],
  "recommended_action": "route_to_ae",
  "lead_id": 142,
  "hubspot_contact_id": "123456789",
  "salesforce_contact_id": null,
  "slack_alert": true,
  "sequence_id": "seq_t1_outbound_v3"
}
```

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Runtime | Python 3.11 |
| Server | Vercel Serverless Functions |
| Database | SQLite (local file) |
| Authentication | API Key (Bearer Token) |
| UI | HTML/Tailwind (built into API) |

---

## Need to Customize?

The scoring logic lives in `classifier.py`. You can adjust:

- How each signal is scored
- What counts as a match
- Adjacent industry matching
- Confidence calculation
- Tier thresholds

The API logic and database handling is in `api.py`.

---

## Production Recommendations

Before going live with high volume, consider adding:

- Rate limiting on API endpoints
- Error monitoring (Datadog, Sentry)
- Staging environment for testing config changes
- Unit tests for classifier logic
- Redis caching for client configs (if you have many clients)

---

## Support

For questions or modifications:
- Scoring logic: Check `classifier.py`
- API and routing: Check `api.py`
- Config format: See the example in "Configure a Client" section

---

**License:** MIT  
**Repository:** https://github.com/kausxal/icp-classifier
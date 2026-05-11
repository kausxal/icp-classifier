# ICP Classifier API

Real-time lead classification API for GTM agencies. Classifies leads against client Ideal Customer Profiles (ICP), assigns tiers, and recommends actions.

## Features

- **Weighted Signal Scoring** — Industry, headcount, funding stage, geography, tech stack, job signals
- **Tier Assignment** — Tier 1, Tier 2, Not ICP, Disqualified
- **Confidence Scoring** — High, Medium, Low based on data gaps
- **API Key Authentication** — Secure endpoints
- **SQLite Database** — Classification history & client configs stored locally
- **Multi-client Support** — Store multiple ICP configurations

## Scoring Logic

| Signal | Full Points | Half Points | Zero |
|--------|-------------|-------------|------|
| **Industry** | Exact/semantic match | Adjacent match | No match |
| **Headcount** | Within hc_min–hc_max | Within 20% margin | Outside |
| **Funding** | Matches target stages | — | No match |
| **Geography** | HQ matches target geo | — | No match |
| **Tech Stack** | 2+ tech matches | 1 match | 0 matches |
| **Job Signals** | Keywords match | Has signals, no match | No signals |

### Disqualification Rules (Hard Overrides)

- Industry in `disqualified_industries`
- Headcount below `hard_hc_floor`
- `is_competitor` is true
- Domain in `blocklist_domains`

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/classify` | Classify a lead |
| POST | `/admin/api-keys` | Create API key |
| POST | `/admin/client-configs` | Save client config |
| GET | `/admin/client-configs/{client_id}` | Get client config |
| GET | `/admin/classifications` | Classification history |

## Usage

### 1. Start the Server

```bash
pip install -r requirements.txt
python api.py
```

Server runs at `http://localhost:8000`

### 2. Create an API Key

```bash
curl -X POST http://localhost:8000/admin/api-keys \
  -H "Content-Type: application/json" \
  -d '{"label": "production"}'
```

### 3. Save a Client Config

```bash
curl -X POST http://localhost:8000/admin/client-configs \
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

### 4. Classify a Lead

```bash
curl -X POST http://localhost:8000/classify \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "acme_co",
    "lead": {
      "company": "Notion",
      "domain": "notion.so",
      "industry": "SaaS",
      "headcount": 400,
      "funding_stage": "Series C+",
      "hq_country": "US",
      "tech_stack": ["HubSpot", "Segment", "Intercom"],
      "job_signals": ["Hiring 3 SDRs", "New VP of Marketing hired"],
      "is_competitor": false
    }
  }'
```

### Response

```json
{
  "client_id": "acme_co",
  "company": "Notion",
  "score": 100,
  "tier": "Tier 1",
  "confidence": "high",
  "signal_breakdown": {
    "industry": { "score": 30, "max": 30, "matched": true },
    "headcount": { "score": 20, "max": 20, "matched": true },
    "funding": { "score": 15, "max": 15, "matched": true },
    "geo": { "score": 15, "max": 15, "matched": true },
    "tech": { "score": 15, "max": 15, "matched": true },
    "signals": { "score": 5, "max": 5, "matched": true }
  },
  "signal_gaps": { "tech": false, "funding": false, "signals": false },
  "reasons": [
    "Industry matched: SaaS",
    "Headcount in range: 400",
    "Funding stage matched: Series C+",
    "Geography matched: US",
    "Tech stack matched: 2 technologies",
    "Job signals matched keywords"
  ],
  "missing_data_note": null,
  "recommended_action": "route_to_ae",
  "slack_alert": true,
  "sequence_id": "seq_t1_outbound_v3"
}
```

## Recommended Actions

| Tier | Confidence | Action |
|------|------------|--------|
| Tier 1 | High | `route_to_ae` |
| Tier 1 | Medium/Low | `enrich_first` |
| Tier 2 | Any | `enroll_sequence` |
| Not ICP | Has gaps | `enrich_first` |
| Not ICP | No gaps | `discard` |
| Disqualified | Any | `discard` |

## Deployment

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "api.py"]
```

### Vercel (Serverless)

1. Push to GitHub
2. Import project in Vercel
3. Deploy — API runs at `https://your-project.vercel.app`

## Tech Stack

- FastAPI / Vercel Python
- SQLite
- Pydantic

## License

MIT
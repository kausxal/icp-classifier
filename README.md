================================================================================
ICP CLASSIFIER - LEAD SCORING AND ROUTING SYSTEM
================================================================================

WHAT IS THIS TOOL?
------------------
The ICP Classifier is a smart lead scoring system that helps GTM agencies 
automatically evaluate and categorize leads based on each client's Ideal 
Customer Profile. Think of it as an intelligent filter that sits between 
your lead sources (Apollo) and your CRM (HubSpot/Salesforce).

When a lead comes in, the system looks at company size, industry, funding 
stage, technology they use, and job signals to calculate a score from 0-100. 
Based on that score, it assigns a tier and tells you what to do next - route 
to an AE, enroll in a nurture sequence, or discard.

WHY USE THIS?
-------------
Manually reviewing every lead is time consuming and inconsistent. This system 
gives you:

1. Consistent Scoring - Every lead gets evaluated the same way using the exact 
   same criteria you define

2. Automatic Tier Assignment - Leads are sorted into Tier 1 (hot), Tier 2 
   (warm), or Not ICP automatically

3. CRM Integration - Classified leads can be pushed directly to HubSpot or 
   Salesforce with ICP score as custom fields

4. Full Audit Trail - Every classification is logged so you can see exactly 
   why a lead was scored a certain way

5. Admin Dashboard - See your lead pipeline, tier distribution, and activity 
   logs in one place

HOW THE SCORING WORKS
---------------------
The system evaluates leads across 6 different signals, each weighted according 
to your configuration:

1. INDUSTRY (e.g., 30% of total score)
   - Full points if the lead's industry matches your target industries
   - Half points if the industry is adjacent (like "B2B SaaS" matching "SaaS")
   - Zero points if there's no match

2. HEADCOUNT (e.g., 20% of total score)
   - Full points if employee count is within your min-max range
   - Half points if within 20% outside the range
   - Zero points if far outside

3. FUNDING STAGE (e.g., 15% of total score)
   - Full points if funding stage matches your target stages
   - Zero otherwise
   - If funding data is missing, it's flagged as a data gap

4. GEOGRAPHY (e.g., 15% of total score)
   - Full points if HQ country/region matches your target geos
   - Zero if no match

5. TECH STACK (e.g., 15% of total score)
   - Full points if 2+ technologies match your target tech
   - Half points if exactly 1 matches
   - Zero if no matches

6. JOB SIGNALS (e.g., 5% of total score)
   - Full points if job signals contain keywords like "Hiring SDRs" or 
     "VP of Marketing"
   - Half points if signals exist but don't match keywords

DISQUALIFICATION RULES
----------------------
Before scoring, the system checks for hard disqualifiers. If any of these 
are true, the lead gets "Disqualified" status immediately:

- Industry is in your disqualified list (like gambling, crypto)
- Headcount is below your hard floor
- The company is marked as a competitor
- Domain is in your blocklist

TIER ASSIGNMENTS
----------------
After scoring, leads are sorted into tiers based on your thresholds:

- TIER 1: Score >= T1 threshold (usually 70+) - These are your best fits, 
  route directly to an AE

- TIER 2: Score >= T2 threshold but below T1 (usually 40-69) - Good leads, 
  put them in a nurture sequence

- NOT ICP: Score below T2 threshold - These don't match well, either 
  discard or enrich with more data first

- DISQUALIFIED: Failed one of the hard rules - Automatically discarded

CONFIDENCE SCORING
------------------
The system also tells you how confident it is in the classification:

- HIGH CONFIDENCE: At least 2 of the 3 data gaps are filled (tech, funding, 
  signals) AND the score is at least 10 points away from the nearest threshold

- MEDIUM CONFIDENCE: Either 3-4 data gaps exist OR the score is within 
  10 points of a threshold

- LOW CONFIDENCE: 5+ data gaps exist OR enrichment data is sparse across 
  multiple fields

WHAT TO DO NEXT (RECOMMENDED ACTIONS)
-------------------------------------
Based on tier and confidence, the system recommends next steps:

- Tier 1 + High confidence: route_to_ae - Send directly to sales
- Tier 1 + Medium/Low confidence: enrich_first - Get more data first
- Tier 2: enroll_sequence - Add to nurture campaign
- Not ICP + Data gaps present: enrich_first - Don't give up yet
- Not ICP + No gaps: discard - Really not a fit
- Disqualified: discard - Never show to sales

GETTING STARTED
---------------

STEP 1: DEPLOY THE SYSTEM
The easiest way is Vercel. Connect your GitHub repo to Vercel and it will 
auto-deploy. You'll need to add these environment variables:

- APOLLO_API_KEY (optional, for auto-enrichment)
- HUBSPOT_API_KEY (optional, for pushing to HubSpot)
- SALESFORCE_INSTANCE_URL (optional, for Salesforce)
- SALESFORCE_ACCESS_TOKEN (optional, for Salesforce)

STEP 2: CREATE AN API KEY
Once deployed, make a POST call to create an API key:
POST /admin/api-keys
Body: {"label": "my-key"}

STEP 3: CONFIGURE YOUR CLIENTS
For each client, save their ICP configuration:
POST /admin/client-configs
Body: {
  "client_id": "client_xyz",
  "target_industries": ["SaaS", "MarTech"],
  "hc_min": 50,
  "hc_max": 500,
  "target_funding_stages": ["Series A", "Series B"],
  "target_geos": ["US", "UK"],
  "target_tech": ["HubSpot", "Salesforce"],
  "signal_keywords": ["Hiring SDRs", "VP Marketing"],
  "t1_threshold": 70,
  "t2_threshold": 40,
  "weights": {
    "industry": 30,
    "headcount": 20,
    "funding": 15,
    "geo": 15,
    "tech": 15,
    "signals": 5
  }
}

STEP 4: SET UP ROUTING
For each client, decide where classified leads should go:
POST /admin/routing
Body: {
  "client_id": "client_xyz",
  "route_to_db": true,
  "route_to_hubspot": true,
  "hubspot_pipeline": "default",
  "hubspot_stage": "appointmentscheduled",
  "route_to_salesforce": false
}

STEP 5: IMPORT LEADS
Go to the Import page in the admin UI, upload a CSV exported from Apollo, 
select the client, and the system will classify all leads in batch.

USING THE ADMIN DASHBOARD
-------------------------
The system includes a full admin UI at /admin with these sections:

- Dashboard: See total leads, tier breakdown, CRM pushes, weekly stats
- Leads: View all classified leads with filters and search
- Clients: See all client ICP configurations
- Integrations: Connect/disconnect Apollo, HubSpot, Salesforce
- Import: Upload Apollo CSV exports for batch processing
- Activity Logs: See everything that happened - classifications, CRM pushes, 
  errors

API REFERENCE
-------------

Main endpoints:

GET /health
- Returns system health status

POST /classify
- Classify a single lead
- Requires: client_id or client_config, and lead object
- Returns: score, tier, confidence, signal_breakdown, recommended_action

POST /webhook/apollo
- Webhook for Apollo events
- Automatically enriches from Apollo and classifies

POST /admin/client-configs
- Save or update a client's ICP configuration

GET /admin/client-configs/{client_id}
- Retrieve a client's ICP configuration

POST /admin/routing
- Configure where leads go (database, HubSpot, Salesforce)

GET /admin/leads
- List all leads in the database

GET /admin/leads/{id}
- Get details of a specific lead including signal breakdown

GET /admin/stats
- Get dashboard statistics

POST /admin/api-keys
- Create a new API key

EXAMPLE WORKFLOW
----------------
Here's how a typical day might work:

1. Your team exports 500 leads from Apollo
2. You go to the Import page, upload the CSV, select client "tech_startup"
3. The system processes all 500 leads:
   - Each gets scored against the tech_startup ICP
   - Scores range from 20 to 95
   - 80 become Tier 1, 150 become Tier 2, 270 are Not ICP
   - Based on routing config, all 80 Tier 1s get pushed to HubSpot
4. You check the Dashboard and see the breakdown
5. Your sales team in HubSpot sees the ICP_Score__c and ICP_Tier__c fields 
   on each contact and knows which ones to prioritize

TECHNICAL DETAILS
-----------------
- Built with Python and Vercel's serverless functions
- Uses SQLite for local storage (leads, configs, logs)
- API key authentication on all endpoints
- All classification logic is in classifier.py - easy to modify scoring 
  rules if needed
- Response times are typically under 500ms

SUPPORT
-------
If you need to modify how scoring works, check classifier.py - all the 
weighted signal logic is there. The api.py file handles the web server, 
database, and integrations.

For production use, consider adding:
- Rate limiting to prevent abuse
- Logging service like Datadog or New Relic
- Staging environment for testing config changes
- Unit tests for the classifier logic
- Redis for caching client configs if you have many clients

================================================================================
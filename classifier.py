import json
import re
from typing import Optional

def classify_lead(client_config: dict, lead: dict) -> dict:
    client_id = client_config.get("client_id", "unknown")
    company = lead.get("company", "Unknown")

    disqualification_reasons = []

    if lead.get("industry") in client_config.get("disqualified_industries", []):
        return build_response(client_id, company, 0, "Disqualified", "high", {}, {"tech": False, "funding": False, "signals": False}, ["Industry is disqualified"], None, "discard", False, None)

    hard_hc_floor = client_config.get("hard_hc_floor")
    if hard_hc_floor and lead.get("headcount", 0) < hard_hc_floor:
        return build_response(client_id, company, 0, "Disqualified", "high", {}, {"tech": False, "funding": False, "signals": False}, ["Headcount below hard floor"], None, "discard", False, None)

    if lead.get("is_competitor"):
        return build_response(client_id, company, 0, "Disqualified", "high", {}, {"tech": False, "funding": False, "signals": False}, ["Company is a competitor"], None, "discard", False, None)

    blocklist = client_config.get("blocklist_domains", [])
    lead_domain = lead.get("domain", "").lower()
    if any(bl in lead_domain for bl in [d.lower() for d in blocklist]):
        return build_response(client_id, company, 0, "Disqualified", "high", {}, {"tech": False, "funding": False, "signals": False}, ["Domain is blocklisted"], None, "discard", False, None)

    weights = client_config.get("weights", {})
    signal_breakdown = {}
    signal_gaps = {"tech": False, "funding": False, "signals": False}
    reasons = []

    industry_score, industry_matched = score_industry(lead, client_config, weights.get("industry", 0))
    signal_breakdown["industry"] = {"score": industry_score, "max": weights.get("industry", 0), "matched": industry_matched}
    if industry_matched:
        reasons.append(f"Industry matched: {lead.get('industry', 'unknown')}")

    hc_score, hc_matched = score_headcount(lead, client_config, weights.get("headcount", 0))
    signal_breakdown["headcount"] = {"score": hc_score, "max": weights.get("headcount", 0), "matched": hc_matched}
    if hc_matched:
        reasons.append(f"Headcount in range: {lead.get('headcount')}")

    funding_score, funding_matched, funding_gap = score_funding(lead, client_config, weights.get("funding", 0))
    signal_breakdown["funding"] = {"score": funding_score, "max": weights.get("funding", 0), "matched": funding_matched}
    signal_gaps["funding"] = funding_gap
    if funding_matched:
        reasons.append(f"Funding stage matched: {lead.get('funding_stage', 'unknown')}")

    geo_score, geo_matched = score_geography(lead, client_config, weights.get("geo", 0))
    signal_breakdown["geo"] = {"score": geo_score, "max": weights.get("geo", 0), "matched": geo_matched}
    if geo_matched:
        reasons.append(f"Geography matched: {lead.get('hq_country', 'unknown')}")

    tech_score, tech_matched, tech_gap = score_tech_stack(lead, client_config, weights.get("tech", 0))
    signal_breakdown["tech"] = {"score": tech_score, "max": weights.get("tech", 0), "matched": tech_matched}
    signal_gaps["tech"] = tech_gap
    if tech_matched:
        reasons.append(f"Tech stack matched: {len([t for t in lead.get('tech_stack', []) if t in client_config.get('target_tech', [])])} technologies")

    signals_score, signals_matched, signals_gap = score_signals(lead, client_config, weights.get("signals", 0))
    signal_breakdown["signals"] = {"score": signals_score, "max": weights.get("signals", 0), "matched": signals_matched}
    signal_gaps["signals"] = signals_gap
    if signals_matched:
        reasons.append(f"Job signals matched keywords")

    total_score = sum(s["score"] for s in signal_breakdown.values())

    t1 = client_config.get("t1_threshold", 70)
    t2 = client_config.get("t2_threshold", 40)

    if total_score >= t1:
        tier = "Tier 1"
    elif total_score >= t2:
        tier = "Tier 2"
    else:
        tier = "Not ICP"

    gap_count = sum(signal_gaps.values())
    distance_to_threshold = min(abs(total_score - t1), abs(total_score - t2)) if tier != "Tier 1" else abs(total_score - t1)

    if gap_count <= 3 and distance_to_threshold >= 10:
        confidence = "high"
    elif gap_count >= 5:
        confidence = "low"
    else:
        confidence = "medium"

    missing_fields = []
    if not lead.get("tech_stack"):
        missing_fields.append("tech stack")
    if not lead.get("funding_stage"):
        missing_fields.append("funding stage")
    if not lead.get("job_signals"):
        missing_fields.append("job signals")
    missing_data_note = f"Missing enrichment: {', '.join(missing_fields)}" if missing_fields else None

    recommended_action = determine_action(tier, confidence, signal_gaps, tier != "Not ICP")

    slack_alert = tier == "Tier 1" and confidence in ["high", "medium"]

    sequence_id = client_config.get("tier_sequences", {}).get(tier, None) if tier in ["Tier 1", "Tier 2"] else None

    return build_response(client_id, company, total_score, tier, confidence, signal_breakdown, signal_gaps, reasons, missing_data_note, recommended_action, slack_alert, sequence_id)


def score_industry(lead: dict, config: dict, weight: float) -> tuple:
    lead_industry = lead.get("industry", "").lower()
    target_industries = [i.lower() for i in config.get("target_industries", [])]

    for ti in target_industries:
        if lead_industry == ti or ti in lead_industry or lead_industry in ti:
            return weight, True

    adjacent_pairs = {
        "saas": ["b2b saas", "software"],
        "fintech": ["payments", "banking", "financial services"],
        "payments": ["fintech", "banking"],
        "martech": ["marketing", "advertising"],
        "marketing": ["martech"],
    }

    for ti in target_industries:
        if ti in adjacent_pairs:
            for adj in adjacent_pairs[ti]:
                if adj in lead_industry or lead_industry in adj:
                    return weight / 2, True

    return 0, False


def score_headcount(lead: dict, config: dict, weight: float) -> tuple:
    hc = lead.get("headcount")
    if hc is None:
        return 0, False

    hc_min = config.get("hc_min", 0)
    hc_max = config.get("hc_max", float("inf"))

    if hc_min <= hc <= hc_max:
        return weight, True

    margin = 0.2
    if hc_min - (hc_min * margin) <= hc < hc_min or hc_max < hc <= hc_max + (hc_max * margin):
        return weight / 2, True

    return 0, False


def score_funding(lead: dict, config: dict, weight: float) -> tuple:
    funding_stage = lead.get("funding_stage", "").lower()
    target_stages = [s.lower() for s in config.get("target_funding_stages", [])]

    if not funding_stage:
        return 0, False, True

    for ts in target_stages:
        if funding_stage == ts or ts in funding_stage or funding_stage in ts:
            return weight, True, False

    return 0, False, False


def score_geography(lead: dict, config: dict, weight: float) -> tuple:
    hq_country = lead.get("hq_country", "").upper()
    hq_region = lead.get("hq_region", "").upper()
    target_geos = [g.upper() for g in config.get("target_geos", [])]

    for tg in target_geos:
        if tg in [hq_country, hq_region]:
            return weight, True

    return 0, False


def score_tech_stack(lead: dict, config: dict, weight: float) -> tuple:
    tech_stack = lead.get("tech_stack", [])
    target_tech = [t.lower() for t in config.get("target_tech", [])]

    if not tech_stack:
        return 0, False, True

    matches = sum(1 for t in tech_stack if t.lower() in target_tech)

    if matches >= 2:
        return weight, True, False
    elif matches == 1:
        return weight / 2, True, False

    return 0, False, False


def score_signals(lead: dict, config: dict, weight: float) -> tuple:
    job_signals = lead.get("job_signals", [])
    signal_keywords = [k.lower() for k in config.get("signal_keywords", [])]

    if not job_signals:
        return 0, False, True

    signals_lower = [s.lower() for s in job_signals]

    for sk in signal_keywords:
        sk_words = set(sk.split())
        for sig in signals_lower:
            sig_words = set(sig.split())
            if sk_words & sig_words:
                return weight, True, False

    if job_signals:
        return weight / 2, True, False

    return 0, False, True


def determine_action(tier: str, confidence: str, signal_gaps: dict, has_matches: bool) -> str:
    if tier == "Tier 1":
        if confidence == "high":
            return "route_to_ae"
        else:
            return "enrich_first"
    elif tier == "Tier 2":
        return "enroll_sequence"
    elif tier == "Not ICP":
        if any(signal_gaps.values()):
            return "enrich_first"
        return "discard"
    return "discard"


def build_response(client_id, company, score, tier, confidence, signal_breakdown, signal_gaps, reasons, missing_data_note, recommended_action, slack_alert, sequence_id):
    return {
        "client_id": client_id,
        "company": company,
        "score": score,
        "tier": tier,
        "confidence": confidence,
        "signal_breakdown": signal_breakdown,
        "signal_gaps": signal_gaps,
        "reasons": reasons,
        "missing_data_note": missing_data_note,
        "recommended_action": recommended_action,
        "slack_alert": slack_alert,
        "sequence_id": sequence_id
    }


if __name__ == "__main__":
    test_config = {
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
        "is_competitor": False,
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
    }

    test_lead = {
        "company": "Notion",
        "domain": "notion.so",
        "industry": "SaaS",
        "headcount": 400,
        "funding_stage": "Series C+",
        "hq_country": "US",
        "tech_stack": ["HubSpot", "Segment", "Intercom"],
        "job_signals": ["Hiring 3 SDRs", "New VP of Marketing hired"],
        "is_competitor": False
    }

    result = classify_lead(test_config, test_lead)
    print(json.dumps(result, indent=2))
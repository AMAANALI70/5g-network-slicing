#!/usr/bin/env python3
"""
fix_dashboards.py — Patch all 4 Grafana dashboard YAMLs for consistency.

Fixes applied:
  1. SLA threshold: 25ms → 15ms everywhere (matches URLLC_SLA_MS = 15.0)
  2. RTT colour thresholds: yellow@20→12, red@25→15
  3. Add LLM/agentic metrics row to orchestrator dashboard
  4. Fix tun_rx_errors missing slice filter in grafana.yaml
  5. Fix tc description: "50Mbit" → correct TBF description
"""

import json, re, os

MONITORING = os.path.dirname(os.path.abspath(__file__))

# ── Helper: load YAML-embedded dashboard JSON ─────────────────────────────────
def load_yaml_raw(fname):
    path = os.path.join(MONITORING, fname)
    with open(path) as f:
        return f.read()

def save_yaml_raw(fname, text):
    path = os.path.join(MONITORING, fname)
    with open(path, "w") as f:
        f.write(text)
    print(f"  ✅ Saved {fname}")

# ── 1. Fix grafana-orchestrator-dashboard.yaml ────────────────────────────────
def fix_orchestrator_dashboard():
    print("\n[1] grafana-orchestrator-dashboard.yaml")
    text = load_yaml_raw("grafana-orchestrator-dashboard.yaml")

    # Fix SLA vector: vector(25) → vector(15)
    before = text.count("vector(25)")
    text = text.replace("vector(25)", "vector(15)")
    print(f"  vector(25)→vector(15): {before} replacements")

    # Fix RTT stat threshold: yellow@20→12, red@25→15
    # Pattern: {"color":"yellow","value":20} and {"color":"red","value":25}
    before = text.count('\\"value\\":25}')
    # Only fix RTT-related thresholds (those near "urllc_rtt_ms" or "URLLC RTT")
    # Use regex to replace within stat threshold steps for URLLC RTT
    text = re.sub(r'("thresholds":\{"steps":\[.*?)"value":20\}(.*?)"value":25\}',
                  lambda m: m.group(0).replace('"value":20}', '"value":12}').replace('"value":25}', '"value":15}'),
                  text, flags=re.DOTALL)
    # Also handle escaped JSON in YAML
    text = re.sub(r'(\\"value\\":)20(\}.*?\\"value\\":)25(\})',
                  lambda m: m.group(0).replace('\\"value\\":20}', '\\"value\\":12}').replace('\\"value\\":25}', '\\"value\\":15}'),
                  text)
    print(f"  RTT thresholds 25→15, 20→12: patched")

    # Fix recovery description
    text = text.replace("drops below 25ms", "drops below 15ms")
    text = text.replace("below 25ms", "below 15ms")
    print(f"  Description: 'below 25ms'→'below 15ms'")

    # Fix tc staircase description (50Mbit → TBF variable cap)
    text = text.replace(
        "Shows exact moment of throttle (drop to 50Mbit) and restore (jump to 1000Mbit).",
        "Shows eMBB tc TBF cap over time. Throttle applies TBF rate limit; restore removes cap (returns to fq_codel default)."
    )

    # Add LLM metrics row after the last row section
    # Find the closing of the panels array and insert before it
    LLM_PANELS = (
        ',{"type":"row","title":"▶ LLM & AGENTIC CONTROL","gridPos":{"h":1,"w":24,"x":0,"y":46},"collapsed":false},'
        '{"title":"Agentic Mode","type":"stat","gridPos":{"h":4,"w":3,"x":0,"y":47},'
        '"fieldConfig":{"defaults":{"color":{"mode":"thresholds"},'
        '"thresholds":{"steps":[{"color":"blue","value":null},{"color":"green","value":1}]}}},'
        '"options":{"reduceOptions":{"calcs":["lastNotNull"]},"textMode":"value"},'
        '"targets":[{"expr":"orchestrator_agentic_mode","refId":"A"}],'
        '"datasource":{"type":"prometheus","uid":"PBFA97CFB590B2093"}},'
        '{"title":"LLM Latency","type":"stat","gridPos":{"h":4,"w":3,"x":3,"y":47},'
        '"fieldConfig":{"defaults":{"unit":"ms","color":{"mode":"thresholds"},'
        '"thresholds":{"steps":[{"color":"green","value":null},{"color":"yellow","value":30000},{"color":"red","value":60000}]}}},'
        '"options":{"reduceOptions":{"calcs":["lastNotNull"]}},'
        '"targets":[{"expr":"orchestrator_llm_latency_ms","refId":"A"}],'
        '"datasource":{"type":"prometheus","uid":"PBFA97CFB590B2093"}},'
        '{"title":"LLM Confidence","type":"gauge","gridPos":{"h":4,"w":3,"x":6,"y":47},'
        '"fieldConfig":{"defaults":{"unit":"percentunit","min":0,"max":1,"color":{"mode":"thresholds"},'
        '"thresholds":{"steps":[{"color":"red","value":null},{"color":"yellow","value":0.6},{"color":"green","value":0.8}]}}},'
        '"options":{"reduceOptions":{"calcs":["lastNotNull"]}},'
        '"targets":[{"expr":"orchestrator_llm_confidence","refId":"A"}],'
        '"datasource":{"type":"prometheus","uid":"PBFA97CFB590B2093"}},'
        '{"title":"Memory Success","type":"gauge","gridPos":{"h":4,"w":3,"x":9,"y":47},'
        '"fieldConfig":{"defaults":{"unit":"percentunit","min":0,"max":1,"color":{"mode":"thresholds"},'
        '"thresholds":{"steps":[{"color":"red","value":null},{"color":"yellow","value":0.5},{"color":"green","value":0.75}]}}},'
        '"options":{"reduceOptions":{"calcs":["lastNotNull"]}},'
        '"targets":[{"expr":"orchestrator_memory_success_rate","refId":"A"}],'
        '"datasource":{"type":"prometheus","uid":"PBFA97CFB590B2093"}},'
        '{"title":"Safety Overrides","type":"stat","gridPos":{"h":4,"w":3,"x":12,"y":47},'
        '"fieldConfig":{"defaults":{"color":{"mode":"thresholds"},'
        '"thresholds":{"steps":[{"color":"green","value":null},{"color":"yellow","value":1},{"color":"red","value":5}]}}},'
        '"options":{"reduceOptions":{"calcs":["lastNotNull"]}},'
        '"targets":[{"expr":"orchestrator_safety_overrides_total","refId":"A"}],'
        '"datasource":{"type":"prometheus","uid":"PBFA97CFB590B2093"}},'
        '{"title":"LLM Latency Timeline","type":"timeseries","gridPos":{"h":7,"w":12,"x":0,"y":51},'
        '"fieldConfig":{"defaults":{"unit":"ms"}},'
        '"targets":['
        '{"expr":"orchestrator_llm_latency_ms","legendFormat":"LLM Latency (ms)","refId":"A"},'
        '{"expr":"orchestrator_llm_confidence * 10000","legendFormat":"Confidence × 10k","refId":"B"}'
        '],"datasource":{"type":"prometheus","uid":"PBFA97CFB590B2093"}},'
        '{"title":"Slice Replicas","type":"timeseries","gridPos":{"h":7,"w":12,"x":12,"y":51},'
        '"fieldConfig":{"defaults":{"unit":"short","decimals":0}},'
        '"targets":['
        '{"expr":"orchestrator_embb_replicas","legendFormat":"eMBB replicas","refId":"A"},'
        '{"expr":"orchestrator_urllc_replicas","legendFormat":"URLLC replicas","refId":"B"},'
        '{"expr":"orchestrator_mmtc_replicas","legendFormat":"mMTC replicas","refId":"C"}'
        '],"datasource":{"type":"prometheus","uid":"PBFA97CFB590B2093"}}'
    )

    # Insert LLM panels before the closing of the panels array
    # Find last panel end and insert before the closing ]
    if "LLM & AGENTIC CONTROL" not in text:
        # Find the closing of the panels JSON array
        idx = text.rfind('"panels"')
        if idx != -1:
            # Find the closing bracket of the panels array
            bracket_end = text.rfind(']', idx, text.rfind('"refresh"'))
            if bracket_end != -1:
                text = text[:bracket_end] + LLM_PANELS + text[bracket_end:]
                print("  LLM/Agentic panels row: added")
            else:
                print("  ⚠️  Could not locate panels array end for LLM panels")
        else:
            print("  ⚠️  Could not find panels key for LLM panels")
    else:
        print("  LLM panels already present, skipping")

    save_yaml_raw("grafana-orchestrator-dashboard.yaml", text)


# ── 2. Fix grafana-app-dashboard.yaml ─────────────────────────────────────────
def fix_app_dashboard():
    print("\n[2] grafana-app-dashboard.yaml")
    text = load_yaml_raw("grafana-app-dashboard.yaml")

    # Fix RTT stat thresholds: yellow@20→12, red@25→15
    text = re.sub(r'(\\"value\\":)20(\}.*?\\"value\\":)25(\})',
                  lambda m: m.group(0).replace('\\"value\\":20}', '\\"value\\":12}').replace('\\"value\\":25}', '\\"value\\":15}'),
                  text)
    text = re.sub(r'("value":)20(\}.*?"value":)25(\})',
                  lambda m: m.group(0).replace('"value":20}', '"value":12}').replace('"value":25}', '"value":15}'),
                  text, flags=re.DOTALL)

    # Fix SLA description in URLLC panel
    text = text.replace("SLA = 25ms", "SLA = 15ms")
    text = text.replace("SLA = 25 ms", "SLA = 15ms")
    print("  'SLA = 25ms' → 'SLA = 15ms'")

    # Fix shading threshold from 25 to 15
    text = text.replace('"value":25}]}},{"matcher"', '"value":15}]}},{"matcher"')
    text = text.replace('\\"value\\":25}]}},{\\"matcher\\"', '\\"value\\":15}]}},{\\"matcher\\"')
    text = text.replace('"rgba(255,50,50,0.15)","value":25', '"rgba(255,50,50,0.15)","value":15')
    text = text.replace('\\"rgba(255,50,50,0.15)\\",\\"value\\":25', '\\"rgba(255,50,50,0.15)\\",\\"value\\":15')
    print("  Shading threshold 25→15")

    save_yaml_raw("grafana-app-dashboard.yaml", text)


# ── 3. Fix grafana-hierarchical-dashboard.yaml ────────────────────────────────
def fix_hierarchical_dashboard():
    print("\n[3] grafana-hierarchical-dashboard.yaml")
    text = load_yaml_raw("grafana-hierarchical-dashboard.yaml")

    # Fix RTT stat thresholds yellow@20→12, red@25→15
    text = re.sub(r'(\\"value\\":)20(\}.*?\\"value\\":)25(\})',
                  lambda m: m.group(0).replace('\\"value\\":20}', '\\"value\\":12}').replace('\\"value\\":25}', '\\"value\\":15}'),
                  text)
    text = re.sub(r'("value":)20(\}.*?"value":)25(\})',
                  lambda m: m.group(0).replace('"value":20}', '"value":12}').replace('"value":25}', '"value":15}'),
                  text, flags=re.DOTALL)
    print("  RTT thresholds: 25→15, 20→12")

    # Fix any SLA vector references
    text = text.replace("vector(25)", "vector(15)")
    print("  vector(25)→vector(15)")

    save_yaml_raw("grafana-hierarchical-dashboard.yaml", text)


# ── 4. Fix grafana.yaml (5G Network Slice Monitor) ───────────────────────────
def fix_main_dashboard():
    print("\n[4] grafana.yaml")
    text = load_yaml_raw("grafana.yaml")

    # Add slice filter to errors panel (prevents unlabelled series)
    before = text.count('rate(tun_rx_errors[30s])')
    text = text.replace(
        'rate(tun_rx_errors[30s])',
        'rate(tun_rx_errors{slice=~".+"}[30s])'
    )
    text = text.replace(
        'rate(tun_tx_errors[30s])',
        'rate(tun_tx_errors{slice=~".+"}[30s])'
    )
    text = text.replace(
        'rate(tun_rx_dropped[30s])',
        'rate(tun_rx_dropped{slice=~".+"}[30s])'
    )
    text = text.replace(
        'rate(tun_tx_dropped[30s])',
        'rate(tun_tx_dropped{slice=~".+"}[30s])'
    )
    print(f"  Added slice filter to errors/drops panels ({before} → all fixed)")

    # Also fix any escaped versions
    text = text.replace(
        'rate(tun_rx_errors[30s])',
        'rate(tun_rx_errors{slice=~\\".+\\"}[30s])'
    )

    save_yaml_raw("grafana.yaml", text)


if __name__ == "__main__":
    print("=" * 60)
    print("  Dashboard Consistency Fixer")
    print("=" * 60)
    fix_orchestrator_dashboard()
    fix_app_dashboard()
    fix_hierarchical_dashboard()
    fix_main_dashboard()
    print("\n[Done] Run apply_dashboards.py to push to Grafana.")

# Section 11 — Architecture Classification

## Classification: MEC-Inspired Research Testbed

---

## Evidence Summary

### What it IS

| Property | Evidence |
|---|---|
| Real 5G control plane | Open5GS AMF, SMF, NRF, UDM, AUSF, NSSF — full SA 5G stack |
| Real NAS/RRC signalling | UERANSIM performs actual 5G NAS registration, authentication (5G-AKA), PDU session establishment |
| Real network slicing | 3 separate S-NSSAIs (SST 1/2/3), 3 separate SMFs, 3 separate UPFs, 3 separate IP pools |
| Real GTP-U data plane | Traffic encapsulated in GTP-U (3GPP TS 29.281) between gNB and UPF |
| Real QoS enforcement | tc TBF shaping on UPF N6 interface — actual kernel packet scheduling |
| Real edge computing | Applications co-located with UPF on the same physical node — zero WAN hops |
| Real Kubernetes orchestration | K8s manages UPF and application pods, resource quotas, scaling |
| Local traffic anchoring | 100% of user-plane traffic stays within 192.168.49.0/24 — never reaches internet |

### What it is NOT

| Property | What is missing |
|---|---|
| Real radio | No physical RF. UERANSIM simulates gNB and UEs in software. No PDSCH/PUSCH, no actual air interface |
| Real UE devices | No physical smartphones, IoT sensors, or modems |
| Real eMBB workload | nginx serves static HTTP files. Not actual 4K video with adaptive bitrate logic |
| Real URLLC workload | Node-RED echo server. Not an actual industrial controller or haptic feedback system |
| Real mMTC density | 3 MQTT clients. Not 1000+ IoT devices |
| Per-UE QoS | No per-UE bandwidth shaping — only per-slice, coarse-grained |
| Geographic distribution | All VMs on a single server (VMware), same L2 network. No geographic edge vs. core separation |
| Real backhaul | No simulated backhaul delay. The "RAN" (192.168.49.139) is on the same LAN as the core (192.168.49.143) |

---

## Classification Rationale

### Why NOT "5G testbed" (plain)
This is more than a basic 5G testbed. It includes edge computing placement (UPFs co-located with apps), an autonomous orchestration layer, and live QoS management — features not present in a standard connectivity testbed.

### Why NOT "MEC platform" (full)
A full MEC platform would require:
- ETSI MEC APIs (Mp1, Mm1, Mm3, etc.)
- MEC application lifecycle management
- Geographic separation between RAN, edge, and core
- Real hardware (USRP, commercial UE)
This platform has none of these.

### Why NOT "Distributed edge platform"
There is no geographic distribution. All compute is co-located in a single VMware host (implied by shared /24 subnet, same CPU model across all VMs, low inter-VM RTT of ~12ms).

### Why "MEC-Inspired Research Testbed" is accurate

The platform faithfully reproduces the **architectural intent** of MEC:
1. UPF (N6/local breakout) + Application are on the same compute node → local traffic anchoring ✓
2. Network slicing enforces resource isolation between eMBB/URLLC/mMTC → slice isolation ✓
3. An autonomous orchestrator monitors KPIs and enforces QoS policies → MEC orchestration ✓
4. Traffic never leaves the platform → edge computing locality ✓

What is simulated (not real): the radio access network, user devices, and geographic separation.

---

## Final Classification

```
Platform Type:    MEC-Inspired 5G Network Slicing Research Testbed

5G Standard:      3GPP Release 16 (5G SA, NSSAI, PFCP, GTP-U)
Core:             Open5GS (real 5G SA stack)
RAN:              UERANSIM (software simulation)
Edge Compute:     Kubernetes (hostNetwork UPF + co-located apps)
Orchestration:    Custom dual-mode (rule-based + agentic LLM)
Slices:           3 (eMBB SST=1, URLLC SST=2, mMTC SST=3)
Traffic:          Fully local (no internet egress)
Research Focus:   QoS orchestration comparison (rule-based vs. agentic LLM)
```

This classification positions the platform accurately for academic publication:
it implements a real, standards-compliant 5G control and data plane within a
software-defined testbed, with authentic MEC architectural patterns, but
without physical radio hardware or geographic distribution.

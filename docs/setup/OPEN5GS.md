# Open5GS Setup

## Installation

```bash
# On shinegami VM (192.168.49.143)
sudo apt install software-properties-common
sudo add-apt-repository ppa:open5gs/latest
sudo apt update
sudo apt install open5gs
```

## Slice Configuration

The deployment uses one SMF and UPF instance per slice:

| Slice | SMF Config | UPF Config | PFCP Port |
|-------|-----------|-----------|-----------|
| eMBB | /etc/open5gs/smf-embb.yaml | /etc/open5gs/upf-embb.yaml | 8805 |
| URLLC | /etc/open5gs/smf-urllc.yaml | /etc/open5gs/upf-urllc.yaml | 8806 |
| mMTC | /etc/open5gs/smf-mmtc.yaml | /etc/open5gs/upf-mmtc.yaml | 8807 |

## Service Management

```bash
# Start all Open5GS services
sudo systemctl start open5gs-amfd open5gs-nrfd open5gs-ausfd open5gs-udmd open5gs-udrd
sudo systemctl start open5gs-pcfd open5gs-scpd open5gs-bsfd open5gs-nssfd
sudo systemctl start open5gs-smfd-embb open5gs-smfd-urllc open5gs-smfd-mmtc

# Restart specific slice
sudo systemctl restart open5gs-smfd-embb open5gs-upfd-embb

# Check logs
sudo journalctl -u open5gs-amfd -f
```

## UPF on Worker Node (Kubernetes)

UPF pods run on the kube worker node:
```bash
kubectl get pods -n embb
kubectl logs deployment/upf-embb -n embb
```

## Subscriber Database

Add subscribers via Open5GS WebUI (port 9999) or MongoDB:
```bash
# WebUI
open5gs-dbctl add <imsi> <ki> <opc>
```

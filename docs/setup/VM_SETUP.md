# VM Architecture & Setup

## Physical Topology

5 Ubuntu 22.04 VMs running on VMware, subnet 192.168.49.0/24

| VM Name | IP | User | Role | RAM | vCPU |
|---------|----|------|------|-----|------|
| kubemaster | 192.168.49.174 | kube-master | K8s Control Plane + Orchestrator | 8GB | 4 |
| kube (y2) | 192.168.49.171 | kube | K8s Worker Node 1 | 8GB | 4 |
| kube2 | 192.168.49.181 | kube2 | K8s Worker Node 2 (offline) | 4GB | 2 |
| shinegami (cloney2) | 192.168.49.143 | shinegami | Open5GS 5G Core | 8GB | 4 |
| shinegami (y2-ue) | 192.168.49.139 | shinegami | UERANSIM + MEC | 8GB | 4 |

## SSH Access

All VMs use key-based SSH from kubemaster. Ensure your SSH key is in `~/.ssh/authorized_keys` on each VM.

```bash
# From kubemaster
ssh kube@192.168.49.171
ssh shinegami@192.168.49.143
ssh shinegami@192.168.49.139
```

## Network Interfaces

- `ens33`: Physical VM NIC (192.168.49.x)
- `cni0`: Kubernetes pod network (10.244.0.0/24)
- `flannel.1`: Flannel VXLAN overlay
- `ogstun-embb`: Open5GS UPF TUN for eMBB
- `ogstun-urllc`: Open5GS UPF TUN for URLLC
- `ogstun-mmtc`: Open5GS UPF TUN for mMTC

## Kubernetes Cluster Setup (kubeadm)

```bash
# On kubemaster (already done — for reference)
kubeadm init --pod-network-cidr=10.244.0.0/16 --apiserver-advertise-address=192.168.49.174

# Install Flannel
kubectl apply -f https://raw.githubusercontent.com/coreos/flannel/master/Documentation/kube-flannel.yml

# Join worker nodes
kubeadm join 192.168.49.174:6443 --token <token> --discovery-token-ca-cert-hash <hash>
```

## Namespaces

| Namespace | Purpose |
|-----------|---------|
| embb | eMBB slice — UPF + MEC app |
| urllc | URLLC slice — UPF + latency-critical app |
| mmtc | mMTC slice — UPF + MQTT broker |
| monitoring | Prometheus + Grafana |
| orchestrator | LangGraph QoS orchestrator |
| default-slice | Default/management slice |

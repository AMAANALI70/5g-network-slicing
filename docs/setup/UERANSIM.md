# UERANSIM Setup

## Installation

UERANSIM is built from source on the MEC/UE VM (192.168.49.139):

```bash
# Prerequisites
sudo apt install make g++ libsctp-dev lksctp-tools iproute2

# Clone and build
git clone https://github.com/aligungr/UERANSIM
cd UERANSIM
make -j$(nproc)
```

## Configuration Files

Located in `ueransim/configs/`:

| File | Purpose |
|------|---------|
| gnb.yaml | gNB (base station) configuration |
| ue-embb.yaml | UE config for eMBB slice |
| ue-urllc.yaml | UE config for URLLC slice |
| ue-mmtc.yaml | UE config for mMTC slice |

## Running UERANSIM

```bash
# Start gNB
./build/nr-gnb -c config/gnb.yaml &

# Start UEs per slice
./build/nr-ue -c config/ue-embb.yaml &
./build/nr-ue -c config/ue-urllc.yaml &
./build/nr-ue -c config/ue-mmtc.yaml &

# Verify tunnel interfaces
ip link show | grep uesimtun
```

## Logs

```bash
# Check UERANSIM logs
tail -f ~/UERANSIM/urllc.log
```

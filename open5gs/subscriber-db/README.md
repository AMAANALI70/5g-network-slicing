# Open5GS Subscriber Database

## Backup

`open5gs-subscribers.tar.gz` contains a `mongodump` snapshot of the Open5GS MongoDB database,
captured from the running testbed (shinegami @ 192.168.49.143) on 2026-07-02.

## Restore

```bash
# On the Open5GS VM (192.168.49.143)
tar -xzf open5gs-subscribers.tar.gz
mongorestore open5gs-db-backup/
```

## Re-add Subscribers Manually (alternative)

```bash
# Using Open5GS dbctl
open5gs-dbctl add <IMSI> <Ki> <OPc>

# Example (eMBB UE)
open5gs-dbctl add 001010000000001 465B5CE8B199B49FAA5F0A2EE238A6BC E8ED289DEBA952E4283B54E88E6183CA

# Add all 3 slice UEs
open5gs-dbctl add 001010000000001 465B5CE8B199B49FAA5F0A2EE238A6BC E8ED289DEBA952E4283B54E88E6183CA  # eMBB
open5gs-dbctl add 001010000000002 465B5CE8B199B49FAA5F0A2EE238A6BC E8ED289DEBA952E4283B54E88E6183CA  # URLLC
open5gs-dbctl add 001010000000003 465B5CE8B199B49FAA5F0A2EE238A6BC E8ED289DEBA952E4283B54E88E6183CA  # mMTC
```

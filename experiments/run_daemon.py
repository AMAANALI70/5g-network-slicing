#!/usr/bin/env python3
"""Daemonize run_ag_only.sh using double-fork to survive parent shell exit."""
import os, sys, time

LOG = '/home/kube-master/k8s/experiments/campaign_logs/supplemental.log'
SCRIPT = '/home/kube-master/k8s/experiments/run_ag_only.sh'

pid = os.fork()
if pid > 0:
    print("Daemon fork 1 done, parent exiting")
    sys.exit(0)

os.setsid()

pid2 = os.fork()
if pid2 > 0:
    print("Daemon fork 2 done, exiting")
    sys.exit(0)

# Grandchild — true daemon
ts = time.strftime("%Y-%m-%d %H:%M:%S")
with open(LOG, 'a') as f:
    f.write('\n=== DAEMON START: ' + ts + ' ===\n')

fd = os.open(LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
os.dup2(fd, 1)
os.dup2(fd, 2)
os.close(fd)
# Redirect stdin from /dev/null
nfd = os.open('/dev/null', os.O_RDONLY)
os.dup2(nfd, 0)
os.close(nfd)

os.execv('/bin/bash', ['/bin/bash', SCRIPT])

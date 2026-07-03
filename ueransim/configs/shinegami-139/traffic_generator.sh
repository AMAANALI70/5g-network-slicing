#!/bin/bash

############################################
# CONFIGURATION
############################################

SESSION_COUNT=${1:-9}        # default 9 sessions (uesimtun0-8)
DURATION_MIN=${2:-120}       # default 120 minutes
SERVER_URL="http://speedtest.tele2.net/10MB.zip"
PING_TARGET="8.8.8.8"

END_TIME=$((SECONDS + DURATION_MIN*60))

echo "----------------------------------------"
echo "Starting traffic on $SESSION_COUNT sessions"
echo "Duration: $DURATION_MIN minutes"
echo "----------------------------------------"

############################################
# TRAFFIC PER SESSION
############################################

for ((i=0; i<SESSION_COUNT; i++)); do
    IFACE="uesimtun$i"

    (
        echo "Starting traffic on $IFACE"

        while [ $SECONDS -lt $END_TIME ]; do

            # High throughput traffic (eMBB style)
            curl --interface $IFACE -o /dev/null -s $SERVER_URL &

            # Low latency traffic (URLLC style)
            ping -I $IFACE -c 5 -i 0.1 $PING_TARGET > /dev/null &

            # Small IoT burst (mMTC style)
            curl --interface $IFACE -X POST https://httpbin.org/post \
                -d "{\"session\":$i,\"value\":42}" -s > /dev/null &

            wait
            sleep 1
        done

        echo "$IFACE finished."

    ) &

done

wait

echo "----------------------------------------"
echo "Traffic generation completed."
echo "----------------------------------------"
#!/bin/bash
# Fallback process supervisor for machines without systemd (or if you'd
# rather not set one up). Restarts the server automatically if it
# crashes. Run inside a screen/tmux session, or from an @reboot cron
# entry, e.g.:
#   @reboot /opt/smart-hostel-mess/deploy/start.sh >> /opt/smart-hostel-mess/server.log 2>&1
cd "$(dirname "$0")/.."
while true; do
    echo "$(date): starting Smart Hostel Mess server"
    python3 run.py
    echo "$(date): server exited with code $?, restarting in 5s"
    sleep 5
done

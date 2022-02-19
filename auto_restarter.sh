#!/bin/sh
counter=0
last_crash_time=$(date +%s)
echo "start auto_restarter"
while true; do
    python3 bot.py
    counter=$((counter+1))
    echo "counter: $counter"
    sleep 2
    current_diff=$(($(date +%s)-last_crash_time))
    last_crash_time=$(date +%s)
    echo "current_diff: $current_diff"
    if [ $counter -eq 3 ]; then
        echo "oh oh, bot mal wieder gecrasht, prÃ¼fe Zeitpunkt vom letzten Crash"
        if [ $current_diff -kt 900 ]; then
            echo "Bereits 3 Restart Versuche und letzter Crash weniger als 15 Minuten her -> kein weiterer Restart"
            break
        else
            echo "Letzter Crash mehr als 15 Minuten her -> restart counter resetten und Bot restart einleiten"
            counter=0
        fi
    fi
done

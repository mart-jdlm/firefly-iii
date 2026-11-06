#!/bin/bash
# bash ~/server/firefly-iii/update/install-timer.sh : enable the weekly update check (systemd user timer).
set -e
systemctl --user link ~/server/firefly-iii/update/firefly-update.service
systemctl --user enable --now ~/server/firefly-iii/update/firefly-update.timer
systemctl --user list-timers firefly-update.timer --no-pager

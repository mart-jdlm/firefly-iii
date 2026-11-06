#!/bin/bash
# bash ~/server/firefly-iii/watchdog/install-timers.sh : enable the hourly health check and the monthly restore test.
set -e
cd ~/server/firefly-iii/watchdog
for name in firefly-watchdog firefly-restore-test; do
  systemctl --user link "$PWD/$name.service"
  systemctl --user enable --now "$PWD/$name.timer"
done
systemctl --user list-timers 'firefly-*' --no-pager

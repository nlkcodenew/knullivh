#!/bin/bash
# KnulliVietHoa - cong cu Viet hoa Knulli OS (font + ban dich)
APP=/userdata/system/knulli-vi
mkdir -p "$APP/logs"
cd "$APP" || exit 1
./bin/knulli-vi >> "$APP/logs/launcher.log" 2>&1

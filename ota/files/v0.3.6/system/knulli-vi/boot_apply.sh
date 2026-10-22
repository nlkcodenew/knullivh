#!/bin/sh
# knulli-vi boot apply - duoc custom.sh goi luc khoi dong (truoc ES).
# Nhiem vu: nap file .mo dung trang thai + ap ThemeSet dang cho (pending)
# vao es_settings.cfg trong luc ES chua chay ( tranh bi ES ghi de).
# Khi khong con gi de ap (da rollback het): tu go hook khoi custom.sh.
APP=/userdata/system/knulli-vi
STATE="$APP/state"
MO_DIR=/usr/share/locale/vi_VN/LC_MESSAGES
ES_SET=/userdata/system/configs/emulationstation/es_settings.cfg

# ES dang chay thi khong dung vao (tranh dua ghi file voi ES)
pidof emulationstation >/dev/null 2>&1 && exit 0

# 1) ThemeSet dang cho
if [ -f "$STATE/pending_themeset.txt" ]; then
  T=$(cat "$STATE/pending_themeset.txt" 2>/dev/null)
  if [ -n "$T" ]; then
    sed -i "s#<string name=\"ThemeSet\" value=\"[^\"]*\" />#<string name=\"ThemeSet\" value=\"$T\" />#" "$ES_SET" 2>/dev/null
  fi
  rm -f "$STATE/pending_themeset.txt"
fi

# 2) File dich theo trang thai
I18N=0; HOOK=0; FEATURES=0; MANUAL=0
if [ -f "$STATE/state.json" ]; then
  grep -q '"i18n": true' "$STATE/state.json" && I18N=1
  grep -q '"hook": true' "$STATE/state.json" && HOOK=1
  grep -q '"features": true' "$STATE/state.json" && FEATURES=1
  grep -q '"manual": true' "$STATE/state.json" && MANUAL=1
fi
if [ "$I18N" = "1" ]; then
  cp "$APP/i18n/emulationstation2.mo" "$MO_DIR/emulationstation2.mo" 2>/dev/null
  # 2a) Menu Cai dat tro choi: fork ES khong dich es_features.cfg qua
  # catalog nen phai nap ban XML da dich san (goc o overlay, mat khi reboot)
  if [ "$FEATURES" = "1" ]; then
    cp "$APP/features/es_features.cfg" /usr/share/emulationstation/es_features.cfg 2>/dev/null
  fi
  # 2a2) Sach huong dan (User Manual): ban PDF tieng Viet, goc o overlay
  if [ "$MANUAL" = "1" ]; then
    cp "$APP/manual/notice-vi.pdf" /usr/share/knulli/doc/notice.pdf 2>/dev/null
  fi
  # 2b) Font mac dinh noi bo cua ES (resources): ghi de bang DejaVu day du
  # (font goc thieu khoi tieng Viet 1EA0-1EF9; reboot se tu khoi phuc neu hook dung ghi)
  RSRC=/usr/share/emulationstation/resources
  DFONT="$APP/fonts/DejaVuSans.ttf"
  [ -f "$DFONT" ] || DFONT=/userdata/themes/es-theme-knulli-vi/_inc/fonts/font.ttf
  for rf in ubuntu_condensed.ttf Vazirmatn-Regular.ttf Rubik-Regular.ttf GmarketSansTTFMedium.ttf opensans_hebrew_condensed_light.ttf opensans_hebrew_condensed_regular.ttf DroidSansFallbackFull.ttf; do
    cp "$DFONT" "$RSRC/$rf" 2>/dev/null
  done
else
  cp "$APP/i18n/emulationstation2.pristine.mo" "$MO_DIR/emulationstation2.mo" 2>/dev/null
  # 3) Khong con gi ca: tu go hook (rollback sach se)
  if [ "$HOOK" = "0" ] && [ ! -f "$STATE/pending_themeset.txt" ]; then
    sed -i '/# >>> knulli-vi hook >>>/,/# <<< knulli-vi hook <<</d' /userdata/system/custom.sh 2>/dev/null
  fi
fi
exit 0

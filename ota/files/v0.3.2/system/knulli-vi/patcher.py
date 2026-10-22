#!/usr/bin/env python3
# patcher.py - engine Viet hoa Knulli (chay tren may, python3).
# Lenh: scan | apply <id> | rscan | rollback <id>
# Moi "unit" la mot buoc cong viec; app SDL goi tung unit de tinh % chinh xac.
# Nguyen tac: chi ghi vao /userdata (ben vung) + file .mo trong overlay
# (co hook custom.sh nap lai moi boot). Font goc luon duoc sao luu.
import glob, io, json, os, re, shutil, subprocess, sys

APP = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(APP, "fonts")
I18N_DIR = os.path.join(APP, "i18n")
STATE_DIR = os.path.join(APP, "state")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
SYS_THEMES = "/usr/share/emulationstation/themes"
USER_THEMES = "/userdata/themes"
LOCALE_MO = "/usr/share/locale/vi_VN/LC_MESSAGES/emulationstation2.mo"
KNULLI_CONF = "/userdata/system/knulli.conf"
ES_SETTINGS = "/userdata/system/configs/emulationstation/es_settings.cfg"
CUSTOM_SH = "/userdata/system/custom.sh"
DRY = os.environ.get("KNVI_DRY") == "1"

SKIP_FONTS = {"players.ttf", "5by7.ttf", "fontawesome-webfont.ttf"}
SENTINELS = [0x0102, 0x0110, 0x01A0, 0x01A1, 0x01AF, 0x01B0,
             0x1EA1, 0x1EB9, 0x1EC7, 0x1ED8, 0x1EE3, 0x1EF3]
HOOK_BEGIN = "# >>> knulli-vi hook >>>"
HOOK_END = "# <<< knulli-vi hook <<<"

def log(msg):
    print(msg, flush=True)

def load_state():
    try:
        with io.open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"copied_themes": [], "patched_themes": {}, "i18n": False,
                "hook": False, "prev_language": None, "prev_themeset": None}

def save_state(st):
    if DRY:
        return
    os.makedirs(STATE_DIR, exist_ok=True)
    with io.open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)

# ---------- do phu glyph bang fc-query (doc truc tiep file) ----------
def font_ranges(path):
    out = subprocess.check_output(["fc-query", "-f", "%{charset}\n", path],
                                  stderr=subprocess.DEVNULL).decode()
    rs = []
    for tok in out.split():
        if "-" in tok:
            a, b = tok.split("-", 1)
            rs.append((int(a, 16), int(b, 16)))
        elif tok:
            rs.append((int(tok, 16), int(tok, 16)))
    return rs

def covers(rs, cp):
    return any(a <= cp <= b for a, b in rs)

def font_status(path):
    """tra ve: 'icon' | 'full' | 'deficient'"""
    try:
        rs = font_ranges(path)
    except Exception:
        return "full"  # khong doc duoc thi khong dung vao
    if not covers(rs, 0x41) or not covers(rs, 0x61):
        return "icon"
    if all(covers(rs, cp) for cp in SENTINELS):
        return "full"
    return "deficient"

def theme_fonts(theme_dir):
    out = []
    for p in glob.glob(os.path.join(theme_dir, "**", "*.ttf"), recursive=True) + \
             glob.glob(os.path.join(theme_dir, "**", "*.otf"), recursive=True):
        if "vi-backup" in p:
            continue
        out.append(p)
    return sorted(out)

def deficient_fonts(theme_dir):
    return [p for p in theme_fonts(theme_dir)
            if os.path.basename(p) not in SKIP_FONTS
            and font_status(p) == "deficient"]

def pick_replacement(font_path):
    n = os.path.basename(font_path).lower()
    bold = "bold" in n
    ital = "italic" in n or "oblique" in n
    cond = "condensed" in n
    if bold and ital:
        f = "DejaVuSans-BoldOblique.ttf"
    elif bold and cond:
        f = "DejaVuSansCondensed-Bold.ttf"
    elif bold:
        f = "DejaVuSans-Bold.ttf"
    elif ital:
        f = "DejaVuSans-Oblique.ttf"
    elif cond:
        f = "DejaVuSansCondensed.ttf"
    else:
        f = "DejaVuSans.ttf"
    return os.path.join(FONTS_DIR, f)

# ---------- helpsystem ----------
HELP_RE = re.compile(r"(<helpsystem[^>]*>)(.*?)(</helpsystem>)", re.S)

def choose_help_font(theme_dir):
    """font thuong (regular) du glyph trong theme, duong dan tuong doi tu goc theme."""
    cands = []
    for p in theme_fonts(theme_dir):
        n = os.path.basename(p).lower()
        if any(w in n for w in ("bold", "italic", "oblique")):
            continue
        if font_status(p) == "full":
            cands.append(p)
    if not cands:
        return None
    cands.sort(key=lambda p: (0 if "regular" in os.path.basename(p).lower() else 1, p))
    return os.path.relpath(cands[0], theme_dir)

def patch_helpsystems(theme_dir, backup_root):
    """gan fontPath cho helpsystem nao chua co. Tra ve so file da sua."""
    changed = 0
    help_font = choose_help_font(theme_dir)
    if not help_font:
        return 0
    for xml in glob.glob(os.path.join(theme_dir, "**", "*.xml"), recursive=True):
        if "vi-backup" in xml:
            continue
        with io.open(xml, encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
        m = HELP_RE.search(text)
        if not m or "fontPath" in m.group(2) or "fontPath" in m.group(1):
            continue
        # ES giai quyet fontPath theo GOC THEME (da kiem chung tren may 21/10:
        # "./_inc/fonts/font.ttf" chay dung; duong dan theo thu muc xml thi sai)
        rel_from_xml = "./" + help_font
        if xml.endswith(os.path.join("_inc", "xml", "help.xml")):
            # kieu attribute (knulli): chen attribute vao the mo
            new = m.group(0).replace('<helpsystem name="help"',
                                     '<helpsystem name="help"\n\t\t\tfontPath="%s"' % rel_from_xml, 1)
            if new == m.group(0):
                continue
        else:
            new = m.group(1) + '\n         <fontPath>%s</fontPath>' % rel_from_xml + m.group(2) + m.group(3)
        if not DRY:
            bdir = os.path.join(backup_root, os.path.relpath(xml, theme_dir))
            os.makedirs(os.path.dirname(bdir), exist_ok=True)
            shutil.copy2(xml, bdir)
            with io.open(xml, "w", encoding="utf-8", newline="") as f:
                f.write(text.replace(m.group(0), new, 1))
        changed += 1
        log("helpsystem: %s" % os.path.relpath(xml, theme_dir))
    return changed

def patch_fonts(theme_dir, backup_root):
    """thay font thieu glyph bang font dong goi; sao luu goc. Tra ve so font da thay."""
    n = 0
    for p in deficient_fonts(theme_dir):
        rel = os.path.relpath(p, theme_dir)
        if not DRY:
            bdst = os.path.join(backup_root, rel)
            if not os.path.exists(bdst):
                os.makedirs(os.path.dirname(bdst), exist_ok=True)
                shutil.copy2(p, bdst)
            shutil.copy2(pick_replacement(p), p)
        n += 1
        log("font: %s" % rel)
    return n

# ---------- xac dinh OS: CHI chay tren Knulli ----------
def os_check():
    """Tra ve (ok, missing[]). Yeu cau DU cac dau hieu dac trung Knulli —
    thieu mot cai la tu choi lam viec (phong user chay nham OS khac)."""
    missing = []
    if not os.path.isfile(KNULLI_CONF):
        missing.append("khong co /userdata/system/knulli.conf")
    if not glob.glob("/usr/bin/knulli-*"):
        missing.append("khong co cong cu knulli-* trong /usr/bin")
    if not os.path.isfile(LOCALE_MO):
        missing.append("khong co catalog emulationstation2 (vi_VN)")
    if not os.path.isdir(SYS_THEMES):
        missing.append("khong co thu muc theme cua EmulationStation")
    return (not missing), missing

# ---------- cac unit ----------
def current_themeset():
    try:
        with io.open(ES_SETTINGS, encoding="utf-8", errors="replace") as f:
            m = re.search(r'name="ThemeSet" value="([^"]*)"', f.read())
            return m.group(1) if m else None
    except Exception:
        return None

def current_language():
    try:
        with io.open(KNULLI_CONF, encoding="utf-8", errors="replace") as f:
            m = re.search(r"^system\.language=(.*)$", f.read(), re.M)
            return m.group(1).strip() if m else None
    except Exception:
        return None

def scan():
    st = load_state()
    units = []
    sys_names = sorted(os.listdir(SYS_THEMES)) if os.path.isdir(SYS_THEMES) else []
    for name in sys_names:
        tdir = os.path.join(SYS_THEMES, name)
        if not os.path.isdir(tdir):
            continue
        if deficient_fonts(tdir):
            units.append({"id": "copy-theme:%s" % name,
                          "vi": "Dựng theme %s-vi + vá font" % name,
                          "en": "Build theme %s-vi + patch fonts" % name})
    if os.path.isdir(USER_THEMES):
        for name in sorted(os.listdir(USER_THEMES)):
            tdir = os.path.join(USER_THEMES, name)
            if not os.path.isdir(tdir) or name.endswith("-vi"):
                continue
            if name in st.get("patched_themes", {}):
                continue
            if deficient_fonts(tdir):
                units.append({"id": "patch-theme:%s" % name,
                              "vi": "Vá font theme %s" % name,
                              "en": "Patch fonts of theme %s" % name})
    units.append({"id": "i18n", "vi": "Nạp bản dịch tiếng Việt đầy đủ",
                  "en": "Install full Vietnamese translation"})
    units.append({"id": "hook", "vi": "Cài hook tự nạp lại khi khởi động",
                  "en": "Install boot hook"})
    if current_language() != "vi_VN":
        units.append({"id": "lang", "vi": "Đặt ngôn ngữ hệ thống: Tiếng Việt",
                      "en": "Set system language: Vietnamese"})
    ts = current_themeset()
    if ts and os.path.isdir(os.path.join(SYS_THEMES, ts)) and \
            any(u["id"] == "copy-theme:%s" % ts for u in units):
        units.append({"id": "themeset", "vi": "Chuyển theme đang dùng sang bản -vi",
                      "en": "Switch active theme to the -vi build"})
    return units

def do_copy_theme(name):
    src = os.path.join(SYS_THEMES, name)
    dst = os.path.join(USER_THEMES, name + "-vi")
    if not DRY:
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst, symlinks=True)
    backup_root = os.path.join(dst, "vi-backup-kv")
    patch_fonts(dst, backup_root)
    patch_helpsystems(dst, os.path.join(backup_root, "xml"))
    st = load_state()
    if name + "-vi" not in st["copied_themes"]:
        st["copied_themes"].append(name + "-vi")
    save_state(st)

def do_patch_theme(name):
    tdir = os.path.join(USER_THEMES, name)
    backup_root = os.path.join(tdir, "vi-backup-kv")
    # nhan ban sao luu thu cong cu (vi-backup/) neu co - giu kha nang rollback
    manual = os.path.join(tdir, "_inc", "fonts", "vi-backup")
    patch_fonts(tdir, backup_root)
    patch_helpsystems(tdir, os.path.join(backup_root, "xml"))
    st = load_state()
    st["patched_themes"][name] = {"backup": "vi-backup-kv",
                                  "manual_backup": os.path.isdir(manual)}
    save_state(st)

def hook_block():
    return (HOOK_BEGIN + "\n"
            "sh " + os.path.join(APP, "boot_apply.sh") + " >/dev/null 2>&1\n"
            + HOOK_END + "\n")

def do_hook():
    if not DRY:
        with io.open(CUSTOM_SH, encoding="utf-8", errors="replace") as f:
            text = f.read()
        text = re.sub(re.escape(HOOK_BEGIN) + r".*?" + re.escape(HOOK_END) + r"\n?",
                      "", text, flags=re.S)
        with io.open(CUSTOM_SH, "w", encoding="utf-8", newline="\n") as f:
            f.write(text.rstrip("\n") + "\n\n" + hook_block())
    st = load_state()
    st["hook"] = True
    save_state(st)

def do_i18n():
    if not DRY:
        shutil.copy2(os.path.join(I18N_DIR, "emulationstation2.mo"), LOCALE_MO)
    st = load_state()
    st["i18n"] = True
    save_state(st)

def do_lang():
    st = load_state()
    if st.get("prev_language") is None:
        st["prev_language"] = current_language()
    if not DRY:
        with io.open(KNULLI_CONF, encoding="utf-8", errors="replace") as f:
            text = f.read()
        if re.search(r"^system\.language=.*$", text, re.M):
            text = re.sub(r"^system\.language=.*$", "system.language=vi_VN", text, flags=re.M)
        else:
            text += "\nsystem.language=vi_VN\n"
        with io.open(KNULLI_CONF, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    save_state(st)

def do_themeset():
    st = load_state()
    ts = current_themeset()
    if st.get("prev_themeset") is None:
        st["prev_themeset"] = ts
    if ts:
        if not DRY:
            os.makedirs(STATE_DIR, exist_ok=True)
            with io.open(os.path.join(STATE_DIR, "pending_themeset.txt"), "w", encoding="utf-8") as f:
                f.write(ts + "-vi")
    save_state(st)

APPLY = {"copy-theme": do_copy_theme, "patch-theme": do_patch_theme,
         "i18n": lambda: do_i18n(), "hook": lambda: do_hook(),
         "lang": lambda: do_lang(), "themeset": lambda: do_themeset()}

# ---------- rollback ----------
def rscan():
    st = load_state()
    units = []
    if st.get("i18n"):
        units.append({"id": "un-i18n", "vi": "Trả lại bản dịch gốc",
                      "en": "Restore original translation"})
    for name in st.get("copied_themes", []):
        units.append({"id": "remove-copy:%s" % name,
                      "vi": "Xoá theme %s" % name, "en": "Remove theme %s" % name})
    for name in st.get("patched_themes", {}):
        units.append({"id": "restore-theme:%s" % name,
                      "vi": "Trả font gốc cho theme %s" % name,
                      "en": "Restore original fonts of theme %s" % name})
    if st.get("prev_themeset"):
        units.append({"id": "un-themeset", "vi": "Trả theme đang dùng về bản gốc",
                      "en": "Restore original active theme"})
    if st.get("prev_language"):
        units.append({"id": "un-lang", "vi": "Trả ngôn ngữ về %s" % st["prev_language"],
                      "en": "Restore language to %s" % st["prev_language"]})
    if st.get("hook"):
        units.append({"id": "un-hook", "vi": "Gỡ hook khởi động",
                      "en": "Remove boot hook"})
    return units

def rb_remove_copy(name):
    dst = os.path.join(USER_THEMES, name)
    if not DRY and os.path.exists(dst):
        shutil.rmtree(dst)
    st = load_state()
    st["copied_themes"] = [c for c in st["copied_themes"] if c != name]
    save_state(st)

def rb_restore_theme(name):
    tdir = os.path.join(USER_THEMES, name)
    info = load_state().get("patched_themes", {}).get(name, {})
    broot = os.path.join(tdir, info.get("backup", "vi-backup-kv"))
    if os.path.isdir(broot):
        for p in glob.glob(os.path.join(broot, "**", "*.*"), recursive=True):
            if os.path.isfile(p):
                rel = os.path.relpath(p, broot)
                if rel.startswith("xml" + os.sep):
                    rel = rel[len("xml" + os.sep):]
                dst = os.path.join(tdir, rel)
                if not DRY:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(p, dst)
        if not DRY:
            shutil.rmtree(broot)
    # theme tung va tay truoc khi co app: tra font goc tu vi-backup/ thu cong
    if info.get("manual_backup"):
        mroot = os.path.join(tdir, "_inc", "fonts", "vi-backup")
        if os.path.isdir(mroot):
            for p in glob.glob(os.path.join(mroot, "*.ttf")) + \
                     glob.glob(os.path.join(mroot, "*.otf")):
                if not DRY:
                    shutil.copy2(p, os.path.join(tdir, "_inc", "fonts",
                                                 os.path.basename(p)))
    st = load_state()
    st["patched_themes"].pop(name, None)
    save_state(st)

def rb_un_i18n():
    if not DRY:
        shutil.copy2(os.path.join(I18N_DIR, "emulationstation2.pristine.mo"), LOCALE_MO)
    st = load_state()
    st["i18n"] = False
    save_state(st)

def rb_un_themeset():
    st = load_state()
    prev = st.get("prev_themeset")
    if prev and not DRY:
        os.makedirs(STATE_DIR, exist_ok=True)
        with io.open(os.path.join(STATE_DIR, "pending_themeset.txt"), "w", encoding="utf-8") as f:
            f.write(prev)
    st["prev_themeset"] = None
    save_state(st)

def rb_un_lang():
    st = load_state()
    prev = st.get("prev_language")
    if prev and not DRY:
        with io.open(KNULLI_CONF, encoding="utf-8", errors="replace") as f:
            text = f.read()
        text = re.sub(r"^system\.language=.*$", "system.language=" + prev, text, flags=re.M)
        with io.open(KNULLI_CONF, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    st["prev_language"] = None
    save_state(st)

def rb_un_hook():
    # chi danh dau; boot_apply.sh se tu go block o lan boot ke tiep khi khong con viec.
    st = load_state()
    st["hook"] = False
    save_state(st)

ROLLBACK = {"remove-copy": rb_remove_copy, "restore-theme": rb_restore_theme,
            "un-i18n": lambda: rb_un_i18n(), "un-themeset": lambda: rb_un_themeset(),
            "un-lang": lambda: rb_un_lang(), "un-hook": lambda: rb_un_hook()}

def main():
    if len(sys.argv) < 2:
        print("usage: patcher.py scan|apply <id>|rscan|rollback <id>")
        return 2
    cmd = sys.argv[1]
    if cmd == "oscheck":
        ok, missing = os_check()
        print("OK 1" if ok else "OK 0")
        for m in missing:
            print("MISSING " + m)
        return 0 if ok else 3
    if cmd in ("scan", "rscan", "apply", "rollback"):
        ok, missing = os_check()
        if not ok:
            print("TU CHOI: khong phai Knulli OS (%s)" % "; ".join(missing),
                  file=sys.stderr)
            if cmd in ("scan", "rscan"):
                return 0  # danh sach rong = app khong co viec de chay
            return 3
    if cmd in ("scan", "rscan"):
        units = scan() if cmd == "scan" else rscan()
        if os.environ.get("KNVI_PLAIN"):
            for u in units:
                print("%s\t%s\t%s" % (u["id"], u["vi"], u["en"]))
        else:
            print(json.dumps(units, ensure_ascii=False))
    elif cmd in ("apply", "rollback"):
        table = APPLY if cmd == "apply" else ROLLBACK
        uid = sys.argv[2]
        key, _, arg = uid.partition(":")
        fn = table.get(key)
        if fn is None:
            print("unknown unit: " + uid)
            return 1
        fn(arg) if arg else fn()
        log("DONE " + uid)
    return 0

if __name__ == "__main__":
    sys.exit(main())

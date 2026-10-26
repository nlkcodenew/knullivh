#!/usr/bin/env python3
# patcher.py - engine Viet hoa Knulli (chay tren may, python3).
# Lenh: scan | apply <id> | rscan | rollback <id>
# Moi "unit" la mot buoc cong viec; app SDL goi tung unit de tinh % chinh xac.
# Nguyen tac: chi ghi vao /userdata (ben vung) + file .mo trong overlay
# (co hook custom.sh nap lai moi boot) + ban .mo staged tren /boot
# (hook S00 nap truoc ES, vi custom.sh chay o S99 la sau ES).
# Font goc luon duoc sao luu.
import glob, io, json, os, re, shutil, struct, subprocess, sys, tarfile
import tempfile, urllib.request

APP = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(APP, "fonts")
FAMILIES_DIR = os.path.join(APP, "fonts-extra")
LOGS_DIR = os.path.join(APP, "logs")
FONT_REPORT = os.path.join(LOGS_DIR, "font-report.txt")
I18N_DIR = os.path.join(APP, "i18n")
LANG_DIR = os.path.join(APP, "lang")
LANG_VI = os.path.join(LANG_DIR, "lang-vi.xml")
FEATURES_DIR = os.path.join(APP, "features")
FEATURES_SRC = os.path.join(FEATURES_DIR, "es_features.cfg")
SYS_FEATURES = "/usr/share/emulationstation/es_features.cfg"
MANUAL_DIR = os.path.join(APP, "manual")
MANUAL_SRC = os.path.join(MANUAL_DIR, "notice-vi.pdf")
SYS_MANUAL = "/usr/share/knulli/doc/notice.pdf"
ICON_SRC = os.path.join(APP, "icon", "knulliviethoa.png")
ICON_DST_DIR = "/userdata/roms/tools/images"
ICON_DST = os.path.join(ICON_DST_DIR, "knulliviethoa.png")
ICON_TAG = "./images/knulliviethoa.png"
TOOLS_GAMELIST = "/userdata/roms/tools/gamelist.xml"
STATE_DIR = os.path.join(APP, "state")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
FEATURES_BACKUP = os.path.join(STATE_DIR, "es_features.cfg.orig")
MANUAL_BACKUP = os.path.join(STATE_DIR, "notice.pdf.orig")
SPLASH_BACKUP_DIR = os.path.join(STATE_DIR, "splash-backup")
THEME_BACKUP_DIR = os.path.join(STATE_DIR, "theme-backup")
LANG_ARTBOOK = os.path.join(LANG_DIR, "art-book-next-vi.xml")
SYS_THEMES = "/usr/share/emulationstation/themes"
USER_THEMES = "/userdata/themes"
LOCALE_MO = "/usr/share/locale/vi_VN/LC_MESSAGES/emulationstation2.mo"
# Early locale (S00 < S31): /boot ben vung + da mount truoc S00, trong khi
# /usr/share la tmpfs-backed va mat khi reboot. Stage catalog len /boot va
# copy tu /boot/boot-custom.sh o S00 dam bao ES nap catalog tieng Viet ngay
# tu dau (hook custom.sh o S99 chay sau ES nen qua muon: ES giu catalog
# stock no map truoc). File staged la cong tac: co = tieng Viet, khong = no-op.
BOOT_STAGED_MO = "/boot/knulli-vi-emulationstation2.mo"
BOOT_CUSTOM = "/boot/boot-custom.sh"
BOOT_BLOCK_START = "# >>> knulli-vi early-locale >>>"
BOOT_BLOCK_END = "# <<< knulli-vi early-locale <<<"
KNULLI_CONF = "/userdata/system/knulli.conf"
ES_SETTINGS = "/userdata/system/configs/emulationstation/es_settings.cfg"
CUSTOM_SH = "/userdata/system/custom.sh"
BOOT_DIR = "/boot"
BOOTLOGO = "/boot/bootlogo.bmp"
BOOTLOGO_BOARD_FILE = "/boot/boot/knulli.board"
# Board co panel doc bam sinh nhung bootlogo dong goi ngang -> anh khoi dong
# bi xoay 90 do o giai doan bootloader (truoc khi kernel/ES xu ly huong man).
BOOTLOGO_BOARDS = {"trimui-smart-pro-s"}
BOOTLOGO_BACKUP = os.path.join(STATE_DIR, "bootlogo.bmp.orig")
# RetroArch: thong bao OSD (tai state, netplay...) dung font o video_font_path.
# configgen cua Knulli EP gia tri nay = DejaVuSansMono.ttf moi lan mo game
# (libretroRetroarchCustom.generateRetroarchCustomPathes) nen sua cfg khong
# ben. Ban goc cua DejaVu Sans Mono thieu 59 glyph tieng Viet (moi nguyen am
# dau hoi/nga...) nen chu thanh o vuong. Cach sua: giu nguyen duong dan, thay
# NOI DUNG file bang DejaVuSans.ttf day du glyph (nhu cach app ghi de font
# resources cua ES); /usr/share la overlay nen boot_apply nap lai moi boot.
SYS_RA_FONT = "/usr/share/fonts/dejavu/DejaVuSansMono.ttf"
RA_FONT_SRC = os.path.join(FONTS_DIR, "DejaVuSans.ttf")
RA_FONT_BACKUP = os.path.join(STATE_DIR, "DejaVuSansMono.ttf.orig")
DRY = os.environ.get("KNVI_DRY") == "1"

SKIP_FONTS = {"players.ttf", "5by7.ttf", "fontawesome-webfont.ttf"}
# Tap glyph tieng Viet "du" cho ES: ES render chuoi precomposed (khong tu
# ghep dau bang shaping engine) nen font phai co SAN cac ky tu ghep san.
# Chu y: Ubuntu goc cung KHONG co khoi precomposed 1EA0-1EF9 (chi co dau
# to hop) nen khong dung lam font sua cho ES duoc - da kiem chung 25/10
# bang ca cmap parser lan fc-query (phuong phap cua chinh ham nay).
VI_BASE = [0x00C2, 0x00E2, 0x00CA, 0x00EA, 0x00D4, 0x00F4,
           0x0102, 0x0103, 0x0110, 0x0111, 0x01A0, 0x01A1, 0x01AF, 0x01B0]
VI_PRECOMPOSED = list(range(0x1EA0, 0x1EFA))
VI_MARKS = [0x0300, 0x0301, 0x0303, 0x0309, 0x0323]
SENTINELS = VI_BASE + VI_PRECOMPOSED + VI_MARKS
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
                "features": False, "manual": False, "icon": False,
                "rafont": False, "splash_upper": [],
                "theme_xml": [], "theme_lang": [],
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
    """tra ve: 'icon' | 'full' | 'deficient' | 'unreadable'"""
    try:
        rs = font_ranges(path)
    except Exception:
        return "unreadable"  # khong doc duoc: khong tu sua, de bao cao rieng
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

def font_family_slug(path):
    """ho font cua file (vd 'Saira', 'Noto Sans') -> slug ('saira', 'notosans').
    Tra ve '' neu khong doc duoc."""
    try:
        out = subprocess.check_output(["fc-query", "-f", "%{family}\n", path],
                                      stderr=subprocess.DEVNULL).decode()
        fam = out.split("|")[0].split(",")[0].strip()
        return re.sub(r"[^a-z0-9]", "", fam.lower())
    except Exception:
        return ""

def pick_replacement(font_path):
    """Chon font thay the cho font thieu glyph, uu tien GIU NGUYEN HO FONT:
    font regular/bold cung ho (trong fonts-extra, da kiem chung du tieng Viet
    precomposed) -> DejaVu theo dung kieu (fallback). Rieng italic/condensed
    thi uu tien giu kieu (DejaVu Oblique/Condensed) hon giu ho, vi kieu la
    lua chon bo cuc co chu dich cua theme."""
    n = os.path.basename(font_path).lower()
    bold = "bold" in n
    ital = "italic" in n or "oblique" in n
    cond = "condensed" in n
    if not ital and not cond:
        fam = font_family_slug(font_path)
        if fam:
            cand = os.path.join(FAMILIES_DIR,
                                "%s-%s.ttf" % (fam, "Bold" if bold else "Regular"))
            if os.path.isfile(cand):
                return cand
            if bold:
                cand = os.path.join(FAMILIES_DIR, "%s-Regular.ttf" % fam)
                if os.path.isfile(cand):
                    return cand
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

# ---------- bao cao font khong va duoc ----------
# Font icon (khong co A/a) CO TINH khong bao cao: chung lam viec dung nhu
# thiet ke, va khong phai font chu. Chi bao cao nhung truong hop app that su
# khong sua duoc font chu: khong doc duoc file, theme tro toi file khong
# ton tai, dinh dang ngoai .ttf/.otf (quet khong nhin thay).
UNFIXABLE_EXTS = {".woff", ".woff2", ".bdf", ".pcf", ".fnt", ".fon"}
FONT_PATH_RE = re.compile(r"<fontPath>([^<]+)</fontPath>")

def _theme_path_exists(theme_dir, xml_dir, v):
    """fontPath co tro toi file that khong? ES giai quyet duong dan tuong
    doi khong nhat quan tuy cho: view thi theo thu muc file xml, helpsystem
    thi theo goc theme, file include (subsets/) thi theo file include no.
    Quy uoc chung cua theme: ./../ o dau nghia la 've goc theme' - nen
    ngoai 2 cach noi tren, con thu ca dang da got cac ../ o dau ve goc.
    Chi bao 'khong ton tai' khi ca 3 cach deu khong thay file."""
    rel = v[2:] if v.startswith("./") else v
    stripped = rel
    while stripped.startswith("../"):
        stripped = stripped[3:]
    for base in (xml_dir, theme_dir):
        if os.path.isfile(os.path.join(base, rel)):
            return True
    if stripped != rel and os.path.isfile(os.path.join(theme_dir, stripped)):
        return True
    return False

def theme_xml_fontpaths(theme_dir):
    """(xml_rel, fontpath, ton_tai) cho cac fontPath dang duong dan that
    (bo qua bien ${...} vi muc tieu cua chung da nam trong theme_fonts)."""
    out = []
    for xml in glob.glob(os.path.join(theme_dir, "**", "*.xml"), recursive=True):
        if "vi-backup" in xml:
            continue
        try:
            with io.open(xml, encoding="utf-8-sig", errors="replace") as f:
                text = f.read()
        except Exception:
            continue
        for m in FONT_PATH_RE.finditer(text):
            v = m.group(1).strip()
            if not v or "$" in v or ":" in v or "/" not in v:
                continue
            ok = _theme_path_exists(theme_dir, os.path.dirname(xml), v)
            out.append((os.path.relpath(xml, theme_dir), v, ok))
    return out

def unfixable_fonts(theme_dir):
    """Danh sach dict {font, kind, vi, en} ma app khong va duoc."""
    out = []
    for p in theme_fonts(theme_dir):
        if font_status(p) == "unreadable":
            out.append({"font": os.path.relpath(p, theme_dir),
                        "kind": "unreadable",
                        "vi": "Không đọc được file font (có thể hỏng hoặc định dạng lạ)",
                        "en": "Unreadable font file (may be corrupt or exotic format)"})
    seen = set()
    for _xml, v, ok in theme_xml_fontpaths(theme_dir):
        if not ok and v not in seen:
            seen.add(v)
            out.append({"font": v,
                        "kind": "missing",
                        "vi": "Theme trỏ tới file font không tồn tại",
                        "en": "Theme references a missing font file"})
    for p in glob.glob(os.path.join(theme_dir, "**", "*"), recursive=True):
        if os.path.isfile(p) and os.path.splitext(p)[1].lower() in UNFIXABLE_EXTS:
            out.append({"font": os.path.relpath(p, theme_dir),
                        "kind": "unsupported",
                        "vi": "Định dạng font không hỗ trợ (chỉ quét .ttf/.otf)",
                        "en": "Unsupported font format (only .ttf/.otf are scanned)"})
    return out

def font_report():
    """Quet moi theme, tra ve danh sach {theme, font, kind, vi, en} khong
    va duoc; dong thoi ghi log logs/font-report.txt (tru DRY)."""
    import datetime
    rows = []
    for base in (SYS_THEMES, USER_THEMES):
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            tdir = os.path.join(base, name)
            if not os.path.isdir(tdir):
                continue
            for u in unfixable_fonts(tdir):
                rows.append({"theme": name, "font": u["font"],
                             "kind": u["kind"], "vi": u["vi"], "en": u["en"]})
    if not DRY:
        try:
            os.makedirs(LOGS_DIR, exist_ok=True)
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with io.open(FONT_REPORT, "w", encoding="utf-8", newline="\n") as f:
                f.write("# Báo cáo font không vá được — KnulliVietHoa\n")
                f.write("# Ngày: %s\n" % now)
                f.write("# Thấy lỗi font ở đâu -> gửi log này cho tác giả để sửa.\n")
                f.write("# Tổng: %d mục\n" % len(rows))
                for r in rows:
                    f.write("[%s] %s — %s\n" % (r["theme"], r["font"], r["vi"]))
                if not rows:
                    f.write("(Không có mục nào — mọi font chữ đều vá được.)\n")
        except Exception:
            pass
    return rows

def theme_check():
    """Kiem tra theme hien tai (chi doc, khong sua): font tung file +
    trang thai dich + ket luan. Tra ve dict de in PLAIN/JSON."""
    name = current_themeset()
    if not name:
        return {"error": {"vi": "Không đọc được theme đang dùng (ThemeSet).",
                          "en": "Cannot read the active theme (ThemeSet)."}}
    tdir = None
    loc = None
    for base, lb in ((USER_THEMES, "user"), (SYS_THEMES, "sys")):
        if os.path.isdir(os.path.join(base, name)):
            tdir = os.path.join(base, name)
            loc = lb
            break
    if not tdir:
        return {"error": {"vi": "Theme đang dùng (%s) không tìm thấy trên máy." % name,
                          "en": "Active theme (%s) not found on this device." % name}}
    st = load_state()
    is_vi = name.endswith("-vi") or name in st.get("copied_themes", [])
    fonts = []
    for p in theme_fonts(tdir):
        base = os.path.basename(p)
        status = "skip" if base in SKIP_FONTS else font_status(p)
        fonts.append({"font": os.path.relpath(p, tdir), "status": status})
    # dich rieng cua theme (chi nhung co che nao theme do co)
    tr_vi = []
    tr_en = []
    tr_ok = True
    if theme_vars_dir(tdir) is not None:
        ok = theme_strings_current(tdir)
        tr_vi.append("menu theme đã có" if ok else "menu theme chưa có")
        tr_en.append("theme menu strings installed" if ok else
                     "theme menu strings missing")
        tr_ok = tr_ok and ok
    if os.path.basename(tdir) in ("es-theme-art-book-next",
                                  "es-theme-art-book-next-vi"):
        try:
            with io.open(os.path.join(tdir, "theme.xml"),
                         encoding="utf-8", errors="replace") as f:
                xml = f.read()
        except Exception:
            xml = ""
        done = sum(1 for v in ARTBOOK_SUBSETS.values()
                   if ('displayName="%s"' % v["name"]) in xml)
        total = len(ARTBOOK_SUBSETS)
        tr_vi.append("subset %d/%d" % (done, total))
        tr_en.append("subsets %d/%d" % (done, total))
        tr_ok = tr_ok and done == total
    lang_dir = os.path.join(tdir, "_inc", "lang")
    if os.path.isdir(lang_dir):
        ok = os.path.exists(os.path.join(lang_dir, "vi.xml"))
        tr_vi.append("lang vi đã có" if ok else "lang vi chưa có")
        tr_en.append("lang vi present" if ok else "lang vi missing")
        tr_ok = tr_ok and ok
    # ban dich ES toan cuc (ngu canh cho ket luan)
    lang = current_language()
    sys_ok = bool(st.get("i18n")) and lang == "vi_VN"
    deficient = [f["font"] for f in fonts if f["status"] == "deficient"]
    unreadable = [f["font"] for f in fonts if f["status"] == "unreadable"]
    full_n = sum(1 for f in fonts if f["status"] == "full")
    font_ok = not deficient and not unreadable
    verdict_ok = font_ok and tr_ok and sys_ok
    if tr_vi:
        trsum_vi = "Dịch theme: " + ", ".join(tr_vi)
        trsum_en = "Theme translation: " + ", ".join(tr_en)
    else:
        trsum_vi = "Dịch theme: theme không có chuỗi riêng để dịch"
        trsum_en = "Theme translation: theme has no own strings to translate"
    if verdict_ok:
        verdict = {"vi": "ĐỦ — theme hiện tại đã đủ tiếng Việt",
                   "en": "OK — current theme is fully Vietnamese"}
    else:
        verdict = {"vi": "CHƯA ĐỦ — xem chi tiết bên trên",
                   "en": "NOT YET — see details above"}
    hints = []
    if deficient:
        hints.append({"vi": "Vào Việt hoá để vá font thiếu",
                      "en": "Run Viet hoa to patch the missing fonts"})
    if unreadable:
        hints.append({"vi": "Font lỗi không vá được — xem Báo cáo font",
                      "en": "Unreadable fonts cannot be patched — see Font report"})
    if tr_vi and not tr_ok:
        hints.append({"vi": "Vào Việt hoá để dịch theme",
                      "en": "Run Viet hoa to translate the theme"})
    if not sys_ok:
        hints.append({"vi": "Vào Việt hoá để nạp bản dịch tiếng Việt",
                      "en": "Run Viet hoa to install the Vietnamese translation"})
    out = {"theme": name, "location": loc, "is_vi": is_vi, "fonts": fonts,
           "full": full_n, "deficient": deficient, "unreadable": unreadable,
           "trsum": {"vi": trsum_vi, "en": trsum_en},
           "syslang": lang, "sys_ok": sys_ok,
           "verdict_ok": verdict_ok, "verdict": verdict, "hints": hints}
    if not DRY:
        try:
            import datetime
            os.makedirs(LOGS_DIR, exist_ok=True)
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with io.open(os.path.join(LOGS_DIR, "theme-check.txt"),
                         "w", encoding="utf-8", newline="\n") as f:
                f.write("# Kiểm tra theme hiện tại — KnulliVietHoa\n")
                f.write("# Ngày: %s\n" % now)
                f.write("Theme: %s (%s, %s)\n" %
                        (name, loc, "ban -vi" if is_vi else "ban goc"))
                for fn in fonts:
                    f.write("Font: %s — %s\n" % (fn["font"], fn["status"]))
                f.write("%s\n" % trsum_vi)
                f.write("Ngôn ngữ hệ thống: %s, bản dịch ES: %s\n" %
                        (lang, "đã nạp" if sys_ok else "chưa nạp"))
                f.write("Kết luận: %s\n" % verdict["vi"])
        except Exception:
            pass
    return out

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

# ---------- theme strings (chu tieng Viet cho menu chu de) ----------
# ES cua Knulli viet hoa chuoi khi hien thi bang ham loi: chuoi nguon dang
# thuong bi hong dau (¶). File lang-vi.xml cua goi da viet hoa san cac chuoi
# subset.* nen vuot qua duoc. ES tu nap _inc/variables/lang-<lang>.xml cua
# theme; ta chi can dat lang-vi.xml + lang-vi_VN.xml vao theme da sao chep.
def theme_vars_dir(theme_dir):
    d = os.path.join(theme_dir, "_inc", "variables")
    if os.path.isdir(d) and os.path.exists(os.path.join(d, "lang-default.xml")):
        return d
    return None

def theme_strings_current(theme_dir):
    """True neu theme khong dung co che lang-*.xml, hoac da co ban moi nhat."""
    d = theme_vars_dir(theme_dir)
    if not d or not os.path.exists(LANG_VI):
        return True
    try:
        with io.open(LANG_VI, "rb") as f:
            want = f.read()
        for fn_ in ("lang-vi.xml", "lang-vi_VN.xml"):
            p = os.path.join(d, fn_)
            if not os.path.exists(p):
                return False
            with io.open(p, "rb") as f:
                if f.read() != want:
                    return False
        return True
    except Exception:
        return True

# ---------- features (Cai dat tro choi) ----------
# Fork ES cua Knulli KHONG dich chuoi trong es_features.cfg qua catalog
# (da xac nhan tren may 22/10: 'REWIND' co san ban dich trong .mo ma van
# hien tieng Anh). Cach duy nhat: thay thang file XML bang ban da dich san
# (chi doi name/description/submenu/group, giu nguyen value/preset).
# File goc nam o overlay /usr/share -> hook boot nap lai moi lan khoi dong.
def features_current():
    """True neu khong co payload, hoac file he thong da la ban dich moi nhat."""
    if not os.path.exists(FEATURES_SRC):
        return True
    try:
        with io.open(FEATURES_SRC, "rb") as f:
            want = f.read()
        with io.open(SYS_FEATURES, "rb") as f:
            return f.read() == want
    except Exception:
        return True

def manual_current():
    """True neu khong co payload, hoac sach huong dan he thong da la ban Viet."""
    if not os.path.exists(MANUAL_SRC):
        return True
    try:
        with io.open(MANUAL_SRC, "rb") as f:
            want = f.read()
        with io.open(SYS_MANUAL, "rb") as f:
            return f.read() == want
    except Exception:
        return True

def install_theme_strings(theme_dir):
    d = theme_vars_dir(theme_dir)
    if not d or not os.path.exists(LANG_VI):
        return 0
    if not DRY:
        for fn_ in ("lang-vi.xml", "lang-vi_VN.xml"):
            shutil.copy2(LANG_VI, os.path.join(d, fn_))
    log("theme-strings: %s" % os.path.basename(theme_dir))
    return 1

# ---------- icon trong muc Tools (gamelist) ----------
def icon_current():
    if not os.path.exists(ICON_DST):
        return False
    try:
        with io.open(TOOLS_GAMELIST, encoding="utf-8") as f:
            return ICON_TAG in f.read()
    except Exception:
        return False

def gamelist_set_icon(on):
    """Gan/go the <image> cua KnulliVietHoa trong gamelist Tools.
    ES ghi de gamelist tu RAM khi thoat -> goi luc ES dang chay chi la tam thoi;
    boot_apply goi lai lenh nay truoc khi ES khoi dong nen trang thai se dung."""
    entry_new = ("\t<game>\n\t\t<path>./KnulliVietHoa.sh</path>\n"
                 "\t\t<name>KnulliVietHoa</name>\n"
                 "\t\t<image>" + ICON_TAG + "</image>\n\t</game>\n")
    if not os.path.exists(TOOLS_GAMELIST):
        if on and not DRY:
            os.makedirs(os.path.dirname(TOOLS_GAMELIST), exist_ok=True)
            with io.open(TOOLS_GAMELIST, "w", encoding="utf-8", newline="\n") as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n<gameList>\n'
                        + entry_new + "</gameList>\n")
        return
    with io.open(TOOLS_GAMELIST, encoding="utf-8") as f:
        data = f.read()

    def fix(m):
        g = re.sub(r"\s*<image>\./images/knulliviethoa\.png</image>", "", m.group(0))
        if on:
            g = g.replace("</game>",
                          "\t\t<image>" + ICON_TAG + "</image>\n\t</game>")
        return g

    data2 = re.sub(r"<game>(?:(?!</game>).)*KnulliVietHoa\.sh.*?</game>",
                   fix, data, flags=re.S)
    if data2 == data and on and "KnulliVietHoa.sh" not in data:
        data2 = data.replace("</gameList>", entry_new + "</gameList>")
    if data2 != data and not DRY:
        with io.open(TOOLS_GAMELIST, "w", encoding="utf-8", newline="\n") as f:
            f.write(data2)

# ---------- font thong bao RetroArch (thay noi dung DejaVuSansMono) ----------
def _same_file(a, b):
    try:
        with io.open(a, "rb") as f:
            da = f.read()
        with io.open(b, "rb") as f:
            db = f.read()
        return da == db
    except Exception:
        return False

def rafont_current():
    return os.path.exists(RA_FONT_SRC) and _same_file(SYS_RA_FONT, RA_FONT_SRC)

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
            # Khong bo qua theme da va: theme cap nhat co the them font
            # hong moi; font da va thanh DejaVu (du) nen quet lai se khong
            # hien nua, chi font hong moi moi hien - va lai an toan
            # (sao luu chi ghi khi chua co).
            # Unit patch-theme khong chi cho font: theme font du nhung
            # splash hong hoac (art-book-next) dich thieu thi van can va.
            if (deficient_fonts(tdir) or splash_needs_patch(tdir) or
                    artbook_needs_patch(tdir)):
                units.append({"id": "patch-theme:%s" % name,
                              "vi": "Vá theme %s" % name,
                              "en": "Patch theme %s" % name})
    ts_targets = [os.path.join(USER_THEMES, n)
                  for n in list(st.get("copied_themes", [])) +
                  list(st.get("patched_themes", {}))]
    if any(os.path.isdir(t) and not theme_strings_current(t) for t in ts_targets):
        units.append({"id": "theme-strings",
                      "vi": "Cài chữ tiếng Việt cho menu của theme",
                      "en": "Install Vietnamese theme menu strings"})
    units.append({"id": "i18n", "vi": "Nạp bản dịch tiếng Việt đầy đủ",
                  "en": "Install full Vietnamese translation"})
    if not features_current():
        units.append({"id": "features",
                      "vi": "Dịch menu Cài đặt trò chơi (es_features)",
                      "en": "Translate Game Settings menu (es_features)"})
    if not manual_current():
        units.append({"id": "manual",
                      "vi": "Dịch sách hướng dẫn sử dụng (User Manual)",
                      "en": "Translate the User Manual"})
    if not st.get("icon") or not icon_current():
        units.append({"id": "icon",
                      "vi": "Thêm icon cho app ở mục Tools",
                      "en": "Add the app icon in Tools"})
    if not rafont_current():
        units.append({"id": "rafont",
                      "vi": "Sửa font thông báo trong RetroArch (hết ô vuông)",
                      "en": "Fix the RetroArch notification font (no more boxes)"})
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
    if bootlogo_needs_fix():
        units.append({"id": "bootlogo",
                      "vi": "Sửa logo khởi động bị xoay 90° (máy panel dọc)",
                      "en": "Fix the 90°-rotated boot logo (portrait-panel device)"})
    return units

# ---------- splash loading: forceUppercase vo chu tieng Viet ----------
# ES ve dong loading ("Dang nap du lieu...") bang label cua splash theme
# dang nap. Neu label dat forceUppercase=true, chu tieng Viet bi vo
# (kiem chung 26/10: knulli=false thi tot; art-book-next/atlas-es=true thi
# vo; doi atlas-es sang false thi het vo ngay). Sua: ep false. File goc
# luon duoc sao luu vao state/splash-backup de rollback tra ve duoc.
def patch_splash_uppercase(theme_dir, scope):
    """Ep forceUppercase=false trong splash.xml cua theme.
    Chi sua khi dang la true (dang attr hoac element); da false hoac
    khong co tag thi de yen. Backup file goc truoc khi sua lan dau.
    Tra ve True neu co true can sua (ke ca che do DRY)."""
    sp = os.path.join(theme_dir, "splash.xml")
    if not os.path.isfile(sp):
        return False
    with io.open(sp, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if 'forceUppercase="true"' not in text and \
            "<forceUppercase>true</forceUppercase>" not in text:
        return False
    if not DRY:
        os.makedirs(SPLASH_BACKUP_DIR, exist_ok=True)
        bak = os.path.join(SPLASH_BACKUP_DIR, "%s-%s.splash.xml" %
                           (scope, os.path.basename(theme_dir)))
        if not os.path.exists(bak):
            shutil.copy2(sp, bak)
        text = text.replace('forceUppercase="true"',
                            'forceUppercase="false"')
        text = text.replace("<forceUppercase>true</forceUppercase>",
                            "<forceUppercase>false</forceUppercase>")
        with io.open(sp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        st = load_state()
        lst = st.setdefault("splash_upper", [])
        key = "%s:%s" % (scope, os.path.basename(theme_dir))
        if key not in lst:
            lst.append(key)
        save_state(st)
    return True

# ---------- dich theme art-book-next: subset + lang ----------
# Lang file cua theme (_inc/lang/*.xml) chi co 2 bien lang.games/game
# (bo dem game); label/option man cau hinh theme la displayName viet
# thang trong theme.xml nen lang file KHONG dich duoc chung. Cach sua:
# va displayName trong khoi <subset> theo bang duoi + cai vi.xml.
# Chi ap cho art-book-next (bang theo ten subset rieng cua theme nay);
# option khong co trong bang (ten rieng, ti le) duoc giu nguyen.
ARTBOOK_SUBSETS = {
    "distribution": {"name": "Phân phối", "options": {}},
    "aspect-ratio": {"name": "Tỉ lệ khung hình",
                     "options": {"Automatic": "Tự động"}},
    "system-view-artwork": {"name": "Ảnh nền hệ máy",
                            "options": {"Default": "Mặc định",
                                        "Custom": "Tùy chỉnh",
                                        "Custom (Fullscreen)": "Tùy chỉnh (Toàn màn hình)"}},
    "system-count": {"name": "Số lượng game",
                     "options": {"Off": "Tắt", "On": "Bật"}},
    "system-logos": {"name": "Logo hệ máy",
                     "options": {"Default": "Mặc định",
                                 "Custom": "Tùy chỉnh"}},
    "system-logo-animation": {"name": "Hiệu ứng logo",
                              "options": {"Default": "Mặc định",
                                          "Fade In": "Mờ dần",
                                          "Zoom Bump": "Phóng to",
                                          "Swoop": "Lướt",
                                          "Drop": "Rơi",
                                          "Skid": "Trượt",
                                          "Spinner": "Xoay"}},
    "gamelist-view-artwork": {"name": "Ảnh game",
                              "options": {"Image": "Hình ảnh",
                                          "Image (Cropped)": "Hình ảnh (Cắt)",
                                          "Boxart": "Ảnh bìa"}},
    "gamelist-view-metadata": {"name": "Thông tin game",
                               "options": {"Default": "Mặc định",
                                           "Play Time &amp; Play Count": "Thời gian &amp; Số lần chơi",
                                           "Release Date &amp; Play Time": "Ngày phát hành &amp; Thời gian chơi",
                                           "Off": "Tắt"}},
    "gamelist-video-delay": {"name": "Độ trễ video",
                             "options": {"Default": "Mặc định",
                                         "Longer": "Dài hơn"}},
    "fonts": {"name": "Phông chữ",
              "options": {"Default": "Mặc định", "Custom": "Tùy chỉnh"}},
    "font-size": {"name": "Cỡ chữ",
                  "options": {"Default": "Mặc định", "Large": "Lớn",
                              "Extra Large": "Rất lớn", "Small": "Nhỏ"}},
    "color-scheme": {"name": "Bảng màu",
                     "options": {"Default": "Mặc định", "Light": "Sáng",
                                 "Custom": "Tùy chỉnh"}},
    "splash-screen": {"name": "Màn hình chờ",
                      "options": {"Default": "Mặc định",
                                  "Custom": "Tùy chỉnh"}},
    "network-icon": {"name": "Biểu tượng mạng",
                     "options": {"Default": "Mặc định"}},
}

def patch_theme_subsets(theme_dir, scope):
    """Dich displayName subset/option art-book-next trong theme.xml.
    Chi sua trong khoi <subset> (theo ten subset); displayName ngoai
    khoi subset khong dung vao. Backup nguyen theme.xml truoc khi sua
    lan dau. Tra ve True neu co sua (ke ca DRY)."""
    sp = os.path.join(theme_dir, "theme.xml")
    if not os.path.isfile(sp):
        return False
    with io.open(sp, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    cur = None
    changed = False
    out = []
    for ln in lines:
        m = re.search(r'<subset\s+name="([^"]+)"', ln)
        if m:
            cur = m.group(1)
            if cur in ARTBOOK_SUBSETS:
                ln2 = re.sub(r'displayName="[^"]*"',
                             'displayName="%s"' % ARTBOOK_SUBSETS[cur]["name"],
                             ln, count=1)
                if ln2 != ln:
                    changed = True
                    ln = ln2
            out.append(ln)
            continue
        if ln.strip().startswith("</subset"):
            cur = None
            out.append(ln)
            continue
        if cur in ARTBOOK_SUBSETS:
            dm = re.search(r'displayName="([^"]*)"', ln)
            if dm and dm.group(1) in ARTBOOK_SUBSETS[cur]["options"]:
                ln = ln.replace('displayName="%s"' % dm.group(1),
                                'displayName="%s"' %
                                ARTBOOK_SUBSETS[cur]["options"][dm.group(1)])
                changed = True
        out.append(ln)
    if not changed:
        return False
    if not DRY:
        os.makedirs(THEME_BACKUP_DIR, exist_ok=True)
        bak = os.path.join(THEME_BACKUP_DIR, "%s-%s.theme.xml" %
                           (scope, os.path.basename(theme_dir)))
        if not os.path.exists(bak):
            shutil.copy2(sp, bak)
        with io.open(sp, "w", encoding="utf-8", newline="") as f:
            f.writelines(out)
        st = load_state()
        lst = st.setdefault("theme_xml", [])
        key = "%s:%s" % (scope, os.path.basename(theme_dir))
        if key not in lst:
            lst.append(key)
        save_state(st)
    return True

def install_theme_lang(theme_dir, scope):
    """Cai vi.xml + vi_VN.xml (bo dem game) vao _inc/lang/ cua theme.
    Backup file goc neu da co. Tra ve True neu co cai/dat (ke ca DRY)."""
    d = os.path.join(theme_dir, "_inc", "lang")
    if not os.path.isdir(d) or not os.path.exists(LANG_ARTBOOK):
        return False
    with io.open(LANG_ARTBOOK, "rb") as f:
        src = f.read()
    changed = False
    for fn_ in ("vi.xml", "vi_VN.xml"):
        dst = os.path.join(d, fn_)
        cur = None
        if os.path.exists(dst):
            with io.open(dst, "rb") as f:
                cur = f.read()
        if cur != src:
            changed = True
    if not changed:
        return False
    if not DRY:
        os.makedirs(THEME_BACKUP_DIR, exist_ok=True)
        for fn_ in ("vi.xml", "vi_VN.xml"):
            dst = os.path.join(d, fn_)
            if os.path.exists(dst):
                bak = os.path.join(THEME_BACKUP_DIR, "%s-%s.%s" %
                                   (scope, os.path.basename(theme_dir), fn_))
                if not os.path.exists(bak):
                    shutil.copy2(dst, bak)
            shutil.copy2(LANG_ARTBOOK, dst)
        st = load_state()
        lst = st.setdefault("theme_lang", [])
        key = "%s:%s" % (scope, os.path.basename(theme_dir))
        if key not in lst:
            lst.append(key)
        save_state(st)
    return True

def splash_needs_patch(theme_dir):
    """True neu splash.xml cua theme con forceUppercase=true (dang attr
    hoac element). Dung cho scan: theme font du nhung splash hong thi
    van can unit patch-theme."""
    sp = os.path.join(theme_dir, "splash.xml")
    if not os.path.isfile(sp):
        return False
    try:
        with io.open(sp, encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except Exception:
        return False
    return ('forceUppercase="true"' in txt or
            "<forceUppercase>true</forceUppercase>" in txt)

def artbook_needs_patch(theme_dir):
    """True neu la theme art-book-next (goc hoac -vi) ma subset chua
    dich het hoac thieu vi.xml (khi theme co _inc/lang/)."""
    if os.path.basename(theme_dir) not in ("es-theme-art-book-next",
                                           "es-theme-art-book-next-vi"):
        return False
    try:
        with io.open(os.path.join(theme_dir, "theme.xml"),
                     encoding="utf-8", errors="replace") as f:
            xml = f.read()
    except Exception:
        xml = ""
    done = sum(1 for v in ARTBOOK_SUBSETS.values()
               if ('displayName="%s"' % v["name"]) in xml)
    if done < len(ARTBOOK_SUBSETS):
        return True
    lang_dir = os.path.join(theme_dir, "_inc", "lang")
    return os.path.isdir(lang_dir) and not os.path.exists(
        os.path.join(lang_dir, "vi.xml"))

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
    if install_theme_strings(dst):
        st0 = load_state()
        st0["theme_strings"] = True
        save_state(st0)
    patch_splash_uppercase(dst, "user")
    if name == "es-theme-art-book-next":
        patch_theme_subsets(dst, "user")
        install_theme_lang(dst, "user")
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
    install_theme_strings(tdir)
    patch_splash_uppercase(tdir, "user")
    if name in ("es-theme-art-book-next", "es-theme-art-book-next-vi"):
        patch_theme_subsets(tdir, "user")
        install_theme_lang(tdir, "user")
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
        if os.path.exists(CUSTOM_SH):
            with io.open(CUSTOM_SH, encoding="utf-8", errors="replace") as f:
                text = f.read()
        else:
            # May moi flash Knulli chua he co custom.sh -> tu tao moi.
            # (Ban <= 0.3.8 crash FileNotFoundError o day - da gap tren
            # Smart Pro S moi flash ngay 23/10/2026.)
            text = "#!/bin/sh\n"
        text = re.sub(re.escape(HOOK_BEGIN) + r".*?" + re.escape(HOOK_END) + r"\n?",
                      "", text, flags=re.S)
        with io.open(CUSTOM_SH, "w", encoding="utf-8", newline="\n") as f:
            f.write(text.rstrip("\n") + "\n\n" + hook_block())
        try:
            os.chmod(CUSTOM_SH, 0o755)
        except Exception:
            pass
    st = load_state()
    st["hook"] = True
    save_state(st)

# ---------- sua logo khoi dong bi xoay (board panel doc) ----------
# Bootloader ve /boot/bootlogo.bmp thang len panel truoc khi kernel boot.
# Voi board panel doc (vd Smart Pro S) ma file logo dong goi NGANG thi anh
# hien xoay 90 do. Cach sua: xoay san noi dung BMP 90 do ngay trong file
# (doi chieu w/h trong header, tong so byte khong doi), bootloader ve
# thang la thanh dung chieu. Da kiem chung tren may that 23/10/2026.
def _bmp_info(path):
    """(w, h, bpp, data_off) hoac None neu khong phai BMP doc duoc."""
    try:
        with io.open(path, "rb") as f:
            hdr = f.read(138)
        if len(hdr) < 54 or hdr[0:2] != b"BM":
            return None
        return (struct.unpack_from("<i", hdr, 18)[0],
                struct.unpack_from("<i", hdr, 22)[0],
                struct.unpack_from("<H", hdr, 28)[0],
                struct.unpack_from("<I", hdr, 10)[0])
    except Exception:
        return None

def _board_name():
    try:
        with io.open(BOOTLOGO_BOARD_FILE, encoding="utf-8",
                     errors="replace") as f:
            return f.read().strip()
    except Exception:
        return ""

def bootlogo_needs_fix():
    if load_state().get("bootlogo"):
        return False
    if _board_name() not in BOOTLOGO_BOARDS:
        return False
    info = _bmp_info(BOOTLOGO)
    if not info:
        return False
    w, h, bpp, _off = info
    return bpp == 32 and w > h > 0

def _rotate_bmp_cw(data):
    """Xoay noi dung BMP 32bpp 90 do theo chieu kim dong ho (tren ma tran
    pixel da luu trong file), doi w/h trong header. Tong so byte giu nguyen."""
    data_off = struct.unpack_from("<I", data, 10)[0]
    w = struct.unpack_from("<i", data, 18)[0]
    h = struct.unpack_from("<i", data, 22)[0]
    pix = data[data_off:]
    if w <= 0 or h <= 0 or len(pix) != w * h * 4:
        raise ValueError("bootlogo: kich thuoc pixel khong khop header")
    hdr = bytearray(data[:data_off])
    struct.pack_into("<ii", hdr, 18, h, w)
    rows = [pix[r * w * 4:(r + 1) * w * 4] for r in range(h)]
    out = bytearray(len(pix))
    pos = 0
    for i in range(w):
        for j in range(h):
            src = rows[h - 1 - j]
            out[pos:pos + 4] = src[i * 4:i * 4 + 4]
            pos += 4
    return bytes(hdr) + bytes(out)

def _boot_remount(mode):
    try:
        subprocess.call(["mount", "-o", "remount," + mode, BOOT_DIR])
    except Exception:
        pass

def do_bootlogo():
    if not DRY:
        with io.open(BOOTLOGO, "rb") as f:
            data = f.read()
        rotated = _rotate_bmp_cw(data)
        os.makedirs(STATE_DIR, exist_ok=True)
        if not os.path.exists(BOOTLOGO_BACKUP):
            with io.open(BOOTLOGO_BACKUP, "wb") as f:
                f.write(data)
        _boot_remount("rw")
        try:
            tmp = BOOTLOGO + ".tmp"
            with io.open(tmp, "wb") as f:
                f.write(rotated)
            os.rename(tmp, BOOTLOGO)
            subprocess.call(["sync"])
        finally:
            _boot_remount("ro")
    st = load_state()
    st["bootlogo"] = True
    save_state(st)

def _boot_early_block():
    return "\n".join([
        BOOT_BLOCK_START,
        "# knulli-vi early locale: copy the staged catalog before ES starts.",
        "# The staged file is the switch: present = Vietnamese, absent = no-op.",
        "if [ -f " + BOOT_STAGED_MO + " ]; then",
        "  mkdir -p /usr/share/locale/vi_VN/LC_MESSAGES 2>/dev/null",
        "  cp " + BOOT_STAGED_MO + " /usr/share/locale/vi_VN/LC_MESSAGES/emulationstation2.mo 2>/dev/null",
        "fi",
        BOOT_BLOCK_END,
    ]) + "\n"

def _boot_is_ro():
    try:
        with io.open("/proc/mounts", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and parts[1] == BOOT_DIR:
                    return "ro" in parts[3].split(",")
    except Exception:
        pass
    return False

def ensure_boot_early_locale():
    # Best-effort: khong bao gio lam hong ca lan apply vi loi /boot staging.
    try:
        was_ro = _boot_is_ro()
        if was_ro:
            _boot_remount("rw")
        try:
            shutil.copyfile(os.path.join(I18N_DIR, "emulationstation2.mo"), BOOT_STAGED_MO)
            subprocess.call(["sync"])
        finally:
            if was_ro:
                _boot_remount("ro")
    except Exception:
        return False
    try:
        block = _boot_early_block()
        if os.path.exists(BOOT_CUSTOM):
            with io.open(BOOT_CUSTOM, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if BOOT_BLOCK_START in content:
                return True
            if content and not content.endswith("\n"):
                content += "\n"
            content += block
        else:
            content = "#!/bin/sh\n" + block
        was_ro = _boot_is_ro()
        if was_ro:
            _boot_remount("rw")
        try:
            with io.open(BOOT_CUSTOM, "w", encoding="utf-8") as f:
                f.write(content)
            subprocess.call(["sync"])
        finally:
            if was_ro:
                _boot_remount("ro")
        return True
    except Exception:
        return False

def remove_boot_early_locale():
    # Rollback: xoa file staged thi block S00 thanh no-op.
    try:
        if os.path.exists(BOOT_STAGED_MO):
            was_ro = _boot_is_ro()
            if was_ro:
                _boot_remount("rw")
            try:
                os.remove(BOOT_STAGED_MO)
                subprocess.call(["sync"])
            finally:
                if was_ro:
                    _boot_remount("ro")
        return True
    except Exception:
        return False

def do_i18n():
    if not DRY:
        shutil.copy2(os.path.join(I18N_DIR, "emulationstation2.mo"), LOCALE_MO)
        ensure_boot_early_locale()
    st = load_state()
    st["i18n"] = True
    save_state(st)

def do_features():
    if not DRY:
        os.makedirs(STATE_DIR, exist_ok=True)
        if not os.path.exists(FEATURES_BACKUP) and os.path.exists(SYS_FEATURES):
            shutil.copy2(SYS_FEATURES, FEATURES_BACKUP)
        shutil.copy2(FEATURES_SRC, SYS_FEATURES)
    st = load_state()
    st["features"] = True
    save_state(st)

def do_manual():
    if not DRY and not os.path.isdir(os.path.dirname(SYS_MANUAL)):
        # Ban Knulli khong co muc sach huong dan (vd ban T527 khong co
        # /usr/share/knulli/doc) -> bo qua unit nay, khong phai loi.
        log("manual: bo qua (he thong khong co thu muc doc)")
        return
    if not DRY:
        os.makedirs(STATE_DIR, exist_ok=True)
        if not os.path.exists(MANUAL_BACKUP) and os.path.exists(SYS_MANUAL):
            shutil.copy2(SYS_MANUAL, MANUAL_BACKUP)
        shutil.copy2(MANUAL_SRC, SYS_MANUAL)
    st = load_state()
    st["manual"] = True
    save_state(st)

def do_icon():
    if not DRY:
        os.makedirs(ICON_DST_DIR, exist_ok=True)
        if os.path.exists(ICON_SRC):
            shutil.copy2(ICON_SRC, ICON_DST)
        gamelist_set_icon(True)
    st = load_state()
    st["icon"] = True
    save_state(st)

def do_rafont():
    if not DRY:
        os.makedirs(STATE_DIR, exist_ok=True)
        # Sao luu ban Mono goc mot lan (chi khi file he thong chua phai ban
        # da thay, tranh tu sao luu chinh ban thay).
        if not os.path.exists(RA_FONT_BACKUP) and os.path.exists(SYS_RA_FONT) \
                and not _same_file(SYS_RA_FONT, RA_FONT_SRC):
            shutil.copy2(SYS_RA_FONT, RA_FONT_BACKUP)
        shutil.copy2(RA_FONT_SRC, SYS_RA_FONT)
    st = load_state()
    st["rafont"] = True
    st.pop("prev_video_font_path", None)  # truong cua cach sua cfg cu (bo)
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

def do_theme_strings():
    st = load_state()
    for name in list(st.get("copied_themes", [])) + list(st.get("patched_themes", {})):
        tdir = os.path.join(USER_THEMES, name)
        if os.path.isdir(tdir):
            install_theme_strings(tdir)
    st["theme_strings"] = True
    save_state(st)

APPLY = {"copy-theme": do_copy_theme, "patch-theme": do_patch_theme,
         "theme-strings": lambda: do_theme_strings(),
         "i18n": lambda: do_i18n(), "features": lambda: do_features(),
         "manual": lambda: do_manual(), "icon": lambda: do_icon(),
         "rafont": lambda: do_rafont(), "hook": lambda: do_hook(),
         "lang": lambda: do_lang(), "themeset": lambda: do_themeset(),
         "bootlogo": lambda: do_bootlogo()}

# ---------- tien ich tuy chon (menu "Tien ich" trong app) ----------
# Cac tweak doc lap voi goi Viet hoa: chi hien khi tuong ung co mat tren may,
# bat/tat tung cai, thao tac nao cung kiem tra trang thai truoc (idempotent).
# Lenh rieng: uscan | uapply <id> | urevert <id>.
DK_DIR = "/userdata/roms/ports/DoorKickersActionSquad"
DK_LAUNCH = os.path.join(DK_DIR, "launch.sh")
DK_LAUNCH_BAK = DK_LAUNCH + ".bak-kv"
DK_EXIT_SCRIPT = "/userdata/system/scripts/exit-actionsquad.sh"
THD_CONF = "/userdata/system/configs/multimedia_keys.conf"
THD_STOCK = "/etc/triggerhappy/triggers.d/multimedia_keys.conf"
THD_LINES = ("KEY_HOMEPAGE+BTN_START 1 " + DK_EXIT_SCRIPT,
             "BTN_START+KEY_HOMEPAGE 1 " + DK_EXIT_SCRIPT)
DK_EXIT_BODY = ("#!/bin/sh\n"
                "# Thoat Door Kickers Action Squad bang HOME+START (triggerhappy).\n"
                "P=$(pidof actionsquad-nextos)\n"
                "[ -n \"$P\" ] && kill $P\n")

def _dk_available():
    return os.path.isfile(DK_LAUNCH)

def _dk_applied():
    try:
        with io.open(DK_LAUNCH, encoding="utf-8", errors="replace") as f:
            if "SDL_VIDEODRIVER=mali" in f.read():
                return False
    except Exception:
        return False
    if not os.path.isfile(DK_EXIT_SCRIPT):
        return False
    try:
        with io.open(THD_CONF, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        return False
    return all(l in text for l in THD_LINES)

def _thd_restart():
    try:
        subprocess.call(["/etc/init.d/S50triggerhappy", "restart"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def do_dkexit():
    # 1) Driver SDL: ban port ep "mali" (chi co tren stock OS) -> Knulli dung
    #    kmsdrm. Co sao luu .bak-kv de revert tra lai nguyen trang.
    with io.open(DK_LAUNCH, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if "SDL_VIDEODRIVER=mali" in text and not DRY:
        if not os.path.exists(DK_LAUNCH_BAK):
            shutil.copy2(DK_LAUNCH, DK_LAUNCH_BAK)
        with io.open(DK_LAUNCH, "w", encoding="utf-8", newline="") as f:
            f.write(text.replace("SDL_VIDEODRIVER=mali",
                                 "SDL_VIDEODRIVER=kmsdrm"))
    if DRY:
        return
    # 2) Script thoat game + phim HOME+START trong triggerhappy.
    os.makedirs(os.path.dirname(DK_EXIT_SCRIPT), exist_ok=True)
    with io.open(DK_EXIT_SCRIPT, "w", encoding="utf-8", newline="\n") as f:
        f.write(DK_EXIT_BODY)
    os.chmod(DK_EXIT_SCRIPT, 0o755)
    if os.path.exists(THD_CONF):
        with io.open(THD_CONF, encoding="utf-8", errors="replace") as f:
            conf = f.read()
    elif os.path.exists(THD_STOCK):
        with io.open(THD_STOCK, encoding="utf-8", errors="replace") as f:
            conf = f.read()
    else:
        conf = ""
    missing = [l for l in THD_LINES if l not in conf]
    if missing:
        os.makedirs(os.path.dirname(THD_CONF), exist_ok=True)
        with io.open(THD_CONF, "a", encoding="utf-8", newline="\n") as f:
            if conf and not conf.endswith("\n"):
                f.write("\n")
            for l in missing:
                f.write(l + "\n")
    _thd_restart()

def un_dkexit():
    if DRY:
        return
    if os.path.exists(THD_CONF):
        with io.open(THD_CONF, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        kept = [l for l in lines if "exit-actionsquad.sh" not in l]
        with io.open(THD_CONF, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(kept) + ("\n" if kept else ""))
    if os.path.exists(DK_EXIT_SCRIPT):
        os.remove(DK_EXIT_SCRIPT)
    if os.path.exists(DK_LAUNCH_BAK):
        shutil.copy2(DK_LAUNCH_BAK, DK_LAUNCH)
        os.remove(DK_LAUNCH_BAK)
    _thd_restart()

# Tien ich "shotkey": khoi phuc phim chup man hinh khi bi mat (vd sau
# factory reset). Chuoi chup: thd (triggerhappy) doc
# /userdata/system/configs/multimedia_keys.conf -> chay script kmsgrab.
# Tren Smart 25/10: ca daemon, conf va script deu con nguyen nhung phim
# van khong an -> tien ich cho phep tat/bat lai de nap lai toan bo chuoi
# (ghi lai script + conf + restart thd). So sanh dong conf theo khoang
# trang chuan hoa vi file cu ghi tay can le cot khac nhau.
SHOT_SCRIPT = "/userdata/system/scripts/knulli-screenshot-kms.sh"
SHOT_LINES = ("BTN_START+BTN_SELECT 1 " + SHOT_SCRIPT,
              "BTN_MODE+KEY_HOMEPAGE 1 " + SHOT_SCRIPT,
              "KEY_HOMEPAGE+BTN_MODE 1 " + SHOT_SCRIPT)
SHOT_BODY = ("#!/bin/sh\n"
             "# Chup man hinh — tu chon backend: DRM kmsgrab neu ffmpeg ho tro\n"
             "# (Smart T527 hien thi qua plane DRM), neu khong thi fbdev/fbgrab\n"
             "# (Brick: ffmpeg khong co kmsgrab; truoc day script nay hong tren\n"
             "# Brick va phim chi an nho phim stock goi cong cu stock rieng).\n"
             "OUT_DIR=/userdata/screenshots\n"
             "mkdir -p \"$OUT_DIR\"\n"
             "FILE=\"$1\"\n"
             "if [ -z \"$FILE\" ]; then\n"
             "    FB=$(command -v fbset || echo /usr/sbin/fbset)\n"
             "    W=$($FB | grep geometry | awk '{print $2}')\n"
             "    H=$($FB | grep geometry | awk '{print $3}')\n"
             "    FILE=\"$OUT_DIR/knulli-screenshot_${W}x${H}_$(date +%Y%m%d_%Hh%Mm%Ss).png\"\n"
             "fi\n"
             "FF=$(command -v ffmpeg || echo /usr/bin/ffmpeg)\n"
             "if [ -e /dev/dri/card0 ] && \"$FF\" -hide_banner -formats 2>/dev/null | grep -q kmsgrab; then\n"
             "    exec \"$FF\" -hide_banner -loglevel error -f kmsgrab -device /dev/dri/card0 -i - -vf hwdownload,format=bgr0 -frames:v 1 -update 1 -y \"$FILE\"\n"
             "fi\n"
             "# Fallback fbdev: co $1 thi chup thang vao file, khong thi dung\n"
             "# cong cu stock (tu dat ten file nhu phim stock).\n"
             "if [ -n \"$1\" ]; then\n"
             "    FBGRAB=$(command -v fbgrab || echo /usr/bin/fbgrab)\n"
             "    exec \"$FBGRAB\" \"$FILE\"\n"
             "fi\n"
             "exec knulli-screenshot\n")

def _norm_conf_lines(text):
    return set(re.sub(r"\s+", " ", l).strip() for l in text.splitlines()
               if l.strip())

def _shot_available():
    # Chi hien tren may co DRM (kmsgrab moi chup duoc).
    return os.path.exists("/dev/dri/card0")

def _shot_applied():
    if not os.path.isfile(SHOT_SCRIPT):
        return False
    try:
        with io.open(SHOT_SCRIPT, encoding="utf-8", errors="replace") as f:
            body = f.read()
    except Exception:
        return False
    # Script cu (kmsgrab-only) khac ban hien tai -> coi nhu chua ap dung,
    # de user bat lai la nhan ban script moi (tu thich ung kmsgrab/fbdev).
    if body != SHOT_BODY:
        return False
    try:
        with io.open(THD_CONF, encoding="utf-8", errors="replace") as f:
            have = _norm_conf_lines(f.read())
    except Exception:
        return False
    return all(re.sub(r"\s+", " ", l).strip() in have for l in SHOT_LINES)

def do_shotkey():
    if DRY:
        return
    os.makedirs(os.path.dirname(SHOT_SCRIPT), exist_ok=True)
    with io.open(SHOT_SCRIPT, "w", encoding="utf-8", newline="\n") as f:
        f.write(SHOT_BODY)
    os.chmod(SHOT_SCRIPT, 0o755)
    # Conf tuy bien mat thi lay noi dung stock lam nen; ca hai deu mat thi
    # khong tu tao conf tron (se lam mat phim volume/power cua he thong).
    if os.path.exists(THD_CONF):
        with io.open(THD_CONF, encoding="utf-8", errors="replace") as f:
            conf = f.read()
    elif os.path.exists(THD_STOCK):
        with io.open(THD_STOCK, encoding="utf-8", errors="replace") as f:
            conf = f.read()
    else:
        conf = None
    if conf is not None:
        have = _norm_conf_lines(conf)
        missing = [l for l in SHOT_LINES
                   if re.sub(r"\s+", " ", l).strip() not in have]
        if missing:
            os.makedirs(os.path.dirname(THD_CONF), exist_ok=True)
            with io.open(THD_CONF, "a", encoding="utf-8", newline="\n") as f:
                if conf and not conf.endswith("\n"):
                    f.write("\n")
                for l in missing:
                    f.write(l + "\n")
    _thd_restart()

def un_shotkey():
    if DRY:
        return
    if os.path.exists(THD_CONF):
        with io.open(THD_CONF, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        kept = [l for l in lines if "knulli-screenshot-kms.sh" not in l]
        with io.open(THD_CONF, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(kept) + ("\n" if kept else ""))
    # Giu lai script: con dung cho chuan doan qua SSH, khong anh huong phim.
    _thd_restart()

UTILITIES = {"dkexit": {"vi": "Thoát Door Kickers Action Squad bằng HOME+START",
                        "en": "Exit Door Kickers Action Squad with HOME+START",
                        "available": _dk_available, "applied": _dk_applied,
                        "apply": do_dkexit, "revert": un_dkexit},
             "shotkey": {"vi": "Phím chụp màn hình (Function+Home)",
                         "en": "Screenshot key (Function+Home)",
                         "available": _shot_available, "applied": _shot_applied,
                         "apply": do_shotkey, "revert": un_shotkey}}

def uscan():
    out = []
    for uid, u in UTILITIES.items():
        if u["available"]():
            out.append({"id": uid, "vi": u["vi"], "en": u["en"],
                        "state": 1 if u["applied"]() else 0})
    return out

# ---------- rollback ----------
def rscan():
    st = load_state()
    units = []
    if st.get("theme_strings"):
        units.append({"id": "un-theme-strings",
                      "vi": "Gỡ chữ tiếng Việt của menu theme",
                      "en": "Remove Vietnamese theme menu strings"})
    if st.get("i18n"):
        units.append({"id": "un-i18n", "vi": "Trả lại bản dịch gốc",
                      "en": "Restore original translation"})
    if st.get("splash_upper") or (os.path.isdir(SPLASH_BACKUP_DIR) and
                                  any(fn.endswith(".splash.xml") for fn in
                                      os.listdir(SPLASH_BACKUP_DIR))):
        units.append({"id": "un-splash-upper", "vi": "Trả splash theme về bản gốc",
                      "en": "Restore original theme splash"})
    if st.get("theme_xml") or (os.path.isdir(THEME_BACKUP_DIR) and
                               any(fn.endswith(".theme.xml") for fn in
                                   os.listdir(THEME_BACKUP_DIR))):
        units.append({"id": "un-theme-xml",
                      "vi": "Trả theme.xml của theme về bản gốc",
                      "en": "Restore original theme.xml"})
    if st.get("theme_lang"):
        units.append({"id": "un-theme-lang",
                      "vi": "Gỡ bản dịch theme (vi.xml)",
                      "en": "Remove theme translation (vi.xml)"})
    if st.get("features"):
        units.append({"id": "un-features",
                      "vi": "Trả menu Cài đặt trò chơi về tiếng Anh gốc",
                      "en": "Restore original English Game Settings menu"})
    if st.get("manual"):
        units.append({"id": "un-manual",
                      "vi": "Trả sách hướng dẫn về tiếng Anh gốc",
                      "en": "Restore original English User Manual"})
    if st.get("icon"):
        units.append({"id": "un-icon",
                      "vi": "Gỡ icon của app ở mục Tools",
                      "en": "Remove the app icon from Tools"})
    if st.get("rafont"):
        units.append({"id": "un-rafont",
                      "vi": "Trả font thông báo RetroArch về mặc định",
                      "en": "Restore the default RetroArch notification font"})
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
    if st.get("bootlogo"):
        units.append({"id": "un-bootlogo",
                      "vi": "Trả logo khởi động về bản gốc",
                      "en": "Restore the original boot logo"})
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
        remove_boot_early_locale()
    st = load_state()
    st["i18n"] = False
    save_state(st)

def rb_un_features():
    if not DRY and os.path.exists(FEATURES_BACKUP):
        shutil.copy2(FEATURES_BACKUP, SYS_FEATURES)
    st = load_state()
    st["features"] = False
    save_state(st)

def rb_un_icon():
    if not DRY:
        gamelist_set_icon(False)
        if os.path.exists(ICON_DST):
            os.remove(ICON_DST)
    st = load_state()
    st["icon"] = False
    save_state(st)

def rb_un_rafont():
    if not DRY and os.path.exists(RA_FONT_BACKUP):
        shutil.copy2(RA_FONT_BACKUP, SYS_RA_FONT)
    st = load_state()
    st["rafont"] = False
    st.pop("prev_video_font_path", None)
    save_state(st)

def rb_un_manual():
    if not DRY and os.path.exists(MANUAL_BACKUP):
        shutil.copy2(MANUAL_BACKUP, SYS_MANUAL)
    st = load_state()
    st["manual"] = False
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

def rb_un_bootlogo():
    st = load_state()
    if not DRY and os.path.exists(BOOTLOGO_BACKUP):
        _boot_remount("rw")
        try:
            shutil.copyfile(BOOTLOGO_BACKUP, BOOTLOGO)
            subprocess.call(["sync"])
        finally:
            _boot_remount("ro")
    st["bootlogo"] = False
    save_state(st)

def rb_un_hook():
    # chi danh dau; boot_apply.sh se tu go block o lan boot ke tiep khi khong con viec.
    st = load_state()
    st["hook"] = False
    save_state(st)

def rb_un_theme_strings():
    st = load_state()
    for name in list(st.get("copied_themes", [])) + list(st.get("patched_themes", {})):
        d = os.path.join(USER_THEMES, name, "_inc", "variables")
        if not DRY and os.path.isdir(d):
            for fn_ in ("lang-vi.xml", "lang-vi_VN.xml"):
                p = os.path.join(d, fn_)
                if os.path.exists(p):
                    os.remove(p)
    st["theme_strings"] = False
    save_state(st)

def rb_un_splash_upper():
    # tra splash.xml goc tu backup (nguyen file, khong phai gia tri): khoi
    # phuc ca truong hop goc la true, false hay khong co tag. Theme da bi
    # xoa thi chi don backup, khong co gi de tra.
    if not DRY and os.path.isdir(SPLASH_BACKUP_DIR):
        for fn in os.listdir(SPLASH_BACKUP_DIR):
            if not fn.endswith(".splash.xml"):
                continue
            core = fn[:-len(".splash.xml")]
            scope, _, name = core.partition("-")
            base = SYS_THEMES if scope == "sys" else USER_THEMES
            tdir = os.path.join(base, name)
            if os.path.isdir(tdir):
                shutil.copy2(os.path.join(SPLASH_BACKUP_DIR, fn),
                             os.path.join(tdir, "splash.xml"))
            os.remove(os.path.join(SPLASH_BACKUP_DIR, fn))
    st = load_state()
    st["splash_upper"] = []
    save_state(st)

def rb_un_theme_xml():
    # tra theme.xml goc tu backup (nguyen file). Theme da bi xoa thi chi
    # don backup, khong co gi de tra.
    if not DRY and os.path.isdir(THEME_BACKUP_DIR):
        for fn in os.listdir(THEME_BACKUP_DIR):
            if not fn.endswith(".theme.xml"):
                continue
            core = fn[:-len(".theme.xml")]
            scope, _, name = core.partition("-")
            base = SYS_THEMES if scope == "sys" else USER_THEMES
            tdir = os.path.join(base, name)
            if os.path.isdir(tdir):
                shutil.copy2(os.path.join(THEME_BACKUP_DIR, fn),
                             os.path.join(tdir, "theme.xml"))
            os.remove(os.path.join(THEME_BACKUP_DIR, fn))
    st = load_state()
    st["theme_xml"] = []
    save_state(st)

def rb_un_theme_lang():
    # go vi.xml/vi_VN.xml do app cai; neu truoc do theme da co file
    # (backup ton tai) thi tra lai ban goc thay vi xoa.
    if not DRY:
        st0 = load_state()
        for key in list(st0.get("theme_lang", [])):
            scope, _, name = key.partition(":")
            base = SYS_THEMES if scope == "sys" else USER_THEMES
            d = os.path.join(base, name, "_inc", "lang")
            if not os.path.isdir(d):
                continue
            for fn_ in ("vi.xml", "vi_VN.xml"):
                bak = os.path.join(THEME_BACKUP_DIR, "%s-%s.%s" %
                                   (scope, name, fn_))
                dst = os.path.join(d, fn_)
                if os.path.exists(bak):
                    shutil.copy2(bak, dst)
                    os.remove(bak)
                elif os.path.exists(dst):
                    os.remove(dst)
    st = load_state()
    st["theme_lang"] = []
    save_state(st)

ROLLBACK = {"remove-copy": rb_remove_copy, "restore-theme": rb_restore_theme,
            "un-theme-strings": lambda: rb_un_theme_strings(),
            "un-splash-upper": lambda: rb_un_splash_upper(),
            "un-theme-xml": lambda: rb_un_theme_xml(),
            "un-theme-lang": lambda: rb_un_theme_lang(),
            "un-i18n": lambda: rb_un_i18n(), "un-features": lambda: rb_un_features(),
            "un-manual": lambda: rb_un_manual(), "un-icon": lambda: rb_un_icon(),
            "un-rafont": lambda: rb_un_rafont(),
            "un-themeset": lambda: rb_un_themeset(),
            "un-lang": lambda: rb_un_lang(), "un-hook": lambda: rb_un_hook(),
            "un-bootlogo": lambda: rb_un_bootlogo()}

def main():
    if len(sys.argv) < 2:
        print("usage: patcher.py scan|apply <id>|rscan|rollback <id>|"
              "uscan|uapply <id>|urevert <id>|fontreport")
        return 2
    cmd = sys.argv[1]
    if cmd == "booticon":
        # chay tu boot_apply.sh TRUOC khi ES khoi dong: hoa giai gamelist theo
        # co state icon (them khi bat, go khi tat). Khong bao gio duoc lam hong boot.
        try:
            st = load_state()
            if st.get("icon"):
                os.makedirs(ICON_DST_DIR, exist_ok=True)
                if os.path.exists(ICON_SRC) and not os.path.exists(ICON_DST):
                    shutil.copy2(ICON_SRC, ICON_DST)
            gamelist_set_icon(bool(st.get("icon")))
        except Exception:
            pass
        return 0
    if cmd == "themevi":
        # dung cho boot_apply + va tay theme he thong art-book-next
        # (overlay reset moi boot nen phai va lai; khong bao gio duoc
        # lam hong boot).
        try:
            d = os.path.join(SYS_THEMES, "es-theme-art-book-next")
            patch_theme_subsets(d, "sys")
            install_theme_lang(d, "sys")
        except Exception:
            pass
        return 0
    if cmd == "oscheck":
        ok, missing = os_check()
        print("OK 1" if ok else "OK 0")
        for m in missing:
            print("MISSING " + m)
        return 0 if ok else 3
    if cmd in ("uscan", "uapply", "urevert"):
        ok, missing = os_check()
        if not ok:
            print("TU CHOI: khong phai Knulli OS (%s)" % "; ".join(missing),
                  file=sys.stderr)
            return 0 if cmd == "uscan" else 3
        if cmd == "uscan":
            utils = uscan()
            if os.environ.get("KNVI_PLAIN"):
                for u in utils:
                    print("%s\t%s\t%s\t%d" % (u["id"], u["vi"], u["en"],
                                              u["state"]))
            else:
                print(json.dumps(utils, ensure_ascii=False))
        else:
            if len(sys.argv) < 3:
                print("usage: patcher.py %s <id>" % cmd)
                return 2
            u = UTILITIES.get(sys.argv[2])
            if u is None:
                print("unknown utility: " + sys.argv[2])
                return 1
            (u["apply"] if cmd == "uapply" else u["revert"])()
            log("DONE " + sys.argv[2])
        return 0
    if cmd in ("scan", "rscan", "fontreport", "themecheck",
               "apply", "rollback"):
        ok, missing = os_check()
        if not ok:
            print("TU CHOI: khong phai Knulli OS (%s)" % "; ".join(missing),
                  file=sys.stderr)
            if cmd in ("scan", "rscan", "fontreport", "themecheck"):
                return 0  # danh sach rong = app khong co viec de chay
            return 3
    if cmd == "themecheck":
        r = theme_check()
        if os.environ.get("KNVI_PLAIN"):
            if "error" in r:
                print("ERROR\t%s\t%s" % (r["error"]["vi"], r["error"]["en"]))
            else:
                print("THEME\t%s\t%s\t%d" % (r["theme"], r["location"],
                                             1 if r["is_vi"] else 0))
                for fn in r["fonts"]:
                    print("FONT\t%s\t%s" % (fn["font"], fn["status"]))
                print("TRSUM\t%s\t%s" % (r["trsum"]["vi"], r["trsum"]["en"]))
                print("VERDICT\t%d\t%s\t%s" % (1 if r["verdict_ok"] else 0,
                                                r["verdict"]["vi"],
                                                r["verdict"]["en"]))
                for h in r["hints"]:
                    print("HINT\t%s\t%s" % (h["vi"], h["en"]))
        else:
            print(json.dumps(r, ensure_ascii=False))
        return 0
    if cmd == "fontreport":
        rows = font_report()
        if os.environ.get("KNVI_PLAIN"):
            for r in rows:
                print("%s\t%s\t%s\t%s" % (r["theme"], r["font"],
                                          r["vi"], r["en"]))
        else:
            print(json.dumps(rows, ensure_ascii=False))
        return 0
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

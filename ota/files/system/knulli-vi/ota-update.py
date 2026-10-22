#!/usr/bin/env python3
"""ota-update.py - Cap nhat OTA cho KnulliVietHoa (chay TREN MAY Knulli).

Nguon: repo public nlkcodenew/knullivh (ota/manifest.json + ota/files/).
Manifest duoc ky Ed25519 (kid=kv1); khoa cong khai nhung san trong file nay,
xac thuc bang thuan toan Ed25519 thuan Python (khong phu thuoc thu vien ngoai).
File trong manifest co duong dan tuong doi so voi /userdata
(vi du: system/knulli-vi/bin/knulli-vi, roms/ports/KnulliVietHoa.sh).

Dung:
  python3 ota-update.py --avail   # chi kiem tra: in STATUS ..., exit 0/2/3
  python3 ota-update.py --apply   # tai + xac thuc tat ca roi moi cai de

Nguyen tac an toan: tai het ve thu muc tam, xac thuc chu ky + sha256 + size
tung file; chi khi MOI file deu dat moi bat dau ghi de. Loi mang/xac thuc
thi khong dong vao he thong.
"""
import base64
import hashlib
import io
import json
import os
import shutil
import sys
import time
import urllib.request

MANIFEST_URL = ("https://raw.githubusercontent.com/nlkcodenew/knullivh"
                "/main/ota/manifest.json")
FILES_BASE = ("https://raw.githubusercontent.com/nlkcodenew/knullivh"
              "/main/ota/files/")
KID = "kv1"
PUBKEY = bytes.fromhex(
    "34a8bdd156bd168f893db9754c5a3e123de4e698d4c38fd51e30804ee738b761")
ROOT = "/userdata"
SELF_DIR = "/userdata/system/knulli-vi"
STAGE = os.path.join(SELF_DIR, "state", "update-tmp")
LOG = os.path.join(SELF_DIR, "logs", "ota.log")
TIMEOUT = 25


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with io.open(LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


# ---------- Ed25519 verify (RFC 8032, thuan Python) ----------
_Q = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _Q - 2, _Q)) % _Q
_I = pow(2, (_Q - 1) // 4, _Q)


def _xrecover(y):
    xx = (y * y - 1) * pow(_D * y * y + 1, _Q - 2, _Q) % _Q
    x = pow(xx, (_Q + 3) // 8, _Q)
    if (x * x - xx) % _Q != 0:
        x = (x * _I) % _Q
    if x % 2 != 0:
        x = _Q - x
    return x


_BY = (4 * pow(5, _Q - 2, _Q)) % _Q
_B = (_xrecover(_BY), _BY)


def _edwards(P, Q):
    x1, y1 = P
    x2, y2 = Q
    den = pow(1 + _D * x1 * x2 * y1 * y2, _Q - 2, _Q)
    x3 = (x1 * y2 + x2 * y1) * den % _Q
    den2 = pow(1 - _D * x1 * x2 * y1 * y2, _Q - 2, _Q)
    y3 = (y1 * y2 + x1 * x2) * den2 % _Q
    return x3, y3


def _scalarmult(P, e):
    if e == 0:
        return (0, 1)
    Q = _scalarmult(P, e // 2)
    Q = _edwards(Q, Q)
    if e & 1:
        Q = _edwards(Q, P)
    return Q


def _decode_point(data):
    y = int.from_bytes(data, "little") & ((1 << 255) - 1)
    x = _xrecover(y)
    if (data[31] >> 7) & 1:
        x = _Q - x
    return (x, y)


def ed25519_verify(pub, msg, sig):
    if len(sig) != 64 or len(pub) != 32:
        return False
    try:
        A = _decode_point(pub)
        R = _decode_point(sig[:32])
    except Exception:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= _L:
        return False
    h = int.from_bytes(hashlib.sha512(sig[:32] + pub + msg).digest(),
                       "little") % _L
    return _scalarmult(_B, s) == _edwards(R, _scalarmult(A, h))


# ---------- tai + xac thuc manifest ----------
def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "knulli-vi-ota"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def get_manifest():
    raw = fetch(MANIFEST_URL)
    m = json.loads(raw.decode("utf-8"))
    if m.get("kid") != KID:
        raise ValueError("kid khong khop: %s" % m.get("kid"))
    body_obj = {"files": m["files"], "kid": m["kid"], "version": m["version"]}
    body = json.dumps(body_obj, separators=(",", ":"), sort_keys=True,
                      ensure_ascii=False).encode("utf-8")
    sig_b64 = m["signature"].strip()
    sig = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
    if not ed25519_verify(PUBKEY, body, sig):
        raise ValueError("chu ky manifest khong hop le")
    return m


def current_version():
    try:
        with io.open(os.path.join(SELF_DIR, "VERSION"),
                     encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "0.0.0"


def ver_tuple(v):
    out = []
    for part in v.strip().split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out)


def cmd_avail():
    cur = current_version()
    try:
        m = get_manifest()
    except Exception as e:
        log("avail LOI: %s" % e)
        print("STATUS error %s" % e)
        return 3
    new = m["version"]
    if ver_tuple(new) > ver_tuple(cur):
        print("STATUS available %s %s" % (cur, new))
        log("avail: co ban moi %s (dang dung %s)" % (new, cur))
        return 2
    print("STATUS uptodate %s %s" % (cur, new))
    log("avail: da moi nhat %s" % cur)
    return 0


def cmd_apply():
    cur = current_version()
    try:
        m = get_manifest()
    except Exception as e:
        log("apply LOI manifest: %s" % e)
        print("FAIL manifest %s" % e)
        return 1
    new = m["version"]
    if ver_tuple(new) <= ver_tuple(cur):
        print("STATUS uptodate %s %s" % (cur, new))
        return 0
    files = m["files"]
    print("TOTAL %d" % len(files))
    sys.stdout.flush()
    shutil.rmtree(STAGE, ignore_errors=True)
    os.makedirs(STAGE, exist_ok=True)
    try:
        for i, ent in enumerate(files, 1):
            path = ent["path"]
            if path.startswith("/") or ".." in path.split("/"):
                raise ValueError("duong dan khong an toan: %s" % path)
            data = fetch(FILES_BASE + path)
            if len(data) != ent["size"]:
                raise ValueError("size sai: %s" % path)
            if hashlib.sha256(data).hexdigest() != ent["sha256"]:
                raise ValueError("sha256 sai: %s" % path)
            dest = os.path.join(STAGE, path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(data)
            print("PROGRESS %d %d %s" % (i, len(files), path))
            sys.stdout.flush()
    except Exception as e:
        log("apply LOI tai: %s" % e)
        print("FAIL download %s" % e)
        shutil.rmtree(STAGE, ignore_errors=True)
        return 1
    # Tat ca da xac thuc xong -> cai de
    try:
        for i, ent in enumerate(files, 1):
            path = ent["path"]
            src = os.path.join(STAGE, path)
            dst = os.path.join(ROOT, path)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            # ghi ra file tam roi doi ten: an toan khi file dich dang duoc
            # chay (binary cua app / chinh script nay) - inode cu giu nguyen
            tmp = dst + ".new"
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
            if path.endswith((".py", ".sh")) or "/bin/" in path:
                os.chmod(dst, 0o755)
            print("INSTALLED %d %d %s" % (i, len(files), path))
            sys.stdout.flush()
    except Exception as e:
        log("apply LOI cai dat: %s" % e)
        print("FAIL install %s" % e)
        return 1
    shutil.rmtree(STAGE, ignore_errors=True)
    log("apply XONG: %s -> %s (%d file)" % (cur, new, len(files)))
    print("DONE %s" % new)
    return 0


def main():
    if len(sys.argv) < 2:
        print("usage: ota-update.py --avail|--apply")
        return 64
    if sys.argv[1] == "--avail":
        return cmd_avail()
    if sys.argv[1] == "--apply":
        return cmd_apply()
    print("tham so khong hop le")
    return 64


if __name__ == "__main__":
    sys.exit(main())

"""OPEM PZU (gün öncesi piyasa) saatlik fiyatlarını indirir.

`fiyat.yml` OPEM'in ertesi gün fiyatlarını yayınlayacağı saatlerde (≈09:40 Moldova saati) birkaç kez çalıştırır.
Çıktı: data/prices/YYYY-MM-DD.json (24 saatlik MDL/MWh) ve panelin okuduğu prices.json (son günler + `updated`:
fiyat verisinin en son değiştiği an, Moldova saati).
Panel bu fiyatı yalnızca "referans" olarak gösterir; satış fiyatı girişi kullanıcıda kalır.
"""
import json, os, sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import tracking as tk

TZ = ZoneInfo("Europe/Chisinau")
PRICE_DIR = os.path.join("data", "prices")
VOL_DIR = os.path.join("data", "volumes")
REV_FILE = os.path.join("data", "price_revisions.json")
TOL = 0.005  # MDL/MWh; bundan küçük fark düzeltme sayılmaz


def updated_stamp(old, days, now):
    """Fiyat verisi değiştiyse (yeni gün ya da farklı fiyat) `now`, değişmediyse eski damga. Penceredeki eski günlerin düşmesi güncelleme sayılmaz."""
    old = old or {}
    old_days = old.get("days") or {}
    changed = any(old_days.get(d) != p for d, p in days.items())
    return now if changed or not old.get("updated") else old["updated"]


def refresh_day(d, price_dir, vol_dir, rev_file, now):
    """Kayıtlı günü OPEM'den yeniden okur. Fiyat değişmişse dosyayı günceller ve düzeltmeyi `rev_file`a yazar.
    Dönüş: True = düzeltme yapıldı."""
    path = os.path.join(price_dir, f"{d}.json")
    try:
        old = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return False
    got = tk.fetch_pzu(d)
    if not got:
        return False
    new, vols = got
    tk.save_volumes(d, vols, vol_dir)
    if len(new) != len(old) or all(abs(a - b) <= TOL for a, b in zip(old, new)):
        return False
    json.dump(new, open(path, "w", encoding="utf-8"))
    try:
        log = json.load(open(rev_file, encoding="utf-8"))
    except (OSError, ValueError):
        log = []
    log.append({"day": d, "at": now, "old": old, "new": new})
    os.makedirs(os.path.dirname(rev_file) or ".", exist_ok=True)
    json.dump(log[-200:], open(rev_file, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"{d}: OPEM fiyatı düzeltilmiş, dosya güncellendi")
    return True


def main():
    now = datetime.now(TZ)
    today = now.date()
    days, vols = {}, {}
    for k in range(-3, 2):  # 3 gün geri, bugün, yarın
        d = (today + timedelta(days=k)).isoformat()
        refresh_day(d, PRICE_DIR, VOL_DIR, REV_FILE, now.strftime("%Y-%m-%dT%H:%M"))
        p = tk.load_prices(d, PRICE_DIR, fetch=True, vol_dir=VOL_DIR)
        if p and len(p) == 24:
            days[d] = p
            try:
                v = json.load(open(os.path.join(VOL_DIR, f"{d}.json"), encoding="utf-8"))
                if len(v) == 24:
                    vols[d] = v
            except (OSError, ValueError):
                pass
        elif p:
            print(f"{d}: {len(p)} saat (24 değil, atlandı)")
        else:
            print(f"{d}: fiyat yok")
    try:
        with open("prices.json", encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = None
    updated = updated_stamp(old, days, now.strftime("%Y-%m-%dT%H:%M"))
    with open("prices.json", "w", encoding="utf-8") as f:
        json.dump({"unit": "MDL/MWh", "source": "OPEM PZU", "updated": updated, "days": days, "volumes": vols}, f, ensure_ascii=False, separators=(",", ":"))
    print("yazıldı:", ", ".join(days) or "(boş)")
    # Bugünün fiyatı mutlaka olmalı; yoksa OPEM biçimi değişmiş ya da erişilemiyor demektir (iş akışı kırmızı olur).
    return 0 if today.isoformat() in days else 1


if __name__ == "__main__":
    sys.exit(main())

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


def updated_stamp(old, days, now):
    """Fiyat verisi değiştiyse (yeni gün ya da farklı fiyat) `now`, değişmediyse eski damga. Penceredeki eski günlerin düşmesi güncelleme sayılmaz."""
    old = old or {}
    old_days = old.get("days") or {}
    changed = any(old_days.get(d) != p for d, p in days.items())
    return now if changed or not old.get("updated") else old["updated"]


def main():
    now = datetime.now(TZ)
    today = now.date()
    days = {}
    for k in range(-3, 2):  # 3 gün geri, bugün, yarın
        d = (today + timedelta(days=k)).isoformat()
        p = tk.load_prices(d, PRICE_DIR, fetch=True)
        if p and len(p) == 24:
            days[d] = p
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
        json.dump({"unit": "MDL/MWh", "source": "OPEM PZU", "updated": updated, "days": days}, f, ensure_ascii=False, separators=(",", ":"))
    print("yazıldı:", ", ".join(days) or "(boş)")
    # Bugünün fiyatı mutlaka olmalı; yoksa OPEM biçimi değişmiş ya da erişilemiyor demektir (iş akışı kırmızı olur).
    return 0 if today.isoformat() in days else 1


if __name__ == "__main__":
    sys.exit(main())

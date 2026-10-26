"""OPEM PZU (gün öncesi piyasa) saatlik fiyatlarını indirir.

`fiyat.yml` her gün OPEM'in ertesi gün fiyatlarını yayınlamasından (≈09:40 Moldova saati) sonra çalıştırır.
Çıktı: data/prices/YYYY-MM-DD.json (24 saatlik MDL/MWh) ve panelin okuduğu prices.json (son günler).
Panel bu fiyatı yalnızca "referans" olarak gösterir; satış fiyatı girişi kullanıcıda kalır.
"""
import json, os, sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import tracking as tk

TZ = ZoneInfo("Europe/Chisinau")
PRICE_DIR = os.path.join("data", "prices")


def main():
    today = datetime.now(TZ).date()
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
    with open("prices.json", "w", encoding="utf-8") as f:
        json.dump({"unit": "MDL/MWh", "source": "OPEM PZU", "days": days}, f, ensure_ascii=False, separators=(",", ":"))
    print("yazıldı:", ", ".join(days) or "(boş)")
    # Bugünün fiyatı mutlaka olmalı; yoksa OPEM biçimi değişmiş ya da erişilemiyor demektir (iş akışı kırmızı olur).
    return 0 if today.isoformat() in days else 1


if __name__ == "__main__":
    sys.exit(main())

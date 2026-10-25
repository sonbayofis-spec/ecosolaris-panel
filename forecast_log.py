"""Ecosolaris gün öncesi tahmin kaydı.

GitHub Actions her sabah (OPEM PZU teklif kapanışı 09:30'dan önce) çalıştırır. Ertesi günün saatlik
V90-2.0 MW güç tahminini (kW) ECMWF, ICON ve GFS için kaydeder: data/forecast/YYYY-MM-DD.json.
Kayıt, teklif verilirken elde olan bilgiyi korur; sonradan gelen güncel tahminle üzerine yazılmaz.
tracking.py bu kayıtları gerçek üretimle karşılaştırır.
"""
import json, os, sys, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import telegram_report as tr

TZ = ZoneInfo("Europe/Chisinau")
OUT = os.path.join("data", "forecast")


def main():
    now = datetime.now(TZ)
    delivery = (now + timedelta(days=1)).date().isoformat()
    path = os.path.join(OUT, f"{delivery}.json")
    if os.path.exists(path) and "--force" not in sys.argv:
        print(f"{delivery} için kayıt zaten var, değiştirilmedi.")
        return 0
    req = urllib.request.Request(tr.URL, headers={"User-Agent": "ecosolaris-panel"})
    h = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))["hourly"]
    idx = [i for i, s in enumerate(h["time"]) if s.startswith(delivery)]
    if len(idx) < 23:
        print(f"{delivery} için yeterli saat yok ({len(idx)}), kayıt yazılmadı.")
        return 1
    rec = {"issued": now.strftime("%Y-%m-%dT%H:%M"), "delivery": delivery, "net": tr.NET,
           "times": [h["time"][i][11:16] for i in idx], "kw": {}}
    for m, key in tr.MODELS.items():
        if not h.get(f"wind_speed_100m_{key}"):
            continue
        _, kw = tr.compute(h, key)
        rec["kw"][m] = [round(kw[i], 1) for i in idx]
    if "e" not in rec["kw"]:
        print("ECMWF tahmini yok, kayıt yazılmadı.")
        return 1
    os.makedirs(OUT, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Yazıldı: {path} ({len(idx)} saat, modeller: {', '.join(rec['kw'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

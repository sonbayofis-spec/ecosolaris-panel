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
    tr.validate_hourly(h)
    idx = [i for i, s in enumerate(h["time"]) if s.startswith(delivery)]
    if len(idx) < 23:
        print(f"{delivery} için yeterli saat yok ({len(idx)}), kayıt yazılmadı.")
        return 1
    rec = {"issued": now.strftime("%Y-%m-%dT%H:%M"), "delivery": delivery, "net": tr.NET,
           "times": [h["time"][i][11:16] for i in idx], "kw": {}, "raw": {},
           # Hangi ayarlarla hesaplandığı: katsayı ya da yöntem değişirse geçmiş tahminler ham girdiden yeniden hesaplanabilir.
           "method": {"version": "2026-10-26", "site": tr.SITE, "net": tr.NET, "hub": tr.HUB, "rotor_radius": tr.R,
                      "density": "saatlik: 2 m sıcaklık, göbekte standart atmosfer basıncı", "rho_fallback": tr.RHO,
                      "elevation_m": tr.ELEV, "power_curve": "Vestas V90-2.0 MW (OEDB), başlama 3,5 m/s, durma 25 m/s"}}
    levels = [name for name, _ in tr.LEVELS]
    for m, key in tr.MODELS.items():
        if not h.get(f"wind_speed_100m_{key}"):
            continue
        _, kw = tr.compute(h, key)
        rec["kw"][m] = [round(kw[i], 1) for i in idx]
        # Ham girdi: rüzgâr profili, yön ve sıcaklık (modelin verdiği değerler, saha katsayısı uygulanmadan).
        raw = {lvl: [h[f"wind_speed_{lvl}_{key}"][i] for i in idx] for lvl in levels if h.get(f"wind_speed_{lvl}_{key}")}
        for name, src in (("dir", "wind_direction_100m"), ("temp", "temperature_2m")):
            if h.get(f"{src}_{key}"):
                raw[name] = [h[f"{src}_{key}"][i] for i in idx]
        rec["raw"][m] = raw
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

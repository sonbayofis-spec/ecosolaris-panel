"""Test verisini yeniler: Open-Meteo'dan gerçek bir yanıtı kaydeder ve Python hesabıyla beklenen değerleri yazar.

Normalde çalıştırmanız gerekmez; hesap yöntemini bilerek değiştirdiğinizde (katsayı, güç eğrisi, yoğunluk)
bu betiği çalıştırıp çıkan `expected.json`'u gözden geçirin, sonra testleri çalıştırın.
Kullanım:  python tests/refresh_fixture.py [sabit_zaman]    örn. 2026-10-27T12:00
Sabit zaman verilmezse yanıtın 2. günü 12:00 alınır. Dosya küçük kalsın diye yanıt ilk 72 saate kırpılır.
"""
import json, os, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import telegram_report as tr

FIXED_NOW = sys.argv[1] if len(sys.argv) > 1 else None
URL = ("https://api.open-meteo.com/v1/forecast?latitude=46.8932&longitude=28.6946"
       "&hourly=wind_speed_10m,wind_speed_80m,wind_speed_100m,wind_speed_120m,wind_speed_180m,wind_direction_100m,temperature_2m,precipitation"
       "&wind_speed_unit=ms&timezone=Europe%2FChisinau&forecast_days=7&models=ecmwf_ifs025,icon_seamless,gfs_seamless")


def window_energy(h, key, site, fixed_now):
    old = tr.SITE
    tr.SITE = site
    try:
        _, kw = tr.compute(h, key)
    finally:
        tr.SITE = old
    i0 = h["time"].index(fixed_now)
    return sum(kw[i0:i0 + 24]) / 1000 * tr.NET


def main():
    j = json.loads(urllib.request.urlopen(URL, timeout=60).read())
    tr.validate_hourly(j["hourly"])
    j["hourly"] = {k: v[:72] for k, v in j["hourly"].items()}   # 3 gün yeter
    h = j["hourly"]
    fixed = FIXED_NOW or h["time"][36]
    exp = {"fixed_now": fixed, "models": {m: window_energy(h, k, tr.SITE, fixed) for m, k in tr.MODELS.items()},
           "site_lo": window_energy(h, tr.MODELS["e"], 1.05, fixed), "site_hi": window_energy(h, tr.MODELS["e"], 1.25, fixed)}
    os.makedirs(os.path.join(HERE, "fixtures"), exist_ok=True)
    json.dump(j, open(os.path.join(HERE, "fixtures", "open_meteo.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(exp, open(os.path.join(HERE, "fixtures", "expected.json"), "w", encoding="utf-8"), indent=1)
    print("kaydedildi:", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in exp.items() if k != "models"}, {m: round(v, 3) for m, v in exp["models"].items()})


if __name__ == "__main__":
    main()

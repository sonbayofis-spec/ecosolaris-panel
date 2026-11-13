"""Ecosolaris tahmin doğruluğu kontrolü.

Her gece GitHub Actions çalıştırır. Son 7 günün her saati için, ECMWF, ICON ve GFS'in
bir gün önceden yaptığı 10 m rüzgâr tahminini Kişinev havalimanının (LUKK) ölçümüyle
karşılaştırır ve sonucu accuracy.json dosyasına yazar. Panel bu dosyayı okuyup gösterir.

Ayrıca her günün sonucunu data/accuracy/days.json arşivine ekler (gün → ölçüm ortalaması, model ortalamaları,
model başına ortalama mutlak hata ve saat sayısı). Arşiv yalnızca büyür; her çalışmada son BACK gün yeniden
hesaplanıp eksik günler doldurulur, böylece atlanan geceler ve geçmiş (BACK güne kadar) sonradan tamamlanır.
"""
import csv, io, json, os, sys, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Chisinau")
LAT, LON = 46.927, 28.931  # Kişinev havalimanı (LUKK)
MODELS = {"e": "ecmwf_ifs025", "i": "icon_seamless", "g": "gfs_seamless"}
DAYS = 7
BACK = 45   # arşiv için geriye bakılan gün sayısı
ARCHIVE = os.path.join("data", "accuracy", "days.json")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ecosolaris-panel"})
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8")


def day_record(day, fcmap, obs):
    """Bir günün kaydı; 18 saatten az ölçüm varsa None. Model alanları: ortalama (e/i/g), mae_*, n_*."""
    hours = [f"{day.isoformat()}T{h:02d}:00" for h in range(24)]
    oh = [h for h in hours if h in obs]
    if len(oh) < 18:
        return None, {}
    rec = {"date": day.isoformat(), "obs": round(sum(obs[h] for h in oh) / len(oh), 2), "n_obs": len(oh)}
    sums = {}
    for m in MODELS:
        pairs = [(fcmap[m].get(h), obs[h]) for h in oh if fcmap[m].get(h) is not None]
        if len(pairs) < 18:
            continue
        rec[m] = round(sum(f for f, _ in pairs) / len(pairs), 2)
        rec[f"mae_{m}"] = round(sum(abs(f - o) for f, o in pairs) / len(pairs), 2)
        rec[f"n_{m}"] = len(pairs)
        sums[m] = {"f": sum(f for f, _ in pairs), "o": sum(o for _, o in pairs), "ae": sum(abs(f - o) for f, o in pairs), "n": len(pairs)}
    return rec, sums


def update_archive(records, path=ARCHIVE):
    """Yeni gün kayıtlarını arşive ekler; var olan günleri yeniden hesaplananla günceller. Değiştiyse True."""
    try:
        with open(path, encoding="utf-8") as f:
            arc = json.load(f)
    except (OSError, ValueError):
        arc = {}
    before = json.dumps(arc, sort_keys=True)
    for r in records:
        arc[r["date"]] = {k: v for k, v in r.items() if k != "date"}
    if json.dumps(arc, sort_keys=True) == before:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(arc.items())), f, ensure_ascii=False, separators=(",", ":"))
    return True


def main():
    today = datetime.now(TZ).date()
    start = today - timedelta(days=BACK + 1)
    fc_url = ("https://previous-runs-api.open-meteo.com/v1/forecast"
              f"?latitude={LAT}&longitude={LON}&hourly=wind_speed_10m_previous_day1"
              f"&models={','.join(MODELS.values())}&past_days={BACK + 1}&forecast_days=1"
              "&wind_speed_unit=ms&timezone=Europe%2FChisinau")
    fc = json.loads(get(fc_url))["hourly"]
    fcmap = {m: dict(zip(fc["time"], fc.get(f"wind_speed_10m_previous_day1_{k}", []))) for m, k in MODELS.items()}

    ob_url = ("https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=LUKK&data=sknt"
              f"&year1={start.year}&month1={start.month}&day1={start.day}"
              f"&year2={today.year}&month2={today.month}&day2={today.day}"
              "&tz=Europe%2FChisinau&format=onlycomma&latlon=no&missing=M&trace=T&direct=no"
              "&report_type=3&report_type=4")
    obs = {}
    for row in csv.DictReader(io.StringIO(get(ob_url))):
        v, t = row.get("sknt"), row.get("valid", "")
        if v in (None, "", "M") or not t.endswith(":00"):
            continue
        obs[t.replace(" ", "T")] = float(v) * 0.5144

    days, archive = [], []
    tot = {m: {"f": 0.0, "o": 0.0, "ae": 0.0, "n": 0} for m in MODELS}
    for k in range(BACK, 0, -1):
        rec, sums = day_record(today - timedelta(days=k), fcmap, obs)
        if not rec or not sums:
            continue
        archive.append(rec)
        if k <= DAYS:
            days.append({x: rec[x] for x in ("date", "obs", *MODELS) if x in rec})
            for m, t in sums.items():
                for key in t:
                    tot[m][key] += t[key]
    if update_archive(archive):
        print(f"Arşiv güncellendi: {len(archive)} gün işlendi.")

    summary = {}
    for m, t in tot.items():
        if t["n"]:
            summary[m] = {"bias": round((t["f"] / t["o"] - 1) * 100, 1), "mae": round(t["ae"] / t["n"], 2), "hours": t["n"]}
    if not days or not summary:
        print("Yeterli veri yok, accuracy.json değiştirilmedi.")
        return 0
    best = min(summary, key=lambda m: summary[m]["mae"])
    out = {"updated": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M"), "station": "LUKK", "height_m": 10,
           "lead": "day1", "days": days, "summary": summary, "best": best}
    with open("accuracy.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

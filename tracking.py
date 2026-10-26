"""Ecosolaris tahmin ↔ gerçek üretim takibi.

Girdiler
  actual.csv          saatlik (ya da 30/15 dk) gerçek üretim, kWh. Sütunlar: saat (yerel, aralığın başı), kwh.
                      Örnek:  2026-11-02 14:00,812.5   (ayraç , ya da ;  — ; kullanılırsa ondalık virgüldür)
  data/forecast/*.json  forecast_log.py'nin her sabah kaydettiği gün öncesi tahminler (kW)
  OPEM PZU fiyatları  https://www.opem.md/tranzactionare-rezultate/RezultatePZU/export/csv?Data=YYYY-MM-DD
                      (yalnızca gerçek üretimi olan günler için indirilir, data/prices/ altında saklanır)

Çıktı: tracking.json  (panel okur)

Hata = tahmin − gerçek. Artı: tahmin fazla (bildirilen üretim gerçekleşmedi, eksik/deficit sapma),
eksi: tahmin az (gerçek üretim bildirilenden fazla, fazla/surplus sapma).
"Referans maliyet" sapmanın PZU saatlik fiyatıyla çarpımıdır; gerçek dengeleme fiyatı değildir.
"""
import argparse, csv, glob, io, json, math, os, re, sys, urllib.request
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

CAP_KW = 2000.0
TZ = ZoneInfo("Europe/Chisinau")
MODELS = ["e", "i", "g"]
PZU = "https://www.opem.md/tranzactionare-rezultate/RezultatePZU/export/csv?Data={d}&lang=ro"


def parse_time(s):
    s = s.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def read_actual(path):
    """Saat başına toplam kWh döndürür: {(tarih, 'SS'): kwh}. Eksik aralıklı saatler atlanır."""
    if not os.path.exists(path):
        return {}, 0
    text = open(path, encoding="utf-8-sig").read()
    lines = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        return {}, 0
    semi = ";" in lines[0]
    rows = list(csv.reader(lines, delimiter=";" if semi else ","))
    head = [c.strip().lower() for c in rows[0]]
    tcol, vcol, scale = 0, 1, 1.0
    for k, c in enumerate(head):
        if re.search(r"time|saat|zaman|data|date|ora", c):
            tcol = k
        if re.search(r"kwh|mwh|uretim|üretim|energy|energ", c):
            vcol = k
            if "mwh" in c:
                scale = 1000.0
    body = rows[1:] if parse_time(rows[0][tcol]) is None else rows
    cell = defaultdict(list)
    for r in body:
        if len(r) <= max(tcol, vcol):
            continue
        t = parse_time(r[tcol])
        v = r[vcol].strip()
        v = v.replace(",", ".") if semi else v.replace(",", "")
        try:
            kwh = float(v) * scale
        except ValueError:
            continue
        if t is None or not math.isfinite(kwh):
            continue
        cell[(t.strftime("%Y-%m-%d"), t.strftime("%H"))].append((t.minute, kwh))
    out, skipped = {}, 0
    for key, items in cell.items():
        mins = sorted({m for m, _ in items})
        step = 60 if len(mins) == 1 else min(b - a for a, b in zip(mins, mins[1:]))
        if len(items) == 60 // max(step, 1) and len(mins) == len(items):
            out[key] = sum(k for _, k in items)
        else:
            skipped += 1
    return out, skipped


def load_prices(date, price_dir, fetch=True):
    path = os.path.join(price_dir, f"{date}.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    if not fetch:
        return None
    try:
        req = urllib.request.Request(PZU.format(d=date), headers={"User-Agent": "ecosolaris-panel"})
        txt = urllib.request.urlopen(req, timeout=60).read().decode("utf-8-sig")
        prices, on = [], False
        for r in csv.reader(io.StringIO(txt)):
            if r and r[0].strip() == "Interval":
                on = True
                continue
            if on and r and r[0].strip().isdigit():
                prices.append(float(r[1].replace(",", "")))
        if len(prices) < 23:
            return None
        os.makedirs(price_dir, exist_ok=True)
        json.dump(prices, open(path, "w", encoding="utf-8"))
        return prices
    except Exception as e:
        print(f"PZU fiyatı alınamadı ({date}): {e}", file=sys.stderr)
        return None


def stats(pairs):
    """pairs: [(tahmin_kwh, gercek_kwh)]"""
    n = len(pairs)
    if not n:
        return None
    d = [f - a for f, a in pairs]
    fs, as_ = sum(f for f, _ in pairs), sum(a for _, a in pairs)
    return {"n": n, "forecast_mwh": round(fs / 1000, 3), "actual_mwh": round(as_ / 1000, 3),
            "bias_pct": round((fs / as_ - 1) * 100, 1) if as_ > 0 else None,
            "bias_kwh": round(sum(d) / n, 1), "mae_kwh": round(sum(map(abs, d)) / n, 1),
            "rmse_kwh": round(math.sqrt(sum(x * x for x in d) / n), 1),
            "nmae_pct": round(sum(map(abs, d)) / n / CAP_KW * 100, 2),
            "over_h": sum(1 for x in d if x > 0), "under_h": sum(1 for x in d if x < 0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--actual", default="actual.csv")
    ap.add_argument("--forecast-dir", default=os.path.join("data", "forecast"))
    ap.add_argument("--price-dir", default=os.path.join("data", "prices"))
    ap.add_argument("--out", default="tracking.json")
    ap.add_argument("--no-fetch", action="store_true", help="OPEM fiyatlarını indirme")
    a = ap.parse_args()

    actual, skipped = read_actual(a.actual)
    pairs = {m: [] for m in MODELS + ["m"]}
    days, cost = [], {"hours": 0, "abs_mwh": 0.0, "cost_mdl": 0.0, "over_mdl": 0.0, "under_mdl": 0.0}
    for fp in sorted(glob.glob(os.path.join(a.forecast_dir, "*.json"))):
        fc = json.load(open(fp, encoding="utf-8"))
        date, net = fc["delivery"], fc.get("net", 0.92)
        hours = [(k, t[:2]) for k, t in enumerate(fc["times"]) if (date, t[:2]) in actual]
        if not hours:
            continue
        prices = load_prices(date, a.price_dir, fetch=not a.no_fetch)
        day = {"date": date, "n": len(hours), "actual_mwh": round(sum(actual[(date, hh)] for _, hh in hours) / 1000, 3),
               "late": bool(fc.get("late"))}  # teklif kapanışından (09:30) sonra alınmış kayıt mı
        day_pairs = {m: [] for m in MODELS + ["m"]}
        for k, hh in hours:
            act = actual[(date, hh)]
            f = {m: fc["kw"][m][k] * net for m in MODELS if m in fc["kw"]}
            if f:
                f["m"] = sum(f.values()) / len(f)
            for m, v in f.items():
                pairs[m].append((v, act)); day_pairs[m].append((v, act))
            if "e" in f and prices and k < len(prices):
                err = (f["e"] - act) / 1000
                c = abs(err) * prices[k]
                cost["hours"] += 1; cost["abs_mwh"] += abs(err); cost["cost_mdl"] += c
                cost["over_mdl" if err > 0 else "under_mdl"] += c
        for m in MODELS + ["m"]:
            s = stats(day_pairs[m])
            if s:
                day[m] = s["forecast_mwh"]
                day["nmae_" + m] = s["nmae_pct"]
        days.append(day)

    summary = {m: s for m in MODELS + ["m"] if (s := stats(pairs[m]))}
    best = min((m for m in MODELS if m in summary), key=lambda m: summary[m]["nmae_pct"], default=None)
    out = {"updated": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M"), "capacity_kw": CAP_KW,
           "hours": summary.get("e", {}).get("n", 0), "skipped_partial_hours": skipped,
           "late_days": sum(1 for d in days if d.get("late")),
           "summary": summary, "best": best, "days": days[-30:],
           "ref_cost": {k: round(v, 1) if isinstance(v, float) else v for k, v in cost.items()}}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps({k: out[k] for k in ("updated", "hours", "skipped_partial_hours", "best")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

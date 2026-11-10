"""Ecosolaris BESS günlük planı (şarj / deşarj saatleri ve teslim programı).

Girdi: data/forecast/YYYY-MM-DD.json (gün öncesi ECMWF tahmini, kW) ve data/prices/YYYY-MM-DD.json (OPEM PZU, MDL/MWh).
Çıktı: bess.json (panel ve Telegram okur) ve data/bess/YYYY-MM-DD.json (o gün için verilen son plan).

Kurallar (sözleşme 038/03 ve bağlantı koşulları):
- Batarya yalnızca türbinin ürettiği enerjiyle şarj olur; şebekeden çekiş yok.
- Sayaçta (Pilon-95) şebekeye verilen güç 3,96 MW'ı geçemez: rüzgâr − şarj + deşarj ≤ 3,96.
- Satış fiyatı = saatlik piyasa fiyatı − spread (15 EUR/MWh, BNM kuruyla MDL'ye çevrilir).
- Günde en fazla bir tam çevrim; gün 0 şarjla başlar ve biter.

Ertesi günün OPEM fiyatı henüz yayınlanmadıysa plan, son 7 günün saatlik ortalamasıyla yapılır ("est");
fiyat yayınlanınca aynı gün yeniden hesaplanır ("opem").

Kullanılabilir kapasite ve çevrim verimi üretici verisi gelene kadar VARSAYIMDIR (USABLE, RTE).
Panel plan gösterir; bataryayı yönetmez.
"""
import json, os, sys, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Chisinau")
FC_DIR = os.path.join("data", "forecast")
PRICE_DIR = os.path.join("data", "prices")
OUT_DIR = os.path.join("data", "bess")

P_MW = 5.0          # batarya gücü
E_MWH = 5.01        # batarya kapasitesi
USABLE = 0.90       # kullanılabilir pay (varsayım)
RTE = 0.88          # gidiş-dönüş verimi (varsayım)
LIMIT_MW = 3.96     # sayaçta şebekeye verilebilecek en yüksek güç
SPREAD_EUR = 15.0   # sözleşme Ek 4
EUR_MDL_FALLBACK = 20.0
WEAR = 0.0          # MDL / satılan MWh; batarya yıpranma payı (üretici verisi gelince)
Q = 0.02            # hesap adımı, MWh
BNM = "https://www.bnm.md/en/official_exchange_rates?get_xml=1&date={d}"


def eur_rate(day):
    """BNM resmî EUR kuru; alınamazsa (None, yedek)."""
    try:
        req = urllib.request.Request(BNM.format(d=day.strftime("%d.%m.%Y")), headers={"User-Agent": "ecosolaris-panel"})
        root = ET.fromstring(urllib.request.urlopen(req, timeout=30).read())
        for v in root.iter("Valute"):
            if v.findtext("CharCode") == "EUR":
                r = float(v.findtext("Value")) / float(v.findtext("Nominal") or 1)
                if 10 < r < 40:
                    return r, "bnm"
    except Exception as e:  # ağ, biçim
        print(f"BNM kuru alınamadı: {e}", file=sys.stderr)
    return EUR_MDL_FALLBACK, "fallback"


def plan(wind, price, p_mw=P_MW, cap=E_MWH * USABLE, rte=RTE, limit=LIMIT_MW, wear=WEAR, q=Q):
    """wind: saatlik MWh (=ortalama MW), price: saatlik net fiyat (MDL/MWh). (şarj, deşarj) listelerini döndürür.

    Açgözlü eşleştirme: her adımda q MWh'yi en çok kazandıran (şarj saati → sonraki deşarj saati) çiftine verir;
    güç, rüzgâr, sayaç sınırı ve doluluk kısıtlarını korur. Sonuç tests/test_bess.py'de doğrusal programla karşılaştırılır.
    """
    n = len(wind)
    ec = rte ** 0.5
    c, d, soc = [0.0] * n, [0.0] * n, [0.0] * n   # soc[h]: h saatinin sonundaki doluluk
    stored = 0.0
    eps = 1e-9
    while stored + q * ec <= cap + eps:
        best, pair = eps, None
        for hc in range(n):
            if d[hc] > 0 or c[hc] + q > min(p_mw, max(wind[hc], 0.0)) + eps:
                continue
            for hd in range(hc + 1, n):
                g = (price[hd] - wear) * q * rte - price[hc] * q
                if g <= best or c[hd] > 0:
                    continue
                if d[hd] + q * rte > p_mw + eps or wind[hd] + d[hd] + q * rte > limit + eps:
                    continue
                if max(soc[hc:hd]) + q * ec > cap + eps:
                    continue
                best, pair = g, (hc, hd)
        if not pair:
            break
        hc, hd = pair
        c[hc] += q
        d[hd] += q * rte
        for h in range(hc, hd):
            soc[h] += q * ec
        stored += q * ec
    return c, d


def day_plan(day, wind, price, src, spread):
    net = [p - spread for p in price]
    c, d = plan(wind, net)
    grid = [wind[h] - c[h] + d[h] for h in range(len(wind))]
    ec = RTE ** 0.5
    soc, s = [], 0.0
    for h in range(len(wind)):
        s += c[h] * ec - d[h] / ec
        soc.append(max(s, 0.0))
    base = sum(w * p for w, p in zip(wind, net))
    total = sum(g * p for g, p in zip(grid, net))
    r3 = lambda a: [round(x, 3) for x in a]
    return {"date": day, "price_src": src, "wind": r3(wind), "price": [round(p, 1) for p in net],
            "charge": r3(c), "discharge": r3(d), "grid": r3(grid), "soc": r3(soc),
            "base_mdl": round(base), "extra_mdl": round(total - base), "sold_mwh": round(sum(d), 2),
            "charged_mwh": round(sum(c), 2), "peak_mw": round(max(grid), 2)}


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def wind_mwh(day):
    f = load_json(os.path.join(FC_DIR, f"{day}.json"))
    if not f or len((f.get("kw") or {}).get("e") or []) != 24:
        return None
    return [max(k, 0.0) * f.get("net", 0.92) / 1000.0 for k in f["kw"]["e"]]


def price_for(day):
    """(fiyat listesi, kaynak). Yayınlanmışsa OPEM; değilse önceki en çok 7 günün saatlik ortalaması."""
    p = load_json(os.path.join(PRICE_DIR, f"{day}.json"))
    if p and len(p) == 24:
        return [float(x) for x in p], "opem"
    prev, d0 = [], datetime.fromisoformat(day).date()
    for k in range(1, 15):
        q = load_json(os.path.join(PRICE_DIR, f"{(d0 - timedelta(days=k)).isoformat()}.json"))
        if q and len(q) == 24:
            prev.append(q)
        if len(prev) == 7:
            break
    if len(prev) < 3:
        return None, None
    return [sum(x[h] for x in prev) / len(prev) for h in range(24)], "est"


def main():
    now = datetime.now(TZ)
    rate, rate_src = eur_rate(now.date())
    spread = SPREAD_EUR * rate
    days = {}
    for k in (0, 1):
        day = (now.date() + timedelta(days=k)).isoformat()
        w = wind_mwh(day)
        p, src = price_for(day)
        if not w or not p:
            print(f"{day}: {'tahmin' if not w else 'fiyat'} yok, plan yapılmadı")
            continue
        days[day] = day_plan(day, w, p, src, spread)
        print(f"{day}: fiyat={src}, satılan {days[day]['sold_mwh']} MWh, ek gelir {days[day]['extra_mdl']} MDL")
    params = {"p_mw": P_MW, "e_mwh": E_MWH, "usable": USABLE, "rte": RTE, "limit_mw": LIMIT_MW,
              "spread_eur": SPREAD_EUR, "eur_mdl": round(rate, 4), "eur_src": rate_src, "spread_mdl": round(spread, 1)}
    old = load_json("bess.json") or {}
    changed = old.get("days") != days or old.get("params") != params
    out = {"unit": "MWh, MDL/MWh", "updated": now.strftime("%Y-%m-%dT%H:%M") if changed or not old.get("updated") else old["updated"],
           "params": params, "days": days}
    with open("bess.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.makedirs(OUT_DIR, exist_ok=True)
    for day, rec in days.items():
        with open(os.path.join(OUT_DIR, f"{day}.json"), "w", encoding="utf-8") as f:
            json.dump({"params": params, **rec}, f, ensure_ascii=False, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

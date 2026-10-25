"""Ecosolaris saat başı Telegram raporu / hourly Telegram report / raport orar Telegram.

GitHub Actions her saat çalıştırır. Open-Meteo'dan ECMWF, ICON ve GFS tahminini çeker,
paneldeki hesabın aynısıyla V90-2.0 MW üretimini bulur ve Telegram'a gönderir.

Uyarılar (aynı çalıştırmada, yalnızca gerektiğinde ayrı mesaj olarak):
  - Fırtına ya da buzlanma 3 saat sonra başlıyorsa: "⚠️ Ecosolaris uyarısı"
    (türbinin durabileceği fırtına, yani ≥ 24 m/s ya da hamle ≥ 32 m/s, gece de sesli gelir)
  - Her sabah 08:00 raporunda: önümüzdeki 3 günün fırtına, buzlanma ve en uzun sakin bakım penceresi
  Eşikler: fırtına = ECMWF göbek hızı ≥ 20 m/s, herhangi bir model ≥ 22 m/s ya da 10 m hamlesi ≥ 25 m/s;
  buzlanma = göbekte ≈ 0,5 °C altı ve yağış ≥ 0,1 mm ya da nem ≥ %95 (en az 2 saat);
  sakin pencere = 08:00–18:00 arasında en az 4 saat rüzgâr 3,5 m/s altında.

Gizli değişkenler (Settings -> Secrets and variables -> Actions -> Secrets):
  TELEGRAM_BOT_TOKEN  BotFather'ın verdiği anahtar
  TELEGRAM_CHAT_ID    alıcı(lar): "123456" ya da dil ile "123456:tr,789012:en,-100345:ro"
                      dil verilmezse Türkçe gönderilir.
İsteğe bağlı değişken (Variables): PRICE_LEI (varsayılan 2.50)
"""
import json, math, os, sys, urllib.parse, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

URL = ("https://api.open-meteo.com/v1/forecast?latitude=46.8932&longitude=28.6946"
       "&hourly=wind_speed_10m,wind_speed_80m,wind_speed_100m,wind_speed_120m,wind_speed_180m,wind_direction_100m,temperature_2m"
       "&wind_speed_unit=ms&timezone=Europe%2FChisinau&forecast_days=3"
       "&models=ecmwf_ifs025,icon_seamless,gfs_seamless")
WX_URL = ("https://api.open-meteo.com/v1/forecast?latitude=46.8932&longitude=28.6946"
          "&hourly=temperature_2m,relative_humidity_2m,precipitation,wind_gusts_10m"
          "&wind_speed_unit=ms&timezone=Europe%2FChisinau&forecast_days=4")
PANEL = "https://sonbayofis-spec.github.io/ecosolaris-panel/"
SITE, RHO, NET, HUB, R = 1.14, 1.198, 0.92, 105, 45
NORM = [17.25, 16.48, 15.14, 14.46, 10.69, 9.44, 8.73, 8.84, 10.8, 12.6, 13.14, 16.2]
PC = [(3, 0), (3.5, 42), (4, 93), (4.5, 145), (5, 211), (5.5, 284), (6, 391), (6.5, 492), (7, 601), (7.5, 732), (8, 885),
      (8.5, 1088), (9, 1247), (9.5, 1430), (10, 1594), (10.5, 1743), (11, 1861), (11.5, 1948), (12, 1993), (12.5, 2000), (25, 2000)]
MODELS = {"e": "ecmwf_ifs025", "i": "icon_seamless", "g": "gfs_seamless"}
LEVELS = [("10m", 10), ("80m", 80), ("100m", 100), ("120m", 120), ("180m", 180)]
SLICES = [(z, math.sqrt(R * R - (z - HUB) ** 2)) for z in range(60, 151, 5) if R * R - (z - HUB) ** 2 > 0]
ELEV = 176
# Hava yoğunluğu saatlik hesaplanır (panelle aynı): standart atmosfer basıncı ve o saatin sıcaklığı.
# Sıcaklık yoksa RHO kullanılır. Güç eğrisi 1,225 kg/m³ içindir; hız küp kökle ölçeklenir.
HUBP = 101325 * (1 - 2.25577e-5 * (ELEV + HUB)) ** 5.25588


def dens_factor(tc):
    rho = HUBP / (287.05 * (tc - 0.0065 * HUB + 273.15)) if isinstance(tc, (int, float)) and -50 < tc < 50 else RHO
    return (rho / 1.225) ** (1 / 3)


L = {
    "tr": {"mon": ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"],
           "month": ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"],
           "days": ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"],
           "dirs": ["kuzey", "kuzeydoğu", "doğu", "güneydoğu", "güney", "güneybatı", "batı", "kuzeybatı"],
           "now": "Şimdi", "of_cap": "kapasite %{p}", "next3": "Sonraki saatler", "h24": "Önümüzdeki 24 saat", "today": "Bugün", "dfull": ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"], "proj": "💰 <b>{d} için tahmini brüt satış</b>: ≈{lei} lei ({lo}–{hi}) · {e} MWh",
           "expected": "beklenen üretim", "conf": "Tahmin güvenilirliği", "levels": ["Yüksek", "Orta", "Düşük"],
           "times": "{m} ortalamasının {x} katı", "pct": "{m} ortalamasına göre %{p}", "gross": "brüt satış",
           "stop": "{n} saat rüzgâr yetersiz, üretim yok", "link": "Paneli aç", "dec": ","},
    "en": {"mon": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
           "month": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
           "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
           "dirs": ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"],
           "now": "Now", "of_cap": "{p}% of capacity", "next3": "Next hours", "h24": "Next 24 hours", "today": "Today", "dfull": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"], "proj": "💰 <b>Projected gross sales, {d}</b>: ≈{lei} lei ({lo}–{hi}) · {e} MWh",
           "expected": "expected output", "conf": "Forecast confidence", "levels": ["High", "Medium", "Low"],
           "times": "{x}× a normal {m} day", "pct": "{p}% of a normal {m} day", "gross": "gross sales",
           "stop": "{n} h too calm to produce", "link": "Open panel", "dec": "."},
    "ro": {"mon": ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct", "noi", "dec"],
           "month": ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie"],
           "days": ["Lun", "Mar", "Mie", "Joi", "Vin", "Sâm", "Dum"],
           "dirs": ["nord", "nord-est", "est", "sud-est", "sud", "sud-vest", "vest", "nord-vest"],
           "now": "Acum", "of_cap": "{p}% din capacitate", "next3": "Orele următoare", "h24": "Următoarele 24 de ore", "today": "Azi", "dfull": ["luni", "marți", "miercuri", "joi", "vineri", "sâmbătă", "duminică"], "proj": "💰 <b>Vânzări brute estimate, {d}</b>: ≈{lei} lei ({lo}–{hi}) · {e} MWh",
           "expected": "producție estimată", "conf": "Încredere în prognoză", "levels": ["ridicată", "medie", "scăzută"],
           "times": "de {x} ori o zi normală de {m}", "pct": "{p}% dintr-o zi normală de {m}", "gross": "vânzări brute",
           "stop": "{n} ore fără vânt suficient", "link": "Deschide panoul", "dec": ","},
}

A = {
    "tr": {"head_daily": "🛠 <b>Ecosolaris · önümüzdeki 3 gün</b>", "head_now": "⚠️ <b>Ecosolaris uyarısı</b>",
           "ice": "🧊 <b>Buzlanma riski</b>: {w}. Göbekte sıcaklık 0 °C civarı ve nem/yağış var; kanatlarda buz tutabilir, türbin durabilir.",
           "storm": "🌪 <b>Kuvvetli rüzgâr</b>: {w}, en yüksek {v} m/s (hamle {g} m/s). Türbin bu hızda tam güçte çalışır; 25 m/s üzerinde güvenlik için durur.",
           "calm": "🔧 <b>Bakıma uygun sakin pencere</b>: {w}. Rüzgâr 3,5 m/s altında, üretim kaybı yok denecek kadar az.",
           "soon": "{h} saat sonra başlıyor", "hours": "{n} saat",
           "c_now": "UYARI · 3 SAAT SONRA", "c_daily": "ÖNÜMÜZDEKİ 3 GÜN",
           "h_storm": "Kuvvetli rüzgâr · tam güç", "h_cut": "Fırtına · türbin durabilir", "h_ice": "Buzlanma riski", "h_calm": "Bakıma uygun sakin pencere",
           "b_storm": "En yüksek {v} m/s, yerde hamle {g} m/s. Türbin bu hızlarda tam güçte (2 MW) çalışır; 25 m/s durma eşiğine yaklaştığı için takip edin.",
           "b_cut": "En yüksek {v} m/s, yerde hamle {g} m/s. 25 m/s'nin üzerinde türbin güvenlik için durur ve bu saatlerde üretim olmaz; rüzgâr 20 m/s altına inince yeniden başlar.",
           "b_ice": "Göbekte sıcaklık 0 °C civarında, nem ya da yağış var. Kanatlarda buz tutabilir; türbin kendini durdurabilir, sahada buz düşmesine dikkat.",
           "b_calm": "Rüzgâr 3,5 m/s altında; üretim kaybı neredeyse sıfır. Planlı bakım için en uygun zaman.",
           "foot": "Eşikler: fırtına ≥ 20 m/s göbek · buzlanma ≈ 0 °C + nem/yağış · sakin < 3,5 m/s (08–18)"},
    "en": {"head_daily": "🛠 <b>Ecosolaris · next 3 days</b>", "head_now": "⚠️ <b>Ecosolaris alert</b>",
           "ice": "🧊 <b>Icing risk</b>: {w}. Near 0 °C at hub height with moisture or precipitation; ice may form on the blades and stop the turbine.",
           "storm": "🌪 <b>Strong wind</b>: {w}, up to {v} m/s (gusts {g} m/s). The turbine runs at full power here; above 25 m/s it shuts down for safety.",
           "calm": "🔧 <b>Calm window for maintenance</b>: {w}. Wind below 3.5 m/s, almost no lost output.",
           "soon": "starts in {h} h", "hours": "{n} h",
           "c_now": "ALERT · IN 3 HOURS", "c_daily": "NEXT 3 DAYS",
           "h_storm": "Strong wind · full power", "h_cut": "Storm · turbine may stop", "h_ice": "Icing risk", "h_calm": "Calm window for maintenance",
           "b_storm": "Up to {v} m/s, ground gusts {g} m/s. The turbine runs at full power (2 MW) at these speeds; watch it, as it is close to the 25 m/s cut-out.",
           "b_cut": "Up to {v} m/s, ground gusts {g} m/s. Above 25 m/s the turbine stops for safety and produces nothing; it restarts once the wind drops below 20 m/s.",
           "b_ice": "Near 0 °C at hub height with moisture or precipitation. Ice may form on the blades and stop the turbine; watch for falling ice on site.",
           "b_calm": "Wind below 3.5 m/s, almost no lost output. Best time for planned maintenance.",
           "foot": "Thresholds: storm ≥ 20 m/s at hub · icing ≈ 0 °C + moisture/precipitation · calm < 3.5 m/s (08–18)"},
    "ro": {"head_daily": "🛠 <b>Ecosolaris · următoarele 3 zile</b>", "head_now": "⚠️ <b>Alertă Ecosolaris</b>",
           "ice": "🧊 <b>Risc de givraj</b>: {w}. În jur de 0 °C la butuc, cu umezeală sau precipitații; pe pale se poate forma gheață, turbina se poate opri.",
           "storm": "🌪 <b>Vânt puternic</b>: {w}, până la {v} m/s (rafale {g} m/s). La această viteză turbina merge la putere maximă; peste 25 m/s se oprește pentru siguranță.",
           "calm": "🔧 <b>Fereastră liniștită pentru mentenanță</b>: {w}. Vânt sub 3,5 m/s, pierdere de producție aproape zero.",
           "soon": "începe în {h} ore", "hours": "{n} ore",
           "c_now": "ALERTĂ · ÎN 3 ORE", "c_daily": "URMĂTOARELE 3 ZILE",
           "h_storm": "Vânt puternic · putere maximă", "h_cut": "Furtună · turbina se poate opri", "h_ice": "Risc de givraj", "h_calm": "Fereastră liniștită pentru mentenanță",
           "b_storm": "Până la {v} m/s, rafale la sol {g} m/s. La aceste viteze turbina merge la putere maximă (2 MW); urmăriți, fiind aproape de pragul de oprire de 25 m/s.",
           "b_cut": "Până la {v} m/s, rafale la sol {g} m/s. Peste 25 m/s turbina se oprește pentru siguranță și nu produce; repornește când vântul scade sub 20 m/s.",
           "b_ice": "În jur de 0 °C la butuc, cu umezeală sau precipitații. Pe pale se poate forma gheață și turbina se poate opri; atenție la gheața care cade.",
           "b_calm": "Vânt sub 3,5 m/s, pierdere de producție aproape zero. Cel mai bun moment pentru mentenanță planificată.",
           "foot": "Praguri: furtună ≥ 20 m/s la butuc · givraj ≈ 0 °C + umezeală/precipitații · calm < 3,5 m/s (08–18)"},
}

def pw(v):
    if not v or v < 3.5 or v > 25:
        return 0.0
    for (a, pa), (b, pb) in zip(PC, PC[1:]):
        if v <= b:
            return pa + (pb - pa) * (v - a) / (b - a)
    return 0.0


def profile(lv):
    def u(z):
        for k in range(len(lv) - 1):
            (z1, u1), (z2, u2) = lv[k], lv[k + 1]
            if z <= z2 or k == len(lv) - 2:
                if u1 > 0.05 and u2 > 0.05:
                    a = math.log(u2 / u1) / math.log(z2 / z1)
                    a = min(max(a, 0), 0.6) if z > z2 else min(max(a, -0.3), 0.9)
                    return u1 * (z / z1) ** a
                return max(0.0, u1 + (u2 - u1) * (z - z1) / (z2 - z1))
        return lv[-1][1]
    return u


def compute(h, key):
    hub, kw = [], []
    temps = h.get(f"temperature_2m_{key}") or []
    for i in range(len(h["time"])):
        lv = []
        for name, z in LEVELS:
            arr = h.get(f"wind_speed_{name}_{key}")
            if arr and arr[i] is not None:
                lv.append((z, arr[i] * SITE))
        if len(lv) < 2:
            hub.append(None); kw.append(0.0); continue
        u = profile(lv)
        s = sum(w * u(z) ** 3 for z, w in SLICES); w = sum(w for _, w in SLICES)
        hub.append(u(HUB)); kw.append(pw((s / w) ** (1 / 3) * dens_factor(temps[i] if i < len(temps) else None)))
    return hub, kw


def fmt(x, d, lang):
    s = f"{x:,.{d}f}"
    return s if L[lang]["dec"] == "." else s.replace(",", "X").replace(".", ",").replace("X", ".")


def summary(h, now, price):
    t = h["time"]
    res = {m: compute(h, k) for m, k in MODELS.items() if h.get(f"wind_speed_100m_{k}")}
    key = now.strftime("%Y-%m-%dT%H:00")
    i0 = t.index(key) if key in t else 0
    i1 = min(i0 + 24, len(t))
    hub, kw = res["e"]
    e24 = {m: sum(k[i0:i1]) / 1000 * NET for m, (_, k) in res.items()}
    lo, hi = min(e24.values()), max(e24.values())
    spread = (hi - lo) / max(sum(e24.values()) / len(e24), 0.5)
    return {
        "hub": hub[i0], "kw": kw[i0],
        "next": [(t[j][11:16], hub[j], kw[j]) for j in range(i0 + 1, min(i0 + 4, len(t)))],
        "e": e24["e"], "lo": lo, "hi": hi, "lei": e24["e"] * 1000 * price, "llo": lo * 1000 * price, "lhi": hi * 1000 * price,
        "ratio": e24["e"] / NORM[now.month - 1], "agree": 0 if spread < 0.3 else 1 if spread < 0.6 else 2,
        "dir": round((h[f"wind_direction_100m_{MODELS['e']}"][i0] % 360) / 45) % 8,
        "stop": sum(1 for j in range(i0, i1) if kw[j] <= 0),
        "series": [kw[j] for j in range(i0, i1)], "hours": [t[j][11:13] for j in range(i0, i1)],
        **today_sales(t, res, now, price),
    }


def today_sales(t, res, now, price):
    day = now.strftime("%Y-%m-%d")
    idx = [j for j, x in enumerate(t) if x[:10] == day]
    if not idx:
        return {"td_e": 0.0, "td_lei": 0.0, "td_llo": 0.0, "td_lhi": 0.0}
    a, b = idx[0], idx[-1] + 1
    ed = {m: sum(k[a:b]) / 1000 * NET for m, (_, k) in res.items()}
    return {"td_e": ed["e"], "td_lei": ed["e"] * 1000 * price,
            "td_llo": min(ed.values()) * 1000 * price, "td_lhi": max(ed.values()) * 1000 * price}


def runs(flags, t, min_len=1):
    """Ardışık True saat blokları: [(başlangıç indeksi, bitiş indeksi hariç)]."""
    out, a = [], None
    for j, f in enumerate(flags + [False]):
        if f and a is None:
            a = j
        elif not f and a is not None:
            if j - a >= min_len:
                out.append((a, j))
            a = None
    return out


def alerts(h, wx, now):
    t = h["time"]
    res = {m: compute(h, k) for m, k in MODELS.items() if h.get(f"wind_speed_100m_{k}")}
    key = now.strftime("%Y-%m-%dT%H:00")
    i0 = t.index(key) if key in t else 0
    end = min(i0 + 72, len(t))
    wt = wx.get("time", [])
    pos = {x: j for j, x in enumerate(wt)}
    def w(name, j):
        k = pos.get(t[j]); arr = wx.get(name) or []
        return arr[k] if k is not None and k < len(arr) else None
    hub = {m: r[0] for m, r in res.items()}
    ice, storm, calm, smax = [], [], [], {}
    for j in range(len(t)):
        tc, rh, pr, gu = w("temperature_2m", j), w("relative_humidity_2m", j), w("precipitation", j), w("wind_gusts_10m", j)
        th = None if tc is None else tc - 0.65  # 105 m'de yaklaşık sıcaklık
        ice.append(th is not None and th <= 0.5 and ((pr or 0) >= 0.1 or (rh or 0) >= 95))
        hv = [v[j] for v in hub.values() if v[j] is not None]
        top = max(hv) if hv else 0
        storm.append((hub["e"][j] or 0) >= 20 or top >= 22 or (gu or 0) >= 25)
        smax[j] = (top, gu or 0)
        hr = int(t[j][11:13])
        calm.append(8 <= hr < 18 and (hub["e"][j] or 0) < 3.5 and top < 4.5)
    def lim(bl):
        return [(a, b) for a, b in bl if b > i0 and a < end]
    return {"t": t, "i0": i0, "smax": smax,
            "ice": lim(runs(ice, t, 2)), "storm": lim(runs(storm, t, 1)), "calm": lim(runs(calm, t, 4)),
            "ice_flags": ice, "storm_flags": storm}


def span(t, a, b, lang):
    x = L[lang]
    da = datetime.fromisoformat(t[a]); db = datetime.fromisoformat(t[b - 1]) + timedelta(hours=1)
    s = f"{x['days'][da.weekday()]} {da.day} {x['mon'][da.month - 1]} {da:%H}:00–{db:%H}:00"
    return s + f" ({A[lang]['hours'].format(n=b - a)})"


def span_card(t, a, b, lang):
    x = L[lang]
    da = datetime.fromisoformat(t[a]); db = datetime.fromisoformat(t[b - 1]) + timedelta(hours=1)
    left = f"{x['days'][da.weekday()]} {da.day} {x['mon'][da.month - 1]} {da:%H}:00"
    right = f"{db:%H}:00" if db.date() == da.date() or db.hour == 0 and (db - da).days == 0 else f"{x['days'][db.weekday()]} {db.day} {x['mon'][db.month - 1]} {db:%H}:00"
    return f"{left} – {right} · {A[lang]['hours'].format(n=b - a)}"


def alert_messages(al, now, lang):
    lang = lang if lang in A else "tr"
    a_, t, i0 = A[lang], al["t"], al["i0"]
    f = lambda v: fmt(v, 0, lang)
    def storm_line(a, b):
        v = max(al["smax"][j][0] for j in range(a, b)); g = max(al["smax"][j][1] for j in range(a, b))
        return a_["storm"].format(w=span(t, a, b, lang), v=f(v), g=f(g))
    def item(kind, a, b):
        if kind == "storm":
            v = max(al["smax"][j][0] for j in range(a, b)); g = max(al["smax"][j][1] for j in range(a, b))
            cut = v >= 24 or g >= 32  # durma eşiğine (25 m/s, 10 dk ortalama) ulaşma ihtimali
            key = "cut" if cut else "storm"
            return (key, a_["h_" + key], span_card(t, a, b, lang), a_["b_" + key].format(v=f(v), g=f(g)))
        return (kind, a_["h_" + kind], span_card(t, a, b, lang), a_["b_" + kind])
    msgs = []
    # 1) Acil: buzlanma ya da fırtına tam 3 saat sonra başlıyorsa (her olay için bir kez)
    k = i0 + 3
    urgent = []; uitems = []
    if k < len(t):
        for name in ("storm", "ice"):
            fl = al[name + "_flags"]
            if fl[k] and not fl[k - 1]:
                blk = next(((a, b) for a, b in runs(fl, t, 1) if a == k), None)
                if blk:
                    line = storm_line(*blk) if name == "storm" else a_["ice"].format(w=span(t, *blk, lang))
                    urgent.append((name, line + f" — {a_['soon'].format(h=3)}"))
                    uitems.append(item(name, *blk))
    if urgent:
        kind = uitems[0][0] if uitems else "storm"
        msgs.append((any(it[1] == a_["h_cut"] for it in uitems), "\n\n".join([a_["head_now"]] + [u[1] for u in urgent]),
                     {"kind": kind, "title": a_["c_now"], "items": uitems}))
    # 2) Her sabah 08:00 raporunda 3 günlük özet (yalnızca bir şey varsa)
    if now.hour == 8:
        lines = [storm_line(a, b) for a, b in al["storm"]]
        ditems = [item("storm", a, b) for a, b in al["storm"]]
        lines += [a_["ice"].format(w=span(t, a, b, lang)) for a, b in al["ice"]]
        ditems += [item("ice", a, b) for a, b in al["ice"]]
        if al["calm"]:
            a, b = max(al["calm"], key=lambda r: r[1] - r[0])
            lines.append(a_["calm"].format(w=span(t, a, b, lang)))
            ditems.append(item("calm", a, b))
        if lines:
            msgs.append((False, "\n\n".join([a_["head_daily"]] + lines), {"kind": "daily", "title": a_["c_daily"], "items": ditems[:5]}))
    return msgs


def bar(frac, n=10):
    k = max(0, min(n, round(frac * n)))
    return "▰" * k + "▱" * (n - k)


def message(s, now, lang):
    lang = lang if lang in L else "tr"
    x = L[lang]
    f = lambda v, d=1: fmt(v, d, lang)
    r100 = lambda v: f(round(v / 100) * 100, 0)
    cap = s["kw"] / 2000 * 100
    month = x["month"][now.month - 1]
    rel = (x["times"].format(m=month, x=f(s["ratio"], 1)) if s["ratio"] >= 1.15
           else x["pct"].format(m=month, p=f(s["ratio"] * 100, 0)))
    conf_icon = ["🟢", "🟡", "🔴"][s["agree"]]
    rows = "\n".join(f"{hh}  {f(v):>5} m/s  {f(k, 0):>5} kW" for hh, v, k in s["next"])
    hash_ = "" if lang == "tr" else "#" + lang
    out = [
        f"🌬 <b>Ecosolaris</b> · {x['days'][now.weekday()]} {now.day} {x['mon'][now.month - 1]}, {now:%H}:00",
        "",
        f"<b>{x['now']}</b>: {f(s['hub'])} m/s, {x['dirs'][s['dir']]}",
        f"⚡ <b>{f(s['kw'], 0)} kW</b>  {bar(s['kw'] / 2000)}  {x['of_cap'].format(p=f(cap, 0))}",
        "",
        f"<b>{x['next3']}</b>",
        f"<pre>{rows}</pre>",
        f"<b>{x['h24']}</b>",
        f"📈 <b>{f(s['e'])} MWh</b> {x['expected']}",
        f"{conf_icon} {x['conf']}: {x['levels'][s['agree']]} ({f(math.floor(s['lo']), 0)}–{f(math.ceil(s['hi']), 0)} MWh)",
        f"📅 {rel}",
    ]
    if s["stop"]:
        out.append(f"⏸ {x['stop'].format(n=s['stop'])}")
    out += ["", x['proj'].format(d=f"{x['dfull'][now.weekday()]} ({now.day} {x['mon'][now.month - 1]})", lei=r100(s['td_lei']), lo=r100(s['td_llo']), hi=r100(s['td_lhi']), e=f(s['td_e']))]
    out += ["", f'<a href="{PANEL}{hash_}">{x["link"]} →</a>']
    return "\n".join(out)

CARD = {
    "tr": {"kicker": "RÜZGÂR · SAATLİK RAPOR", "stamp": "Rapor · {h}", "site": "Pojăreni · Vestas V90-2.0 MW · göbek 105 m",
           "now_l": "ŞİMDİ · {h}", "now_s": "{kw} kW  ·  kapasite %{cap}  ·  {dir}",
           "t1_l": "ÖNÜMÜZDEKİ 24 SAAT", "t1_s": "modeller {lo}–{hi} MWh",
           "t2_l": "{d} TAHMİNİ BRÜT SATIŞ", "t2_s": "{e} MWh · tahmin, tahsilat değil",
           "chart_l": "ÖNÜMÜZDEKİ 24 SAAT · TÜRBİN GÜCÜ (kW)",
           "foot_stop": "{n} saat rüzgâr 3,5 m/s altında, üretim yok", "foot_ok": "24 saatin tamamında üretim bekleniyor",
           "foot2": "ECMWF · ICON · GFS (Open-Meteo), saha düzeltmeli 105 m · fiyat {p} lei/kWh"},
    "en": {"kicker": "WIND · HOURLY REPORT", "stamp": "Report · {h}", "site": "Pojăreni · Vestas V90-2.0 MW · hub 105 m",
           "now_l": "NOW · {h}", "now_s": "{kw} kW  ·  {cap}% of capacity  ·  {dir}",
           "t1_l": "NEXT 24 HOURS", "t1_s": "models {lo}–{hi} MWh",
           "t2_l": "{d} PROJECTED GROSS SALES", "t2_s": "{e} MWh · projection, not revenue",
           "chart_l": "NEXT 24 HOURS · TURBINE POWER (kW)",
           "foot_stop": "{n} h with wind below 3.5 m/s, no output", "foot_ok": "Output expected in every hour",
           "foot2": "ECMWF · ICON · GFS (Open-Meteo), site-corrected 105 m · price {p} lei/kWh"},
    "ro": {"kicker": "VÂNT · RAPORT ORAR", "stamp": "Raport · {h}", "site": "Pojăreni · Vestas V90-2.0 MW · butuc 105 m",
           "now_l": "ACUM · {h}", "now_s": "{kw} kW  ·  {cap}% din capacitate  ·  {dir}",
           "t1_l": "URMĂTOARELE 24 DE ORE", "t1_s": "modele {lo}–{hi} MWh",
           "t2_l": "VÂNZĂRI BRUTE ESTIMATE, {d}", "t2_s": "{e} MWh · estimare, nu încasare",
           "chart_l": "URMĂTOARELE 24 DE ORE · PUTEREA TURBINEI (kW)",
           "foot_stop": "{n} ore cu vânt sub 3,5 m/s, fără producție", "foot_ok": "Producție estimată în fiecare oră",
           "foot2": "ECMWF · ICON · GFS (Open-Meteo), corectat pentru amplasament, 105 m · preț {p} lei/kWh"},
}


def card_data(s, now, lang, price):
    x, c = L[lang], CARD[lang]
    f = lambda v, d=1: fmt(v, d, lang)
    r100 = lambda v: f(round(v / 100) * 100, 0)
    month = x["month"][now.month - 1]
    rel = (x["times"].format(m=month, x=f(s["ratio"], 1)) if s["ratio"] >= 1.15
           else x["pct"].format(m=month, p=f(s["ratio"] * 100, 0)))
    return {
        "kicker": c["kicker"], "date": f"{now.day} {x['mon'][now.month - 1]} {now.year}", "stamp": c["stamp"].format(h=f"{now:%H:%M}"),
        "site": c["site"], "now_l": c["now_l"].format(h=f"{now:%H}:00"), "now_v": f"{f(s['hub'])} m/s",
        "now_s": c["now_s"].format(kw=f(s["kw"], 0), cap=f(s["kw"] / 20, 0), dir=x["dirs"][s["dir"]]), "now_kw": s["kw"],
        "t1_l": c["t1_l"], "t1_v": f(s["e"]), "t1_s": c["t1_s"].format(lo=f(math.floor(s["lo"]), 0), hi=f(math.ceil(s["hi"]), 0)),
        "t2_l": c["t2_l"].format(d=x["dfull"][now.weekday()].upper() if lang != "tr" else x["dfull"][now.weekday()].upper().replace("I", "I")),
        "t2_v": r100(s["td_lei"]), "t2_s": c["t2_s"].format(e=f(s["td_e"])),
        "agree": s["agree"], "conf": f"{x['conf']}: {x['levels'][s['agree']]}", "norm": rel,
        "chart_l": c["chart_l"], "kw": s["series"], "hours": s["hours"],
        "foot1": c["foot_stop"].format(n=s["stop"]) if s["stop"] else c["foot_ok"],
        "foot2": c["foot2"].format(p=fmt(price, 2, lang)),
    }


def get_card(s, now, lang, price):
    try:
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            import subprocess
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "matplotlib"], check=True, timeout=180)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import card
        return card.render(card_data(s, now, lang, price), lang)
    except Exception as e:
        print("Kart çizilemedi, düz metin gönderilecek:", e, file=sys.stderr)
        return None


def get_alert_card(spec, now, lang):
    try:
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            import subprocess
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "matplotlib"], check=True, timeout=180)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import card
        x = L[lang]
        d = dict(spec, stamp=f"{x['days'][now.weekday()]} {now.day} {x['mon'][now.month - 1]} · {now:%H:%M}", foot=A[lang]["foot"])
        return card.render_alert(d)
    except Exception as e:
        print("Uyarı kartı çizilemedi:", e, file=sys.stderr)
        return None


def caption(s, now, lang):
    x = L[lang]
    f = lambda v, d=1: fmt(v, d, lang)
    r100 = lambda v: f(round(v / 100) * 100, 0)
    hash_ = "" if lang == "tr" else "#" + lang
    conf_icon = ["🟢", "🟡", "🔴"][s["agree"]]
    return "\n".join([
        f"🌬 <b>Ecosolaris</b> · {x['days'][now.weekday()]} {now.day} {x['mon'][now.month - 1]}, {now:%H}:00",
        f"{x['now']}: {f(s['hub'])} m/s · {f(s['kw'], 0)} kW",
        f"{x['h24']}: {f(s['e'])} MWh · {conf_icon} {x['levels'][s['agree']]}",
        x['proj'].format(d=f"{x['dfull'][now.weekday()]}", lei=r100(s['td_lei']), lo=r100(s['td_llo']), hi=r100(s['td_lhi']), e=f(s['td_e'])),
        f'<a href="{PANEL}{hash_}">{x["link"]} →</a>',
    ])


def send_photo(token, chat, png, cap, quiet):
    import uuid
    bnd = uuid.uuid4().hex
    parts = []
    for k, v in {"chat_id": chat, "caption": cap, "parse_mode": "HTML", **({"disable_notification": "true"} if quiet else {})}.items():
        parts.append(f'--{bnd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{bnd}\r\nContent-Disposition: form-data; name="photo"; filename="ecosolaris.png"\r\nContent-Type: image/png\r\n\r\n'.encode() + png + b"\r\n")
    parts.append(f"--{bnd}--\r\n".encode())
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendPhoto", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={bnd}"})
    return json.load(urllib.request.urlopen(req, timeout=60)).get("ok", False)

def send(token, chat, text, quiet):
    fields = {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}
    if quiet:
        fields["disable_notification"] = "true"
    body = urllib.parse.urlencode(fields).encode()
    r = json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=body, timeout=30))
    return r.get("ok", False)


ALERT_LANGS_DEFAULT = ["tr", "ro"]  # dil yazılmamış alıcıya uyarılar Türkçe + Romence gider


def alert_langs(lang_given):
    return [lang_given] if lang_given else ALERT_LANGS_DEFAULT


def test_alerts(token, chats, now):
    """Elle başlatılan test: örnek uyarı kartlarını 'TEST' işaretiyle gönderir, saatlik raporu göndermez."""
    t = [(now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=k)).strftime("%Y-%m-%dT%H:00") for k in range(12)]
    for c in chats:
      chat, _, given = c.partition(":")
      for lang in alert_langs(given.lower()):
        lang = lang if lang in A else "tr"
        a_ = A[lang]; f = lambda v, lang=lang: fmt(v, 0, lang)
        items = [("cut", a_["h_cut"], span_card(t, 3, 6, lang), a_["b_cut"].format(v=f(26), g=f(33))),
                 ("ice", a_["h_ice"], span_card(t, 8, 11, lang), a_["b_ice"])]
        spec = {"kind": "cut", "title": "TEST · " + a_["c_now"], "items": items}
        png = get_alert_card(spec, now, lang)
        cap = "🧪 TEST · " + a_["head_now"]
        ok = send_photo(token, chat, png, cap, False) if png else send(token, chat, cap, False)
        print(("TEST OK " if ok else "TEST HATA ") + chat + " " + lang)
    return 0


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chats = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    if os.environ.get("TEST_ALERT", "").lower() in ("true", "1", "evet"):
        return test_alerts(token, chats, datetime.now(ZoneInfo("Europe/Chisinau")))
    price = float(os.environ.get("PRICE_LEI") or 2.50)
    h = json.load(urllib.request.urlopen(URL, timeout=30))["hourly"]
    now = datetime.now(ZoneInfo("Europe/Chisinau"))
    s = summary(h, now, price)
    quiet = now.hour >= 23 or now.hour < 7
    if not token or not chats:
        print(message(s, now, "tr"))
        try:
            wx = json.load(urllib.request.urlopen(WX_URL, timeout=30))["hourly"]
            for _, m, _spec in alert_messages(alerts(h, wx, now), now, "tr"):
                print("\n" + m)
        except Exception as e:
            print("Uyarı verisi alınamadı:", e, file=sys.stderr)
        print("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik; mesaj gönderilmedi.", file=sys.stderr)
        return 1
    try:
        wx = json.load(urllib.request.urlopen(WX_URL, timeout=30))["hourly"]
        al = alerts(h, wx, now)
    except Exception as e:  # uyarılar ana raporu asla durdurmasın
        print("Uyarı verisi alınamadı:", e, file=sys.stderr)
        al = None
    failed = 0
    for c in chats:
        chat, _, given = c.partition(":")
        given = given.lower()
        lang = given or "tr"
        lang = lang if lang in L else "tr"
        png = get_card(s, now, lang, price)
        ok = False
        if png:
            try:
                ok = send_photo(token, chat, png, caption(s, now, lang), quiet)
            except Exception as e:
                print("Fotoğraf gönderilemedi:", e, file=sys.stderr)
        if not ok:
            ok = send(token, chat, message(s, now, lang), quiet)
        print(("OK " if ok else "HATA ") + chat)
        failed += 0 if ok else 1
        for alang in (alert_langs(given) if al else []):
            for loud, msg, spec in alert_messages(al, now, alang):
                ok2 = False
                png = get_alert_card(spec, now, alang)
                if png:
                    try:
                        ok2 = send_photo(token, chat, png, msg.split("\n")[0], quiet and not loud)
                    except Exception as e:
                        print("Uyarı kartı gönderilemedi:", e, file=sys.stderr)
                if not ok2:
                    ok2 = send(token, chat, msg, quiet and not loud)
                print(("UYARI OK " if ok2 else "UYARI HATA ") + chat)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

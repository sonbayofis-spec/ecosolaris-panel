"""Ecosolaris saat başı Telegram raporu / hourly Telegram report / raport orar Telegram.

GitHub Actions her saat çalıştırır. Open-Meteo'dan ECMWF, ICON ve GFS tahminini çeker,
paneldeki hesabın aynısıyla V90-2.0 MW üretimini bulur ve Telegram'a gönderir.

Gizli değişkenler (Settings -> Secrets and variables -> Actions -> Secrets):
  TELEGRAM_BOT_TOKEN  BotFather'ın verdiği anahtar
  TELEGRAM_CHAT_ID    alıcı(lar): "123456" ya da dil ile "123456:tr,789012:en,-100345:ro"
                      dil verilmezse Türkçe gönderilir.
İsteğe bağlı değişken (Variables): PRICE_LEI (varsayılan 2.50)
"""
import json, math, os, sys, urllib.parse, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

URL = ("https://api.open-meteo.com/v1/forecast?latitude=46.8932&longitude=28.6946"
       "&hourly=wind_speed_10m,wind_speed_80m,wind_speed_100m,wind_speed_120m,wind_speed_180m,wind_direction_100m"
       "&wind_speed_unit=ms&timezone=Europe%2FChisinau&forecast_days=3"
       "&models=ecmwf_ifs025,icon_seamless,gfs_seamless")
PANEL = "https://sonbayofis-spec.github.io/ecosolaris-panel/"
SITE, RHO, NET, HUB, R = 1.14, 1.198, 0.92, 105, 45
NORM = [17.25, 16.48, 15.14, 14.46, 10.69, 9.44, 8.73, 8.84, 10.8, 12.6, 13.14, 16.2]
PC = [(3, 0), (3.5, 42), (4, 93), (4.5, 145), (5, 211), (5.5, 284), (6, 391), (6.5, 492), (7, 601), (7.5, 732), (8, 885),
      (8.5, 1088), (9, 1247), (9.5, 1430), (10, 1594), (10.5, 1743), (11, 1861), (11.5, 1948), (12, 1993), (12.5, 2000), (25, 2000)]
MODELS = {"e": "ecmwf_ifs025", "i": "icon_seamless", "g": "gfs_seamless"}
LEVELS = [("10m", 10), ("80m", 80), ("100m", 100), ("120m", 120), ("180m", 180)]
SLICES = [(z, math.sqrt(R * R - (z - HUB) ** 2)) for z in range(60, 151, 5) if R * R - (z - HUB) ** 2 > 0]
DENS = (RHO / 1.225) ** (1 / 3)

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
        hub.append(u(HUB)); kw.append(pw((s / w) ** (1 / 3) * DENS))
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
        f"{conf_icon} {x['conf']}: {x['levels'][s['agree']]} ({f(s['lo'], 0)}–{f(s['hi'], 0)} MWh)",
        f"📅 {rel}",
    ]
    if s["stop"]:
        out.append(f"⏸ {x['stop'].format(n=s['stop'])}")
    out += ["", x['proj'].format(d=f"{x['dfull'][now.weekday()]} ({now.day} {x['mon'][now.month - 1]})", lei=r100(s['td_lei']), lo=r100(s['td_llo']), hi=r100(s['td_lhi']), e=f(s['td_e']))]
    out += ["", f'<a href="{PANEL}{hash_}">{x["link"]} →</a>']
    return "\n".join(out)

def send(token, chat, text, quiet):
    fields = {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}
    if quiet:
        fields["disable_notification"] = "true"
    body = urllib.parse.urlencode(fields).encode()
    r = json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=body, timeout=30))
    return r.get("ok", False)


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chats = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    price = float(os.environ.get("PRICE_LEI") or 2.50)
    h = json.load(urllib.request.urlopen(URL, timeout=30))["hourly"]
    now = datetime.now(ZoneInfo("Europe/Chisinau"))
    s = summary(h, now, price)
    quiet = now.hour >= 23 or now.hour < 7
    if not token or not chats:
        print(message(s, now, "tr"))
        print("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik; mesaj gönderilmedi.", file=sys.stderr)
        return 1
    failed = 0
    for c in chats:
        chat, _, lang = c.partition(":")
        text = message(s, now, (lang or "tr").lower())
        ok = send(token, chat, text, quiet)
        print(("OK " if ok else "HATA ") + chat)
        failed += 0 if ok else 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

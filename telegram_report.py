"""Ecosolaris saat başı Telegram raporu / hourly Telegram report / raport orar Telegram.

GitHub Actions her saat çalıştırır. Open-Meteo'dan ECMWF, ICON ve GFS tahminini çeker,
paneldeki hesabın aynısıyla V90-2.0 MW üretimini bulur ve Telegram'a gönderir.

Gizli değişkenler (Settings -> Secrets and variables -> Actions -> Secrets):
  TELEGRAM_BOT_TOKEN  BotFather'ın verdiği anahtar
  TELEGRAM_CHAT_ID    alıcı(lar): "123456" ya da dil ile "123456:tr,789012:en,-100345:ro"
                      dil "all" ise tek mesajda üç dil gider (ortak grup için).
İsteğe bağlı değişken (Variables): PRICE_LEI (varsayılan 1.42)
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
           "dirs": ["K", "KD", "D", "GD", "G", "GB", "B", "KB"],
           "now": "Şimdi", "next3": "Sonraki 3 saat", "h24": "24 saat", "models": "modeller",
           "norm": "{m} normaline göre %{p}", "agree": ["modeller uyumlu", "modeller kısmen ayrışıyor", "modeller ayrışıyor, belirsiz"],
           "stop": "Üretimsiz saat (24 saatte): {n}", "link": "Paneli aç", "dec": ","},
    "en": {"mon": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
           "month": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
           "dirs": ["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
           "now": "Now", "next3": "Next 3 hours", "h24": "Next 24 h", "models": "models",
           "norm": "{p}% of a normal {m} day", "agree": ["models agree", "models partly diverge", "models diverge, uncertain"],
           "stop": "Hours without output (next 24 h): {n}", "link": "Open panel", "dec": "."},
    "ro": {"mon": ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct", "noi", "dec"],
           "month": ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie"],
           "dirs": ["N", "NE", "E", "SE", "S", "SV", "V", "NV"],
           "now": "Acum", "next3": "Următoarele 3 ore", "h24": "Următoarele 24 h", "models": "modele",
           "norm": "{p}% față de o zi normală de {m}", "agree": ["modelele concordă", "modelele diferă parțial", "modelele diferă, incert"],
           "stop": "Ore fără producție (24 h): {n}", "link": "Deschide panoul", "dec": ","},
}


def pw(v):
    if not v or v < 3 or v > 25:
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
        "i0": i0, "hub": hub[i0], "kw": kw[i0], "next": [hub[j] for j in range(i0 + 1, min(i0 + 4, len(t)))],
        "e": e24["e"], "lo": lo, "hi": hi, "lei": e24["e"] * 1000 * price,
        "pct": e24["e"] / NORM[now.month - 1] * 100, "agree": 0 if spread < 0.3 else 1 if spread < 0.6 else 2,
        "dir": round((h[f"wind_direction_100m_{MODELS['e']}"][i0] % 360) / 45) % 8,
        "stop": sum(1 for j in range(i0, i1) if kw[j] <= 0),
    }


def text_for(s, now, lang, head=True):
    x = L[lang]
    f = lambda v, d=1: fmt(v, d, lang)
    out = []
    if head:
        out.append(f"<b>Ecosolaris · {now.day} {x['mon'][now.month - 1]} {now:%H}:00</b>")
    out += [
        f"{x['now']}: <b>{f(s['hub'])} m/s</b> ({x['dirs'][s['dir']]}) → <b>{f(s['kw'], 0)} kW</b>",
        f"{x['next3']}: {' / '.join(f(v) for v in s['next'])} m/s",
        f"{x['h24']}: <b>{f(s['e'])} MWh</b> ({x['models']} {f(s['lo'])}–{f(s['hi'])}) · ≈{f(s['lei'], 0)} lei",
        x["norm"].format(m=x["month"][now.month - 1], p=f(s["pct"], 0)) + " · " + x["agree"][s["agree"]],
    ]
    if s["stop"]:
        out.append(x["stop"].format(n=s["stop"]))
    return out


def message(s, now, lang):
    if lang == "all":
        parts = [f"<b>Ecosolaris · {now.day:02d}.{now.month:02d} {now:%H}:00</b>"]
        for lg, flag in (("tr", "🇹🇷"), ("en", "🇬🇧"), ("ro", "🇲🇩")):
            parts.append("")
            parts.append(flag)
            parts += text_for(s, now, lg, head=False)
        parts += ["", f'<a href="{PANEL}">Panel</a>']
        return "\n".join(parts)
    lang = lang if lang in L else "tr"
    hash_ = "" if lang == "tr" else "#" + lang
    return "\n".join(text_for(s, now, lang) + [f'<a href="{PANEL}{hash_}">{L[lang]["link"]}</a>'])


def send(token, chat, text, quiet):
    body = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true",
                                   "disable_notification": "true" if quiet else "false"}).encode()
    r = json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=body, timeout=30))
    return r.get("ok", False)


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chats = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    price = float(os.environ.get("PRICE_LEI") or 1.42)
    h = json.load(urllib.request.urlopen(URL, timeout=30))["hourly"]
    now = datetime.now(ZoneInfo("Europe/Chisinau"))
    s = summary(h, now, price)
    quiet = now.hour >= 23 or now.hour < 7
    if not token or not chats:
        print(message(s, now, "all"))
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

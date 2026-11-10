"""BESS "yarının planı" Telegram kartı. bess.yml, bess.py'den sonra çalıştırır.

Yarının planı ilk kez hesaplandığında (sabah, teslim programı bildirilmeden önce) günde BİR kart gönderir.
Hangi gün için gönderildiği data/bess/sent.json'da tutulur; aynı gün için aynı kartı ikinci kez göndermez.
İlk kart fiyat tahminiyle gittiyse ve OPEM fiyatı açıklanınca ek gelir belirgin değiştiyse (en az %20 ve 1.000 lei)
bir kez "plan güncellendi" kartı gönderir.
BESS_TEST=true ise kayıt tutmadan hemen gönderir (deneme).

Ortam değişkenleri telegram_report.py ile aynı: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID ("id" ya da "id:dil").
"""
import json, os, sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import telegram_report as tr

TZ = ZoneInfo("Europe/Chisinau")
SENT = os.path.join("data", "bess", "sent.json")

T = {
    "tr": {"upd": "BESS · PLAN GÜNCELLENDİ", "updcap": "OPEM fiyatı açıklandı; sabahki tahmin {o} lei idi.", "upd_t2s": "sabahki tahmin {o} lei", "kicker": "BESS · YARININ PLANI", "today": "BESS · BUGÜNÜN PLANI", "t1": "BATARYADAN SATIŞ", "t1s": "şarj {c} MWh · kayıp {l} MWh",
           "t2": "BEKLENEN EK GELİR", "t2s": "batarya olmadan {b} lei", "charge": "Şarj saatleri", "sell": "Satış saatleri",
           "peak": "Şebekeye en yüksek teslim", "src": "Plan fiyatı", "opem": "OPEM, açıklanan", "est": "tahmini fiyat, son 7 gün",
           "none": "yok", "chart": "SAATLİK PLAN (MW)", "leg": ["Türbinden şebekeye", "Bataryaya şarj", "Bataryadan şebekeye"],
           "foot1": "Teslim programı panelde: BESS bölümü → “Teslim programını indir”",
           "foot2": "Plan gösterimidir. Fiyat: OPEM − 15 EUR/MWh · kapasite %{u}, verim %{r} varsayım",
           "cap": "<b>BESS planı, {d}</b>\nŞarj {ch} · satış {se}\nEk gelir <b>{x} lei</b> ({s})", "nocap": "<b>BESS planı, {d}</b>\nFiyat farkı kaydırmaya değmiyor; batarya beklemede."},
    "en": {"upd": "BESS · PLAN UPDATED", "updcap": "OPEM published its prices; this morning's estimate was {o} lei.", "upd_t2s": "morning estimate {o} lei", "kicker": "BESS · TOMORROW'S PLAN", "today": "BESS · TODAY'S PLAN", "t1": "SOLD FROM BATTERY", "t1s": "charged {c} MWh · losses {l} MWh",
           "t2": "EXPECTED EXTRA INCOME", "t2s": "without battery {b} lei", "charge": "Charge hours", "sell": "Sale hours",
           "peak": "Peak delivery to grid", "src": "Plan price", "opem": "OPEM, published", "est": "estimated price, last 7 days",
           "none": "none", "chart": "HOURLY PLAN (MW)", "leg": ["Turbine to grid", "Charging battery", "Battery to grid"],
           "foot1": "Delivery schedule on the panel: BESS section → “Download delivery schedule”",
           "foot2": "Plan only. Price: OPEM − 15 EUR/MWh · capacity {u}%, efficiency {r}% assumed",
           "cap": "<b>BESS plan, {d}</b>\nCharge {ch} · sell {se}\nExtra income <b>{x} lei</b> ({s})", "nocap": "<b>BESS plan, {d}</b>\nPrice spread not worth shifting; battery idle."},
    "ro": {"upd": "BESS · PLAN ACTUALIZAT", "updcap": "OPEM a publicat prețurile; estimarea de dimineață era {o} lei.", "upd_t2s": "estimarea de dimineață {o} lei", "kicker": "BESS · PLANUL DE MÂINE", "today": "BESS · PLANUL DE AZI", "t1": "VÂNDUT DIN BATERIE", "t1s": "încărcare {c} MWh · pierderi {l} MWh",
           "t2": "VENIT SUPLIMENTAR ESTIMAT", "t2s": "fără baterie {b} lei", "charge": "Ore de încărcare", "sell": "Ore de vânzare",
           "peak": "Livrare maximă în rețea", "src": "Prețul din plan", "opem": "OPEM, publicat", "est": "preț estimat, ultimele 7 zile",
           "none": "nu", "chart": "PLAN ORAR (MW)", "leg": ["Din turbină în rețea", "Încărcarea bateriei", "Din baterie în rețea"],
           "foot1": "Graficul de livrare în panou: secțiunea BESS → „Descarcă graficul de livrare”",
           "foot2": "Doar plan. Preț: OPEM − 15 EUR/MWh · capacitate {u}%, randament {r}% ipoteze",
           "cap": "<b>Plan BESS, {d}</b>\nÎncărcare {ch} · vânzare {se}\nVenit suplimentar <b>{x} lei</b> ({s})", "nocap": "<b>Plan BESS, {d}</b>\nDiferența de preț nu merită mutarea; bateria în așteptare."},
}


def spans(vals, lang, thr=0.05):
    """0.05 MWh üstü saatleri aralıklara çevirir: '00–07, 10–16'."""
    out, a = [], None
    for h, v in enumerate(list(vals) + [0]):
        if v > thr and a is None:
            a = h
        elif v <= thr and a is not None:
            out.append(f"{a:02d}–{h % 24:02d}")
            a = None
    return ", ".join(out) or T[lang]["none"]


def day_label(day, lang):
    d = datetime.fromisoformat(day)
    return f"{tr.L[lang]['dfull'][d.weekday()]}, {d.day} {tr.L[lang]['mon'][d.month - 1]}"


def card_data(plan, params, now, lang, is_today=False, prev=None, update=False):
    t = T[lang]
    f = lambda x, n: tr.fmt(x, n, lang)
    ch, di = sum(plan["charge"]), sum(plan["discharge"])
    sign = lambda v: ("+" if v > 0 else "") + f(v, 0)
    return {"kicker": t["upd"] if update else t["today" if is_today else "kicker"], "date": day_label(plan["date"], lang), "stamp": now.strftime("%H:%M"),
            "t1_l": t["t1"], "t1_v": f(di, 2), "t1_s": t["t1s"].format(c=f(ch, 2), l=f(ch - di, 2)),
            "t2_l": t["t2"], "t2_v": ("+" if plan["extra_mdl"] > 0 else "") + f(plan["extra_mdl"], 0), "t2_s": t["upd_t2s"].format(o=sign(prev)) if update and prev is not None else t["t2s"].format(b=f(plan["base_mdl"], 0)),
            "rows": [(t["charge"], spans(plan["charge"], lang), "acc"), (t["sell"], spans(plan["discharge"], lang), "blue"),
                     (t["peak"], f(plan["peak_mw"], 2) + " MW", "mid"), (t["src"], t[plan["price_src"]], "muted")],
            "chart_l": t["chart"], "wind": plan["wind"], "charge": plan["charge"], "discharge": plan["discharge"],
            "limit": params.get("limit_mw", 3.96), "leg": t["leg"], "foot1": t["foot1"],
            "foot2": t["foot2"].format(u=round(params.get("usable", 0) * 100), r=round(params.get("rte", 0) * 100))}


def caption(plan, lang, prev=None, update=False):
    t = T[lang]
    extra = ("\n" + t["updcap"].format(o=("+" if prev > 0 else "") + tr.fmt(prev, 0, lang))) if update and prev is not None else ""
    if sum(plan["discharge"]) < 0.05:
        return t["nocap"].format(d=day_label(plan["date"], lang)) + extra + f"\n{tr.PANEL}"
    return t["cap"].format(d=day_label(plan["date"], lang), ch=spans(plan["charge"], lang), se=spans(plan["discharge"], lang),
                           x=("+" if plan["extra_mdl"] > 0 else "") + tr.fmt(plan["extra_mdl"], 0, lang), s=t[plan["price_src"]]) + extra + f"\n{tr.PANEL}"


def render(plan, params, now, lang, is_today=False, prev=None, update=False):
    try:
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            import subprocess
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "matplotlib"], check=True, timeout=180)
        import card
        return card.render_bess(card_data(plan, params, now, lang, is_today, prev, update))
    except Exception as e:
        print("BESS kartı çizilemedi, düz metin gönderilecek:", e, file=sys.stderr)
        return None


def decide(sent, day, plan):
    """Gönderim kararı: 'first' (o gün için ilk kart), 'update' (tahminle gitmişti, OPEM belirgin değiştirdi),
    'mark' (OPEM geldi ama fark küçük; yalnızca kayda geçir) ya da None."""
    if sent.get("day") != day:
        return "first"
    if sent.get("price_src") == "est" and plan["price_src"] == "opem":
        old = sent.get("extra_mdl")
        if old is None or abs(plan["extra_mdl"] - old) >= max(1000, 0.2 * abs(old)):
            return "update"
        return "mark"
    return None


def main():
    now = datetime.now(TZ)
    test = os.environ.get("BESS_TEST", "").lower() in ("true", "1", "evet")
    try:
        with open("bess.json", encoding="utf-8") as f:
            b = json.load(f)
    except (OSError, ValueError):
        print("bess.json yok; kart gönderilmedi.")
        return 0
    tomorrow = (now.date() + timedelta(days=1)).isoformat()
    day = tomorrow if tomorrow in b.get("days", {}) else (now.date().isoformat() if test else None)
    plan = b.get("days", {}).get(day) if day else None
    if not plan:
        print("Yarının planı henüz yok; kart gönderilmedi.")
        return 0
    try:
        with open(SENT, encoding="utf-8") as f:
            sent = json.load(f)
    except (OSError, ValueError):
        sent = {}
    what = "first" if test else decide(sent, day, plan)
    rec = {"day": day, "sent": now.strftime("%Y-%m-%dT%H:%M"), "price_src": plan["price_src"], "extra_mdl": plan["extra_mdl"]}
    if what is None:
        print(f"{day} planı zaten gönderildi.")
        return 0
    if what == "mark":
        with open(SENT, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        print(f"{day}: OPEM fiyatı geldi, fark küçük; güncelleme kartı gönderilmedi.")
        return 0
    update, prev = what == "update", sent.get("extra_mdl")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chats = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    if not token or not chats:
        print(caption(plan, "tr"))
        print("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik; kart gönderilmedi.", file=sys.stderr)
        return 0
    quiet = now.hour < 7
    okn = 0
    for c in chats:
        chat, _, lang = c.partition(":")
        lang = lang.lower() if lang.lower() in T else "tr"
        png, ok = render(plan, b.get("params", {}), now, lang, day != tomorrow, prev, update), False
        if png:
            try:
                ok = tr.send_photo(token, chat, png, caption(plan, lang, prev, update), quiet)
            except Exception as e:
                print("BESS kartı gönderilemedi:", e, file=sys.stderr)
        if not ok:
            try:
                ok = tr.send(token, chat, caption(plan, lang, prev, update), quiet)
            except Exception as e:
                print("BESS mesajı gönderilemedi:", e, file=sys.stderr)
        print(("OK " if ok else "HATA ") + chat)
        okn += 1 if ok else 0
    if okn and not test:
        os.makedirs(os.path.dirname(SENT), exist_ok=True)
        with open(SENT, "w", encoding="utf-8") as f:
            json.dump(rec, f)
    return 0 if okn else 1


if __name__ == "__main__":
    sys.exit(main())

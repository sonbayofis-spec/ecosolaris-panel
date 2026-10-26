"""İş akışı izleme.

`izleme.yml` bir iş akışı tamamlandığında bunu çalıştırır. İş akışı başarısız olduysa ve bir önceki çalışması
başarılıydıysa Telegram'a bir kez uyarı gönderir; sonra düzelince bir kez "düzeldi" mesajı atar.
Aynı sorun için her saat tekrar uyarı gelmez.

Ortam: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (ilk alıcıya gider), GITHUB_TOKEN, GITHUB_REPOSITORY,
RUN_ID, WORKFLOW_ID, WORKFLOW_NAME, CONCLUSION, RUN_URL. MONITOR_DRY=1: göndermeden yazdırır.
"""
import json, os, sys, urllib.parse, urllib.request

API = "https://api.github.com"


def previous_conclusion(runs, run_id):
    """runs: GitHub'ın verdiği (yeniden eskiye) tamamlanmış çalışmalar. run_id'den önceki başarı/başarısızlık sonucu."""
    ids = [r.get("id") for r in runs]
    if run_id not in ids:
        return None
    for r in runs[ids.index(run_id) + 1:]:
        if r.get("conclusion") in ("success", "failure"):
            return r["conclusion"]
    return None


def decide(conclusion, previous):
    if conclusion == "failure" and previous != "failure":
        return "fail"
    if conclusion == "success" and previous == "failure":
        return "ok"
    return None


def text(kind, name, url):
    if kind == "fail":
        return (f"⚠️ <b>Ecosolaris sistem uyarısı</b>\n«{name}» iş akışı başarısız oldu.\nAyrıntı: {url}\n"
                "Veri sağlayıcıda geçici bir sorun olabilir. Düzelirse haber vereceğim.")
    return f"✅ <b>Ecosolaris</b>: «{name}» yeniden başarıyla çalıştı."


def api_get(path, token):
    req = urllib.request.Request(API + path, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                                      "User-Agent": "ecosolaris-panel"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def send(token, chat, msg):
    body = urllib.parse.urlencode({"chat_id": chat, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
    return json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=body, timeout=30)).get("ok", False)


def main():
    e = os.environ.get
    run_id, conclusion, name, url = int(e("RUN_ID", "0")), e("CONCLUSION", ""), e("WORKFLOW_NAME", "?"), e("RUN_URL", "")
    runs = api_get(f"/repos/{e('GITHUB_REPOSITORY')}/actions/workflows/{e('WORKFLOW_ID')}/runs?status=completed&per_page=15",
                   e("GITHUB_TOKEN", ""))["workflow_runs"]
    kind = decide(conclusion, previous_conclusion(runs, run_id))
    if not kind:
        print(f"{name}: bildirim gerekmiyor ({conclusion}).")
        return 0
    msg = text(kind, name, url)
    if e("MONITOR_DRY"):
        print(msg)
        return 0
    token = e("TELEGRAM_BOT_TOKEN", "").strip()
    chats = [c.strip() for c in e("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    if not token or not chats:
        print("Telegram anahtarı yok; bildirim gönderilmedi.", file=sys.stderr)
        return 0
    ok = send(token, chats[0].partition(":")[0], msg)
    print("gönderildi" if ok else "GÖNDERİLEMEDİ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

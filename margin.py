"""Trader payı: OPEM fiyatından düşülen tutar (sözleşme Ek 4). Tek kaynak; bess.py ve telegram_report.py buradan okur.
Panelde (index.html) aynı değer varsayılandır, kullanıcı kendi tarayıcısında değiştirebilir (eco_spread)."""
import json, os

SPREAD_EUR = 15.0        # EUR/MWh
EUR_MDL_FALLBACK = 20.0  # BNM kuru okunamazsa


def eur_mdl(root=None):
    """Güncel EUR/MDL kuru: bess.py'nin yazdığı bess.json'dan (BNM); okunamazsa yedek değer."""
    root = root or os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(root, "bess.json"), encoding="utf-8") as f:
            v = float(json.load(f)["params"]["eur_mdl"])
        return v if 15 < v < 30 else EUR_MDL_FALLBACK
    except Exception:
        return EUR_MDL_FALLBACK


def spread_mdl(root=None):
    """Trader payı, MDL/MWh."""
    return SPREAD_EUR * eur_mdl(root)

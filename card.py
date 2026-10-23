"""Telegram raporu için görsel kart (PNG). telegram_report.py kullanır."""
import io


def render(d, lang="tr"):
    """d: başlık, saat ve sayı alanları + 'kw' (24 değer) ve 'hours' (24 etiket). PNG bytes döner."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    BG, PANEL, FG, MUTED, LINE = "#0B1F1C", "#12302A", "#E6F2EF", "#8FAAA4", "#1F3C36"
    ACC, MID, BAD = "#45C7AB", "#E4A64F", "#E88A75"
    plt.rcParams["font.family"] = "DejaVu Sans"
    W, H = 10.0, 12.5
    fig = plt.figure(figsize=(W, H), dpi=100, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")

    def card(x, y, w, h):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.18",
                                    fc=PANEL, ec=LINE, lw=1.2))

    def txt(x, y, s, size, color=FG, weight="normal", ha="left", va="baseline"):
        ax.text(x, y, s, fontsize=size, color=color, fontweight=weight, ha=ha, va=va)

    def big(x, y, val, unit):
        t = ax.text(x, y, val, fontsize=34, color=FG, fontweight="bold")
        fig.canvas.draw()
        bb = t.get_window_extent().transformed(ax.transData.inverted())
        ax.text(bb.x1 + 0.12, y, unit, fontsize=15, color=MUTED)

    # başlık
    txt(0.6, 11.75, "ECOSOLARIS", 30, weight="bold")
    txt(0.62, 11.35, d["kicker"], 12.5, ACC, "bold")
    txt(9.4, 11.8, d["date"], 15, ha="right")
    txt(9.4, 11.4, d["stamp"], 12.5, MUTED, ha="right")
    ax.plot([0.6, 9.4], [11.05, 11.05], color=LINE, lw=1.2)
    txt(0.6, 10.62, d["site"], 12.5, MUTED)

    # şimdi
    txt(0.6, 10.05, d["now_l"], 13, MUTED, "bold")
    txt(0.55, 8.75, d["now_v"], 64, weight="bold")
    txt(0.6, 8.25, d["now_s"], 15, MUTED)
    # güç çubuğu
    frac = max(0.0, min(1.0, d["now_kw"] / 2000))
    ax.add_patch(FancyBboxPatch((0.6, 7.75), 8.8, 0.16, boxstyle="round,pad=0,rounding_size=0.08", fc=LINE, ec="none"))
    if frac > 0.005:
        ax.add_patch(FancyBboxPatch((0.6, 7.75), 8.8 * frac, 0.16, boxstyle="round,pad=0,rounding_size=0.08", fc=ACC, ec="none"))

    # iki kutu
    card(0.6, 5.6, 4.25, 1.85); card(5.15, 5.6, 4.25, 1.85)
    txt(0.9, 7.0, d["t1_l"], 11.5, MUTED, "bold")
    big(0.9, 6.15, d["t1_v"], "MWh")
    txt(0.9, 5.82, d["t1_s"], 11.5, MUTED)
    txt(5.45, 7.0, d["t2_l"], 11.5, MUTED, "bold")
    big(5.45, 6.15, d["t2_v"], "lei")
    txt(5.45, 5.82, d["t2_s"], 11.5, MUTED)

    # güvenilirlik satırı
    col = [ACC, MID, BAD][d["agree"]]
    ax.add_patch(plt.Circle((0.78, 5.12), 0.11, color=col))
    txt(1.05, 5.04, d["conf"], 14, col, "bold")
    txt(9.4, 5.04, d["norm"], 13, MUTED, ha="right")

    # grafik
    card(0.6, 1.25, 8.8, 3.35)
    txt(0.9, 4.2, d["chart_l"], 11.5, MUTED, "bold")
    cx = fig.add_axes([0.105, 0.135, 0.80, 0.18], facecolor=PANEL)
    kw = d["kw"]; n = len(kw); xs = list(range(n))
    cx.fill_between(xs, kw, color=ACC, alpha=0.28, linewidth=0)
    cx.plot(xs, kw, color=ACC, lw=2.4)
    cx.set_ylim(0, 2000); cx.set_xlim(0, n - 1)
    cx.set_yticks([0, 1000, 2000]); cx.set_yticklabels(["0", "1000", "2000 kW"], color=MUTED, fontsize=10)
    step = 3
    cx.set_xticks(xs[::step]); cx.set_xticklabels(d["hours"][::step], color=MUTED, fontsize=10)
    for sp in cx.spines.values():
        sp.set_visible(False)
    cx.tick_params(length=0)
    cx.grid(axis="y", color=LINE, lw=1)

    # alt bilgi
    txt(0.6, 0.78, d["foot1"], 12, FG)
    txt(0.6, 0.38, d["foot2"], 10.5, MUTED)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, dpi=100)
    plt.close(fig)
    return buf.getvalue()


def render_alert(d):
    """Uyarı kartı. d: kind ('storm'|'ice'|'daily'), title, stamp, items[(icon_kind, başlık, zaman, açıklama)], foot."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    import textwrap

    BG, PANEL, FG, MUTED, LINE = "#0B1F1C", "#12302A", "#E6F2EF", "#8FAAA4", "#1F3C36"
    COL = {"storm": "#E4A64F", "cut": "#E88A75", "ice": "#86B6F2", "calm": "#45C7AB", "daily": "#45C7AB"}
    SYM = {"storm": "\u2191", "cut": "!", "ice": "\u2744", "calm": "\u2713"}
    plt.rcParams["font.family"] = "DejaVu Sans"
    items = d["items"]
    W = 10.0
    H = 2.3 + 2.6 * len(items) + 0.9
    fig = plt.figure(figsize=(W, H), dpi=100, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    accent = COL[d["kind"]]
    ax.add_patch(FancyBboxPatch((0, H - 0.22), W, 0.22, boxstyle="square,pad=0", fc=accent, ec="none"))
    ax.text(0.6, H - 1.05, "ECOSOLARIS", fontsize=24, color=FG, fontweight="bold")
    ax.text(0.62, H - 1.5, d["title"], fontsize=13, color=accent, fontweight="bold")
    ax.text(9.4, H - 1.0, d["stamp"], fontsize=13, color=MUTED, ha="right")
    ax.plot([0.6, 9.4], [H - 1.9, H - 1.9], color=LINE, lw=1.2)
    y = H - 2.2
    for kind, head, when, body in items:
        c = COL[kind]
        ax.add_patch(FancyBboxPatch((0.6, y - 2.3), 8.8, 2.3, boxstyle="round,pad=0,rounding_size=0.18", fc=PANEL, ec=LINE, lw=1.2))
        ax.add_patch(FancyBboxPatch((0.6, y - 2.3), 0.12, 2.3, boxstyle="square,pad=0", fc=c, ec="none"))
        ax.add_patch(plt.Circle((1.35, y - 0.55), 0.3, color=c))
        ax.text(1.35, y - 0.55, SYM[kind], fontsize=17, color=BG, fontweight="bold", ha="center", va="center")
        ax.text(1.9, y - 0.48, head, fontsize=16, color=FG, fontweight="bold", va="center")
        ax.text(1.9, y - 0.98, when, fontsize=13, color=c, fontweight="bold", va="center")
        lines = textwrap.wrap(body, 84)[:3]
        for k, ln in enumerate(lines):
            ax.text(1.9, y - 1.38 - 0.3 * k, ln, fontsize=11.5, color=MUTED, va="center")
        y -= 2.6
    ax.text(0.6, 0.45, d["foot"], fontsize=10.5, color=MUTED)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, dpi=100)
    plt.close(fig)
    return buf.getvalue()

"""Generate portfolio cover images for honest-backtest (GitHub-dark dev aesthetic).

Pure Pillow, no browser dependency. Outputs 1200x630 PNGs (Malt / LinkedIn / OG).
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
W, H = 1200, 630

# GitHub-dark palette
BG = (13, 17, 23)
PANEL = (22, 27, 34)
BORDER = (48, 54, 61)
WHITE = (230, 237, 243)
GRAY = (139, 148, 158)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
BLUE = (88, 166, 255)

F = "C:/Windows/Fonts/"
def font(name, size): return ImageFont.truetype(F + name, size)

bold = lambda s: font("arialbd.ttf", s)
reg = lambda s: font("arial.ttf", s)
mono = lambda s: font("consola.ttf", s)


def pill(d, x, y, text, fnt, fg, bg, pad=16):
    w = d.textlength(text, font=fnt)
    h = fnt.size
    d.rounded_rectangle([x, y, x + w + pad * 2, y + h + pad], radius=(h + pad) // 2,
                        fill=bg, outline=BORDER, width=1)
    d.text((x + pad, y + pad // 2), text, font=fnt, fill=fg)
    return x + w + pad * 2 + 12


def cover():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # left accent bar
    d.rectangle([0, 0, 8, H], fill=GREEN)
    # prompt tag
    d.text((64, 60), "$ honest-backtest", font=mono(24), fill=GREEN)
    # title
    d.text((62, 110), "honest-backtest", font=bold(76), fill=WHITE)
    # tagline (two lines)
    d.text((64, 210), "Prove a trading edge survives real costs", font=reg(30), fill=GRAY)
    d.text((64, 250), "out-of-sample — or kill it.", font=reg(30), fill=GRAY)
    # big stat
    d.text((64, 332), "8", font=bold(96), fill=WHITE)
    d.text((150, 360), "hypotheses tested", font=reg(30), fill=GRAY)
    d.text((64, 332 + 0, ), "", font=reg(10), fill=GRAY)
    d.text((430, 332), "0", font=bold(96), fill=RED)
    d.text((516, 360), "survived out-of-sample", font=reg(30), fill=GRAY)
    # pills
    x = 64
    for label in ("Python", "Databento", "pytest", "walk-forward OOS", "CME futures"):
        x = pill(d, x, 478, label, mono(22), BLUE, PANEL)
    # footer url
    d.text((64, 560), "github.com/Makeph/honest-backtest", font=mono(26), fill=GRAY)
    img.save(HERE / "cover.png")
    print("wrote", HERE / "cover.png")


def verdict():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # terminal window
    m = 70
    d.rounded_rectangle([m, m, W - m, H - m], radius=14, fill=PANEL, outline=BORDER, width=1)
    # title bar
    d.rounded_rectangle([m, m, W - m, m + 46], radius=14, fill=(33, 38, 45))
    d.rectangle([m, m + 30, W - m, m + 46], fill=(33, 38, 45))
    for i, c in enumerate((RED, (245, 191, 79), GREEN)):
        d.ellipse([m + 22 + i * 26, m + 16, m + 36 + i * 26, m + 30], fill=c)
    d.text((m + 120, m + 14), "validate.py — honest edge verdict", font=mono(20), fill=GRAY)

    x, y = m + 36, m + 74
    lh = 37
    lines = [
        (GREEN, "$ honest-backtest mr MES 5m 1y"),
        (GRAY,  ""),
        (WHITE, "== HONEST EDGE VERDICT: MES session mean-reversion =="),
        (GRAY,  "   1-year Databento data  |  8-fold walk-forward"),
        (GRAY,  ""),
        (WHITE, "   OUT-OF-SAMPLE:"),
        (GRAY,  "     trades      184"),
        (GRAY,  "     net/trade   $-5.76"),
        (GRAY,  "     PF          0.84      win 52%"),
    ]
    for color, text in lines:
        d.text((x, y), text, font=mono(26), fill=color)
        y += lh
    d.text((x, y), "   >>> ", font=mono(30), fill=GRAY)
    d.text((x + d.textlength("   >>> ", font=mono(30)), y), "NO EDGE (rejected)",
           font=font("consolab.ttf" if (Path(F) / "consolab.ttf").exists() else "arialbd.ttf", 30),
           fill=RED)
    y += lh + 8
    d.text((x, y), "   The discipline to say no is the product.", font=mono(22), fill=GREEN)
    img.save(HERE / "verdict.png")
    print("wrote", HERE / "verdict.png")


if __name__ == "__main__":
    cover()
    verdict()

"""Elemental posters: the old promo set rebranded, plus new formats. Writes HTML pages
(rendered at 2x by headless Chrome in render.sh)."""
import importlib.util, os, sys

ADDON = os.path.expanduser("~/Library/Application Support/Anki2/addons21/Interactive Heatmap")
OLD = os.path.expanduser("~/Documents/Stanford Med/Anki Addons/Promo Images")
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("brand", os.path.join(ADDON, "brand.py"))
brand = importlib.util.module_from_spec(spec); spec.loader.exec_module(brand)

TEAL = "#6fd1c0"          # accent text on dark
CODE = "1782362167"
TAG = "Break your studying down to its elements."
FONT = "-apple-system,'SF Pro Display','Segoe UI',Roboto,sans-serif"


def logo(n, night=True):
    return brand.svg("#0e7d6e", night, n)


def old(name):
    return "file://" + os.path.join(OLD, name)


BASE = f"""html,body{{margin:0;overflow:hidden}}
body{{background:radial-gradient(ellipse 90% 70% at 50% -10%,#24302f 0%,#161a1b 62%,#121516 100%);color:#f4f4f5;
 font-family:{FONT};-webkit-font-smoothing:antialiased}}
.shot{{border-radius:14px;box-shadow:0 26px 60px rgba(0,0,0,.55),0 0 0 1px rgba(255,255,255,.08);flex:none}}
.mark{{display:flex;align-items:center;gap:10px;font-weight:700;letter-spacing:-.2px}}
.code{{display:inline-flex;align-items:center;gap:8px;font-weight:600;border-radius:12px;background:rgba(255,255,255,.07);
 border:1px solid rgba(255,255,255,.12)}}.code b{{color:{TEAL}}}
.shells{{position:absolute;pointer-events:none}}"""


def crop(img, x, y, w, h, scale, extra=""):
    """Part (x, y, w, h) of an old 2600x1600 poster, in its 1300x800 CSS px, scaled."""
    return (f'<div class="shot" style="width:{w*scale:.0f}px;height:{h*scale:.0f}px;'
            f'background:url(\'{old(img)}\') {-x*scale:.1f}px {-y*scale:.1f}px / {1300*scale:.1f}px {800*scale:.1f}px no-repeat;{extra}"></div>')


def shells(cx, cy, radii, op=.16, dots=()):
    rings = "".join(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#3a9789" stroke-width="2" stroke-opacity="{op}"/>' for r in radii)
    ds = "".join(f'<circle cx="{x}" cy="{y}" r="7" fill="#3a9789" fill-opacity="{op*3:.2f}"/>' for x, y in dots)
    return rings + ds


HUD = (433, 463, 433, 284)          # the heatmap panel in 01-at-a-glance
DECKS = (370, 177, 560, 239)        # the deck list in 01-at-a-glance
STAGE = (346, 162, 608, 592)        # the whole photo frame in 01-at-a-glance

pages = {}

# --- the old set, rebranded: a small Elemental mark top left on every slide
for f in ["01-at-a-glance", "02-six-views", "03-time-left", "04-review-pill", "05-themes",
          "06-card-browser", "07-settings", "09-day-details"]:
    pages[f] = (1300, 800, f"""<style>{BASE}
body{{background:url('{old(f + ".png")}') 0 0/1300px 800px no-repeat}}
.mark{{position:absolute;left:40px;top:32px;font-size:17px;color:#e8e8ea}}</style>
<div class="mark">{logo(26)}Elemental</div>""")

STRIP = f"""<style>{BASE}
body{{height:130px;background:linear-gradient(90deg,#161b1c,#1c2425)}}
.ban{{display:flex;align-items:center;justify-content:space-between;height:130px;padding:0 56px}}
.name{{font-size:30px;font-weight:700;letter-spacing:-.3px}}.tagline{{font-size:16px;color:#a1a1aa;margin-top:3px}}
.code{{font-size:16px;padding:11px 20px}}</style>"""
pages["00-header"] = (1300, 130, STRIP + f"""<div class="ban"><div class="mark" style="gap:18px">{logo(62)}
<div><div class="name">Elemental</div><div class="tagline">{TAG} A heatmap of your reviews, right on Anki's main screen.</div></div></div>
<div class="code">Add-on code <b>{CODE}</b></div></div>""")
pages["08-feedback"] = (1300, 130, STRIP + f"""<div class="ban"><div class="mark" style="gap:18px">{logo(46)}
<div><div class="name" style="font-size:26px">Found a bug or have an idea?</div>
<div class="tagline">Send it from inside Elemental. No account needed, and every message is read.</div></div></div>
<div class="code">Settings → <b>Feedback</b></div></div>""")

# --- new: cover poster (2600x1600)
pages["10-cover"] = (1300, 800, f"""<style>{BASE}
.l{{position:absolute;left:96px;top:0;bottom:0;width:470px;display:flex;flex-direction:column;justify-content:center}}
.name{{font-size:76px;font-weight:700;letter-spacing:-2px;margin:26px 0 10px}}
.tag{{font-size:24px;line-height:1.35;color:#b4bcbb}}.sm{{font-size:17px;line-height:1.5;color:#8b9493;margin-top:18px}}
.code{{font-size:18px;padding:12px 20px;margin-top:34px;align-self:flex-start}}
.r{{position:absolute;right:70px;top:50%;transform:translateY(-50%)}}</style>
<svg class="shells" width="1300" height="800">{shells(1080, 400, (260, 380, 500), .13, ((1014, 26), (1146, 774)))}</svg>
<div class="l">{logo(96)}<div class="name">Elemental</div><div class="tag">{TAG}</div>
<div class="code">Add-on code <b>{CODE}</b></div></div>
<div class="r">{crop("01-at-a-glance.png", *STAGE, 1.08)}</div>""")

# --- new: wide social card (2400x1350)
pages["11-social-wide"] = (1200, 675, f"""<style>{BASE}
.top{{position:absolute;left:0;right:0;top:46px;text-align:center}}
.mark{{justify-content:center;font-size:40px;gap:16px}}
.tag{{font-size:22px;color:#b4bcbb;margin-top:12px}}
.st{{position:absolute;left:0;right:0;bottom:-30px;display:flex;justify-content:center}}</style>
<svg class="shells" width="1200" height="675">{shells(600, 760, (420, 560, 700), .12)}</svg>
<div class="top"><div class="mark">{logo(54)}Elemental</div><div class="tag">{TAG}</div></div>
<div class="st">{crop("01-at-a-glance.png", *HUD, 1.62)}</div>""")

# --- new: square post (2160x2160)
pages["12-square"] = (1080, 1080, f"""<style>{BASE}
.top{{position:absolute;left:0;right:0;top:80px;text-align:center}}
.mark{{justify-content:center;font-size:56px;gap:20px}}
.tag{{font-size:28px;color:#b4bcbb;margin-top:16px}}
.st{{position:absolute;left:0;right:0;top:300px;display:flex;justify-content:center}}
.bot{{position:absolute;left:0;right:0;bottom:70px;display:flex;justify-content:center}}
.code{{font-size:22px;padding:14px 26px}}</style>
<svg class="shells" width="1080" height="1080">{shells(540, 560, (380, 500), .12, ((170, 470), (905, 650)))}</svg>
<div class="top"><div class="mark">{logo(78)}Elemental</div><div class="tag">{TAG}</div></div>
<div class="st">{crop("01-at-a-glance.png", *HUD, 2.15)}</div>
<div class="bot"><div class="code">Free on AnkiWeb · Add-on code <b>{CODE}</b></div></div>""")

# --- new: vertical story (1080x1920)
pages["13-story"] = (540, 960, f"""<style>{BASE}
.top{{position:absolute;left:0;right:0;top:70px;text-align:center}}
.mark{{justify-content:center;font-size:40px;gap:14px}}
.tag{{font-size:19px;line-height:1.35;color:#b4bcbb;margin:12px auto 0;max-width:380px}}
.st{{position:absolute;left:0;right:0;display:flex;justify-content:center}}
.bot{{position:absolute;left:0;right:0;bottom:54px;text-align:center}}
.code{{font-size:16px;padding:11px 18px}}</style>
<svg class="shells" width="540" height="960">{shells(270, 520, (250, 330), .12)}</svg>
<div class="top"><div class="mark">{logo(52)}Elemental</div><div class="tag">{TAG}</div></div>
<div class="st" style="top:250px">{crop("01-at-a-glance.png", *DECKS, .86)}</div>
<div class="st" style="top:490px">{crop("01-at-a-glance.png", *HUD, 1.1)}</div>
<div class="bot"><div class="code">Add-on code <b>{CODE}</b></div></div>""")

# --- new: light cover, for light pages
pages["14-cover-light"] = (1300, 800, f"""<style>{BASE}
body{{background:radial-gradient(ellipse 90% 70% at 50% -10%,#ffffff 0%,#f1f5f4 62%,#e9efee 100%);color:#14201f}}
.l{{position:absolute;left:96px;top:0;bottom:0;width:470px;display:flex;flex-direction:column;justify-content:center}}
.name{{font-size:76px;font-weight:700;letter-spacing:-2px;margin:26px 0 10px}}
.tag{{font-size:24px;line-height:1.35;color:#4e5d5b}}
.code{{font-size:18px;padding:12px 20px;margin-top:34px;align-self:flex-start;background:#fff;border-color:rgba(0,0,0,.1)}}
.code b{{color:#0e7d6e}}
.shot{{box-shadow:0 26px 60px rgba(20,40,38,.28),0 0 0 1px rgba(0,0,0,.06)}}
.r{{position:absolute;right:70px;top:50%;transform:translateY(-50%)}}</style>
<svg class="shells" width="1300" height="800">{shells(1080, 400, (260, 380, 500), .25)}</svg>
<div class="l">{brand.svg("#0e7d6e", False, 96)}<div class="name">Elemental</div><div class="tag">{TAG}</div>
<div class="code">Add-on code <b>{CODE}</b></div></div>
<div class="r">{crop("01-at-a-glance.png", *STAGE, 1.08)}</div>""")

def cap(img, x, y, w, h, scale, extra=""):
    """Part (x, y, w, h) of a fresh 1100x900 deck-screen capture (2x PNG), scaled."""
    url = "file://" + os.path.join("/private/tmp/claude-501/-Users-jerryshen-Documents-Stanford-Med-Anki-Addons/9c59ddce-b604-4a22-8bcb-34f73bdee8c5/scratchpad", "promo", img)
    return (f'<div class="shot" style="width:{w*scale:.0f}px;height:{h*scale:.0f}px;'
            f'background:url(\'{url}\') {-x*scale:.1f}px {-y*scale:.1f}px / {1100*scale:.1f}px {900*scale:.1f}px no-repeat;{extra}"></div>')


for key, img in (("forest", "hero_forest_volume.png"), ("napali", "hero_napali_volume.png"), ("hills", "hero_hills_volume.png")):
    shot = cap(img, 150, 12, 800, 778, 0.82)
    pages[f"10-cover-{key}"] = (1300, 800, pages["10-cover"][2].replace(crop("01-at-a-glance.png", *STAGE, 1.08), shot))
    pages[f"14-cover-light-{key}"] = (1300, 800, pages["14-cover-light"][2].replace(crop("01-at-a-glance.png", *STAGE, 1.08), shot))

# Rolling Hills is the default look: the main cover and the other formats use its capture
H_IMG = "hero_hills_volume.png"
DECKP, HUDP = (173, 30, 754, 327), (213, 417, 673, 374)
OLDSTAGE = crop("01-at-a-glance.png", *STAGE, 1.08)
pages["10-cover"] = (1300, 800, pages["10-cover"][2].replace(OLDSTAGE, cap(H_IMG, 150, 12, 800, 778, 0.82)))
pages["14-cover-light"] = (1300, 800, pages["14-cover-light"][2].replace(OLDSTAGE, cap(H_IMG, 150, 12, 800, 778, 0.82)))
pages["11-social-wide"] = (1200, 675, pages["11-social-wide"][2].replace(crop("01-at-a-glance.png", *HUD, 1.62), cap(H_IMG, *HUDP, 1.29)))
pages["12-square"] = (1080, 1080, pages["12-square"][2].replace(crop("01-at-a-glance.png", *HUD, 2.15), cap(H_IMG, *HUDP, 1.38)))
st = pages["13-story"][2].replace(crop("01-at-a-glance.png", *DECKS, .86), cap(H_IMG, *DECKP, .64)).replace(crop("01-at-a-glance.png", *HUD, 1.1), cap(H_IMG, *HUDP, .7))
pages["13-story"] = (540, 960, st.replace('style="top:250px"', 'style="top:240px"').replace('style="top:490px"', 'style="top:480px"'))
pages["01-at-a-glance"] = (1300, 800, f"""<style>{BASE}
body{{background:radial-gradient(ellipse 90% 70% at 50% -10%,#2b2b35 0%,#18181c 62%,#141417 100%)}}
.mark{{position:absolute;left:40px;top:32px;font-size:17px;color:#e8e8ea}}
.head{{text-align:center;padding-top:50px}}h1{{font-size:42px;font-weight:700;letter-spacing:-.5px;margin:0}}
.sub{{font-size:18px;line-height:1.45;color:#a1a1aa;margin:12px auto 0;max-width:860px}}
.stage{{position:absolute;left:0;right:0;top:186px;bottom:0;display:flex;align-items:center;justify-content:center}}</style>
<div class="mark">{logo(26)}Elemental</div>
<div class="head"><h1>Your learning, at a glance</h1><div class="sub">A heatmap, today's stats and your graphs, right on Anki's main screen.</div></div>
<div class="stage">{cap(H_IMG, 150, 12, 800, 778, 0.76)}</div>""")

PHOTO = "file://" + os.path.join(ADDON, "builtin_backgrounds", "rolling_hills.webp")
RBASE = BASE + """
html,body{background:transparent!important}
.card{position:absolute;inset:0;border-radius:36px;overflow:hidden;
 background:radial-gradient(ellipse 90% 80% at 20% -10%,#24302f 0%,#161a1b 62%,#121516 100%)}
.edge{position:absolute;inset:0;border-radius:36px;box-shadow:inset 0 0 0 2px rgba(255,255,255,.08);pointer-events:none}
.l{position:absolute;left:84px;top:0;bottom:0;display:flex;align-items:center;gap:30px}
.name{font-size:72px;font-weight:700;letter-spacing:-1.8px;line-height:1}
.tag{font-size:23px;color:#b4bcbb;margin-top:14px}
.code{font-size:16px;padding:10px 18px;margin-top:26px}"""

# A: the cover, as a 3:1 banner (2400x800)
pages["15-banner-cover"] = (1200, 400, f"""<style>{RBASE}
.r{{position:absolute;right:-40px;top:50%;transform:translateY(-50%)}}</style>
<div class="card"><svg class="shells" width="1200" height="400">{shells(980, 200, (230, 330, 430), .13)}</svg>
<div class="l">{logo(120)}<div><div class="name">Elemental</div><div class="tag">{TAG}</div>
<div class="code">Add-on code <b>{CODE}</b></div></div></div>
<div class="r">{cap(H_IMG, *HUDP, .86)}</div><div class="edge"></div></div>""")

# B: the Rolling Hills photo behind everything (2400x800)
pages["16-banner-photo"] = (1200, 400, f"""<style>{RBASE}
.card{{background:url('{PHOTO}') center 60%/cover}}
.shade{{position:absolute;inset:0;background:linear-gradient(90deg,rgba(10,14,12,.94) 0%,rgba(10,14,12,.86) 38%,rgba(10,14,12,.35) 68%,rgba(10,14,12,.15) 100%)}}
.r{{position:absolute;right:56px;top:50%;transform:translateY(-50%)}}</style>
<div class="card"><div class="shade"></div>
<div class="l">{logo(120)}<div><div class="name">Elemental</div><div class="tag">{TAG}</div>
<div class="code" style="background:rgba(0,0,0,.35)">Add-on code <b>{CODE}</b></div></div></div>
<div class="r">{cap(H_IMG, *HUDP, .72)}</div><div class="edge"></div></div>""")

# C: slim header strip with the photo fading in on the right (2600x260)
pages["00-header-photo"] = (1300, 130, f"""<style>{BASE}
body{{height:130px;background:#161b1c}}
.ph{{position:absolute;inset:0;background:url('{PHOTO}') center 55%/cover}}
.shade{{position:absolute;inset:0;background:linear-gradient(90deg,#161b1c 0%,#161b1c 42%,rgba(22,27,28,.55) 72%,rgba(22,27,28,.25) 100%)}}
.ban{{position:absolute;inset:0;display:flex;align-items:center;justify-content:space-between;padding:0 56px}}
.name{{font-size:30px;font-weight:700;letter-spacing:-.3px}}.tagline{{font-size:16px;color:#a1a1aa;margin-top:3px}}
.code{{font-size:16px;padding:11px 20px;background:rgba(0,0,0,.45)}}</style>
<div class="ph"></div><div class="shade"></div>
<div class="ban"><div class="mark" style="gap:18px">{logo(62)}<div><div class="name">Elemental</div><div class="tagline">{TAG}</div></div></div>
<div class="code">Add-on code <b>{CODE}</b></div></div>""")

# 05: every theme as a tile, light half and dark half, plus a "more on the way" tile
tspec = importlib.util.spec_from_file_location("themes", os.path.join(ADDON, "themes.py"))
TH = importlib.util.module_from_spec(tspec); tspec.loader.exec_module(TH)
import random


def tile(key, t):
    rnd = random.Random(key)
    lv = [0 if rnd.random() < .12 else rnd.random() for _ in range(14 * 5)]
    cells = []
    for i, v in enumerate(lv):
        col = i % 14
        night = col >= 7
        pal = t["dark" if night else "light"]
        c = pal["empty"] if v == 0 else TH.glow(pal["base"], v, night)
        cells.append(f'<i style="background:{c}"></i>')
    ph = t.get("photo")
    bg = (f"background:url('file://{ADDON}/builtin_backgrounds/{ph}.webp') center/cover" if ph else
          f"background:linear-gradient(90deg,{t['light']['empty']} 50%,{t['dark']['empty']} 50%)")
    glass = ('<div class="gl" style="left:0;background:rgba(255,255,255,.62)"></div>'
             '<div class="gl" style="right:0;background:rgba(10,12,12,.55)"></div>') if ph else ""
    return (f'<div class="tile" style="{bg}">{glass}<div class="mini">{"".join(cells)}</div>'
            f'<div class="nm">{t["name"]}{"<span>photo</span>" if ph else ""}</div></div>')


tiles = "".join(tile(k, t) for k, t in TH.THEMES.items())
tiles += '<div class="tile more"><div class="plus">+</div><div>More on the way</div></div>'
pages["05-themes"] = (1300, 800, f"""<style>{BASE}
.mark{{position:absolute;left:40px;top:32px;font-size:17px;color:#e8e8ea}}
.head{{text-align:center;padding-top:46px}}h1{{font-size:42px;font-weight:700;letter-spacing:-.5px;margin:0}}
.sub{{font-size:18px;color:#a1a1aa;margin:10px 0 0}}
.grid{{position:absolute;left:50px;right:50px;top:176px;display:grid;grid-template-columns:repeat(5,1fr);gap:16px}}
.tile{{position:relative;height:136px;border-radius:14px;overflow:hidden;box-shadow:0 14px 30px rgba(0,0,0,.45),0 0 0 1px rgba(255,255,255,.08)}}
.gl{{position:absolute;top:0;bottom:0;width:50%}}
.mini{{position:absolute;left:14px;right:14px;top:14px;display:grid;grid-template-columns:repeat(14,1fr);gap:4px}}
.mini i{{display:block;aspect-ratio:1;border-radius:3px}}
.nm{{position:absolute;left:0;right:0;bottom:0;padding:7px 12px;font-size:13px;font-weight:600;color:#fff;
 background:rgba(0,0,0,.55);display:flex;justify-content:space-between;align-items:center}}
.nm span{{font-size:10px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:{TEAL}}}
.more{{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;background:rgba(255,255,255,.03);
 box-shadow:none;border:2px dashed rgba(111,209,192,.45);color:#c9d3d1;font-size:15px;font-weight:600}}
.plus{{font-size:36px;font-weight:300;color:{TEAL};line-height:1}}</style>
<div class="mark">{logo(26)}Elemental</div>
<div class="head"><h1>19 themes, and counting</h1><div class="sub">Each one in light and dark. Photo themes come with a matching background, and more themes are on the way.</div></div>
<div class="grid">{tiles}</div>""")

# 17: weak spots and stability, from the real Stats window (Repro Block expanded)
def png(img, w, h, scale, extra=""):
    url = "file://" + os.path.join(os.path.dirname(HERE), "promo", img)
    return (f'<div class="shot" style="position:relative;width:{w*scale:.0f}px;height:{h*scale:.0f}px;'
            f'background:url(\'{url}\') 0 0/{w*scale:.1f}px {h*scale:.1f}px no-repeat;{extra}"></div>')


TS = 0.86
pages["17-weak-spots"] = (1300, 800, f"""<style>{BASE}
.mark{{position:absolute;left:40px;top:32px;font-size:17px;color:#e8e8ea}}
.head{{text-align:center;padding-top:46px}}h1{{font-size:42px;font-weight:700;letter-spacing:-.5px;margin:0}}
.sub{{font-size:18px;color:#a1a1aa;margin:10px 0 0}}
.l{{position:absolute;left:52px;top:182px}}
.r{{position:absolute;right:52px;top:182px;width:372px;display:flex;flex-direction:column;gap:22px}}
.ring{{position:absolute;left:617px;top:255px;width:54px;height:25px;margin:-5px;border-radius:14px;box-shadow:0 0 0 2px {TEAL},0 0 18px rgba(111,209,192,.5)}}
.note{{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:18px 20px}}
.note b{{display:block;font-size:34px;color:#f0a09a;letter-spacing:-.5px}}
.note .t{{font-size:16px;font-weight:600;margin-top:4px}}.note .d{{font-size:14px;line-height:1.5;color:#a1a1aa;margin-top:8px}}
.cap{{font-size:13px;font-weight:600;color:#c9d3d1;margin:0 0 8px 2px}}</style>
<div class="mark">{logo(26)}Elemental</div>
<div class="head"><h1>Find what isn't sticking</h1><div class="sub">Retention and stability for every topic, so weak memories show up before they turn into lapses.</div></div>
<div class="l">{png("stats_topics_endo.png", 920, 669, TS, "")}<div class="ring"></div></div>
<div class="r">
<div class="note"><b>−29%</b><div class="t">Adrenal Pathophysiology</div>
<div class="d">Cards in this topic are less stable than cards you started around the same time, even though Endocrine as a whole is only 4% behind.</div></div>
{png("stats_remembered.png", 396, 224, 0.94)}
</div>""")

# 06: the card browser with the user's own look (Darkest theme, no state symbols)
BW = 1040
pages["06-card-browser"] = (1300, 800, f"""<style>{BASE}
.mark{{position:absolute;left:40px;top:32px;font-size:17px;color:#e8e8ea}}
.head{{text-align:center;padding-top:46px}}h1{{font-size:42px;font-weight:700;letter-spacing:-.5px;margin:0}}
.sub{{font-size:18px;color:#a1a1aa;margin:10px 0 0}}
.st{{position:absolute;left:0;right:0;top:250px;display:flex;flex-direction:column;align-items:center;gap:30px}}
.keys{{display:flex;gap:12px}}.keys span{{font-size:14px;font-weight:600;color:#d4d8d7;padding:8px 14px;border-radius:10px;
 background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1)}}</style>
<div class="mark">{logo(26)}Elemental</div>
<div class="head"><h1>A clearer card browser</h1><div class="sub">Clozes colored by number, and suspended, buried, marked and flagged cards easy to spot.</div></div>
<div class="st">{png("browser_mine_crop.png", 2348 / 2.257, 794 / 2.257, 1.0, "border-radius:12px")}
<div class="keys"><span>Colored clozes</span><span>Tinted card states</span><span>Short tags</span><span>Your own colors</span></div></div>""")

os.makedirs(os.path.join(HERE, "html"), exist_ok=True)
with open(os.path.join(HERE, "list.txt"), "w") as lst:
    for name, (w, h, body) in pages.items():
        p = os.path.join(HERE, "html", name + ".html")
        open(p, "w").write(f"<!doctype html><html><head><meta charset='utf-8'></head><body style='width:{w}px;height:{h}px;position:relative'>{body}</body></html>")
        dpr = {"12-square": 1, "11-social-wide": 4 / 3}.get(name, 2)
        lst.write(f"{name} {w} {h} {dpr}\n")
print(len(pages), "pages")

"""Before/after HTML of one AnKing card (the add-on's own render), for a poster."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import load, S
mod, mw, col = load(os.path.join(S, "promo_col/collection.anki2"))
AK = sys.modules["heatmap_mod.anking_style"]
found = AK.targets(col)
print("types", [(nt["name"], n, {k: AK.status(nt, k) for k in AK.ORDER}) for nt, n in found], flush=True)
nt = col.models.get(found[0][0]["id"])
note = AK.sample_note(col, nt) if not os.environ.get("NID") else col.get_note(int(os.environ["NID"]))
print("note", note.id, AK._field(note, "Text", 0)[:120].replace("\n", " "), flush=True)
media = "file://" + os.path.expanduser("~/Library/Application Support/Anki2/jshen100/collection.media") + "/"
import copy
plain = copy.deepcopy(AK.removed(nt, list(AK.ORDER)))
parts = AK._original_parts(plain)
print("own parts found:", sorted(parts), flush=True)
for name, text in parts.items():
    if name.endswith(".css"):
        plain["css"] = plain["css"].replace(text, "")
    else:
        side = "qfmt" if "_front" in name else "afmt"
        for t in plain["tmpls"]:
            t[side] = t[side].replace(text, "")
after = AK.applied(plain, list(AK.ORDER))
for tag, use in (("before", plain), ("after", after)):
    html, css = AK.render(col, note, use, True)
    page = (f"<!doctype html><html class='night-mode'><head><meta charset='utf-8'><base href='{media}'>"
            f"<style>body{{margin:24px;overflow-x:hidden}}</style><style>{css}</style></head>"
            f"<body class='card card1 isMac nightMode night_mode'><div id='qa'>{html}</div>"
            f"<script>function pycmd(){{}}</script></body></html>")
    open(os.path.join(S, "promo", f"anking_{tag}.html"), "w").write(page)
print("written", flush=True)
os._exit(0)

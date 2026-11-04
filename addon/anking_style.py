"""
AnKing card styling — the add-on author's styling for AnKingOverhaul cards, which anyone can
add to their own AnKing note types from Settings → AnKing Cards:

- Clean Reading Theme: the Styling (CSS) plus the Reading Layout script in the front and
  back templates that it relies on (Extra under the answer, centered stacks, cloze pills).
- Beautify Text Dashes: a script that turns dash lines into bullets.

Everything goes below AnkiHub's ANKIHUB_END comment, which AnkiHub and the AnKing add-ons
promise not to touch, so AnKing updates keep it. Each piece is wrapped in its own START/END
markers, so applying again replaces it and Remove takes out exactly what was added. A copy of
each note type is saved to user_files/anking_backups before the first change.

The shared copy lives in anking_style/ (refreshed from the author's own cards with
refresh_bundle, which only shows up for a collection whose cards carry the original).
"""

from __future__ import annotations

import copy
import json
import os
import re
import time

_dir = os.path.dirname(__file__)
BUNDLE = os.path.join(_dir, "anking_style")
BACKUPS = os.path.join(_dir, "user_files", "anking_backups")
MARKER = "ANKIHUB_END"

# key: name, its files (CSS / front template / back template), and text that identifies the
# original in the author's own cards (outside our markers)
PARTS = {
    "theme": {"name": "Clean Reading Theme", "css": "clean_reading.css",
              "front": "reading_layout_front.html", "back": "reading_layout_back.html",
              "signature": "CLEAN READING THEME", "front_signature": "<!-- READING LAYOUT -->"},
    "beautify": {"name": "Beautify Text Dashes", "css": None,
                 "front": "beautify_front.html", "back": "beautify_back.html",
                 "signature": "BEAUTIFY TEXT DASHES", "front_signature": "BEAUTIFY TEXT DASHES"},
}
ORDER = ("theme", "beautify")       # top to bottom below the marker


def _start(key):
    return f"INTERACTIVE HEATMAP {key.upper()} START"


def _end(key):
    return f"INTERACTIVE HEATMAP {key.upper()} END"


def _read(name):
    with open(os.path.join(BUNDLE, name), encoding="utf-8") as f:
        return f.read().strip("\n")


def available() -> bool:
    return all(os.path.exists(os.path.join(BUNDLE, p[f])) for p in PARTS.values()
               for f in ("css", "front", "back") if p[f])


# ──────────────────────────────────────────────────────────────
# Which note types
# ──────────────────────────────────────────────────────────────
def _has_marker(nt) -> bool:
    return MARKER in nt["css"] and all(MARKER in t["qfmt"] and MARKER in t["afmt"] for t in nt["tmpls"])


def is_target(nt) -> bool:
    """AnKingOverhaul note types (the theme is written for their fields and layout) that
    carry AnkiHub's protected section."""
    looks = "AnKingOverhaul" in nt["name"] or "ANKINGOVERHAUL" in nt["css"][:400]
    return looks and _has_marker(nt)


def targets(col) -> list:
    """[(note type, note count)] for every AnKingOverhaul note type that has notes."""
    out = []
    for nt in col.models.all():
        if is_target(nt):
            n = col.models.use_count(nt)
            if n:
                out.append((nt, n))
    return out


# ──────────────────────────────────────────────────────────────
# Reading and changing the protected section
# ──────────────────────────────────────────────────────────────
def _split(text: str, css: bool) -> tuple[str, str]:
    """(everything up to and including the ANKIHUB_END comment, everything after it)."""
    i = text.find(MARKER)
    if i < 0:
        return text, ""
    close = text.find("*/" if css else "-->", i)
    if close < 0:
        return text, ""
    close += 2 if css else 3
    return text[:close], text[close:]


def _block_re(key, css):
    if css:
        return re.compile(r"\n?/\* " + re.escape(_start(key)) + r".*?" + re.escape(_end(key)) + r" \*/\n?", re.S)
    return re.compile(r"\n?<!-- " + re.escape(_start(key)) + r".*?" + re.escape(_end(key)) + r" -->\n?", re.S)


def _wrap(key, body, css):
    note = "added by Elemental (Settings > AnKing Cards); remove it there"
    if css:
        return f"/* {_start(key)}: {note} */\n{body}\n/* {_end(key)} */"
    return f"<!-- {_start(key)}: {note} -->\n{body}\n<!-- {_end(key)} -->"


def status(nt, key) -> str:
    """"applied" (ours, in markers), "original" (the author's own, outside markers), or "none"."""
    css_part = _split(nt["css"], True)[1]
    front = _split(nt["tmpls"][0]["qfmt"], False)[1] if nt["tmpls"] else ""
    if _block_re(key, True).search(css_part) or _block_re(key, False).search(front):
        return "applied"
    sig, fsig = PARTS[key]["signature"], PARTS[key]["front_signature"]
    if (PARTS[key]["css"] and sig in css_part) or fsig in front:
        return "original"
    return "none"


def _without(text, keys, css):
    head, tail = _split(text, css)
    before = tail
    for k in keys:
        tail = _block_re(k, css).sub("\n", tail)
    if tail != before:      # one blank line between the marker and what follows, as AnKing ships it
        tail = ("\n\n" + tail.lstrip("\n")) if tail.strip() else "\n"
    return head + tail


def _with(text, keys, css, side=None):
    """Our blocks for keys right under the marker, in ORDER, above whatever else is there."""
    text = _without(text, keys, css)
    head, tail = _split(text, css)
    blocks = []
    for k in ORDER:
        if k not in keys:
            continue
        name = PARTS[k]["css"] if css else PARTS[k][side]
        if name:
            blocks.append(_wrap(k, _read(name), css))
    if not blocks:
        return text
    rest = tail.lstrip("\n")
    return head + "\n\n" + "\n\n".join(blocks) + ("\n\n" + rest if rest.strip() else "\n")


def applied(nt, keys) -> dict:
    """A copy of the note type with keys added (or brought up to date); others untouched."""
    nt = copy.deepcopy(nt)
    keys = [k for k in keys if status(nt, k) != "original"]
    nt["css"] = _with(nt["css"], keys, True)
    for t in nt["tmpls"]:
        t["qfmt"] = _with(t["qfmt"], keys, False, "front")
        t["afmt"] = _with(t["afmt"], keys, False, "back")
    return nt


def removed(nt, keys) -> dict:
    nt = copy.deepcopy(nt)
    nt["css"] = _without(nt["css"], keys, True)
    for t in nt["tmpls"]:
        t["qfmt"] = _without(t["qfmt"], keys, False)
        t["afmt"] = _without(t["afmt"], keys, False)
    return nt


def backup(nt) -> str:
    os.makedirs(BACKUPS, exist_ok=True)
    path = os.path.join(BACKUPS, f"{nt['id']}_{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"name": nt["name"], "css": nt["css"],
                   "tmpls": [{"name": t["name"], "qfmt": t["qfmt"], "afmt": t["afmt"]} for t in nt["tmpls"]]},
                  f, ensure_ascii=False)
    return path


def save(col, notetypes: list, label: str):
    """Write the note types as one undoable step (Edit → Undo)."""
    pos = col.add_custom_undo_entry(label)
    for nt in notetypes:
        col.models.update_dict(nt)
    return col.merge_undo_entries(pos)


# ──────────────────────────────────────────────────────────────
# Preview
# ──────────────────────────────────────────────────────────────
# the beautify script's own test for a dash line (at the start or after a line break)
_DASH_LINE = re.compile(r"(?:^|<br\s*/?>|</?(?:div|p)[^>]*>)(?:&nbsp;|\s)*-(?:&nbsp;|\s)", re.I)


def _field(note, name, fallback):
    try:
        return note[name]
    except KeyError:
        return note.fields[fallback] if len(note.fields) > fallback else ""


def sample_note(col, nt):
    """A note of this type to preview both changes on: a plain-text cloze (no images or
    audio) whose Extra has a few dash lines for Beautify Text Dashes to turn into bullets.
    Falls back to any plain cloze, then any note."""
    name = nt["name"].replace('"', '\\"')
    plain = lambda t: "<img" not in t and "[sound:" not in t
    fallback = None
    for query in (f'"note:{name}" Extra:*-* -is:suspended', f'"note:{name}" -is:suspended', f'"note:{name}"'):
        try:
            nids = col.find_notes(query)
        except Exception:
            nids = []
        step = max(1, len(nids) // 600)
        for nid in nids[::step][:600]:
            note = col.get_note(nid)
            text, extra = _field(note, "Text", 0), _field(note, "Extra", 1)
            if not ("{{c" in text and 40 < len(text) < 400 and plain(text)):
                continue
            if len(_DASH_LINE.findall(extra)) >= 2 and plain(extra) and len(extra) < 900:
                return note
            if fallback is None and plain("".join(note.fields)):
                fallback = note
        if fallback is not None:
            return fallback
        if nids and query.endswith('"'):
            return col.get_note(nids[0])
    return fallback


def render(col, note, nt, back: bool) -> tuple[str, str]:
    """(card HTML, CSS) for the note's first card as if its note type were nt (unsaved)."""
    from anki.template import TemplateRenderContext
    card = note.cards()[0] if note.cards() else note.ephemeral_card()
    ctx = TemplateRenderContext.from_card_layout(note, card, notetype=nt, template=nt["tmpls"][card.ord],
                                                 fill_empty=False)
    out = ctx.render()
    html = out.answer_text if back else out.question_text
    # audio only becomes a play button in the reviewer; show a small symbol instead of the raw tag
    html = re.sub(r"\[anki:play:[^\]]*\]", "<span style='opacity:.5'>&#9654;</span>", html)
    return html, out.css


# ──────────────────────────────────────────────────────────────
# Author tool: refresh the shared copy from your own cards
# ──────────────────────────────────────────────────────────────
def _original_parts(nt) -> dict:
    """{bundle file: text} cut from the author's own (unmarked) styling."""
    out = {}
    css_tail = _split(nt["css"], True)[1]
    i = css_tail.find("CLEAN READING THEME")
    if i >= 0:
        out["clean_reading.css"] = css_tail[css_tail.rfind("/*", 0, i):].strip("\n")
    t = nt["tmpls"][0]
    for side, html in (("front", t["qfmt"]), ("back", t["afmt"])):
        tail = _split(html, False)[1]
        r = tail.find("<!-- READING LAYOUT -->")
        b = tail.rfind("<script", 0, tail.find("BEAUTIFY TEXT DASHES"))
        if r >= 0 and b > r:
            out[f"reading_layout_{side}.html"] = tail[r:b].strip("\n")
        if b >= 0:
            end = tail.find("</script>", b) + len("</script>")
            out[f"beautify_{side}.html"] = tail[b:end].strip("\n")
    return out


def refresh_bundle(nt) -> list:
    """Write the author's current styling into anking_style/; returns the files written."""
    parts = _original_parts(nt)
    os.makedirs(BUNDLE, exist_ok=True)
    for name, text in parts.items():
        with open(os.path.join(BUNDLE, name), "w", encoding="utf-8") as f:
            f.write(text + "\n")
    return sorted(parts)

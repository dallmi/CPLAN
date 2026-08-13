"""The campaign activity board, drawn to a raster instead of to HTML.

A second renderer over the *same* view. `dashboard_render.build_view` produces
every figure, colour, bar height and status word once; the HTML template and
this module both consume it. That is what stops a PNG and a page from
disagreeing about a number -- neither computes anything the other does not.

Why Pillow and not a plotting library
-------------------------------------
This board is not a chart. It is rectangles, text, bars, one ring and one
polyline, and a plotting library's contribution to that is a layout engine
nobody asked for. `agent_pack`'s chart standards record what that costs: across
twelve test renders, 186 text collisions measured off the rendered artists, 89
of them from tile axes that brought ticks and spines along with them. Placing
the marks directly removes the entire class.

The two things a raster gets wrong, and what is done about them
---------------------------------------------------------------
**Text has no flow.** In HTML a long insight pushes the panel taller; here it
draws straight over whatever is beneath it. So every string this module draws
is recorded with its box, and `collisions()` reports the overlaps afterwards --
measured off what was drawn, never off what was intended. `render()` refuses to
return an image that has any.

**Fonts are not portable.** Helvetica Neue carries no ▲ ● ▼, so the status
marks are drawn as polygons rather than typed. The face itself is resolved
through an explicit ladder and the result is reported in `FontChoice`: two runs
match only if they matched on the font, and a caller that cares is told which
one it got rather than left to assume.
"""

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------
# A family is a weight -> (file, index) map, because the faces that matter here
# are shipped as separate files. DejaVu is four files; Helvetica Neue is one
# collection with four indices; the ladder has to express both.
#
# DejaVu leads, and not because it is the nicest. It is what the agent's sandbox
# has -- measured, 23 files including ExtraLight and Bold -- and a board is
# supposed to look the same for everyone who asks for it. A ladder that put a
# local face first would give this machine a prettier board than the one the
# readers get, which is the drift the whole exercise removes. `bundled` still
# outranks it: a licensed face dropped into fonts/ is a deliberate act and wins.
_DEJAVU_FEDORA = "/usr/share/fonts/dejavu-sans-fonts"
_DEJAVU_DEBIAN = "/usr/share/fonts/truetype/dejavu"


def _dejavu(root):
    return {"light": (f"{root}/DejaVuSans-ExtraLight.ttf", 0),
            "regular": (f"{root}/DejaVuSans.ttf", 0),
            # DejaVu has no 500 or 600. Bold is the only face that reads as
            # emphasis, so the brand's 600 tier lands on it -- heavier than the
            # stylesheet asks for, and the only alternative is no hierarchy.
            "medium": (f"{root}/DejaVuSans-Bold.ttf", 0),
            "bold": (f"{root}/DejaVuSans-Bold.ttf", 0)}


FONT_LADDER = (
    ("bundled", {w: ("fonts/board.ttf", 0)
                 for w in ("light", "regular", "medium", "bold")}),
    ("DejaVu Sans", _dejavu(_DEJAVU_FEDORA)),
    ("DejaVu Sans", _dejavu(_DEJAVU_DEBIAN)),
    ("Helvetica Neue", {"light": ("/System/Library/Fonts/HelveticaNeue.ttc", 7),
                        "regular": ("/System/Library/Fonts/HelveticaNeue.ttc", 0),
                        "medium": ("/System/Library/Fonts/HelveticaNeue.ttc", 10),
                        "bold": ("/System/Library/Fonts/HelveticaNeue.ttc", 1)}),
    ("Arial", {w: ("/System/Library/Fonts/Supplemental/Arial.ttf", 0)
               for w in ("light", "regular", "medium", "bold")}),
    ("Arial (Windows)", {w: ("C:/Windows/Fonts/arial.ttf", 0)
                         for w in ("light", "regular", "medium", "bold")}),
)

LIGHT, REGULAR, MEDIUM, BOLD = "light", "regular", "medium", "bold"


@dataclass(frozen=True)
class FontChoice:
    """Which family was drawn with, and how many distinct faces it gave.

    `weights` is 1 when the ladder fell through to a family with a single face:
    the board still draws, but its hierarchy is carried by size alone. Two runs
    match only if they matched here, so it is reported rather than absorbed.
    """
    name: str
    faces: dict          # weight -> (absolute path, index)
    weights: int

    @property
    def graded(self):
        return self.weights > 1


def resolve_font(ladder=FONT_LADDER, root=None):
    """First family in the ladder whose faces Pillow can all open.

    All of them, not merely the regular: a family that opens for body text and
    fails for the light face would draw a board whose hero figures silently
    changed weight.
    """
    root = Path(root) if root else Path(__file__).resolve().parent
    for name, faces in ladder:
        resolved = {}
        for weight, (raw, index) in faces.items():
            path = Path(raw)
            if not path.is_absolute():
                path = root / raw
            try:
                ImageFont.truetype(str(path), 12, index=index)
            except (OSError, ValueError):
                break
            resolved[weight] = (str(path), index)
        else:
            return FontChoice(name=name, faces=resolved,
                              weights=len(set(resolved.values())))
    raise RuntimeError(
        "no drawable font found. Ship one beside this module at fonts/board.ttf, "
        "or extend FONT_LADDER with a family this machine has."
    )


# --------------------------------------------------------------------------
# Geometry. Named because a raster has no layout engine to fall back on: every
# number here is load-bearing, and a magic one buried in a call is the reason
# a panel silently overlaps its neighbour three edits later.
# --------------------------------------------------------------------------
SUPERSAMPLE = 2
WIDTH, HEIGHT = 1440, 1450
PAD = 48
GUTTER = 20
CARD_H = 200
PANEL_ROW1_H = 480
PANEL_ROW2_H = 400
PANEL_HEAD_H = 78
TIMING_PLOT_H = 180
LEADERSHIP_PLOT_H = 160

BLACK = "#000000"; WHITE = "#ffffff"
GREY_1 = "#cccabc"; GREY_3 = "#8e8d83"; GREY_4 = "#7a7870"
GREY_5 = "#5a5d5c"; GREY_6 = "#404040"
SURFACE = "#ecebe4"; ROW_ALT = "#f8f7f2"; ACCENT = "#e60000"

_ENTITIES = (("&amp;", "&"), ("&mdash;", "\u2014"), ("&ndash;", "\u2013"),
             ("&rsquo;", "\u2019"), ("&times;", "\u00d7"), ("&lt;", "<"),
             ("&gt;", ">"))


def plain(value):
    """The view is built for HTML, so it carries entities. Undo them."""
    text = str(value)
    for entity, char in _ENTITIES:
        text = text.replace(entity, char)
    return text


@dataclass
class Drawn:
    """One string that reached the canvas, with the box it occupies."""
    text: str
    zone: str
    box: tuple


@dataclass
class Canvas:
    """A drawing surface that remembers every string it drew.

    The remembering is the point. A renderer that checks its own intentions
    confirms its intentions; only the recorded boxes say what the reader will
    actually see.
    """
    font: FontChoice
    width: int = WIDTH
    height: int = HEIGHT
    scale: int = SUPERSAMPLE
    zone: str = "page"
    drawn: list = field(default_factory=list)
    inks: set = field(default_factory=set)

    def __post_init__(self):
        self.image = Image.new("RGB", (self.width * self.scale,
                                       self.height * self.scale), WHITE)
        self.draw = ImageDraw.Draw(self.image)
        self._fonts = {}

    def ink(self, colour):
        """Record a colour on its way to the canvas, and hand it back.

        The palette claim is about what the renderer *asks for*. Reading it back
        off the finished image measures the resampler instead: a LANCZOS
        downscale blends white and Pastel I into a dozen tones that are neither,
        and an assertion on those fails for a reason that has nothing to do with
        the palette.
        """
        if colour is not None:
            self.inks.add(str(colour).lower())
        return colour

    # -- primitives --------------------------------------------------------
    def face(self, size, weight=REGULAR):
        key = (round(size * 2), weight)
        if key not in self._fonts:
            path, index = self.font.faces[weight]
            self._fonts[key] = ImageFont.truetype(
                path, round(size * self.scale), index=index)
        return self._fonts[key]

    def measure(self, text, size, weight=REGULAR):
        return self.draw.textlength(text, font=self.face(size, weight)) / self.scale

    def text(self, x, y, text, size=13, weight=REGULAR, fill=BLACK, anchor="la",
             record=True):
        text = plain(text)
        s = self.scale
        face = self.face(size, weight)
        self.draw.text((x * s, y * s), text, font=face, fill=self.ink(fill), anchor=anchor)
        if record and text.strip():
            # The ink box Pillow actually laid down, not a guess from the point
            # size. A 26px face occupies about 19px of height, and estimating it
            # as 32 reported two collisions that were not there -- the same
            # mistake, one level up, as a run that checks its own intentions.
            box = self.draw.textbbox((x * s, y * s), text, font=face, anchor=anchor)
            self.drawn.append(Drawn(text, self.zone, tuple(v / s for v in box)))
        return self.measure(text, size, weight)

    def rect(self, x, y, w, h, fill=None, outline=None, width=1):
        s = self.scale
        self.draw.rectangle([x * s, y * s, (x + w) * s, (y + h) * s],
                            fill=self.ink(fill), outline=self.ink(outline),
                            width=max(1, round(width * s)))

    def line(self, x1, y1, x2, y2, fill=BLACK, width=1):
        s = self.scale
        self.draw.line([x1 * s, y1 * s, x2 * s, y2 * s], fill=self.ink(fill),
                       width=max(1, round(width * s)))

    def dashed(self, x1, y, x2, fill=GREY_5, width=1.25, dash=5, gap=4):
        x = x1
        while x < x2:
            self.line(x, y, min(x + dash, x2), y, fill=fill, width=width)
            x += dash + gap

    def polygon(self, points, fill):
        s = self.scale
        self.draw.polygon([(px * s, py * s) for px, py in points], fill=self.ink(fill))

    def ellipse(self, x, y, w, h, fill=None, outline=None, width=1):
        s = self.scale
        self.draw.ellipse([x * s, y * s, (x + w) * s, (y + h) * s],
                          fill=self.ink(fill), outline=self.ink(outline),
                          width=max(1, round(width * s)))

    def pieslice(self, cx, cy, r, start, end, fill):
        s = self.scale
        self.draw.pieslice([(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s],
                           start, end, fill=self.ink(fill))

    def polyline(self, points, fill=BLACK, width=1.6):
        s = self.scale
        self.draw.line([(px * s, py * s) for px, py in points], fill=self.ink(fill),
                       width=max(1, round(width * s)), joint="curve")

    # -- text helpers ------------------------------------------------------
    def wrap(self, text, size, weight, max_width):
        words, lines, current = plain(text).split(), [], ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if self.measure(candidate, size, weight) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def paragraph(self, x, y, text, size, weight, fill, max_width, leading):
        lines = self.wrap(text, size, weight, max_width)
        for index, line in enumerate(lines):
            self.text(x, y + index * leading, line, size, weight, fill)
        return y + len(lines) * leading

    def status(self, x, y, text, colour, size=11.5):
        """A status mark drawn, plus its words typed.

        The triangles and the dot are polygons because Helvetica Neue has no
        glyph for them and renders a replacement box instead -- which is a
        font-dependent difference in a page whose whole purpose is not having
        any.
        """
        text = plain(text)
        mark, rest = (text[0], text[1:].strip()) if text[:1] in "\u25b2\u25bc\u25cf" else ("", text)
        offset = 0.0
        if mark:
            h = size * 0.62
            top = y + 2.5
            if mark == "\u25b2":
                self.polygon([(x + h / 2, top), (x + h, top + h), (x, top + h)], colour)
            elif mark == "\u25bc":
                self.polygon([(x, top), (x + h, top), (x + h / 2, top + h)], colour)
            else:
                self.ellipse(x, top + h * 0.15, h * 0.72, h * 0.72, fill=colour)
            offset = h + 5
        return offset + self.text(x + offset, y, rest, size, MEDIUM, colour)


# --------------------------------------------------------------------------
# Fitting. A panel has a fixed rectangle and the data does not have a fixed
# size, so something has to give -- and the first design let the renderer
# refuse. That was wrong in a way that took real data to show: refusing does
# not stop the board being drawn, it moves the cutting to whoever is holding
# the data, who cuts silently. A caller that had to drop four of seven teams to
# get an image is worse than a tight label, because the finished board says
# nothing about what left.
#
# So the renderer fits, and where it cannot fit honestly it names what it left
# out on the page.
# --------------------------------------------------------------------------
MIN_LABEL_SIZE = 8.0
MIN_ROW_PITCH = 19.0


# Labels are measured as the lines that get drawn, never as their words. A
# two-part name splits across two lines; measuring "Compliance" and
# "Communications" separately says it fits and then the line
# "Compliance Communications" runs into its neighbour. Both call sites pass the
# segments they will actually draw.
LABEL_MARGIN = 1.15


def fit_label_size(canvas, segments, column_width, size=11.0, weight=REGULAR,
                   floor=MIN_LABEL_SIZE):
    """Largest size at or below `size` that keeps every segment in a column."""
    widest = max((canvas.measure(plain(seg), size, weight) for seg in segments),
                 default=0.0)
    if widest <= column_width or widest == 0:
        return size
    return max(floor, size * column_width / widest)


def label_stride(canvas, segments, column_width, size, weight=REGULAR):
    """Show every k-th label, k being the smallest that leaves them a margin.

    Dropping a tick is a loss a reader can see and reason about -- the axis
    still runs and the gaps stay even. Dropping a bar is not, which is why only
    the axis is ever thinned.
    """
    widest = max((canvas.measure(plain(seg), size, weight) for seg in segments),
                 default=0.0)
    if column_width <= 0:
        return 1
    needed = widest * LABEL_MARGIN
    if needed <= column_width:
        return 1
    return int(needed / column_width) + 1


def clip_text(canvas, text, width, size, weight=REGULAR, ellipsis="\u2026"):
    """Shorten a string to a width, with an ellipsis when it had to give.

    The collision check compares text against text, so a name running under a
    bar track passes it -- the track is not text. A column has a width and the
    label has to respect it, which is a different rule from not overlapping.
    """
    text = plain(text)
    if canvas.measure(text, size, weight) <= width:
        return text
    room = width - canvas.measure(ellipsis, size, weight)
    cut = text
    while cut and canvas.measure(cut, size, weight) > room:
        cut = cut[:-1]
    return (cut.rstrip() + ellipsis) if cut else ellipsis


def fit_rows(count, available, pitch, min_pitch=MIN_ROW_PITCH):
    """How many rows fit, at what pitch, and how many are left over."""
    if count <= 0:
        return 0, pitch, 0
    if count * pitch <= available:
        return count, pitch, 0
    tighter = max(min_pitch, available / count)
    if count * tighter <= available:
        return count, tighter, 0
    shown = max(1, int(available // min_pitch))
    return shown, min_pitch, count - shown


def collisions(canvas, tolerance=1.0):
    """Overlapping text boxes, measured off what was drawn.

    Compared within a zone only. Two panels never share space, so a cross-panel
    pair is a false alarm; inside one, an overlap is a sentence running over a
    label, which is the failure this exists to catch.
    """
    found = []
    by_zone = {}
    for item in canvas.drawn:
        by_zone.setdefault(item.zone, []).append(item)
    for zone, items in by_zone.items():
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                ax1, ay1, ax2, ay2 = a.box
                bx1, by1, bx2, by2 = b.box
                overlap_x = min(ax2, bx2) - max(ax1, bx1)
                overlap_y = min(ay2, by2) - max(ay1, by1)
                if overlap_x > tolerance and overlap_y > tolerance:
                    found.append((zone, a.text, b.text,
                                  round(overlap_x, 1), round(overlap_y, 1)))
    return found


# --------------------------------------------------------------------------
# Icons. Drawn, not typed, for the reason the status marks are: a glyph is a
# property of whatever font the machine happens to have.
# --------------------------------------------------------------------------
def _icon(c, kind, x, y, size=22, colour=BLACK, weight=1.15):
    if kind == "clock":
        c.ellipse(x, y, size, size, outline=colour, width=weight)
        c.line(x + size / 2, y + size * 0.23, x + size / 2, y + size / 2, colour, weight)
        c.line(x + size / 2, y + size / 2, x + size * 0.68, y + size * 0.64, colour, weight)
    elif kind == "warning":
        c.draw.polygon([((x + size / 2) * c.scale, y * c.scale),
                        ((x + size) * c.scale, (y + size * 0.95) * c.scale),
                        (x * c.scale, (y + size * 0.95) * c.scale)],
                       outline=colour, width=max(1, round(weight * c.scale)))
        c.line(x + size / 2, y + size * 0.36, x + size / 2, y + size * 0.64, colour, weight)
        c.ellipse(x + size * 0.46, y + size * 0.72, size * 0.08, size * 0.08, fill=colour)
    elif kind == "people":
        for cx in (0.25, 0.5, 0.75):
            r = size * 0.12
            c.ellipse(x + size * cx - r, y + size * 0.27 - r, r * 2, r * 2,
                      outline=colour, width=weight)
            c.draw.arc([x * c.scale, (y + size * 0.36) * c.scale,
                        (x + size) * c.scale, (y + size * 1.18) * c.scale],
                       180, 360, fill=colour, width=max(1, round(weight * c.scale)))
    elif kind == "bars":
        c.line(x, y + size * 0.91, x + size, y + size * 0.91, colour, weight)
        for i, h in enumerate((0.32, 0.55, 0.77)):
            c.rect(x + size * 0.09 + i * size * 0.32, y + size * 0.91 - size * h,
                   size * 0.2, size * h, outline=colour, width=1)
    elif kind == "target":
        for r in (0.14, 0.33, 0.52):
            c.ellipse(x + size / 2 - size * r, y + size / 2 - size * r,
                      size * r * 2, size * r * 2, outline=colour, width=weight)
    elif kind == "globe":
        c.ellipse(x, y, size, size, outline=colour, width=weight)
        c.ellipse(x + size * 0.27, y, size * 0.46, size, outline=colour, width=weight)
        c.line(x, y + size / 2, x + size, y + size / 2, colour, weight)


def _panel(c, x, y, w, h, eyebrow, title, question):
    c.rect(x, y, w, h, fill=WHITE, outline=GREY_1)
    c.rect(x, y, w, PANEL_HEAD_H, fill=SURFACE, outline=GREY_1)
    c.text(x + 22, y + 16, eyebrow, 11, MEDIUM, GREY_5)
    c.text(x + 22, y + 33, title, 16, MEDIUM, BLACK)
    c.text(x + 22, y + 55, question, 12.5, REGULAR, GREY_5)
    return y + PANEL_HEAD_H


def _insight(c, x, y, w, text):
    if not text:
        return
    c.line(x + 22, y, x + w - 22, y, ROW_ALT, 1)
    c.rect(x + 22, y + 13, 7, 7, fill=GREY_5)
    c.paragraph(x + 39, y + 10, text, 13, REGULAR, GREY_6, w - 78, 21)


def _strip_markup(value):
    """The insight arrives wrapped in the template's own row markup."""
    import re
    return plain(re.sub(r"<[^>]+>", "", str(value))).strip()


def render(view, *, font=None, check=True):
    """Draw the board. Returns (image, FontChoice, collisions)."""
    chosen = font or resolve_font()
    c = Canvas(font=chosen)
    V, ROWS = view["scalars"], view["rows"]
    INS = {k: _strip_markup(v) for k, v in view["insights"].items()}

    # -- header ------------------------------------------------------------
    c.zone = "header"
    y = PAD
    c.rect(PAD, y, 5, 96, fill=ACCENT)
    hx = PAD + 23
    c.text(hx, y + 2, V["eyebrow"], 11, MEDIUM, GREY_5)
    c.text(hx, y + 18, V["title"], 40, LIGHT, BLACK)
    c.paragraph(hx, y + 74, V["subtitle"], 14, REGULAR, GREY_4, 620, 20)

    for i, (label, value) in enumerate((("Reporting period", V["period_label"]),
                                        ("Data as of", V["data_as_of"]),
                                        ("Base", V["base_label"]))):
        yy = y + 4 + i * 22
        c.text(WIDTH - PAD, yy, value, 12.5, MEDIUM, GREY_6, anchor="ra")
        c.text(WIDTH - PAD - c.measure(plain(value), 12.5, MEDIUM) - 12, yy,
               label, 12.5, REGULAR, GREY_4, anchor="ra")

    # -- KPI cards ---------------------------------------------------------
    y = PAD + 140
    card_w = (WIDTH - 2 * PAD - 2 * GUTTER) / 3
    cards = (
        ("Short-notice activities", V["shortnotice_definition"], V["shortnotice_value"],
         V["shortnotice_unit"], V["shortnotice_value_colour"], V["shortnotice_status"],
         V["shortnotice_status_colour"], V["shortnotice_target"], "warning"),
        ("Leadership involvement", V["leadership_definition"], V["leadership_value"],
         V["leadership_unit"], V["leadership_value_colour"], V["leadership_status"],
         V["leadership_status_colour"], V["leadership_target"], "people"),
        ("Activity volume", "Total activities in reporting period", V["volume_value"],
         "", BLACK, V["volume_delta"], V["volume_delta_colour"], V["volume_compare"],
         "bars"),
    )
    for i, (title, defn, value, unit, vcol, st, scol, target, icon) in enumerate(cards):
        c.zone = f"card{i}"
        x = PAD + i * (card_w + GUTTER)
        c.rect(x, y, card_w, CARD_H, fill=WHITE, outline=GREY_1)
        _icon(c, icon, x + 20, y + 21)
        c.text(x + 52, y + 19, title, 13, MEDIUM, BLACK)
        c.paragraph(x + 52, y + 37, defn, 11.5, REGULAR, GREY_5, card_w - 72, 15)
        vw = c.text(x + 20, y + 92, value, 36, LIGHT, vcol)
        if unit:
            c.text(x + 20 + vw + 8, y + 116, unit, 12, REGULAR, GREY_4)
        sw = c.status(x + 20, y + 152, st, scol)
        c.text(x + 20 + sw + 10, y + 152, target, 11.5, REGULAR, GREY_5)

    # -- row one -----------------------------------------------------------
    avail = WIDTH - 2 * PAD - 2 * GUTTER
    w1, w2, w3 = avail * 1.06 / 3, avail * 0.78 / 3, avail * 1.16 / 3
    py = y + CARD_H + GUTTER

    # 01 timing
    c.zone = "timing"
    x = PAD
    by = _panel(c, x, py, w1, PANEL_ROW1_H, "01 · Timing", "Activity load by week",
                "When is the most planned at the same time?")
    lx = x + 22
    for label, colour, kind in ((V["timing_measure"], GREY_3, "square"),
                                ("Peak week", ACCENT, "square"),
                                (V["timing_average_label"], BLACK, "line")):
        if kind == "square":
            c.rect(lx, by + 16, 10, 10, fill=colour)
        else:
            c.line(lx, by + 21, lx + 16, by + 21, BLACK, 1.5)
        lx += 16 + c.text(lx + 16, by + 15, label, 11, REGULAR, GREY_5) + 18

    top, axis_w = by + 48, 32
    plot_x = x + 22 + axis_w + 10
    plot_w = w1 - 44 - axis_w - 10
    ticks = ROWS["timing_axis"]
    for i, row in enumerate(ticks):
        c.text(plot_x - 10, top + i * (TIMING_PLOT_H / (len(ticks) - 1)) - 6,
               row["label"], 11, REGULAR, GREY_5, anchor="ra")
    c.line(plot_x, top + TIMING_PLOT_H, plot_x + plot_w, top + TIMING_PLOT_H, BLACK, 1)

    bars = ROWS["timing_bars"]
    # Fifty-two weeks at a ten-pixel gap is 510 pixels of gap in a 400-pixel
    # plot, and the bar width goes negative. The gap gives first, down to
    # nothing: a chart of touching bars still reads, a chart of negative ones
    # is a stack trace.
    gap = min(10.0, max(0.0, plot_w / max(1, len(bars)) - 2))
    bar_w = (plot_w - gap * (len(bars) - 1)) / len(bars)
    for i, bar in enumerate(bars):
        bx = plot_x + i * (bar_w + gap)
        colour = ACCENT if "accent" in str(bar["colour"]) else bar["colour"]
        c.rect(bx, top + TIMING_PLOT_H - bar["height"], bar_w, bar["height"], fill=colour)

    vb = float(V["timing_viewbox_width"])
    c.polyline([(plot_x + float(p.split(",")[0]) / vb * plot_w,
                 top + float(p.split(",")[1]))
                for p in V["timing_average_points"].split()])

    # A quarter is thirteen weeks; a year is fifty-two, and the sample never
    # said which the board would be handed. Shrink first, then show every k-th
    # -- and never thin away the peak, which is the one week the panel is
    # about.
    tick_texts = [part for l in ROWS["timing_labels"]
                  for part in plain(l["label"]).split(" ")]
    tick_size = fit_label_size(c, tick_texts, bar_w + gap)
    stride = label_stride(c, tick_texts, bar_w + gap, tick_size)
    peaks = {i for i, l in enumerate(ROWS["timing_labels"]) if "600" in l["emphasis"]}
    for i, label in enumerate(ROWS["timing_labels"]):
        strong = i in peaks
        # The peak is drawn whatever the stride says, so its neighbours stand
        # down: a forced label beside a strided one is the collision the stride
        # was calculated to avoid.
        if not strong and (i % stride or any(abs(i - p) < stride for p in peaks)):
            continue
        bx = plot_x + i * (bar_w + gap) + bar_w / 2
        for j, part in enumerate(plain(label["label"]).split(" ")):
            c.text(bx, top + TIMING_PLOT_H + 10 + j * (tick_size + 3), part,
                   tick_size, MEDIUM if strong else REGULAR,
                   BLACK if strong else GREY_5, anchor="ma")
    c.text(x + 22, top + TIMING_PLOT_H + 48, V["timing_axis_caption"], 11, REGULAR, GREY_5)
    detail = plain(V["timing_peak_detail"])
    c.text(x + w1 - 22, top + TIMING_PLOT_H + 48, detail, 11, REGULAR, GREY_5, anchor="ra")
    c.text(x + w1 - 22 - c.measure(detail, 11) - 6, top + TIMING_PLOT_H + 48,
           f"Peak · {plain(V['timing_peak_label'])} ·", 11, MEDIUM, BLACK, anchor="ra")
    _insight(c, x, py + PANEL_ROW1_H - 96, w1, INS["timing_insight"])

    # 02 priority
    c.zone = "priority"
    x2 = PAD + w1 + GUTTER
    by = _panel(c, x2, py, w2, PANEL_ROW1_H, "02 · Prioritisation", "Priority mix",
                "How is the work spread across priority levels?")
    cx, cy, radius, ring = x2 + 98, by + 100, 76, 22
    angle = -90.0
    for row in ROWS["priority_legend"]:
        extent = float(row["share"].rstrip("%")) / 100 * 360
        c.pieslice(cx, cy, radius, angle, angle + extent, row["colour"])
        angle += extent
    c.ellipse(cx - radius + ring, cy - radius + ring,
              (radius - ring) * 2, (radius - ring) * 2, fill=WHITE)
    c.text(cx, cy - 14, V["priority_total"], 26, LIGHT, BLACK, anchor="ma")
    c.text(cx, cy + 14, "Activities", 11, REGULAR, GREY_5, anchor="ma")
    ly = by + 26
    for row in ROWS["priority_legend"]:
        c.rect(x2 + 186, ly, 10, 10, fill=row["colour"])
        c.text(x2 + 206, ly - 3, f"{plain(row['label'])} · {row['share']}", 12.5, MEDIUM, BLACK)
        c.text(x2 + 206, ly + 14, row["detail"], 11, REGULAR, GREY_5)
        ly += 38
    _insight(c, x2, py + PANEL_ROW1_H - 96, w2, INS["priority_insight"])

    # 03 ownership
    c.zone = "ownership"
    x3 = x2 + w2 + GUTTER
    by = _panel(c, x3, py, w3, PANEL_ROW1_H, "03 · Ownership", "Team distribution",
                "Which communications teams carry the largest share of planning?")
    ry = by + 22
    track_x = x3 + 22 + 186 + 12
    track_w = w3 - 44 - 186 - 42 - 24
    rows = ROWS["ownership_rows"]
    # Room between the header and the axis, insight and scale reserved.
    room = (py + PANEL_ROW1_H - 96) - ry - 34
    shown, pitch, dropped = fit_rows(len(rows), room, 28)
    for row in rows[:shown]:
        strong = "600" in row["emphasis"]
        c.text(x3 + 22, ry + 2,
               clip_text(c, row["label"], 186 - 8, 12.5,
                         MEDIUM if strong else REGULAR),
               12.5, MEDIUM if strong else REGULAR, BLACK if strong else GREY_6)
        c.rect(track_x, ry, track_w, 18, fill=ROW_ALT)
        c.rect(track_x, ry, track_w * float(row["width"].rstrip("%")) / 100, 18,
               fill=row["colour"])
        c.text(x3 + w3 - 22, ry + 2, row["share"], 12.5,
               MEDIUM if strong else REGULAR, BLACK if strong else GREY_6, anchor="ra")
        ry += pitch
    if dropped:
        # Named, not dropped. A distribution that quietly stops short is the
        # failure this panel already reports for its unnamed residual.
        rest = sum(float(r["share"].rstrip("%")) for r in rows[shown:])
        c.text(x3 + 22, ry + 2,
               f"{dropped} more team{'' if dropped == 1 else 's'}",
               12.5, REGULAR, GREY_5)
        c.text(x3 + w3 - 22, ry + 2, f"{rest:.0f}%", 12.5, REGULAR, GREY_5,
               anchor="ra")
        ry += pitch
    c.line(track_x, ry + 2, track_x + track_w, ry + 2, BLACK, 1)
    scale = ROWS["ownership_scale"]
    for i, step in enumerate(scale):
        c.text(track_x + i * (track_w / (len(scale) - 1)), ry + 8, step["label"], 11,
               REGULAR, GREY_5,
               anchor="la" if i == 0 else ("ra" if i == len(scale) - 1 else "ma"))
    _insight(c, x3, py + PANEL_ROW1_H - 96, w3, INS["ownership_insight"])

    # -- row two -----------------------------------------------------------
    py2 = py + PANEL_ROW1_H + GUTTER
    avail2 = WIDTH - 2 * PAD - GUTTER
    w4, w5 = avail2 * 1.62 / 2.62, avail2 / 2.62

    c.zone = "leadership"
    x = PAD
    by = _panel(c, x, py2, w4, PANEL_ROW2_H, "04 · Leadership",
                "Leadership involvement by team",
                "Where is leadership already well involved — and where too little?")
    top, inner_x = by + 26, x + 22
    inner_w = w4 - 44
    lead = ROWS["leadership_bars"]
    names = ROWS["leadership_labels"]
    # A rate per team cannot be summarised into an "others" bar -- averaging
    # shares invents a figure. So this panel caps and says how many it is
    # showing, where the distribution panel above sums its residual instead.
    gap4 = 24 if len(lead) <= 8 else 12
    # How many fit is decided by the names, not by the bars. A bar can be four
    # pixels wide and still read; "Corporate Banking" at the smallest legible
    # size cannot be squeezed, so the widest line a team name draws is what
    # sets the column, and the column sets the count.
    widest_name = max((c.measure(part, MIN_LABEL_SIZE)
                       for l in names
                       for part in plain(l["label"]).split("<br>")), default=1.0)
    lead_capacity = max(1, int(inner_w // (widest_name * LABEL_MARGIN)))
    lead_dropped = max(0, len(lead) - lead_capacity)
    lead, names = lead[:lead_capacity], names[:lead_capacity]
    bar_w = (inner_w - gap4 * (len(lead) - 1)) / len(lead)
    c.line(inner_x, top + LEADERSHIP_PLOT_H, inner_x + inner_w, top + LEADERSHIP_PLOT_H, BLACK, 1)
    avg_y = top + LEADERSHIP_PLOT_H - float(V["leadership_average_offset"])
    c.dashed(inner_x, avg_y, inner_x + inner_w)
    # Above the plot, not beside the line. Sitting by the line puts it exactly
    # where a bar at the average has its own label, and a bar at the average is
    # the ordinary case rather than the awkward one.
    c.text(inner_x + inner_w, top - 18, V["leadership_average_label"], 11,
           REGULAR, GREY_5, anchor="ra")
    for i, bar in enumerate(lead):
        bx = inner_x + i * (bar_w + gap4)
        c.rect(bx, top + LEADERSHIP_PLOT_H - bar["height"], bar_w, bar["height"],
               fill=bar["colour"])
        c.text(bx + bar_w / 2, top + LEADERSHIP_PLOT_H - bar["height"] - 18,
               bar["share"], 12.5, MEDIUM, bar["label_colour"], anchor="ma")
    name_size = fit_label_size(
        c, [part for l in names for part in plain(l["label"]).split("<br>")],
        bar_w + gap4 - 4)
    for i, label in enumerate(names):
        bx = inner_x + i * (bar_w + gap4) + bar_w / 2
        strong = "600" in label["emphasis"]
        for j, part in enumerate(plain(label["label"]).split("<br>")):
            c.text(bx, top + LEADERSHIP_PLOT_H + 10 + j * (name_size + 4), part,
                   name_size, MEDIUM if strong else REGULAR,
                   BLACK if strong else GREY_5, anchor="ma")
    if lead_dropped:
        c.text(inner_x + inner_w, top + LEADERSHIP_PLOT_H + 44,
               f"showing the {len(lead)} highest of "
               f"{len(lead) + lead_dropped} teams",
               11, REGULAR, GREY_5, anchor="ra")
    _insight(c, x, py2 + PANEL_ROW2_H - 86, w4, INS["leadership_insight"])

    c.zone = "reach"
    x5 = PAD + w4 + GUTTER
    by = _panel(c, x5, py2, w5, PANEL_ROW2_H, "05 · Reach", "Reach & involvement",
                "How much of the portfolio is large-scale, external or executive-led?")
    ry = by + 18
    rows = ((V["reach_executive_value"], V["reach_executive_colour"],
             "Activities with executive involvement", V["reach_executive_detail"], "people"),
            (V["reach_large_value"], BLACK, "Activities with large audience",
             V["reach_large_detail"], "target"),
            (None, BLACK, "Internal vs. external split", V["reach_split_detail"], "globe"))
    for value, colour, title, detail, icon in rows:
        _icon(c, icon, x5 + 22, ry + 8)
        if value is not None:
            c.text(x5 + 58, ry + 6, value, 28, LIGHT, colour)
        else:
            c.text(x5 + 58, ry + 2, V["reach_internal_share"], 28, LIGHT, BLACK)
            c.text(x5 + 58, ry + 30, V["reach_external_share"], 16, LIGHT, GREY_5)
        tx = x5 + 142
        c.text(tx, ry + 6, title, 12.5, MEDIUM, BLACK)
        if icon != "globe":
            c.text(tx, ry + 24, detail, 11, REGULAR, GREY_5)
        else:
            bar_w2 = w5 - (tx - x5) - 22
            share = float(V["reach_internal_share"].rstrip("%")) / 100
            c.rect(tx, ry + 44, bar_w2, 10, fill=ROW_ALT)
            c.rect(tx, ry + 44, bar_w2 * share, 10, fill=GREY_5)
            c.rect(tx + bar_w2 * share, ry + 44, bar_w2 * (1 - share), 10, fill=GREY_1)
            c.text(tx, ry + 60, detail, 11, REGULAR, GREY_5)
        ry += 84 if icon == "globe" else 68
        if icon != "globe":
            c.line(x5 + 22, ry - 12, x5 + w5 - 22, ry - 12, ROW_ALT, 1)
    _insight(c, x5, py2 + PANEL_ROW2_H - 86, w5, INS["reach_insight"])

    # -- footer ------------------------------------------------------------
    c.zone = "footer"
    fy = py2 + PANEL_ROW2_H + 28
    c.line(PAD, fy, WIDTH - PAD, fy, BLACK, 1)
    c.paragraph(PAD, fy + 16, V["footer_notes"], 11, REGULAR, GREY_5, 470, 17)
    for i, line in enumerate(plain(V["footer_source"]).split("<br>")):
        c.text(WIDTH - PAD, fy + 16 + i * 17, line, 11, REGULAR, GREY_5, anchor="ra")

    overlaps = collisions(c)
    if check and overlaps:
        raise RuntimeError(
            "text collides with text in the drawn board: "
            + "; ".join(f"[{z}] {a!r} over {b!r}" for z, a, b, _, _ in overlaps[:4])
        )
    return c.image.resize((WIDTH, HEIGHT), Image.LANCZOS), chosen, overlaps


def save(view, path, *, font=None, check=True):
    """Write the board as PNG or PDF, chosen by the path's suffix."""
    image, chosen, overlaps = render(view, font=font, check=check)
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        image.save(path, "PDF", resolution=144.0)
    else:
        image.save(path)
    return chosen, overlaps

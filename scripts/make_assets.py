#!/usr/bin/env python3
"""Generates the PNG skin assets in src/JellyfinOpenPLi/images (original artwork).

Enigma2 fills (eLabel backgroundColor) overwrite pixels instead of blending, so every
translucent layer (gradients, glass panels, rounded frames, badges) is an alpha PNG
that the box blends with alphatest="blend".
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from JellyfinOpenPLi.jfi18n import BADGES, badge_file  # noqa: E402 (pure python, no enigma imports)
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "src", "JellyfinOpenPLi", "images")
FB = os.environ.get("ASSET_FONT_BOLD", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
BG = (11, 11, 16)
ACCENT = (0, 164, 220)
PURPLE = (170, 92, 195)
GREEN = (67, 160, 71)
SS = 4
os.makedirs(OUT, exist_ok=True)


def gradient_overlay(w, h, fn):
	img = Image.new("RGBA", (w, h))
	px = img.load()
	for y in range(h):
		for x in range(w):
			px[x, y] = BG + (int(max(0.0, min(1.0, fn(x / float(w), y / float(h)))) * 255),)
	return img


def rounded(w, h, r, fill, outline=None, width=0):
	big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
	d = ImageDraw.Draw(big)
	d.rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], radius=r * SS, fill=fill, outline=outline, width=width * SS)
	return big.resize((w, h), Image.LANCZOS)


def glass(w, h, r=22, tint=(255, 255, 255), alpha=22, border=58):
	"""Translucent panel with a soft top highlight and a thin light border."""
	base = rounded(w, h, r, tint + (alpha,), outline=tint + (border,), width=2)
	hl = Image.new("RGBA", (w, h), (0, 0, 0, 0))
	hd = ImageDraw.Draw(hl)
	for y in range(int(h * 0.45)):
		a = int(16 * (1 - y / (h * 0.45)))
		hd.line([(0, y), (w, y)], fill=(255, 255, 255, a))
	mask = rounded(w, h, r, (255, 255, 255, 255)).split()[3]
	hl.putalpha(Image.composite(hl.split()[3], Image.new("L", (w, h), 0), mask))
	return Image.alpha_composite(base, hl)


def font(size):
	return ImageFont.truetype(FB, size)


def badge(text, w, h, color):
	img = rounded(w, h, h // 3, color + (255,))
	d = ImageDraw.Draw(img)
	if d.textlength(text, font=font(int(h * 0.62))) > w - 12:
		sys.exit("badge text %r does not fit into %d px" % (text, w))
	d.text((w / 2, h / 2 + 1), text, font=font(int(h * 0.62)), fill=(255, 255, 255, 255), anchor="mm")
	return img


def icon(kind, size=44, color=(235, 235, 240, 255)):
	s = size * SS
	img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
	d = ImageDraw.Draw(img)
	lw = int(s * 0.09)
	if kind == "search":
		r = s * 0.30
		d.ellipse([s * 0.12, s * 0.12, s * 0.12 + 2 * r, s * 0.12 + 2 * r], outline=color, width=lw)
		d.line([s * 0.62, s * 0.62, s * 0.88, s * 0.88], fill=color, width=lw)
	elif kind == "home":
		d.polygon([(s * 0.5, s * 0.10), (s * 0.92, s * 0.48), (s * 0.08, s * 0.48)], fill=color)
		d.rectangle([s * 0.2, s * 0.46, s * 0.8, s * 0.88], fill=color)
		d.rectangle([s * 0.42, s * 0.62, s * 0.58, s * 0.88], fill=(0, 0, 0, 0))
	elif kind == "movies":
		d.rounded_rectangle([s * 0.1, s * 0.3, s * 0.9, s * 0.88], radius=s * 0.06, outline=color, width=lw)
		for i in range(4):
			x = s * (0.12 + i * 0.2)
			d.polygon([(x, s * 0.12), (x + s * 0.1, s * 0.12), (x + s * 0.17, s * 0.28), (x + s * 0.07, s * 0.28)], fill=color)
	elif kind == "tv":
		d.rounded_rectangle([s * 0.08, s * 0.16, s * 0.92, s * 0.72], radius=s * 0.06, outline=color, width=lw)
		d.line([s * 0.3, s * 0.88, s * 0.7, s * 0.88], fill=color, width=lw)
	elif kind == "lists":
		for i in range(3):
			y = s * (0.22 + i * 0.28)
			d.ellipse([s * 0.08, y - s * 0.06, s * 0.2, y + s * 0.06], fill=color)
			d.line([s * 0.3, y, s * 0.92, y], fill=color, width=lw)
	elif kind == "settings":
		c = s / 2
		for i in range(8):
			a = i * math.pi / 4
			d.line([c + math.cos(a) * s * 0.18, c + math.sin(a) * s * 0.18, c + math.cos(a) * s * 0.42, c + math.sin(a) * s * 0.42], fill=color, width=int(lw * 1.6))
		d.ellipse([c - s * 0.30, c - s * 0.30, c + s * 0.30, c + s * 0.30], fill=color)
		d.ellipse([c - s * 0.13, c - s * 0.13, c + s * 0.13, c + s * 0.13], fill=(0, 0, 0, 0))
	elif kind == "play":
		d.polygon([(s * 0.22, s * 0.12), (s * 0.22, s * 0.88), (s * 0.88, s * 0.5)], fill=color)
	elif kind == "info":
		d.ellipse([s * 0.08, s * 0.08, s * 0.92, s * 0.92], outline=color, width=lw)
		d.ellipse([s * 0.45, s * 0.24, s * 0.55, s * 0.34], fill=color)
		d.rectangle([s * 0.45, s * 0.42, s * 0.55, s * 0.76], fill=color)
	elif kind == "person":
		d.ellipse([s * 0.30, s * 0.10, s * 0.70, s * 0.50], fill=color)
		d.pieslice([s * 0.10, s * 0.52, s * 0.90, s * 1.30], 180, 360, fill=color)
	return img.resize((size, size), Image.LANCZOS)


# ------------------------------------------------------------------ assets
def _c(v):
	return max(0.0, min(1.0, v))


def hero_alpha(fx, fy):
	side = _c((1 - fx / 0.74) * 1.3) ** 1.2 * 0.93
	bottom = (0.0 if fy < 0.50 else _c((fy - 0.50) / 0.26)) ** 1.1 * 0.97
	return max(0.12, side, bottom)


def detail_alpha(fx, fy):
	"""Text column on the left, the picture stays clearly visible on the right half."""
	side = _c((0.74 - fx) / 0.26) ** 1.1 * 0.90
	bottom = (0.0 if fy < 0.64 else _c((fy - 0.64) / 0.22)) ** 1.2 * 0.94
	return max(0.08, side, bottom)


def rail_alpha(fx, fy):
	a = _c(1.15 - fx / 0.42) * 0.9
	return a if fy < 0.6 else a * _c((0.75 - fy) / 0.15)


def full_overlay(fn):
	"""Gradients are computed at half size and enlarged (smooth anyway)."""
	return gradient_overlay(960, 540, fn).resize((1920, 1080), Image.BICUBIC)


ASSETS = {}


def asset(name, img):
	ASSETS[name] = img


asset("hero_overlay.png", full_overlay(hero_alpha))
asset("dim_overlay.png", full_overlay(lambda fx, fy: 0.80 + 0.16 * _c((fy - 0.70) / 0.30)))
asset("rail_overlay.png", full_overlay(rail_alpha))
asset("detail_overlay.png", full_overlay(detail_alpha))
for name, (w, h, r) in {
	"glass_list.png": (1240, 600, 24),
	"glass_info.png": (1820, 168, 22),
	"glass_episodes.png": (1820, 712, 24),
	"glass_menu.png": (540, 872, 24),
}.items():
	asset(name, glass(w, h, r))
asset("frame_poster.png", rounded(216, 316, 14, (0, 0, 0, 0), outline=(255, 255, 255, 255), width=4))
asset("frame_card.png", rounded(316, 185, 14, (0, 0, 0, 0), outline=(255, 255, 255, 255), width=4))
asset("frame_person.png", rounded(146, 211, 12, (0, 0, 0, 0), outline=(255, 255, 255, 255), width=4))
asset("pill_primary.png", rounded(280, 64, 32, (245, 245, 248, 255)))
asset("pill_secondary.png", glass(280, 64, 32, alpha=40, border=70))
asset("rail_sel.png", rounded(72, 72, 36, ACCENT + (255,)))
for kind, color in (("new", PURPLE), ("seen", GREEN)):
	for lang, (text, width) in BADGES[kind].items():
		asset(badge_file(kind, lang), badge(text, width, 28, color))
for k in ("search", "home", "movies", "tv", "lists", "settings"):
	asset("icon_%s.png" % k, icon(k))
asset("icon_play_dark.png", icon("play", 28, (16, 16, 22, 255)))
asset("icon_info.png", icon("info", 28))
# player overlay ("Intro überspringen", countdown to the next episode): dark enough to read over any picture


def osd_panel(w, h, r=24):
	base = rounded(w, h, r, (12, 12, 18, 222), outline=(255, 255, 255, 60), width=2)
	bar = rounded(w, h, r, (0, 0, 0, 0))
	d = ImageDraw.Draw(bar)
	d.rectangle([0, 0, 8, h], fill=ACCENT + (255,))
	mask = rounded(w, h, r, (255, 255, 255, 255)).split()[3]
	bar.putalpha(Image.composite(bar.split()[3], Image.new("L", (w, h), 0), mask))
	return Image.alpha_composite(base, bar)


def keycap(text, w, h):
	img = rounded(w, h, h // 2, (245, 245, 248, 255))
	ImageDraw.Draw(img).text((w / 2, h / 2 + 1), text, font=font(int(h * 0.48)), fill=(16, 16, 22, 255), anchor="mm")
	return img


asset("osd_panel.png", osd_panel(640, 132))
asset("key_ok.png", keycap("OK", 92, 52))

# 1080p pixel exact in images/, 720p (2/3, rounded like the skin scaler) in images/hd/
for f in os.listdir(OUT):
	if f.endswith(".png"):
		os.remove(os.path.join(OUT, f))
HD = os.path.join(OUT, "hd")
os.makedirs(HD, exist_ok=True)
for f in os.listdir(HD):
	os.remove(os.path.join(HD, f))
for name, im in sorted(ASSETS.items()):
	im.save(os.path.join(OUT, name), optimize=True)
	w, h = im.size
	small = im.resize((int(round(w * 2 / 3.0)), int(round(h * 2 / 3.0))), Image.LANCZOS)
	small.save(os.path.join(HD, name), optimize=True)
print("%d assets written to %s (+ hd/)" % (len(ASSETS), OUT))

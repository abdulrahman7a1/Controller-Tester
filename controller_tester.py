"""
DualSense Tester
================
A simple desktop controller tester with a live 2D controller drawing.
Supports DualSense (PS5), DualShock 4 (PS4), Xbox One and Xbox Series X|S.

Setup (once):   pip install pygame-ce
Run:            python controller_tester.py

Pages (sidebar on the left, or press Tab)
  Controller  the controller lights up as you press buttons, plus both sticks
              (with drift), the triggers and the update rate in Hz (hertz,
              updates per second). Over USB (Universal Serial Bus) a DualSense
              shows about 250 Hz.
  Details     device info incl. VID / PID (Vendor ID / Product ID), raw button
              and axis values, recent presses and a circularity test.
  Settings    General: start with Windows, dark / light mode, stick trails,
              deadzone, button layout, vibration test.
              Design: pick the controller drawing and its colour.
              Light bar: set the DualSense / DualShock 4 light colour
              (presets, RGB (red, green, blue) sliders, brightness, and
              static / breathing / rainbow effects). Needs pygame-ce 2.5.6+.

Keys
  Closing or minimizing hides the app to the system tray (needs
  pip install pystray pillow). Right-click the tray icon to quit.

  Tab  next page     T  colour     M  controller model     V  vibration test
  C    circularity test            F1 button layout        R  reset stats
  Up / Down  deadzone ring         ESC quit

Settings are saved in %APPDATA%\\DualSenseTester\\settings.json.
Tip: close Steam and DS4Windows first so they don't take over the controller.
"""

import os
import sys
import json
import colorsys
import math
import time
from collections import deque

os.environ.setdefault("SDL_JOYSTICK_HIDAPI_PS5", "1")  # SDL's native DualSense driver
os.environ.setdefault("SDL_JOYSTICK_HIDAPI_PS4", "1")
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")

import pygame
import pygame.gfxdraw

APP_NAME = "DualSense Tester"
W, H = 1260, 780
RAIL = 76                 # sidebar width
CW = W - RAIL             # content width
DRAW_FPS = 60

# --------------------------------------------------------------------------
# Interface colours (dark / light). The names below are swapped at runtime.
# --------------------------------------------------------------------------
PALETTES = {
    "dark": dict(BG=(14, 16, 21), SURFACE=(22, 25, 32), SURFACE_2=(31, 35, 44), RAILBG=(18, 20, 26),
                 LINE=(40, 44, 55), TEXT=(236, 238, 243), MUTED=(140, 146, 160), FAINT=(86, 92, 106),
                 ACCENT=(64, 140, 255), SHADOW=90),
    "light": dict(BG=(241, 243, 247), SURFACE=(255, 255, 255), SURFACE_2=(232, 236, 243), RAILBG=(250, 251, 253),
                  LINE=(221, 225, 233), TEXT=(24, 27, 35), MUTED=(98, 105, 120), FAINT=(160, 166, 178),
                  ACCENT=(30, 110, 240), SHADOW=45),
}
BG = SURFACE = SURFACE_2 = RAILBG = LINE = TEXT = MUTED = FAINT = ACCENT = None
SHADOW = 90
GOOD = (52, 186, 118)
WARN = (232, 160, 40)
BAD = (230, 80, 80)
MIC_ORANGE = (255, 140, 40)


def apply_palette(mode):
    globals().update(PALETTES.get(mode, PALETTES["dark"]))


apply_palette("dark")

PS_SYMBOL = {"triangle": (40, 196, 160), "circle": (238, 76, 96), "cross": (90, 150, 245), "square": (226, 110, 200)}
XB_LETTER = {"cross": (100, 190, 70), "circle": (228, 64, 64), "square": (50, 130, 230), "triangle": (236, 184, 30)}

# --------------------------------------------------------------------------
# Button layouts. Internal names follow PlayStation, positions are universal:
# cross = bottom face button (Xbox A), circle = right (B), square = left (X),
# triangle = top (Y), create = View, options = Menu, ps = Xbox button,
# mic = Share on Xbox Series.
# --------------------------------------------------------------------------
LAYOUTS = {
    "SDL": dict(
        label="SDL",
        buttons={"cross": 0, "circle": 1, "square": 2, "triangle": 3, "create": 4, "ps": 5,
                 "options": 6, "l3": 7, "r3": 8, "l1": 9, "r1": 10, "up": 11, "down": 12,
                 "left": 13, "right": 14, "touchpad": 15, "mic": 16},
        axes=dict(lx=0, ly=1, rx=2, ry=3, l2=4, r2=5),
    ),
    "DirectInput": dict(
        label="DirectInput",
        buttons={"square": 0, "cross": 1, "circle": 2, "triangle": 3, "l1": 4, "r1": 5,
                 "l2btn": 6, "r2btn": 7, "create": 8, "options": 9, "l3": 10, "r3": 11,
                 "ps": 12, "touchpad": 13},
        axes=dict(lx=0, ly=1, rx=2, l2=3, r2=4, ry=5),
    ),
    "XInput": dict(
        label="XInput",
        buttons={"cross": 0, "circle": 1, "square": 2, "triangle": 3, "l1": 4, "r1": 5,
                 "create": 6, "options": 7, "l3": 8, "r3": 9, "ps": 10},
        axes=dict(lx=0, ly=1, rx=2, ry=3, l2=4, r2=5),
    ),
}
BUTTON_KEYS = ["cross", "circle", "square", "triangle", "create", "ps", "options", "l3", "r3", "l1", "r1",
               "up", "down", "left", "right", "touchpad", "mic", "l2btn", "r2btn"]

PS_NAMES = {"cross": "Cross", "circle": "Circle", "square": "Square", "triangle": "Triangle",
            "create": "Create", "ps": "PS", "options": "Options", "l3": "L3", "r3": "R3", "l1": "L1",
            "r1": "R1", "up": "Up", "down": "Down", "left": "Left", "right": "Right",
            "touchpad": "Touchpad", "mic": "Mic", "l2btn": "L2", "r2btn": "R2"}
XB_NAMES = {"cross": "A", "circle": "B", "square": "X", "triangle": "Y", "create": "View", "ps": "Xbox",
            "options": "Menu", "l3": "LS", "r3": "RS", "l1": "LB", "r1": "RB", "up": "Up", "down": "Down",
            "left": "Left", "right": "Right", "touchpad": "Touchpad", "mic": "Share", "l2btn": "LT", "r2btn": "RT"}

# --------------------------------------------------------------------------
# Geometry helpers (all controllers are drawn in a 1000 x 660 design space)
# --------------------------------------------------------------------------
DW, DH = 1000, 660


def catmull_rom(points, samples=10):
    """Smooth closed curve through the given points."""
    out = []
    n = len(points)
    for i in range(n):
        p0, p1, p2, p3 = points[i - 1], points[i], points[(i + 1) % n], points[(i + 2) % n]
        for k in range(samples):
            t = k / samples
            t2, t3 = t * t, t * t * t
            out.append(tuple(
                0.5 * (2 * p1[j] + (-p0[j] + p2[j]) * t
                       + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                       + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3)
                for j in (0, 1)))
    return out


def mirrored(half):
    """half runs from top-centre down the left side to bottom-centre."""
    return half + [(DW - x, y) for x, y in reversed(half[1:-1])]


def smooth_half(half, samples=12):
    return catmull_rom(mirrored(half), samples)


def rotate(pts, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [(x * c - y * s, x * s + y * c) for x, y in pts]


ARROW_UP = [(-19, -70), (19, -70), (22, -64), (22, -32), (0, -14), (-22, -32), (-22, -64)]

# ---- DualSense (PS5), traced from the DualSense line drawing ----
DS5_LIGHT = [(331, 150), (334, 210), (341, 246), (358, 270), (384, 288)]
DS5 = dict(
    name="DualSense", sub="PS5", family="ps",
    body=smooth_half([(500, 92), (395, 95), (286, 98), (203, 106), (170, 117), (143, 136), (121, 178),
                      (101, 232), (82, 301), (71, 384), (66, 466), (66, 535), (74, 590), (93, 626),
                      (126, 642), (162, 648), (195, 637), (217, 590), (239, 535), (263, 488), (291, 461),
                      (335, 450), (423, 450), (500, 450)]),
    panel=smooth_half([(500, 285), (395, 285), (318, 288), (285, 321), (255, 373), (225, 439), (198, 521),
                       (170, 604), (151, 653), (258, 741), (500, 741)]),
    touchpad=catmull_rom([(352, 95), (500, 95), (648, 95), (665, 96), (662, 140), (659, 246), (646, 266),
                          (620, 279), (500, 281), (380, 279), (354, 266), (341, 246), (338, 140), (335, 96)], 6),
    lightbars=[DS5_LIGHT, [(DW - x, y) for x, y in DS5_LIGHT]],
    bumper=catmull_rom([(132, 146), (150, 106), (194, 84), (252, 76), (304, 82), (322, 100), (250, 102),
                        (186, 114)], 6),
    trigger=catmull_rom([(166, 96), (174, 58), (206, 34), (256, 30), (290, 44), (302, 88)], 6),
    speaker=(500, 309, 16.5, (5, 4)),
    dpad=(231, 237), dpad_style="arrows", arrow_k=1.08, face=(769, 236), face_style="ps", face_colored=False,
    face_gap=66, face_r=28,
    stick_l=(362, 356), stick_r=(638, 356), well_r=60, cap_r=45, move=15,
    home=(500, 359), home_r=16,
    select=(293, 160), start=(707, 160), small_style="slant", small_len=34, misc=(500, 402), misc_w=38,
    recess=False,
    themes=[
        ("White", dict(body=(240, 242, 246), panel=(32, 35, 43), touch=(232, 235, 241),
                       btn=(226, 229, 236), symbol=(120, 126, 140), stick=(44, 48, 58))),
        ("Midnight Black", dict(body=(54, 57, 66), panel=(28, 30, 36), touch=(62, 66, 76),
                                btn=(70, 74, 86), symbol=(160, 166, 180), stick=(36, 39, 47))),
        ("Starlight Blue", dict(body=(130, 174, 222), panel=(36, 50, 74), touch=(150, 190, 232),
                                btn=(232, 238, 246), symbol=(100, 118, 146), stick=(236, 240, 246))),
        ("Cosmic Red", dict(body=(170, 36, 50), panel=(30, 24, 30), touch=(182, 50, 64),
                            btn=(46, 40, 46), symbol=(186, 166, 174), stick=(34, 30, 36))),
    ],
)

# ---- DualShock 4 (PS4), traced from the DualShock 4 photo ----
DS4 = dict(
    name="DualShock 4", sub="PS4", family="ps",
    body=smooth_half([(500, 115), (369, 115), (309, 106), (234, 98), (189, 106), (151, 143), (125, 196),
                      (106, 263), (95, 338), (87, 413), (87, 488), (95, 563), (114, 616), (144, 642),
                      (189, 649), (234, 638), (264, 601), (286, 541), (301, 488), (320, 455), (361, 432),
                      (421, 425), (500, 423)]),
    panel=None,
    touchpad=catmull_rom([(380, 117), (500, 117), (620, 117), (635, 120), (636, 140), (634, 232), (626, 245),
                          (610, 249), (500, 249), (390, 249), (374, 245), (366, 232), (364, 140), (365, 120)], 6),
    lightbars=[[(392, 123), (608, 123)]],
    bumper=catmull_rom([(136, 150), (156, 110), (200, 86), (258, 78), (310, 84), (330, 102), (258, 104),
                        (192, 116)], 6),
    trigger=catmull_rom([(176, 98), (184, 60), (216, 38), (266, 34), (300, 48), (312, 92)], 6),
    speaker=(500, 279, 13, (6, 5)),
    dpad=(243, 217), dpad_style="arrows", arrow_k=1.0, face=(757, 217), face_style="ps", face_colored=True,
    face_gap=62, face_r=27,
    stick_l=(367, 312), stick_r=(633, 312), well_r=66, cap_r=48, move=16,
    home=(500, 335), home_r=15,
    select=(335, 145), start=(665, 145), small_style="slant", small_len=28, misc=None, recess=True,
    recess_r=92,
    themes=[
        ("Jet Black", dict(body=(44, 46, 53), panel=None, touch=(52, 55, 63),
                           btn=(34, 36, 42), symbol=(150, 156, 170), stick=(32, 34, 40))),
        ("Glacier White", dict(body=(238, 240, 244), panel=None, touch=(226, 229, 235),
                               btn=(226, 229, 235), symbol=(150, 156, 170), stick=(228, 231, 237))),
        ("Wave Blue", dict(body=(46, 98, 178), panel=None, touch=(56, 110, 190),
                           btn=(32, 62, 114), symbol=(170, 190, 226), stick=(32, 62, 114))),
        ("Magma Red", dict(body=(178, 34, 46), panel=None, touch=(190, 46, 58),
                           btn=(122, 22, 32), symbol=(226, 186, 192), stick=(122, 22, 32))),
    ],
)

# ---- Xbox (traced from a flat Xbox Series illustration; Xbox One shares the outline) ----
XB_BODY = smooth_half([(500, 107), (379, 110), (313, 118), (238, 135), (179, 185), (149, 260), (132, 360),
                       (126, 444), (129, 528), (146, 586), (179, 614), (213, 616), (246, 594), (296, 536),
                       (346, 486), (396, 466), (500, 462)])
XB_COMMON = dict(
    family="xbox", body=XB_BODY, panel=None, touchpad=None, lightbars=[], speaker=None,
    bumper=catmull_rom([(186, 172), (198, 136), (232, 108), (286, 94), (346, 92), (386, 100), (392, 120),
                        (330, 118), (262, 126), (216, 150)], 6),
    trigger=catmull_rom([(238, 104), (248, 70), (284, 50), (330, 48), (358, 62), (364, 100)], 6),
    face_style="xbox", face_colored=True, face_gap=47, face_r=23,
    small_style="round", recess=False,
)
XSERIES = dict(XB_COMMON, name="Xbox Series X|S", sub="Series X|S", dpad_style="disc",
               stick_l=(313, 235), dpad=(405, 352), stick_r=(597, 352), face=(692, 240),
               home=(500, 160), home_r=26, select=(444, 239), start=(556, 239), misc=(500, 282),
               well_r=54, cap_r=40, move=14, cross=(16, 46),
               themes=[
                   ("Robot White", dict(body=(242, 243, 246), panel=None, touch=None,
                                        btn=(52, 55, 62), symbol=(150, 156, 170), stick=(52, 55, 62))),
                   ("Carbon Black", dict(body=(46, 48, 54), panel=None, touch=None,
                                         btn=(30, 31, 35), symbol=(150, 156, 170), stick=(30, 31, 35))),
                   ("Shock Blue", dict(body=(36, 114, 202), panel=None, touch=None,
                                       btn=(238, 240, 244), symbol=(110, 124, 146), stick=(238, 240, 244))),
                   ("Pulse Red", dict(body=(198, 36, 46), panel=None, touch=None,
                                      btn=(34, 34, 38), symbol=(170, 160, 164), stick=(34, 34, 38))),
               ])
XONE = dict(XB_COMMON, name="Xbox One", sub="Xbox One", dpad_style="cross",
            body=smooth_half([(500, 108), (408, 108), (378, 113), (288, 118), (208, 131), (173, 153),
                              (143, 203), (118, 283), (98, 383), (83, 473), (78, 553), (88, 603), (118, 628),
                              (168, 633), (208, 623), (248, 588), (288, 548), (333, 513), (388, 498),
                              (448, 491), (500, 489)]),
            bumper=catmull_rom([(190, 150), (202, 108), (238, 84), (298, 74), (358, 76), (384, 92), (388, 120),
                                (320, 118), (250, 128)], 6),
            trigger=catmull_rom([(238, 96), (248, 60), (288, 42), (338, 42), (366, 60), (370, 100)], 6),
            stick_l=(283, 253), dpad=(391, 388), stick_r=(615, 378), face=(743, 238),
            face_gap=65, face_r=26, well_r=60, cap_r=44, move=16,
            home=(500, 153), home_r=28, select=(437, 245), start=(563, 245), misc=None, cross=(19, 58),
            themes=[
                ("Black", dict(body=(48, 50, 56), panel=None, touch=None, btn=(30, 31, 35),
                               symbol=(150, 156, 170), stick=(32, 33, 37))),
                ("White", dict(body=(242, 243, 246), panel=None, touch=None, btn=(40, 42, 48),
                               symbol=(150, 156, 170), stick=(40, 42, 48))),
                ("Blue", dict(body=(42, 106, 188), panel=None, touch=None, btn=(28, 32, 40),
                              symbol=(160, 170, 190), stick=(28, 32, 40))),
                ("Red", dict(body=(186, 34, 44), panel=None, touch=None, btn=(28, 28, 32),
                             symbol=(170, 160, 164), stick=(28, 28, 32))),
            ])

MODELS = {"ds5": DS5, "ds4": DS4, "xone": XONE, "series": XSERIES}
MODEL_ORDER = ["ds5", "ds4", "xone", "series"]


# --------------------------------------------------------------------------
# Drawing helpers
# --------------------------------------------------------------------------
def ipt(p):
    return int(round(p[0])), int(round(p[1]))


def aa_circle(surf, color, c, r):
    x, y = ipt(c)
    r = int(round(r))
    if r < 1:
        return
    pygame.gfxdraw.filled_circle(surf, x, y, r, color)
    pygame.gfxdraw.aacircle(surf, x, y, r, color)


def aa_ring(surf, color, c, r, width=2):
    x, y = ipt(c)
    for i in range(max(1, int(width))):
        rr = int(round(r)) - i
        if rr > 0:
            pygame.gfxdraw.aacircle(surf, x, y, rr, color)


def aa_poly(surf, color, pts):
    pts = [ipt(p) for p in pts]
    if len(pts) < 3:
        return
    pygame.gfxdraw.filled_polygon(surf, pts, color)
    pygame.gfxdraw.aapolygon(surf, pts, color)


def aa_line(surf, color, a, b, width):
    (x1, y1), (x2, y2) = a, b
    dx, dy = x2 - x1, y2 - y1
    ln = math.hypot(dx, dy) or 1
    nx, ny = -dy / ln * width / 2, dx / ln * width / 2
    aa_poly(surf, color, [(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)])
    aa_circle(surf, color, a, width / 2 - 0.5)
    aa_circle(surf, color, b, width / 2 - 0.5)


def aa_polyline(surf, color, pts, width):
    for a, b in zip(pts, pts[1:]):
        aa_line(surf, color, a, b, width)


def rrect(surf, color, rect, radius, width=0):
    pygame.draw.rect(surf, color, pygame.Rect(rect), width, border_radius=int(radius))


def mix(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def outline_col(th):
    """Dark illustration outline that suits the controller colour."""
    body = th["body"]
    return (58, 62, 72) if lum(body) > 150 else mix(body, (0, 0, 0), 0.55)


# --------------------------------------------------------------------------
# Fonts: load Windows' own Segoe UI files directly (SysFont often picks a thin
# or old-looking variant). Falls back to any system font elsewhere.
# --------------------------------------------------------------------------
FONT_DIRS = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")]
FONT_FILES = {
    "regular": ["segoeui.ttf", "SegoeUI.ttf"],
    "semibold": ["seguisb.ttf", "SegoeUI-Semibold.ttf", "segoeuib.ttf"],
    "bold": ["segoeuib.ttf", "SegoeUI-Bold.ttf", "seguisb.ttf"],
    "black": ["seguibl.ttf", "segoeuib.ttf"],
}


def load_font(size, weight="semibold"):
    for name in FONT_FILES.get(weight, FONT_FILES["semibold"]):
        for d in FONT_DIRS:
            path = os.path.join(d, name)
            if d and os.path.exists(path):
                try:
                    return pygame.font.Font(path, size)
                except Exception:
                    pass
    return pygame.font.SysFont("segoeui,helveticaneue,arial,dejavusans", size, bold=weight != "regular")


# --------------------------------------------------------------------------
# Settings file and "start with Windows"
# --------------------------------------------------------------------------
SETTINGS_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "DualSenseTester")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
DEFAULTS = {"mode": "dark", "model": "ds5", "auto_model": True, "colours": {}, "trails": True,
            "deadzone": 0.05, "layout": "auto",
            "tray": True, "notify": True, "led_on": False, "led_color": [0, 90, 255], "led_brightness": 1.0, "led_effect": "static"}

LED_PRESETS = [("Blue", (0, 90, 255)), ("Red", (255, 20, 30)), ("Green", (0, 220, 70)), ("Purple", (150, 40, 255)),
               ("Pink", (255, 60, 170)), ("Orange", (255, 110, 0)), ("Yellow", (255, 210, 0)),
               ("Cyan", (0, 220, 255)), ("White", (255, 255, 255))]
LED_DEFAULT = (0, 0, 255)  # what we hand back when you switch the feature off
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "DualSenseTester"


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            s.update(json.load(f))
    except Exception:
        pass
    return s


def save_settings(s):
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except Exception:
        pass


def launch_command():
    if getattr(sys, "frozen", False):  # running as the built .exe
        return f'"{sys.executable}" --tray'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    return f'"{exe}" "{os.path.abspath(__file__)}" --tray'


# --------------------------------------------------------------------------
# System tray (needs:  pip install pystray pillow)
# --------------------------------------------------------------------------
try:
    import pystray
    from PIL import Image as PILImage
    TRAY_AVAILABLE = sys.platform == "win32"
except Exception:
    pystray = None
    TRAY_AVAILABLE = False

EV_TRAY_OPEN = pygame.event.custom_type()
EV_TRAY_QUIT = pygame.event.custom_type()


class Tray:
    """Tray icon running in its own thread; talks to the app through pygame events."""

    def __init__(self, icon_path):
        self.icon = None
        self.told = False
        if not TRAY_AVAILABLE:
            return
        try:
            img = PILImage.open(icon_path)
        except Exception:
            img = PILImage.new("RGB", (64, 64), (64, 140, 255))
        menu = pystray.Menu(
            pystray.MenuItem("Open DualSense Tester", lambda *_: self._post(EV_TRAY_OPEN), default=True),
            pystray.MenuItem("Quit", lambda *_: self._post(EV_TRAY_QUIT)),
        )
        try:
            self.icon = pystray.Icon("DualSenseTester", img, APP_NAME, menu)
            self.icon.run_detached()
        except Exception:
            self.icon = None

    @staticmethod
    def _post(ev_type):
        try:
            pygame.event.post(pygame.event.Event(ev_type))
        except Exception:
            pass

    @property
    def ok(self):
        return self.icon is not None

    def notify(self, message, title=APP_NAME):
        if self.icon is not None:
            try:
                self.icon.notify(message, title)
            except Exception:
                pass

    def notify_once(self):
        if self.icon is not None and not self.told:
            self.told = True
            try:
                self.icon.notify("Still running in the tray. Right-click the icon to quit.", APP_NAME)
            except Exception:
                pass

    def stop(self):
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass


def _hwnd():
    try:
        return pygame.display.get_wm_info()["window"]
    except Exception:
        return None


def hide_window():
    h = _hwnd()
    if h and sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.ShowWindow(h, 0)  # SW_HIDE
        return True
    return False


def show_window():
    h = _hwnd()
    if h and sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.ShowWindow(h, 9)  # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(h)


def autostart_supported():
    return sys.platform == "win32"


def get_autostart():
    if not autostart_supported():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
        return True
    except Exception:
        return False


def set_autostart(on):
    if not autostart_supported():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------
class App:
    def __init__(self, screen):
        self.real = screen
        self.content = pygame.Surface((CW, H))
        self.screen = self.content
        self.off = (0, 0)
        self.f_title = load_font(24, "bold")
        self.f_h = load_font(15, "bold")
        self.f = load_font(15, "semibold")
        self.f_s = load_font(13, "semibold")
        self.f_xs = load_font(12, "semibold")
        self.f_big = load_font(34, "bold")
        self.f_ms = load_font(13, "semibold")  # numbers (Segoe UI digits are fixed-width)
        self._text_cache = {}
        self.letter_fonts = {}

        self.settings = load_settings()
        apply_palette(self.settings["mode"])
        self.autostart = get_autostart()
        self.body_cache = {}
        self.joys = {}
        self.sel = None
        self.press_log = deque(maxlen=8)
        self.ui = []
        self.mouse = (0, 0)
        self.toast = ("", 0.0)
        self.view = "controller"
        self.settings_tab = "general"
        self.drag = None
        self.slider_rects = {}
        self.led_sent = None
        self.led_last = 0.0
        self.led_ok = None
        self.led_now = tuple(self.settings["led_color"])
        self.tray = None
        self.hidden = False
        self.started = time.perf_counter()
        if self.autostart:  # keep the startup entry pointing at this copy (and open into the tray)
            set_autostart(True)
        self.reset_stats()

    # ---------------- settings ----------------
    def save(self):
        save_settings(self.settings)

    @property
    def deadzone(self):
        return self.settings["deadzone"]

    def model_key(self):
        if self.settings["auto_model"] and self.joy is not None:
            m = self.detect_model()
            if m:
                return m
        return self.settings["model"] if self.settings["model"] in MODELS else "ds5"

    def colour_index(self, model):
        n = len(MODELS[model]["themes"])
        return int(self.settings["colours"].get(model, 0)) % n

    def theme_for(self, model):
        return MODELS[model]["themes"][self.colour_index(model)]

    # ---------------- controller state ----------------
    def reset_stats(self):
        self.trails = {"L": deque(maxlen=80), "R": deque(maxlen=80)}
        self.evt_times = deque()
        self.intervals = deque(maxlen=600)
        self.last_evt = None
        self.hz_hist = deque(maxlen=120)
        self.last_hz_sample = 0.0
        self.rest = {"L": deque(maxlen=90), "R": deque(maxlen=90)}
        self.axis_seen = set()
        self.circ = {"L": [0.0] * 72, "R": [0.0] * 72}
        self.circ_active = False

    @property
    def joy(self):
        return self.joys.get(self.sel)

    def device_info(self):
        j = self.joy
        info = {"conn": "Unknown", "vid": None, "pid": None, "battery": "Unknown"}
        try:
            g = j.get_guid()
            bus = int(g[2:4] + g[0:2], 16)
            info["conn"] = {0x03: "USB", 0x05: "Bluetooth"}.get(bus, "Unknown")
            info["vid"] = int(g[10:12] + g[8:10], 16)
            info["pid"] = int(g[18:20] + g[16:18], 16)
        except Exception:
            pass
        try:
            info["battery"] = j.get_power_level().capitalize()
        except Exception:
            pass
        return info

    @staticmethod
    def conn_of(j):
        try:
            g = j.get_guid()
            return {0x03: "USB", 0x05: "Bluetooth"}.get(int(g[2:4] + g[0:2], 16), "")
        except Exception:
            return ""

    def announce(self, title, message):
        """Windows notification (via the tray icon) and an in-app message."""
        if not self.settings["notify"] or time.perf_counter() - self.started < 2.5:
            return  # skip controllers that were already plugged in at launch
        self.set_toast(f"{title}: {message}")
        if self.tray is not None:
            self.tray.notify(message, title)

    def detect_model(self):
        j = self.joy
        if j is None:
            return None
        info = self.device_info()
        vid, pid, name = info["vid"], info["pid"], j.get_name().lower()
        if vid == 0x054C:
            return "ds5" if pid in (0x0CE6, 0x0DF2) else "ds4"
        if vid == 0x045E or "xbox" in name or "xinput" in name:
            if pid in (0x0B12, 0x0B13) or "series" in name:
                return "series"
            return "xone" if "one" in name else "series"
        if "dualsense" in name:
            return "ds5"
        if "dualshock" in name or "ps4" in name or name == "wireless controller":
            return "ds4"
        return None

    def layout_key(self):
        lay = self.settings["layout"]
        if lay in LAYOUTS:
            return lay
        j = self.joy
        if j is not None and j.get_numhats() > 0:
            name = j.get_name().lower()
            if "xbox" in name or "xinput" in name or self.device_info()["vid"] == 0x045E:
                return "XInput"
            if j.get_numbuttons() <= 14:
                return "DirectInput"
        return "SDL"

    def names(self):
        return XB_NAMES if MODELS[self.model_key()]["family"] == "xbox" else PS_NAMES

    def read_state(self):
        j = self.joy
        lay = LAYOUTS[self.layout_key()]
        nb, na = j.get_numbuttons(), j.get_numaxes()
        raw_b = [j.get_button(i) for i in range(nb)]
        raw_a = [j.get_axis(i) for i in range(na)]
        hats = [j.get_hat(i) for i in range(j.get_numhats())]

        def btn(name):
            i = lay["buttons"].get(name)
            return bool(i is not None and i < nb and raw_b[i])

        def axis(name):
            i = lay["axes"][name]
            return raw_a[i] if i < na else 0.0

        def trig(name):
            i = lay["axes"][name]
            if i >= na:
                return 0.0
            v = raw_a[i]
            if i not in self.axis_seen and abs(v) < 1e-6:
                return 0.0  # an untouched trigger reads 0 before its first event
            return max(0.0, min(1.0, (v + 1) / 2))

        pressed = {n: btn(n) for n in BUTTON_KEYS}
        if hats:
            hx, hy = hats[0]
            pressed["up"] |= hy == 1
            pressed["down"] |= hy == -1
            pressed["left"] |= hx == -1
            pressed["right"] |= hx == 1
        return dict(pressed=pressed, lx=axis("lx"), ly=axis("ly"), rx=axis("rx"), ry=axis("ry"),
                    l2=trig("l2"), r2=trig("r2"), raw_b=raw_b, raw_a=raw_a, hats=hats,
                    names={v: k for k, v in lay["buttons"].items()})

    def update_stats(self, st, now):
        while self.evt_times and now - self.evt_times[0] > 1.0:
            self.evt_times.popleft()
        if now - self.last_hz_sample >= 0.25:
            self.hz_hist.append(len(self.evt_times))
            self.last_hz_sample = now
        if st is None:
            return
        for k, x, y in (("L", st["lx"], st["ly"]), ("R", st["rx"], st["ry"])):
            self.trails[k].append((x, y))
            m = math.hypot(x, y)
            if m < 0.2:
                self.rest[k].append(m)
            if self.circ_active and m > 0.5:
                b = int((math.atan2(y, x) + math.pi) / (2 * math.pi) * 72) % 72
                self.circ[k][b] = max(self.circ[k][b], min(m, 1.5))

    def circ_error(self, k):
        vals = [v for v in self.circ[k] if v > 0]
        if not vals:
            return None, 0
        return sum(abs(v - 1.0) for v in vals) / len(vals) * 100, len(vals)

    # ---------------- actions ----------------
    def log(self, text):
        self.press_log.appendleft((time.strftime("%H:%M:%S"), text))

    def set_toast(self, text):
        self.toast = (text, time.perf_counter() + 2.2)

    def action(self, name):
        s = self.settings
        if name in ("controller", "details", "settings"):
            self.view = name
        elif name.startswith("stab:"):
            self.settings_tab = name[5:]
        elif name == "colour":
            m = self.model_key()
            s["colours"][m] = (self.colour_index(m) + 1) % len(MODELS[m]["themes"])
            self.save()
        elif name.startswith("colour:"):
            s["colours"][self.model_key()] = int(name[7:])
            self.save()
        elif name == "model":
            i = (MODEL_ORDER.index(self.model_key()) + 1) % len(MODEL_ORDER)
            self.action("model:" + MODEL_ORDER[i])
        elif name.startswith("model:"):
            s["model"], s["auto_model"] = name[6:], False
            self.save()
        elif name == "auto_model":
            s["auto_model"] = not s["auto_model"]
            if s["auto_model"] and self.joy is None:
                self.set_toast("The drawing will match your controller when one is connected")
            self.save()
        elif name.startswith("mode:"):
            s["mode"] = name[5:]
            apply_palette(s["mode"])
            self._text_cache.clear()
            self.save()
        elif name == "tray_opt":
            if not TRAY_AVAILABLE:
                self.set_toast("Install the tray helper first:  pip install pystray pillow")
            else:
                s["tray"] = not s["tray"]
                self.save()
        elif name == "notify_opt":
            s["notify"] = not s["notify"]
            self.save()
        elif name == "trails":
            s["trails"] = not s["trails"]
            self.save()
        elif name == "autostart":
            if not autostart_supported():
                self.set_toast("Start with Windows only works on Windows")
            elif set_autostart(not self.autostart):
                self.autostart = get_autostart()
                self.set_toast("Will open when you sign in to Windows" if self.autostart
                               else "Won't open with Windows any more")
            else:
                self.set_toast("Couldn't change the Windows startup setting")
        elif name in ("dz+", "dz-"):
            d = 0.01 if name == "dz+" else -0.01
            s["deadzone"] = round(max(0.0, min(0.5, s["deadzone"] + d)), 2)
            self.save()
        elif name.startswith("layout:"):
            s["layout"] = name[7:]
            self.save()
        elif name == "layout":
            order = ["auto", "SDL", "DirectInput", "XInput"]
            s["layout"] = order[(order.index(s["layout"]) + 1) % len(order)] if s["layout"] in order else "auto"
            self.set_toast(f"Button layout: {s['layout'] if s['layout'] != 'auto' else 'Automatic'}")
            self.save()
        elif name == "rumble":
            ok = False
            try:
                ok = self.joy is not None and self.joy.rumble(0.6, 1.0, 450)
            except Exception:
                ok = False
            self.set_toast("Vibrating..." if ok else "Vibration isn't available for this controller / connection")
        elif name == "circ":
            self.circ = {"L": [0.0] * 72, "R": [0.0] * 72}
            self.circ_active = True
            self.set_toast("Circularity test: slowly roll both sticks around their edge")
        elif name == "reset":
            self.reset_stats()
            self.press_log.clear()
            self.set_toast("Stats reset")
        elif name.startswith("tab:"):
            self.sel = int(name[4:])
            self.reset_stats()
            self.led_sent = None
        elif name == "led_on":
            s["led_on"] = not s["led_on"]
            self.led_sent = None if s["led_on"] else self.led_sent
            self.save()
        elif name.startswith("ledpreset:"):
            s["led_color"] = list(LED_PRESETS[int(name[10:])][1])
            s["led_on"] = True
            if s["led_effect"] == "rainbow":
                s["led_effect"] = "static"
            self.save()
        elif name.startswith("ledfx:"):
            s["led_effect"] = name[6:]
            s["led_on"] = True
            self.save()

    def handle(self, e, now):
        if e.type == pygame.QUIT:
            if self.to_tray():
                return True
            return False
        if e.type == EV_TRAY_OPEN:
            self.show()
            return True
        if e.type == EV_TRAY_QUIT:
            return False
        if e.type == getattr(pygame, "WINDOWMINIMIZED", -1) and not self.hidden:
            self.to_tray()
            return True
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                return False
            keymap = {pygame.K_t: "colour", pygame.K_m: "model", pygame.K_v: "rumble", pygame.K_c: "circ",
                      pygame.K_F1: "layout", pygame.K_r: "reset", pygame.K_UP: "dz+", pygame.K_EQUALS: "dz+",
                      pygame.K_DOWN: "dz-", pygame.K_MINUS: "dz-"}
            if e.key == pygame.K_TAB:
                order = ["controller", "details", "settings"]
                self.view = order[(order.index(self.view) + 1) % 3]
            elif e.key in keymap:
                self.action(keymap[e.key])
        elif e.type == pygame.MOUSEMOTION:
            self.mouse = e.pos
            if self.drag:
                self.set_slider(self.drag, e.pos[0])
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            if self.drag:
                self.drag = None
                self.save()
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            for rect, name in reversed(self.ui):
                if rect.collidepoint(e.pos):
                    if name.startswith("slider:"):
                        self.drag = name[7:]
                        self.set_slider(self.drag, e.pos[0])
                    else:
                        self.action(name)
                    break
        elif e.type == pygame.JOYDEVICEADDED:
            j = pygame.joystick.Joystick(e.device_index)
            j.init()
            self.led_sent = None
            self.joys[j.get_instance_id()] = j
            if self.sel is None:
                self.sel = j.get_instance_id()
            self.log(f"Connected: {j.get_name()}")
            conn = self.conn_of(j)
            batt = ""
            try:
                p = j.get_power_level()
                batt = "" if p in ("unknown", "wired", "max") else f"  ·  battery {p}"
            except Exception:
                pass
            self.announce("Controller connected", f"{j.get_name()}" + (f"  ·  {conn}" if conn else "") + batt)
        elif e.type == pygame.JOYDEVICEREMOVED:
            j = self.joys.pop(e.instance_id, None)
            if j is not None:
                self.log("Controller disconnected")
                try:
                    nm = j.get_name()
                except Exception:
                    nm = "Your controller"
                self.announce("Controller disconnected", nm)
            if self.sel == e.instance_id:
                self.sel = next(iter(self.joys), None)
                self.reset_stats()
        elif getattr(e, "instance_id", None) == self.sel:
            if e.type == pygame.JOYAXISMOTION:
                self.axis_seen.add(e.axis)
                self.evt_times.append(now)
                if self.last_evt is not None:
                    self.intervals.append((now - self.last_evt) * 1000)
                self.last_evt = now
            elif e.type == pygame.JOYBUTTONDOWN:
                lay = LAYOUTS[self.layout_key()]
                name = {v: k for k, v in lay["buttons"].items()}.get(e.button)
                self.log(f"{self.names().get(name, 'Button')}  (B{e.button})")
            elif e.type == pygame.JOYHATMOTION and e.value != (0, 0):
                d = {(0, 1): "Up", (0, -1): "Down", (-1, 0): "Left", (1, 0): "Right"}.get(tuple(e.value), str(e.value))
                self.log(f"D-pad {d}")
        return True

    # ---------------- tray ----------------
    def tray_ready(self):
        return self.settings["tray"] and self.tray is not None and self.tray.ok

    def to_tray(self):
        """Hide to the tray if that's switched on. Returns True if hidden."""
        if self.tray_ready() and hide_window():
            self.hidden = True
            self.tray.notify_once()
            return True
        return False

    def show(self):
        show_window()
        self.hidden = False

    # ---------------- light bar ----------------
    def set_slider(self, key, x):
        r = self.slider_rects.get(key)
        if r is None:
            return
        v = max(0.0, min(1.0, (x - r.x) / max(1, r.w)))
        s = self.settings
        if key in ("r", "g", "b"):
            s["led_color"]["rgb".index(key)] = int(round(v * 255))
            s["led_on"] = True
            if s["led_effect"] == "rainbow":
                s["led_effect"] = "static"
        elif key == "bri":
            s["led_brightness"] = round(v, 2)
            s["led_on"] = True

    def led_status(self):
        """Returns (can_set, message)."""
        j = self.joy
        if j is None:
            return False, "Connect a DualSense or DualShock 4 to change its light"
        if not hasattr(j, "set_led"):
            return False, "Needs a newer pygame-ce: run  pip install -U pygame-ce"
        if MODELS.get(self.detect_model() or "", {}).get("family") == "xbox":
            return False, "Xbox controllers don't have a colour light bar"
        if self.led_ok is False:
            return False, "This controller / connection didn't accept a colour"
        return True, "Changes apply to the controller straight away"

    def led_colour(self, now):
        s = self.settings
        if s["led_effect"] == "rainbow":
            r, g, b = colorsys.hsv_to_rgb((now * 0.12) % 1.0, 1.0, 1.0)
            c = (r * 255, g * 255, b * 255)
        else:
            c = s["led_color"]
        k = s["led_brightness"]
        if s["led_effect"] == "breathe":
            k *= 0.12 + 0.88 * (0.5 - 0.5 * math.cos(now * 2 * math.pi / 3.0))
        return tuple(int(max(0, min(255, v * k))) for v in c)

    def update_led(self, now):
        self.led_now = self.led_colour(now)
        j = self.joy
        if j is None or not hasattr(j, "set_led") or now - self.led_last < 1 / 30:
            return
        if MODELS.get(self.detect_model() or "", {}).get("family") == "xbox":
            return
        if not self.settings["led_on"]:
            if self.led_sent not in (None, "off"):
                try:
                    j.set_led(LED_DEFAULT)
                except Exception:
                    pass
            self.led_sent = "off"
            return
        c = self.led_now
        if c != self.led_sent or now - self.led_last > 2.0:
            try:
                self.led_ok = bool(j.set_led(c))
            except Exception:
                self.led_ok = False
            self.led_sent = c
            self.led_last = now

    # ---------------- text and widgets ----------------
    def text(self, font, s, pos, color=None, anchor="topleft"):
        color = TEXT if color is None else color
        key = (id(font), s, color)
        img = self._text_cache.get(key)
        if img is None:
            if len(self._text_cache) > 3000:
                self._text_cache.clear()
            img = font.render(s, True, color)
            self._text_cache[key] = img
        r = img.get_rect()
        setattr(r, anchor, ipt(pos))
        self.screen.blit(img, r)
        return r

    def letter_font(self, size):
        size = max(8, int(size))
        if size not in self.letter_fonts:
            self.letter_fonts[size] = load_font(size, "bold")
        return self.letter_fonts[size]

    def clickable(self, rect, action):
        r = pygame.Rect(rect).move(self.off)
        self.ui.append((r, action))
        return r.collidepoint(self.mouse)

    def panel(self, rect, title=None):
        rrect(self.screen, SURFACE, rect, 12)
        if title:
            self.text(self.f_h, title, (rect[0] + 20, rect[1] + 16))

    def checkbox(self, x, y, checked, action, enabled=True):
        r = pygame.Rect(x, y, 22, 22)
        hover = self.clickable(r.inflate(8, 8), action)
        if checked:
            rrect(self.screen, ACCENT if enabled else FAINT, r, 6)
            aa_polyline(self.screen, (255, 255, 255), [(x + 6, y + 11.5), (x + 9.5, y + 15), (x + 16, y + 7.5)], 2.4)
        else:
            rrect(self.screen, SURFACE_2 if hover else SURFACE, r, 6)
            rrect(self.screen, MUTED if hover else FAINT, r, 6, 2)

    def segmented(self, right_x, y, options, current, prefix):
        """options: list of (value, label). Drawn right-aligned ending at right_x."""
        widths = [self.f.size(lbl)[0] + 28 for _, lbl in options]
        total = sum(widths) + 8
        x = right_x - total
        rrect(self.screen, SURFACE_2, (x, y, total, 34), 10)
        x += 4
        for (val, lbl), wd in zip(options, widths):
            r = pygame.Rect(x, y + 4, wd, 26)
            hover = self.clickable(r, prefix + val)
            if val == current:
                rrect(self.screen, ACCENT, r, 8)
                self.text(self.f, lbl, r.center, (255, 255, 255), "center")
            else:
                self.text(self.f, lbl, r.center, TEXT if hover else MUTED, "center")
            x += wd

    def button(self, right_x, y, label, action, w=None):
        w = w or self.f.size(label)[0] + 32
        r = pygame.Rect(right_x - w, y, w, 34)
        hover = self.clickable(r, action)
        rrect(self.screen, mix(SURFACE_2, LINE, 0.6) if hover else SURFACE_2, r, 10)
        self.text(self.f, label, r.center, TEXT, "center")
        return r

    def slider(self, x, y, w, value, key, color):
        r = pygame.Rect(x, y - 10, w, 20)
        self.slider_rects[key] = r.move(self.off)
        hover = self.clickable(r, "slider:" + key)
        rrect(self.screen, SURFACE_2, (x, y - 3, w, 6), 3)
        fill = int(w * value)
        if fill > 0:
            rrect(self.screen, color, (x, y - 3, max(6, fill), 6), 3)
        knob = (x + fill, y)
        aa_circle(self.screen, LINE if not (hover or self.drag == key) else MUTED, knob, 10)
        aa_circle(self.screen, (255, 255, 255), knob, 8)

    # ---------------- controller drawing (flat 2D illustration) ----------------
    def _canvas(self, s):
        k = s * 2  # draw at 2x, then smooth-scale down for clean edges
        return k, max(2, int(DW * k)), max(2, int(DH * k))

    def _finish(self, surf, s):
        return pygame.transform.smoothscale(surf, (max(1, int(DW * s)), max(1, int(DH * s))))

    @staticmethod
    def _stroke(surf, color, pts, width, closed=True):
        """Thick outline with round joins (used on the 2x canvas)."""
        width = max(1, int(round(width)))
        pygame.draw.lines(surf, color, closed, pts, width)
        if width > 2:
            for p in pts:
                pygame.draw.circle(surf, color, p, width / 2)

    def body_surface(self, model, s):
        tname, th = self.theme_for(model)
        key = ("body", model, tname, round(s, 3), SHADOW)
        if key in self.body_cache:
            return self.body_cache[key]
        spec = MODELS[model]
        k, w, h = self._canvas(s)
        P = lambda pts: [(x * k, y * k) for x, y in pts]
        lw = 3.4 * k
        ol = outline_col(th)
        surf = pygame.Surface((w, h), pygame.SRCALPHA)

        # flat ground shadow, like a sticker illustration
        pygame.draw.ellipse(surf, (0, 0, 0, SHADOW // 2), (230 * k, 636 * k, 540 * k, 20 * k))

        pygame.draw.polygon(surf, th["body"], P(spec["body"]))
        if spec["panel"] and th.get("panel"):
            pnl = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.polygon(pnl, th["panel"], P(spec["panel"]))
            self._stroke(pnl, ol, P(spec["panel"]), lw * 0.8)
            mask = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.polygon(mask, (255, 255, 255, 255), P(spec["body"]))
            pnl.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            surf.blit(pnl, (0, 0))
        base = th["panel"] if th.get("panel") else th["body"]

        if spec["recess"]:
            for c in (spec["dpad"], spec["face"]):
                rr = spec.get("recess_r", 84)
                pygame.draw.circle(surf, mix(th["body"], (0, 0, 0), 0.14), (c[0] * k, c[1] * k), rr * k)
                pygame.draw.circle(surf, ol, (c[0] * k, c[1] * k), rr * k, max(1, int(lw * 0.6)))
        if spec["touchpad"]:
            pygame.draw.polygon(surf, th["touch"], P(spec["touchpad"]))
            self._stroke(surf, ol, P(spec["touchpad"]), lw * 0.85)
        if spec["speaker"]:
            sx, sy, sp, counts = spec["speaker"]
            for row, n in enumerate(counts):
                for i in range(n):
                    x = sx + (i - (n - 1) / 2) * sp
                    pygame.draw.circle(surf, mix(base, (128, 128, 128), 0.45), (x * k, (sy + row * sp * 0.8) * k), 3.4 * k)
        if spec["dpad_style"] == "disc":
            c = spec["dpad"]
            pygame.draw.circle(surf, mix(th["body"], (0, 0, 0), 0.10), (c[0] * k, c[1] * k), 64 * k)
            pygame.draw.circle(surf, ol, (c[0] * k, c[1] * k), 64 * k, max(1, int(lw * 0.7)))
        for c in (spec["stick_l"], spec["stick_r"]):
            wr = spec.get("well_r", 56)
            pygame.draw.circle(surf, mix(base, (0, 0, 0), 0.22), (c[0] * k, c[1] * k), wr * k)
            pygame.draw.circle(surf, ol, (c[0] * k, c[1] * k), wr * k, max(1, int(lw * 0.7)))

        self._stroke(surf, ol, P(spec["body"]), lw)
        out = self._finish(surf, s)
        self.body_cache[key] = out
        return out

    def part_surface(self, model, s, part, side, state):
        """Cached bumper / trigger art. state: 'off' or 'on'. side 'L' or 'R' (mirror)."""
        tname, th = self.theme_for(model)
        key = ("part", model, tname, round(s, 3), part, side, state, ACCENT)
        if key in self.body_cache:
            return self.body_cache[key]
        spec = MODELS[model]
        k, w, h = self._canvas(s)
        pts = [(x * k, y * k) for x, y in spec[part]]
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        fill = ACCENT if state == "on" else mix(th["body"], (0, 0, 0), 0.24 if part == "trigger" else 0.08)
        pygame.draw.polygon(surf, fill, pts)
        self._stroke(surf, outline_col(th), pts, 3.0 * k)
        out = self._finish(surf, s)
        if side == "R":
            out = pygame.transform.flip(out, True, False)
        self.body_cache[key] = out
        return out

    def draw_controller(self, ox, oy, s, st, model, mini=False):
        spec = MODELS[model]
        th = self.theme_for(model)[1]
        scr = self.screen
        P = lambda x, y: (ox + x * s, oy + y * s)
        pr = st["pressed"] if st else {}
        on = lambda n: pr.get(n, False)
        connected = st is not None
        sym_off = th["symbol"]
        xbox = spec["family"] == "xbox"
        white = (255, 255, 255)
        ol = outline_col(th)
        lw = max(1.0, 2.6 * s)
        base = th["panel"] if th.get("panel") else th["body"]
        o = ipt((ox, oy))

        def outlined_circle(c, r, fill):
            aa_circle(scr, ol, c, r)
            aa_circle(scr, fill, c, r - lw)

        def outlined_poly(pts, fill):
            aa_poly(scr, fill, pts)
            aa_polyline(scr, ol, pts + [pts[0]], lw)

        # triggers (behind) and bumpers, then the body on top
        ys = [y for _, y in spec["trigger"]]
        t_top, t_bot = min(ys), max(ys)
        for side, val in (("L", st["l2"] if st else 0.0), ("R", st["r2"] if st else 0.0)):
            scr.blit(self.part_surface(model, s, "trigger", side, "off"), o)
            if val > 0.002:
                y_cut = oy + (t_bot - (t_bot - t_top) * val) * s
                clip = scr.get_clip()
                scr.set_clip(pygame.Rect(0, int(y_cut), scr.get_width(), int(oy + t_bot * s - y_cut) + 2).clip(clip))
                scr.blit(self.part_surface(model, s, "trigger", side, "on"), o)
                scr.set_clip(clip)
        for side, name in (("L", "l1"), ("R", "r1")):
            scr.blit(self.part_surface(model, s, "bumper", side, "on" if on(name) else "off"), o)
        scr.blit(self.body_surface(model, s), o)

        if not mini:  # trigger labels above the triggers
            xs = [x for x, _ in spec["trigger"]]
            tx = (min(xs) + max(xs)) / 2
            tl, tr = ("LT", "RT") if xbox else ("L2", "R2")
            for lbl, x, val in ((tl, tx, st["l2"] if st else 0.0), (tr, DW - tx, st["r2"] if st else 0.0)):
                txt = f"{lbl}  {val * 100:.0f}%" if val > 0.005 else lbl
                self.text(self.f_s, txt, P(x, t_top - 14), ACCENT if val > 0.005 else MUTED, "center")

        # touchpad press
        if spec["touchpad"] and on("touchpad"):
            c = (500, sum(y for _, y in spec["touchpad"]) / len(spec["touchpad"]))
            aa_poly(scr, mix(th["touch"], ACCENT, 0.6),
                    [P(c[0] + (x - c[0]) * 0.975, c[1] + (y - c[1]) * 0.95) for x, y in spec["touchpad"]])

        # light bars
        if connected and self.settings["led_on"]:
            lb = self.led_now
        else:
            lb = ACCENT if connected else mix(base, (128, 128, 128), 0.4)
        for pts in spec["lightbars"]:
            aa_polyline(scr, lb, [P(x, y) for x, y in pts], 3.4 * s)

        # select / start
        for c, name, tilt in ((spec["select"], "create", 1), (spec["start"], "options", -1)):
            fill = ACCENT if on(name) else th["btn"]
            if spec["small_style"] == "slant":
                hl = spec.get("small_len", 30) / 2 - 7
                a, b = P(c[0] - 5 * tilt, c[1] - hl), P(c[0] + 5 * tilt, c[1] + hl)
                aa_line(scr, ol, a, b, 15 * s + 2 * lw)
                aa_line(scr, fill, a, b, 15 * s)
            else:
                outlined_circle(P(*c), 15 * s, fill)
                if not mini:
                    g = white if on(name) else sym_off
                    x0, y0 = P(*c)
                    t = max(1, int(1.6 * s + 0.5))
                    if name == "create":  # View: two overlapping squares
                        rrect(scr, g, (x0 - 6 * s, y0 - 5 * s, 8 * s, 7 * s), 1, t)
                        rrect(scr, g, (x0 - 2 * s, y0 - 1 * s, 8 * s, 7 * s), 1, t)
                    else:  # Menu: three lines
                        for dy in (-4, 0, 4):
                            pygame.draw.line(scr, g, ipt((x0 - 5 * s, y0 + dy * s)), ipt((x0 + 5 * s, y0 + dy * s)), t)

        # d-pad
        dc = spec["dpad"]
        if spec["dpad_style"] == "arrows":
            for name, ang in (("up", 0), ("right", 90), ("down", 180), ("left", 270)):
                p = on(name)
                ak = spec.get("arrow_k", 1.0)
                outlined_poly([P(dc[0] + x * ak, dc[1] + y * ak) for x, y in rotate(ARROW_UP, ang)],
                              ACCENT if p else th["btn"])
                tip = rotate([(0, -58 * ak), (-6 * ak, -49 * ak), (6 * ak, -49 * ak)], ang)
                aa_poly(scr, white if p else sym_off, [P(dc[0] + x, dc[1] + y) for x, y in tip])
        else:
            a, l = spec.get("cross", (16, 46))  # half arm width, arm length
            cross = [(-a, -l), (a, -l), (a, -a), (l, -a), (l, a), (a, a), (a, l), (-a, l), (-a, a), (-l, a),
                     (-l, -a), (-a, -a)]
            outlined_poly([P(dc[0] + x, dc[1] + y) for x, y in cross], th["btn"])
            for name, ang in (("up", 0), ("right", 90), ("down", 180), ("left", 270)):
                arm = rotate([(-a + 2, -l + 2), (a - 2, -l + 2), (a - 2, -a), (-a + 2, -a)], ang)
                if on(name):
                    aa_poly(scr, ACCENT, [P(dc[0] + x, dc[1] + y) for x, y in arm])
                tip = rotate([(0, -l + 10), (-6, -l + 19), (6, -l + 19)], ang)
                aa_poly(scr, white if on(name) else sym_off, [P(dc[0] + x, dc[1] + y) for x, y in tip])

        # face buttons
        fc, gap, fr = spec["face"], spec["face_gap"], spec["face_r"]
        for name, (dx, dy) in (("triangle", (0, -1)), ("circle", (1, 0)), ("cross", (0, 1)), ("square", (-1, 0))):
            c = P(fc[0] + dx * gap, fc[1] + dy * gap)
            r = fr * s
            p = on(name)
            if xbox:
                col = XB_LETTER[name]
                outlined_circle(c, r, col if p else th["btn"])
                if mini:
                    aa_circle(scr, col, c, r * 0.4)
                else:
                    self.text(self.letter_font(24 * s), XB_NAMES[name], (c[0], c[1] - 1), white if p else col, "center")
                continue
            fill = ACCENT if p else th["btn"]
            outlined_circle(c, r, fill)
            sym = white if p else (PS_SYMBOL[name] if spec["face_colored"] else sym_off)
            sw = max(1.4, 2.6 * s)
            z = r * 0.42
            cx, cy = c
            if name == "triangle":
                v = [(cx, cy - z * 1.05), (cx + z, cy + z * 0.7), (cx - z, cy + z * 0.7)]
                aa_polyline(scr, sym, v + [v[0]], sw)
            elif name == "circle":
                aa_circle(scr, sym, c, z)
                aa_circle(scr, fill, c, z - sw)
            elif name == "cross":
                aa_line(scr, sym, (cx - z * 0.9, cy - z * 0.9), (cx + z * 0.9, cy + z * 0.9), sw)
                aa_line(scr, sym, (cx + z * 0.9, cy - z * 0.9), (cx - z * 0.9, cy + z * 0.9), sw)
            else:
                q = z * 0.8
                v = [(cx - q, cy - q), (cx + q, cy - q), (cx + q, cy + q), (cx - q, cy + q)]
                aa_polyline(scr, sym, v + [v[0]], sw)

        # sticks
        for c, (sx, sy), click in ((spec["stick_l"], (st["lx"], st["ly"]) if st else (0, 0), "l3"),
                                   (spec["stick_r"], (st["rx"], st["ry"]) if st else (0, 0), "r3")):
            b = P(*c)
            mv, cr = spec.get("move", 20), spec.get("cap_r", 40)
            cx, cy = b[0] + sx * mv * s, b[1] + sy * mv * s
            active = on(click) or math.hypot(sx, sy) > self.deadzone
            aa_circle(scr, ACCENT if active else ol, (cx, cy), cr * s + (1.5 if active else 0))
            aa_circle(scr, th["stick"], (cx, cy), cr * s - lw)
            aa_ring(scr, mix(th["stick"], (128, 128, 128), 0.35), (cx, cy), cr * 0.68 * s, max(1, int(1.6 * s + 0.5)))
            if on(click):
                aa_circle(scr, ACCENT, (cx, cy), 11 * s)

        # home button
        hc, hr = spec["home"], spec["home_r"]
        if xbox:
            outlined_circle(P(*hc), hr * s, ACCENT if on("ps") else mix(th["body"], (128, 128, 128), 0.25))
            aa_ring(scr, white if on("ps") else ol, P(*hc), hr * 0.5 * s, max(1, int(2 * s + 0.5)))
        else:
            outlined_circle(P(*hc), hr * s, ACCENT if on("ps") else mix(base, (128, 128, 128), 0.3))

        # mic (DualSense) / share (Xbox Series)
        if spec["misc"]:
            mw, mh = (spec.get("misc_w", 32), 10) if not xbox else (30, 16)
            a, b = P(spec["misc"][0] - mw / 2 + mh / 2, spec["misc"][1]), P(spec["misc"][0] + mw / 2 - mh / 2, spec["misc"][1])
            col = (MIC_ORANGE if not xbox else ACCENT) if on("mic") else (mix(base, (128, 128, 128), 0.35) if not xbox
                                                                       else mix(th["body"], (128, 128, 128), 0.2))
            if xbox:
                aa_line(scr, ol, a, b, mh * s + 2 * lw)
            aa_line(scr, col, a, b, mh * s)

        if not connected and not mini:
            cx, my = P(500, 540)
            self.text(self.f_h, "Waiting for a controller", (cx, my), TEXT, "center")
            self.text(self.f_s, "Connect with USB or Bluetooth", (cx, my + 22), MUTED, "center")

    # ---------------- small widgets ----------------
    def stick_plot(self, cx, cy, r, key, x, y, show_circ=False):
        scr = self.screen
        aa_circle(scr, BG, (cx, cy), r)
        aa_ring(scr, LINE, (cx, cy), r, 1)
        pygame.draw.line(scr, LINE, (cx - r + 2, cy), (cx + r - 2, cy))
        pygame.draw.line(scr, LINE, (cx, cy - r + 2), (cx, cy + r - 2))
        if self.deadzone > 0.005:
            aa_ring(scr, FAINT, (cx, cy), max(2, r * self.deadzone), 1)
        if show_circ:
            pts = [(cx + math.cos((i + 0.5) / 72 * 2 * math.pi - math.pi) * v * r,
                    cy + math.sin((i + 0.5) / 72 * 2 * math.pi - math.pi) * v * r)
                   for i, v in enumerate(self.circ[key]) if v > 0]
            if len(pts) > 2:
                pygame.draw.aalines(scr, WARN, True, pts)
        if self.settings["trails"]:
            trail = list(self.trails[key])
            for i in range(1, len(trail)):
                a, b = trail[i - 1], trail[i]
                pygame.draw.aaline(scr, mix(SURFACE, ACCENT, i / len(trail)),
                                   (cx + a[0] * r, cy + a[1] * r), (cx + b[0] * r, cy + b[1] * r))
        aa_circle(scr, ACCENT, (cx + x * r, cy + y * r), min(7, max(3, r * 0.08)))

    def drift_text(self, key):
        if not self.rest[key]:
            return "Drift: let go", MUTED
        d = max(self.rest[key])
        if d < 0.03:
            return f"Drift {d:.3f}  Good", GOOD
        if d < 0.08:
            return f"Drift {d:.3f}  Slight", WARN
        return f"Drift {d:.3f}  Drifting", BAD

    def bar(self, x, y, w, v):
        rrect(self.screen, BG, (x, y, w, 6), 3)
        if v > 0.002:
            rrect(self.screen, ACCENT, (x, y, max(6, int(w * v)), 6), 3)

    # ---------------- sidebar ----------------
    def icon(self, kind, c, col):
        scr = self.screen
        x, y = c
        if kind == "controller":
            k = 0.036
            aa_poly(scr, col, [(x + (px - 500) * k, y + (py - 370) * k) for px, py in DS5["body"][::3]])
            for sx in (-6, 6):
                aa_circle(scr, RAILBG, (x + sx, y), 2.6)
        elif kind == "details":
            for i, dy in enumerate((-7, 0, 7)):
                aa_circle(scr, col, (x - 9, y + dy), 1.8)
                rrect(scr, col, (x - 4, y + dy - 1, 14 - (i % 2) * 4, 3), 1)
        elif kind == "settings":
            pts = []
            for i in range(48):
                a = i / 48 * 2 * math.pi
                tooth = (i // 3) % 2 == 0
                pts.append((x + math.cos(a) * (11 if tooth else 8.5), y + math.sin(a) * (11 if tooth else 8.5)))
            aa_poly(scr, col, pts)
            aa_circle(scr, RAILBG, (x, y), 3.6)

    def draw_sidebar(self):
        scr = self.screen
        scr.fill(RAILBG, (0, 0, RAIL, H))
        pygame.draw.line(scr, LINE, (RAIL - 1, 0), (RAIL - 1, H))
        aa_circle(scr, ACCENT, (RAIL // 2, 36), 9)
        aa_circle(scr, RAILBG, (RAIL // 2, 36), 4)
        items = [("controller", "Controller", 96), ("details", "Details", 170), ("settings", "Settings", H - 92)]
        for view, label, y in items:
            r = pygame.Rect(8, y, RAIL - 16, 62)
            hover = self.clickable(r, view)
            active = self.view == view
            if active:
                rrect(scr, mix(RAILBG, ACCENT, 0.16), r, 12)
            elif hover:
                rrect(scr, SURFACE_2, r, 12)
            col = ACCENT if active else (TEXT if hover else MUTED)
            self.icon(view, (RAIL // 2, y + 22), col)
            self.text(self.f_xs, label, (RAIL // 2, y + 48), col, "center")

    # ---------------- header / footer ----------------
    def draw_header(self, title):
        self.text(self.f_title, title, (32, 38), TEXT, "midleft")
        if self.joy:
            status = f"{self.joy.get_name()}  ·  {self.device_info()['conn']}"
            dot = GOOD
        else:
            status, dot = "Not connected", WARN
        r = self.text(self.f, status, (CW - 32, 38), MUTED, "midright")
        aa_circle(self.screen, dot, (r.x - 12, 38), 4)
        if len(self.joys) > 1:
            x = CW - 32
            for n, iid in reversed(list(enumerate(self.joys))[:4]):
                label = f"Controller {n + 1}"
                wd = self.f_s.size(label)[0]
                x -= wd
                self.clickable((x - 4, 54, wd + 8, 20), f"tab:{iid}")
                self.text(self.f_s, label, (x, 56), ACCENT if iid == self.sel else FAINT)
                x -= 16

    # ---------------- pages ----------------
    def draw_main(self, st):
        self.draw_header("Controller")
        self.draw_controller((CW - 800) // 2, 74, 0.8, st, self.model_key())
        y, bw, bh, gap = 616, 260, 112, 20
        x0 = (CW - (4 * bw + 3 * gap)) // 2
        for i, (key, label) in enumerate((("L", "Left stick"), ("R", "Right stick"))):
            x = x0 + i * (bw + gap)
            self.panel((x, y, bw, bh))
            sx, sy = ((st["lx"], st["ly"]) if key == "L" else (st["rx"], st["ry"])) if st else (0.0, 0.0)
            self.stick_plot(x + 58, y + bh // 2, 38, key, sx, sy)
            self.text(self.f_h, label, (x + 112, y + 22))
            self.text(self.f_ms, f"X {sx:+.3f}", (x + 112, y + 46), MUTED)
            self.text(self.f_ms, f"Y {sy:+.3f}", (x + 112, y + 62), MUTED)
            t, c = self.drift_text(key)
            self.text(self.f_s, t, (x + 112, y + 84), c)
        x = x0 + 2 * (bw + gap)
        self.panel((x, y, bw, bh), "Triggers")
        xbox = MODELS[self.model_key()]["family"] == "xbox"
        for i, key in enumerate(("l2", "r2")):
            v = st[key] if st else 0.0
            ry = y + 54 + i * 30
            self.text(self.f_h, ("LT", "RT")[i] if xbox else key.upper(), (x + 20, ry), TEXT, "midleft")
            self.bar(x + 52, ry - 3, 130, v)
            self.text(self.f_ms, f"{v * 100:3.0f}%", (x + bw - 20, ry), MUTED, "midright")
        x = x0 + 3 * (bw + gap)
        self.panel((x, y, bw, bh), "Update rate")
        hz = len(self.evt_times)
        col = TEXT if hz == 0 else (GOOD if hz >= 200 else (WARN if hz >= 100 else BAD))
        r = self.text(self.f_big, str(hz), (x + 20, y + 40), col)
        self.text(self.f, "Hz", (r.right + 6, r.bottom - 8), MUTED, "bottomleft")
        if len(self.intervals) > 20:
            srt = sorted(self.intervals)
            sub = f"about {srt[len(srt) // 2]:.1f} ms between updates"
        else:
            sub = "Move a stick to measure"
        self.text(self.f_s, sub, (x + 20, y + 86), MUTED)
        hints = "Tab  Next page      T  Colour      M  Model      V  Vibrate      C  Circularity test"
        self.text(self.f_s, hints, (CW / 2, H - 22), FAINT, "center")

    def draw_details(self, st):
        self.draw_header("Details")
        lx, cw, top = 32, (CW - 32 * 2 - 24) // 2, 80
        rx = lx + cw + 24
        names = self.names()
        self.panel((lx, top, cw, 128), "Device")
        if self.joy:
            info = self.device_info()
            vid = f"{info['vid']:04x}" if info["vid"] is not None else "-"
            pid = f"{info['pid']:04x}" if info["pid"] is not None else "-"
            rows = [("Name", self.joy.get_name()), ("Connection", info["conn"]),
                    ("Battery", info["battery"]), ("VID / PID", f"{vid} / {pid}")]
        else:
            rows = [("Name", "Not connected")]
        for i, (k, v) in enumerate(rows):
            cx, cy = lx + 20 + (i % 2) * (cw // 2), top + 48 + (i // 2) * 38
            self.text(self.f_s, k, (cx, cy), MUTED)
            self.text(self.f, v if len(v) < 32 else v[:30] + "...", (cx, cy + 15))

        y = top + 144
        self.panel((lx, y, cw, 300), "Raw input")
        if st:
            g, th_ = 8, 38
            tw = (cw - 40 - 5 * g) // 6
            for i, v in enumerate(st["raw_b"][:18]):
                r = pygame.Rect(lx + 20 + (i % 6) * (tw + g), y + 48 + (i // 6) * (th_ + g), tw, th_)
                pressed = bool(v)
                rrect(self.screen, ACCENT if pressed else BG, r, 8)
                name = names.get(st["names"].get(i, ""), "")
                self.text(self.f_s, f"B{i}", (r.x + 8, r.y + 4), (255, 255, 255) if pressed else MUTED)
                self.text(self.f_s, name[:9], (r.x + 8, r.y + 20), (255, 255, 255) if pressed else FAINT)
            aw = (cw - 40 - 2 * g) // 3
            for i, v in enumerate(st["raw_a"][:6]):
                r = pygame.Rect(lx + 20 + (i % 3) * (aw + g), y + 196 + (i // 3) * (th_ + g), aw, th_)
                rrect(self.screen, BG, r, 8)
                self.text(self.f_s, f"Axis {i}", (r.x + 10, r.centery), MUTED, "midleft")
                self.text(self.f_ms, f"{v:+.3f}", (r.right - 10, r.centery), TEXT, "midright")
        else:
            self.text(self.f_s, "Connect a controller to see raw values", (lx + 20, y + 50), MUTED)

        y = top + 460
        self.panel((lx, y, cw, H - 32 - y), "Recent presses")
        if not self.press_log:
            self.text(self.f_s, "Press any button", (lx + 20, y + 50), MUTED)
        for i, (ts, line) in enumerate(list(self.press_log)[:6]):
            self.text(self.f, line, (lx + 20, y + 48 + i * 22), TEXT if i == 0 else MUTED)
            self.text(self.f_ms, ts, (lx + cw - 20, y + 50 + i * 22), FAINT, "topright")

        self.panel((rx, top, cw, 440), "Sticks")
        for i, (key, label) in enumerate((("L", "Left"), ("R", "Right"))):
            cx = rx + cw // 4 + i * cw // 2
            sx, sy = ((st["lx"], st["ly"]) if key == "L" else (st["rx"], st["ry"])) if st else (0.0, 0.0)
            self.stick_plot(cx, top + 170, 105, key, sx, sy, show_circ=True)
            self.text(self.f_ms, f"X {sx:+.3f}   Y {sy:+.3f}", (cx, top + 296), TEXT, "center")
            t, c = self.drift_text(key)
            self.text(self.f_s, f"{label}: {t}", (cx, top + 318), c, "center")
            err, _ = self.circ_error(key)
            if self.circ_active:
                txt = f"Circularity error {err:.1f}%" if err is not None else "Roll the stick around its edge"
                self.text(self.f_s, txt, (cx, top + 338), WARN, "center")
        self.button(rx + cw // 2 + 90, top + 380, "Restart circularity test" if self.circ_active
                    else "Start circularity test", "circ", w=180)

        y = top + 460
        self.panel((rx, y, cw, H - 32 - y), "Update rate")
        hz = len(self.evt_times)
        r = self.text(self.f_big, str(hz), (rx + 20, y + 42), GOOD if hz >= 200 else (WARN if hz >= 100 else TEXT))
        self.text(self.f, "Hz  ·  last 30 seconds", (r.right + 8, r.bottom - 8), MUTED, "bottomleft")
        g = pygame.Rect(rx + 20, y + 96, cw - 40, H - 32 - y - 116)
        rrect(self.screen, BG, g, 8)
        hist = list(self.hz_hist)
        top_v = max([260] + hist)
        bw = g.w / self.hz_hist.maxlen
        for i, v in enumerate(hist):
            if v > 0:
                bh = max(1, int((g.h - 8) * v / top_v))
                bx = g.x + (self.hz_hist.maxlen - len(hist) + i) * bw
                pygame.draw.rect(self.screen, ACCENT, (int(bx), g.bottom - 4 - bh, max(1, int(bw) - 1), bh))

    def setting_row(self, y, title, desc, last=False):
        x, w = 32, CW - 64
        self.text(self.f_h, title, (x + 24, y + 13))
        self.text(self.f_s, desc, (x + 24, y + 35), MUTED)
        if not last:
            pygame.draw.line(self.screen, LINE, (x + 24, y + 63), (x + w - 24, y + 63))
        return x + w - 24  # right edge for controls

    def draw_settings(self, st):
        self.draw_header("Settings")
        tabs = [("general", "General"), ("design", "Design"), ("lights", "Light bar")]
        tabs_w = sum(self.f.size(lbl)[0] + 28 for _, lbl in tabs) + 8
        self.segmented(32 + tabs_w, 70, tabs, self.settings_tab, "stab:")
        if self.settings_tab == "design":
            self.draw_design()
            return
        if self.settings_tab == "lights":
            self.draw_lights()
            return
        s = self.settings
        top = 122
        rows = 9
        self.panel((32, top, CW - 64, rows * 64 + 12))
        y = top + 6
        rx = self.setting_row(y, "Minimize and close to tray", "Keep running next to the clock; right-click the "
                              "tray icon to quit" if TRAY_AVAILABLE else "Needs the tray helper: pip install pystray pillow")
        self.checkbox(rx - 22, y + 20, s["tray"] and TRAY_AVAILABLE, "tray_opt", TRAY_AVAILABLE)
        y += 64
        rx = self.setting_row(y, "Connection notifications", "Show a notification when a controller "
                              "connects or disconnects")
        self.checkbox(rx - 22, y + 20, s["notify"], "notify_opt")
        y += 64
        rx = self.setting_row(y, "Start with Windows", "Open DualSense Tester automatically when you sign in"
                              if autostart_supported() else "Only available on Windows")
        self.checkbox(rx - 22, y + 20, self.autostart, "autostart", autostart_supported())
        y += 64
        rx = self.setting_row(y, "Appearance", "Dark or light interface")
        self.segmented(rx, y + 14, [("dark", "Dark"), ("light", "Light")], s["mode"], "mode:")
        y += 64
        rx = self.setting_row(y, "Show stick trails", "Draw a fading line behind each stick position")
        self.checkbox(rx - 22, y + 20, s["trails"], "trails")
        y += 64
        rx = self.setting_row(y, "Deadzone ring", "Size of the small circle around each stick's centre")
        b = self.button(rx, y + 14, "+", "dz+", w=38)
        self.text(self.f_ms, f"{s['deadzone']:.2f}", (b.x - 34, y + 31), TEXT, "center")
        self.button(b.x - 68, y + 14, "-", "dz-", w=38)
        y += 64
        rx = self.setting_row(y, "Button layout", "Change this only if the wrong buttons light up")
        self.segmented(rx, y + 14, [("auto", "Automatic"), ("SDL", "SDL"), ("DirectInput", "DirectInput"),
                                    ("XInput", "XInput")], s["layout"], "layout:")
        y += 64
        rx = self.setting_row(y, "Vibration test", "Rumble the connected controller for half a second")
        self.button(rx, y + 14, "Test", "rumble", w=90)
        y += 64
        rx = self.setting_row(y, "Reset statistics", "Clear drift, update rate, trails and recent presses", last=True)
        self.button(rx, y + 14, "Reset", "reset", w=90)

    def draw_design(self):
        s = self.settings
        top = 122
        cur = self.model_key()
        self.panel((32, top, CW - 64, 318), "Controller")
        gap = 16
        cw = (CW - 64 - 40 - 3 * gap) // 4
        x0 = 32 + 20
        for i, m in enumerate(MODEL_ORDER):
            r = pygame.Rect(x0 + i * (cw + gap), top + 50, cw, 214)
            hover = self.clickable(r, "model:" + m)
            selected = m == cur
            rrect(self.screen, BG if not hover else SURFACE_2, r, 12)
            if selected:
                rrect(self.screen, ACCENT, r, 12, 2)
            self.draw_controller(r.x + (cw - 220) // 2, r.y + 14, 0.22, None, m, mini=True)
            self.text(self.f_h, MODELS[m]["name"], (r.x + 16, r.bottom - 44))
            self.text(self.f_s, MODELS[m]["sub"], (r.x + 16, r.bottom - 24), MUTED)
            if selected:
                aa_circle(self.screen, ACCENT, (r.right - 22, r.bottom - 30), 9)
                aa_polyline(self.screen, (255, 255, 255), [(r.right - 26, r.bottom - 30), (r.right - 23, r.bottom - 27),
                                                           (r.right - 18, r.bottom - 33)], 2)
        cy = top + 280
        self.checkbox(x0, cy, s["auto_model"], "auto_model")
        self.text(self.f, "Match the connected controller automatically", (x0 + 34, cy + 11), TEXT, "midleft")

        y = top + 334
        self.panel((32, y, CW - 64, 140), "Colour")
        themes = MODELS[cur]["themes"]
        ci = self.colour_index(cur)
        for i, (tname, th) in enumerate(themes):
            cx = x0 + 34 + i * 220
            c = (cx, y + 82)
            hover = self.clickable((cx - 30, y + 48, 130, 70), f"colour:{i}")
            if i == ci:
                aa_ring(self.screen, ACCENT, c, 27, 3)
            elif hover:
                aa_ring(self.screen, FAINT, c, 27, 2)
            aa_circle(self.screen, outline_col(th), c, 21)
            aa_circle(self.screen, th["body"], c, 19)
            if th.get("panel"):
                aa_circle(self.screen, th["panel"], (cx, y + 90), 9)
            self.text(self.f, tname, (cx + 38, y + 82), TEXT if i == ci else MUTED, "midleft")
        self.text(self.f_s, "Tip: press T to cycle colours and M to cycle controller models from any page",
                  (CW / 2, H - 22), FAINT, "center")

    def draw_lights(self):
        s = self.settings
        top = 122
        x0, w = 32, CW - 64
        self.panel((x0, top, w, 96))
        self.text(self.f_h, "Control the light bar", (x0 + 24, top + 22))
        ok, msg = self.led_status()
        self.text(self.f_s, msg, (x0 + 24, top + 46), MUTED if ok or self.joy is None else WARN)
        self.text(self.f_s, "Works with DualSense and DualShock 4 over USB and Bluetooth",
                  (x0 + 24, top + 66), FAINT)
        self.checkbox(x0 + w - 46, top + 36, s["led_on"], "led_on")

        y = top + 112
        self.panel((x0, y, w, H - 32 - y))
        # live preview
        cx, cy = x0 + 150, y + 150
        c = self.led_now if s["led_on"] else (60, 64, 74)
        aa_circle(self.screen, mix(SURFACE, c, 0.25), (cx, cy), 92)
        aa_circle(self.screen, mix(SURFACE, c, 0.5), (cx, cy), 78)
        aa_circle(self.screen, c, (cx, cy), 62)
        hexcol = "#%02X%02X%02X" % tuple(s["led_color"])
        label = {"static": hexcol, "breathe": f"{hexcol}  breathing", "rainbow": "Rainbow"}[s["led_effect"]]
        self.text(self.f_h, label if s["led_on"] else "Off", (cx, cy + 118), TEXT, "center")
        self.text(self.f_s, "Preview", (cx, y + 28), MUTED, "center")

        lx = x0 + 330
        self.text(self.f_h, "Colour", (lx, y + 24))
        for i, (name, col) in enumerate(LED_PRESETS):
            pc = (lx + 20 + i * 56, y + 74)
            hover = self.clickable((pc[0] - 24, pc[1] - 24, 48, 48), f"ledpreset:{i}")
            if tuple(s["led_color"]) == col and s["led_effect"] != "rainbow":
                aa_ring(self.screen, TEXT, pc, 24, 2)
            elif hover:
                aa_ring(self.screen, FAINT, pc, 24, 2)
            aa_circle(self.screen, col, pc, 18)

        sy = y + 140
        sw = w - (lx - x0) - 120
        for i, (key, label, col, val) in enumerate((
                ("r", "Red", (240, 70, 70), s["led_color"][0] / 255),
                ("g", "Green", (60, 200, 100), s["led_color"][1] / 255),
                ("b", "Blue", (70, 130, 250), s["led_color"][2] / 255),
                ("bri", "Brightness", ACCENT, s["led_brightness"]))):
            ry = sy + i * 46
            self.text(self.f, label, (lx, ry), TEXT, "midleft")
            self.slider(lx + 100, ry, sw - 100, val, key, col)
            shown = f"{int(val * 100)}%" if key == "bri" else str(s["led_color"]["rgb".index(key)])
            self.text(self.f_ms, shown, (lx + sw + 50, ry), MUTED, "midright")

        ey = sy + 4 * 46 + 16
        self.text(self.f_h, "Effect", (lx, ey + 17), TEXT, "midleft")
        opts = [("static", "Static"), ("breathe", "Breathing"), ("rainbow", "Rainbow")]
        ow = sum(self.f.size(l)[0] + 28 for _, l in opts) + 8
        self.segmented(lx + 100 + ow, ey, opts, s["led_effect"], "ledfx:")
        self.text(self.f_s, "The colour stays while DualSense Tester is open. When you turn this off the "
                            "light goes back to blue.", (lx, ey + 58), FAINT)

    def draw(self, now):
        self.ui = []
        st = self.read_state() if self.joy else None
        self.update_stats(st, now)
        self.update_led(now)
        self.screen, self.off = self.content, (RAIL, 0)
        self.content.fill(BG)
        if self.view == "details":
            self.draw_details(st)
        elif self.view == "settings":
            self.draw_settings(st)
        else:
            self.draw_main(st)
        msg, until = self.toast
        if msg and now < until:
            r = pygame.Rect(0, 0, self.f.size(msg)[0] + 40, 38)
            r.center = (CW // 2, H - 64)
            rrect(self.screen, SURFACE_2, r, 19)
            rrect(self.screen, LINE, r, 19, 1)
            self.text(self.f, msg, r.center, TEXT, "center")
        self.real.blit(self.content, (RAIL, 0))
        self.screen, self.off = self.real, (0, 0)
        self.draw_sidebar()


def resource(name):
    """Find a file next to the script, or inside the built .exe bundle."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def main():
    try:  # give the app its own taskbar icon instead of Python's
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DualSenseTester.App")
    except Exception:
        pass
    pygame.init()
    pygame.joystick.init()
    try:
        pygame.display.set_icon(pygame.image.load(resource("dualsense.png")))
    except Exception:
        pass
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption(APP_NAME)
    app = App(screen)
    app.tray = Tray(resource("dualsense.png"))
    if "--tray" in sys.argv and app.tray_ready():
        hide_window()
        app.hidden = True
    clock = pygame.time.Clock()
    last_draw = 0.0
    running = True
    while running:
        now = time.perf_counter()
        for e in pygame.event.get():
            if not app.handle(e, now):
                running = False
        if app.hidden:
            app.update_led(now)  # keep light-bar effects running while in the tray
            clock.tick(120)
            continue
        if now - last_draw >= 1.0 / DRAW_FPS:
            app.draw(now)
            pygame.display.flip()
            last_draw = now
        clock.tick(1000)  # poll fast so the update-rate meter isn't capped by the frame rate
    app.tray.stop()
    pygame.quit()


if __name__ == "__main__":
    main()

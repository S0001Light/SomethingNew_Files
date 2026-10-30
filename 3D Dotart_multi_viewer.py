#!/usr/bin/env python3
"""
WritersJumbler DOT Artwork Section Viewer

Uses the native .dotart format:
    offset/opposite = left and right rectangle coordinates
    x/y             = top and bottom rectangle coordinates

Flat mode draws the exact rectangles. 3D mode turns every rectangle into a
solid rectangular cuboid using its own X, Y, width, height, and depth, then
stacks the 64 cuboids into one object.

Install:
    python -m pip install pygame PyOpenGL PyOpenGL_accelerate
"""

import json
import random
import datetime
import math
import sys
from pathlib import Path

import pygame
from pygame.locals import DOUBLEBUF, OPENGL, RESIZABLE
from OpenGL.GL import *
from OpenGL.GLU import gluPerspective, gluLookAt

WIDTH = 1100
HEIGHT = 760
ART_WIDTH = 640
ART_HEIGHT = 640
SECTION_COUNT = 64
GRID_STEP = 10
MIN_CUBOID_DEPTH = 10.0
DEPTH_SCALE = 0.35
STACK_GAP = 4.0
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
YELLOW = (255, 230, 70)
GRAY = (145, 145, 145)
PREF_FILE = Path.home() / ".dotart_viewer_prefs.json"


def clamp(value, low, high):
    return max(low, min(high, value))


def timestamp():
    return datetime.datetime.now().strftime("%m-%d-%Y-%I-%M-%S-%p")


def load_preferences():
    try:
        data = json.loads(PREF_FILE.read_text(encoding="utf-8"))
        folder = Path(data.get("save_folder", ""))
        if folder.is_dir():
            return folder
    except Exception:
        pass
    return Path.cwd()


def save_preferences(folder):
    try:
        PREF_FILE.write_text(
            json.dumps({"save_folder": str(folder)}, indent=2),
            encoding="utf-8"
        )
    except OSError:
        pass


def choose_folder(current):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        name = filedialog.askdirectory(
            title="Choose DOTART save folder",
            initialdir=str(current)
        )
        root.destroy()
        return Path(name) if name else current
    except Exception:
        return current


def choose_dotart_file(current):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        name = filedialog.askopenfilename(
            title="Open DOT Artwork",
            initialdir=str(current),
            filetypes=[("DOT Artwork", "*.dotart"), ("JSON", "*.json"), ("All files", "*.*")]
        )
        root.destroy()
        return Path(name) if name else None
    except Exception:
        return None


def make_random_artwork():
    sections = []
    for section_number in range(1, SECTION_COUNT + 1):
        offset = (section_number - 1) * GRID_STEP
        opposite = ART_WIDTH - offset
        random_x = random.randrange(0, ART_HEIGHT + 1, GRID_STEP)
        random_y = random.randrange(0, ART_HEIGHT + 1, GRID_STEP)
        sections.append({
            "section": section_number,
            "offset": offset,
            "opposite": opposite,
            "x": random_x,
            "y": random_y
        })
    return {
        "format": "WritersJumbler DOT Artwork",
        "version": 1,
        "width": ART_WIDTH,
        "height": ART_HEIGHT,
        "sections": sections
    }


def validate_artwork(artwork):
    if not isinstance(artwork, dict):
        raise ValueError("The .dotart root must be an object.")
    if artwork.get("format") != "WritersJumbler DOT Artwork":
        raise ValueError("This is not a WritersJumbler DOT Artwork file.")
    sections = artwork.get("sections")
    if not isinstance(sections, list) or len(sections) != SECTION_COUNT:
        raise ValueError("The artwork must contain exactly 64 sections.")
    width = int(artwork.get("width", ART_WIDTH))
    height = int(artwork.get("height", ART_HEIGHT))
    if width <= 0 or height <= 0:
        raise ValueError("Artwork width and height must be positive.")
    clean = []
    for index, item in enumerate(sections):
        if not isinstance(item, dict):
            raise ValueError("Every section must be an object.")
        clean.append({
            "section": int(item.get("section", index + 1)),
            "offset": clamp(float(item.get("offset", 0)), 0, width),
            "opposite": clamp(float(item.get("opposite", width)), 0, width),
            "x": clamp(float(item.get("x", 0)), 0, height),
            "y": clamp(float(item.get("y", height)), 0, height)
        })
    return {
        "format": "WritersJumbler DOT Artwork",
        "version": artwork.get("version", 1),
        "width": width,
        "height": height,
        "sections": clean
    }


def save_dotart(artwork, folder):
    folder.mkdir(parents=True, exist_ok=True)
    filename = folder / ("DOTartwork_Rectangles_Rndm_" + timestamp() + ".dotart")
    with filename.open("w", encoding="utf-8") as output_file:
        json.dump(artwork, output_file, indent=2)
    return filename


def load_dotart(filename):
    with Path(filename).open("r", encoding="utf-8-sig") as input_file:
        return validate_artwork(json.load(input_file))


def newest_dotart_file(folder):
    files = list(Path(folder).glob("*.dotart"))
    return max(files, key=lambda item: item.stat().st_mtime) if files else None


def section_bounds(section):
    """Return the exact rectangle defined by all four stored dimensions."""
    left = min(section["offset"], section["opposite"])
    right = max(section["offset"], section["opposite"])
    top = min(section["x"], section["y"])
    bottom = max(section["x"], section["y"])
    return left, top, right, bottom


def cuboid_depth(section):
    """Depth is derived from this rectangle's own width and height."""
    left, top, right, bottom = section_bounds(section)
    rect_w = max(1.0, right - left)
    rect_h = max(1.0, bottom - top)
    # Smaller rectangle dimension controls thickness, so every cuboid differs.
    return max(MIN_CUBOID_DEPTH, min(rect_w, rect_h) * DEPTH_SCALE)


def stack_positions(sections):
    """Return centered Z positions for variable-depth cuboids."""
    depths = [cuboid_depth(section) for section in sections]
    total = sum(depths) + STACK_GAP * max(0, len(depths) - 1)
    cursor = -total / 2.0
    result = []
    for depth in depths:
        z0 = cursor
        z1 = cursor + depth
        result.append((z0, z1))
        cursor = z1 + STACK_GAP
    return result


def section_color(index, selected=False):
    if selected:
        return (1.0, 0.90, 0.20)
    t = index / 63.0
    return (
        0.28 + 0.72 * abs(math.sin((t + 0.00) * math.pi)),
        0.28 + 0.72 * abs(math.sin((t + 0.33) * math.pi)),
        0.28 + 0.72 * abs(math.sin((t + 0.66) * math.pi))
    )


def add_box(vertices, faces, face_materials, left, top, right, bottom, z0, z1, material):
    """Add one true rectangular cuboid using X/Y/width/height/depth."""
    start = len(vertices) + 1
    vertices.extend([
        (left, -top, z0), (right, -top, z0),
        (right, -bottom, z0), (left, -bottom, z0),
        (left, -top, z1), (right, -top, z1),
        (right, -bottom, z1), (left, -bottom, z1)
    ])
    cube_faces = [
        (0, 3, 2, 1), (4, 5, 6, 7),
        (0, 1, 5, 4), (1, 2, 6, 5),
        (2, 3, 7, 6), (3, 0, 4, 7)
    ]
    for face in cube_faces:
        faces.append([start + i for i in face])
        face_materials.append(material)


class Viewer:
    def __init__(self, startup_file=None):
        pygame.init()
        pygame.font.init()
        self.size = (WIDTH, HEIGHT)
        self.screen = pygame.display.set_mode(self.size, DOUBLEBUF | OPENGL | RESIZABLE)
        pygame.display.set_caption("WritersJumbler DOT Artwork Viewer")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 25)
        self.small_font = pygame.font.Font(None, 19)
        self.artwork = make_random_artwork()
        self.filename = None
        self.save_folder = load_preferences()
        self.cursor = 1
        self.selected = set()
        self.mode3d = False
        self.stack_all = True
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.rot_x = 24.0
        self.rot_y = -30.0
        self.rot_z = 0.0
        self.dragging = False
        self.last_mouse = (0, 0)
        self.message = "L opens a .dotart file | TAB switches Flat/3D"
        self.message_until = pygame.time.get_ticks() + 5000
        self.setup_gl()
        if startup_file:
            try:
                startup = Path(startup_file)
                self.artwork = load_dotart(startup)
                self.filename = startup
                self.save_folder = startup.parent.resolve()
                save_preferences(self.save_folder)
                self.message = "Opened " + startup.name
            except Exception as exc:
                self.message = "Open error: " + str(exc)

    def setup_gl(self):
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_NORMALIZE)
        glShadeModel(GL_SMOOTH)

    def notify(self, text, seconds=4):
        self.message = str(text)
        self.message_until = pygame.time.get_ticks() + seconds * 1000

    def projection(self, width, height):
        glViewport(0, 0, width, height)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        aw = self.artwork["width"]
        ah = self.artwork["height"]
        if self.mode3d:
            gluPerspective(45.0, width / max(1.0, float(height)), 1.0, 10000.0)
        else:
            aspect = width / max(1.0, float(height))
            view_h = ah * 1.22 / self.zoom
            view_w = view_h * aspect
            if view_w < aw * 1.22 / self.zoom:
                view_w = aw * 1.22 / self.zoom
                view_h = view_w / aspect
            glOrtho(-view_w / 2, view_w / 2, -view_h / 2, view_h / 2, -5000, 5000)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

    def draw_box(self, left, top, right, bottom, z0, z1, color):
        aw = self.artwork["width"]
        ah = self.artwork["height"]
        x0, x1 = left - aw / 2, right - aw / 2
        y0, y1 = ah / 2 - bottom, ah / 2 - top
        c = color
        glBegin(GL_QUADS)
        glColor3f(*c); glNormal3f(0, 0, 1)
        glVertex3f(x0,y0,z1); glVertex3f(x1,y0,z1); glVertex3f(x1,y1,z1); glVertex3f(x0,y1,z1)
        glColor3f(c[0]*.45,c[1]*.45,c[2]*.45); glNormal3f(0,0,-1)
        glVertex3f(x1,y0,z0); glVertex3f(x0,y0,z0); glVertex3f(x0,y1,z0); glVertex3f(x1,y1,z0)
        glColor3f(c[0]*.70,c[1]*.70,c[2]*.70); glNormal3f(-1,0,0)
        glVertex3f(x0,y0,z0); glVertex3f(x0,y0,z1); glVertex3f(x0,y1,z1); glVertex3f(x0,y1,z0)
        glNormal3f(1,0,0)
        glVertex3f(x1,y0,z1); glVertex3f(x1,y0,z0); glVertex3f(x1,y1,z0); glVertex3f(x1,y1,z1)
        glColor3f(c[0]*.84,c[1]*.84,c[2]*.84); glNormal3f(0,-1,0)
        glVertex3f(x0,y0,z0); glVertex3f(x1,y0,z0); glVertex3f(x1,y0,z1); glVertex3f(x0,y0,z1)
        glNormal3f(0,1,0)
        glVertex3f(x0,y1,z1); glVertex3f(x1,y1,z1); glVertex3f(x1,y1,z0); glVertex3f(x0,y1,z0)
        glEnd()

    def draw_flat_rect(self, left, top, right, bottom, color, line_width=2):
        aw = self.artwork["width"]
        ah = self.artwork["height"]
        x0, x1 = left - aw / 2, right - aw / 2
        y0, y1 = ah / 2 - bottom, ah / 2 - top
        glColor3f(*color)
        glLineWidth(line_width)
        glBegin(GL_LINE_LOOP)
        glVertex3f(x0,y0,0); glVertex3f(x1,y0,0)
        glVertex3f(x1,y1,0); glVertex3f(x0,y1,0)
        glEnd()

    def draw_scene(self, width, height):
        glClearColor(0.0, 0.0, 0.0, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        self.projection(width, height)
        aw, ah = self.artwork["width"], self.artwork["height"]
        if self.mode3d:
            distance = max(aw, ah) * 1.85 / self.zoom
            gluLookAt(0, 0, distance, 0, 0, 0, 0, 1, 0)
            glTranslatef(self.pan_x, self.pan_y, 0)
            glRotatef(self.rot_x, 1, 0, 0)
            glRotatef(self.rot_y, 0, 1, 0)
            glRotatef(self.rot_z, 0, 0, 1)
            glEnable(GL_LIGHTING)
            glEnable(GL_LIGHT0)
            glEnable(GL_COLOR_MATERIAL)
            glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
            glLightfv(GL_LIGHT0, GL_POSITION, (aw, ah, 900, 1))
            glLightfv(GL_LIGHT0, GL_AMBIENT, (.25,.25,.28,1))
            glLightfv(GL_LIGHT0, GL_DIFFUSE, (1,1,1,1))
        else:
            glDisable(GL_LIGHTING)
            glTranslatef(self.pan_x, self.pan_y, 0)

        sections = self.artwork["sections"]
        if self.mode3d:
            visible = sections if self.stack_all else [sections[self.cursor - 1]]
            positions = stack_positions(visible)
            for pos, section in enumerate(visible):
                index = int(section["section"]) - 1
                selected = not self.selected or section["section"] in self.selected
                if self.selected and not selected:
                    continue
                left, top, right, bottom = section_bounds(section)
                z0, z1 = positions[pos]
                self.draw_box(left, top, right, bottom, z0, z1,
                              section_color(index, section["section"] in self.selected))
        else:
            visible = sections if not self.selected else [sections[n-1] for n in sorted(self.selected)]
            for section in visible:
                index = int(section["section"]) - 1
                self.draw_flat_rect(*section_bounds(section),
                                    section_color(index, section["section"] in self.selected), 2)
            cursor_section = sections[self.cursor - 1]
            self.draw_flat_rect(*section_bounds(cursor_section), (0.0, .78, 1.0), 4)

        glDisable(GL_LIGHTING)
        glDisable(GL_DEPTH_TEST)
        self.draw_overlay(width, height)
        glEnable(GL_DEPTH_TEST)

    def draw_text(self, text, x, y, color=WHITE, font=None):
        font = font or self.font
        surface = font.render(str(text), True, color)
        data = pygame.image.tostring(surface, "RGBA", True)
        glWindowPos2d(int(x), int(y))
        glDrawPixels(surface.get_width(), surface.get_height(), GL_RGBA, GL_UNSIGNED_BYTE, data)

    def draw_panel(self, x, y, w, h, color):
        width, height = pygame.display.get_surface().get_size()
        glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
        glOrtho(0, width, 0, height, -1, 1)
        glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
        glColor4f(*color); glBegin(GL_QUADS)
        glVertex2f(x,y); glVertex2f(x+w,y); glVertex2f(x+w,y+h); glVertex2f(x,y+h)
        glEnd()
        glPopMatrix(); glMatrixMode(GL_PROJECTION); glPopMatrix(); glMatrixMode(GL_MODELVIEW)

    def draw_overlay(self, width, height):
        self.draw_panel(0, 0, width, 62, (0,0,0,.78))
        mode = "3D CUBOIDS" if self.mode3d else "FLAT RECTANGLES"
        title = f"{mode} | Section {self.cursor:02d}/64 | Zoom {self.zoom:.2f}x"
        self.draw_text(title, 10, 37, WHITE)
        help_text = "Arrows section | WASD rotate | Q/E roll | Z reset | TAB 2D/3D | T stack | P PNG | O OBJ+MTL | F folder"
        self.draw_text(help_text, 10, 13, GRAY, self.small_font)
        if pygame.time.get_ticks() < self.message_until:
            self.draw_text(self.message, 10, height - 28, YELLOW, self.small_font)

    def save_png(self):
        width, height = pygame.display.get_surface().get_size()
        glPixelStorei(GL_PACK_ALIGNMENT, 1)
        pixels = glReadPixels(0, 0, width, height, GL_RGB, GL_UNSIGNED_BYTE)
        image = pygame.image.fromstring(pixels, (width, height), "RGB", True)
        filename = self.save_folder / f"DOTartwork_{'3D' if self.mode3d else 'Flat'}_{timestamp()}.png"
        pygame.image.save(image, str(filename))
        self.notify("Saved " + filename.name)

    def export_obj_mtl(self):
        sections = self.artwork["sections"] if self.stack_all else [self.artwork["sections"][self.cursor-1]]
        if self.selected:
            sections = [s for s in sections if s["section"] in self.selected]
        vertices, faces, face_materials = [], [], []
        materials = {}
        positions = stack_positions(sections)
        for pos, section in enumerate(sections):
            index = int(section["section"]) - 1
            material = f"section_{index+1:02d}"
            materials[material] = section_color(index, section["section"] in self.selected)
            z0, z1 = positions[pos]
            add_box(vertices, faces, face_materials, *section_bounds(section),
                    z0, z1, material)
        base = self.save_folder / f"DOTartwork_Cuboids_{timestamp()}"
        obj_path = base.with_suffix(".obj")
        mtl_path = base.with_suffix(".mtl")
        with obj_path.open("w", encoding="utf-8", newline="\n") as f:
            f.write(f"# WritersJumbler DOT Artwork cuboids\nmtllib {mtl_path.name}\n")
            for x,y,z in vertices:
                f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
            current = None
            for face, material in zip(faces, face_materials):
                if material != current:
                    f.write(f"usemtl {material}\n")
                    current = material
                f.write("f " + " ".join(map(str, face)) + "\n")
        with mtl_path.open("w", encoding="utf-8", newline="\n") as f:
            f.write("# WritersJumbler materials\n")
            for name, (r,g,b) in materials.items():
                f.write(f"\nnewmtl {name}\nKa {r*.2:.6f} {g*.2:.6f} {b*.2:.6f}\n")
                f.write(f"Kd {r:.6f} {g:.6f} {b:.6f}\nKs .18 .18 .18\nNs 32\nd 1.0\nillum 2\n")
        self.notify(f"Saved {obj_path.name} and {mtl_path.name}")

    def run(self):
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.VIDEORESIZE:
                    self.size = (max(800,event.w), max(560,event.h))
                    self.screen = pygame.display.set_mode(self.size, DOUBLEBUF|OPENGL|RESIZABLE)
                    self.setup_gl()
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE: running = False
                    elif event.key == pygame.K_RIGHT: self.cursor = 1 if self.cursor >= 64 else self.cursor + 1
                    elif event.key == pygame.K_LEFT: self.cursor = 64 if self.cursor <= 1 else self.cursor - 1
                    elif event.key == pygame.K_SPACE:
                        if self.cursor in self.selected: self.selected.remove(self.cursor)
                        else: self.selected.add(self.cursor)
                    elif event.key == pygame.K_a and not self.mode3d: self.selected = set(range(1,65))
                    elif event.key in (pygame.K_c, pygame.K_0): self.selected.clear()
                    elif event.key == pygame.K_TAB: self.mode3d = not self.mode3d
                    elif event.key == pygame.K_t: self.stack_all = not self.stack_all
                    elif event.key == pygame.K_w: self.rot_x -= 5
                    elif event.key == pygame.K_s and self.mode3d: self.rot_x += 5
                    elif event.key == pygame.K_a and self.mode3d: self.rot_y -= 5
                    elif event.key == pygame.K_d: self.rot_y += 5
                    elif event.key == pygame.K_q: self.rot_z = getattr(self, "rot_z", 0.0) - 5
                    elif event.key == pygame.K_e: self.rot_z = getattr(self, "rot_z", 0.0) + 5
                    elif event.key == pygame.K_z:
                        self.rot_x, self.rot_y, self.rot_z = 24.0, -30.0, 0.0
                        self.zoom, self.pan_x, self.pan_y = 1.0, 0.0, 0.0
                    elif event.key == pygame.K_r: self.artwork = make_random_artwork(); self.selected.clear()
                    elif event.key == pygame.K_s:
                        name = save_dotart(self.artwork, self.save_folder); self.notify("Saved " + name.name)
                    elif event.key == pygame.K_l:
                        name = choose_dotart_file(self.save_folder)
                        if name:
                            try:
                                self.artwork = load_dotart(name); self.filename = name
                                self.save_folder = name.parent; save_preferences(self.save_folder)
                                self.selected.clear(); self.notify("Loaded " + name.name)
                            except Exception as exc: self.notify("Load error: " + str(exc), 7)
                    elif event.key == pygame.K_p: self.save_png()
                    elif event.key == pygame.K_o: self.export_obj_mtl()
                    elif event.key == pygame.K_f:
                        self.save_folder = choose_folder(self.save_folder)
                        save_preferences(self.save_folder); self.notify("Save folder: " + str(self.save_folder))
                    elif event.key in (pygame.K_EQUALS,pygame.K_PLUS,pygame.K_KP_PLUS): self.zoom=clamp(self.zoom*1.12,.1,12)
                    elif event.key in (pygame.K_MINUS,pygame.K_KP_MINUS): self.zoom=clamp(self.zoom/1.12,.1,12)
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1: self.dragging=True; self.last_mouse=event.pos
                    elif event.button == 4: self.zoom=clamp(self.zoom*1.1,.1,12)
                    elif event.button == 5: self.zoom=clamp(self.zoom/1.1,.1,12)
                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1: self.dragging=False
                elif event.type == pygame.MOUSEMOTION and self.dragging:
                    dx=event.pos[0]-self.last_mouse[0]; dy=event.pos[1]-self.last_mouse[1]
                    self.last_mouse=event.pos
                    if self.mode3d:
                        self.rot_y += dx*.45; self.rot_x=clamp(self.rot_x+dy*.45,-89,89)
                    else:
                        self.pan_x += dx; self.pan_y -= dy
                elif event.type == pygame.MOUSEWHEEL:
                    self.zoom=clamp(self.zoom*(1.1**event.y),.1,12)
            width,height=pygame.display.get_surface().get_size()
            self.draw_scene(width,height)
            pygame.display.flip()
            self.clock.tick(60)
        pygame.quit()


if __name__ == "__main__":
    # Windows/Open-With support: double-click a .dotart file or use
    #     python dotart_viewer.py artwork.dotart
    startup_file = sys.argv[1] if len(sys.argv) > 1 else None
    Viewer(startup_file).run()

#!/usr/bin/env python3
"""
Image Map Studio
A Tkinter image viewer and HTML image-map editor.

Features:
- Open PNG/JPG/BMP/GIF/TIFF/WebP images (Pillow)
- Draw Rectangle, Square, Ellipse, Circle, Polygon, or Freehand regions
- Move the image with Pan mode
- Zoom in/out while preserving image-coordinate accuracy
- Generate HTML <map>/<area> code
- Save a selected region as a transparent PNG cutout
- Save all generated HTML to a file

Install Pillow if needed:
    py -m pip install pillow
Run:
    py image_map_studio.py
"""

import html
import math
import os
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import List, Optional, Tuple

try:
    from PIL import Image, ImageTk, ImageDraw
except ImportError as exc:
    raise SystemExit("Pillow is required. Install it with: py -m pip install pillow") from exc

Point = Tuple[float, float]


@dataclass
class Region:
    kind: str
    points: List[Point]
    href: str = "#"
    alt: str = ""
    title: str = ""
    canvas_ids: List[int] = field(default_factory=list)


class ImageMapStudio(tk.Tk):
    COLORS = {
        "Rectangle": "#00d9ff",
        "Square": "#55ff77",
        "Ellipse": "#ffbf38",
        "Circle": "#ff6d93",
        "Polygon": "#b68cff",
        "Freehand": "#ff7657",
    }

    def __init__(self):
        super().__init__()
        self.title("Image Map Studio")
        self.geometry("1280x820")
        self.minsize(900, 600)

        self.original: Optional[Image.Image] = None
        self.display_photo: Optional[ImageTk.PhotoImage] = None
        self.image_path = ""
        self.image_id: Optional[int] = None
        self.zoom = 1.0
        self.offset_x = 30.0
        self.offset_y = 30.0
        self.regions: List[Region] = []
        self.selected_index: Optional[int] = None
        self.start_image: Optional[Point] = None
        self.live_points: List[Point] = []
        self.preview_ids: List[int] = []
        self.pan_start: Optional[Tuple[int, int]] = None
        self.pan_origin: Optional[Point] = None

        self.mode = tk.StringVar(value="Rectangle")
        self.status = tk.StringVar(value="Open an image to begin.")
        self.map_name = tk.StringVar(value="image-map")
        self._build_ui()
        self._bind_events()

    def _build_ui(self):
        toolbar = ttk.Frame(self, padding=6)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text="Open Image", command=self.open_image).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Save HTML", command=self.save_html).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Cut Out Selection", command=self.save_cutout).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Label(toolbar, text="Tool:").pack(side=tk.LEFT)
        tools = ["Rectangle", "Square", "Ellipse", "Circle", "Polygon", "Freehand", "Pan"]
        ttk.Combobox(toolbar, textvariable=self.mode, values=tools, state="readonly", width=12).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Finish Polygon", command=self.finish_polygon).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Delete", command=self.delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Clear", command=self.clear_regions).pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(toolbar, text="Zoom -", command=lambda: self.set_zoom(self.zoom / 1.25)).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="100%", command=lambda: self.set_zoom(1.0)).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Zoom +", command=lambda: self.set_zoom(self.zoom * 1.25)).pack(side=tk.LEFT, padx=2)

        main = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True)

        viewer_frame = ttk.Frame(main)
        side = ttk.Frame(main, width=340, padding=8)
        main.add(viewer_frame, weight=4)
        main.add(side, weight=1)

        self.canvas = tk.Canvas(viewer_frame, background="#20242a", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        ttk.Label(side, text="Regions", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W)
        self.listbox = tk.Listbox(side, height=11, exportselection=False)
        self.listbox.pack(fill=tk.X, pady=(4, 8))
        self.listbox.bind("<<ListboxSelect>>", self.on_region_select)

        form = ttk.Frame(side)
        form.pack(fill=tk.X)
        self.href_var = tk.StringVar(value="#")
        self.alt_var = tk.StringVar()
        self.title_var = tk.StringVar()
        for row, (label, var) in enumerate((("Link / href", self.href_var), ("Alt text", self.alt_var), ("Title", self.title_var), ("Map name", self.map_name))):
            ttk.Label(form, text=label).grid(row=row * 2, column=0, sticky="w", pady=(3, 0))
            ttk.Entry(form, textvariable=var).grid(row=row * 2 + 1, column=0, sticky="ew")
        form.columnconfigure(0, weight=1)
        ttk.Button(side, text="Apply Region Details", command=self.apply_details).pack(fill=tk.X, pady=8)

        ttk.Label(side, text="Generated HTML", font=("Segoe UI", 11, "bold")).pack(anchor=tk.W, pady=(6, 2))
        code_frame = ttk.Frame(side)
        code_frame.pack(fill=tk.BOTH, expand=True)
        self.code_text = tk.Text(code_frame, wrap="none", font=("Consolas", 9), undo=True)
        ybar = ttk.Scrollbar(code_frame, orient=tk.VERTICAL, command=self.code_text.yview)
        xbar = ttk.Scrollbar(code_frame, orient=tk.HORIZONTAL, command=self.code_text.xview)
        self.code_text.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.code_text.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        code_frame.rowconfigure(0, weight=1)
        code_frame.columnconfigure(0, weight=1)
        ttk.Button(side, text="Copy HTML", command=self.copy_html).pack(fill=tk.X, pady=(8, 0))

        ttk.Label(self, textvariable=self.status, anchor=tk.W, padding=(8, 4)).pack(side=tk.BOTTOM, fill=tk.X)

    def _bind_events(self):
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Double-Button-1>", lambda _e: self.finish_polygon())
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", lambda _e: self.set_zoom(self.zoom * 1.1))
        self.canvas.bind("<Button-5>", lambda _e: self.set_zoom(self.zoom / 1.1))
        self.bind("<Delete>", lambda _e: self.delete_selected())
        self.bind("<Escape>", lambda _e: self.cancel_preview())

    def open_image(self):
        path = filedialog.askopenfilename(
            title="Open image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with Image.open(path) as im:
                self.original = im.convert("RGBA")
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))
            return
        self.image_path = path
        self.regions.clear()
        self.selected_index = None
        self.zoom = 1.0
        self.offset_x = self.offset_y = 30.0
        self.redraw_all()
        self.refresh_list()
        self.update_html()
        self.status.set(f"Loaded {os.path.basename(path)}: {self.original.width} x {self.original.height}")

    def image_to_canvas(self, p: Point) -> Point:
        return self.offset_x + p[0] * self.zoom, self.offset_y + p[1] * self.zoom

    def canvas_to_image(self, x: float, y: float, clamp=True) -> Point:
        if not self.original:
            return 0.0, 0.0
        ix = (x - self.offset_x) / self.zoom
        iy = (y - self.offset_y) / self.zoom
        if clamp:
            ix = min(max(ix, 0.0), self.original.width - 1.0)
            iy = min(max(iy, 0.0), self.original.height - 1.0)
        return ix, iy

    def point_inside_image(self, x, y):
        if not self.original:
            return False
        ix, iy = self.canvas_to_image(x, y, clamp=False)
        return 0 <= ix < self.original.width and 0 <= iy < self.original.height

    def redraw_all(self):
        self.canvas.delete("all")
        self.preview_ids.clear()
        if not self.original:
            return
        w = max(1, round(self.original.width * self.zoom))
        h = max(1, round(self.original.height * self.zoom))
        resized = self.original.resize((w, h), Image.Resampling.LANCZOS)
        self.display_photo = ImageTk.PhotoImage(resized)
        self.image_id = self.canvas.create_image(self.offset_x, self.offset_y, image=self.display_photo, anchor="nw", tags="base_image")
        for i, region in enumerate(self.regions):
            self.draw_region(region, selected=(i == self.selected_index))

    def draw_region(self, region: Region, selected=False):
        region.canvas_ids.clear()
        color = "#ffffff" if selected else self.COLORS.get(region.kind, "#00d9ff")
        width = 3 if selected else 2
        pts = [self.image_to_canvas(p) for p in region.points]
        if region.kind in ("Rectangle", "Square", "Ellipse", "Circle") and len(pts) >= 2:
            x1, y1 = pts[0]
            x2, y2 = pts[1]
            fn = self.canvas.create_rectangle if region.kind in ("Rectangle", "Square") else self.canvas.create_oval
            rid = fn(x1, y1, x2, y2, outline=color, width=width, dash=(6, 3), fill="")
        else:
            flat = [v for p in pts for v in p]
            if len(flat) < 4:
                return
            rid = self.canvas.create_polygon(*flat, outline=color, width=width, fill="", dash=(6, 3))
        region.canvas_ids.append(rid)

    def on_press(self, event):
        if not self.original:
            return
        if self.mode.get() == "Pan" or event.state & 0x0004:
            self.pan_start = (event.x, event.y)
            self.pan_origin = (self.offset_x, self.offset_y)
            self.canvas.configure(cursor="fleur")
            return
        if not self.point_inside_image(event.x, event.y):
            return
        p = self.canvas_to_image(event.x, event.y)
        mode = self.mode.get()
        if mode == "Polygon":
            if not self.live_points:
                self.live_points = [p]
            else:
                self.live_points.append(p)
            self.draw_preview_polygon()
            self.status.set("Polygon: click more points, then double-click or use Finish Polygon.")
            return
        self.start_image = p
        self.live_points = [p]

    def on_drag(self, event):
        if self.pan_start and self.pan_origin:
            self.offset_x = self.pan_origin[0] + event.x - self.pan_start[0]
            self.offset_y = self.pan_origin[1] + event.y - self.pan_start[1]
            self.redraw_all()
            return
        if not self.original or self.start_image is None:
            return
        p = self.canvas_to_image(event.x, event.y)
        mode = self.mode.get()
        if mode == "Freehand":
            if not self.live_points or math.dist(self.live_points[-1], p) >= max(1, 2 / self.zoom):
                self.live_points.append(p)
            self.draw_preview_polygon(close=False)
        elif mode in ("Rectangle", "Square", "Ellipse", "Circle"):
            end = self.constrained_endpoint(self.start_image, p, mode)
            self.live_points = [self.start_image, end]
            self.draw_preview_box(mode)

    def on_release(self, event):
        if self.pan_start:
            self.pan_start = None
            self.pan_origin = None
            self.canvas.configure(cursor="crosshair")
            return
        mode = self.mode.get()
        if self.start_image is None or mode == "Polygon":
            return
        if mode == "Freehand":
            if len(self.live_points) >= 3:
                self.add_region("Freehand", self.live_points.copy())
        elif mode in ("Rectangle", "Square", "Ellipse", "Circle") and len(self.live_points) == 2:
            if math.dist(self.live_points[0], self.live_points[1]) >= 2:
                self.add_region(mode, self.live_points.copy())
        self.start_image = None
        self.live_points.clear()
        self.cancel_preview(redraw=False)
        self.redraw_all()

    def constrained_endpoint(self, start, end, mode):
        if mode not in ("Square", "Circle"):
            return end
        dx, dy = end[0] - start[0], end[1] - start[1]
        side = max(abs(dx), abs(dy))
        x = start[0] + side * (1 if dx >= 0 else -1)
        y = start[1] + side * (1 if dy >= 0 else -1)
        return self.canvas_to_image(*self.image_to_canvas((x, y)))

    def clear_preview(self):
        for item in self.preview_ids:
            self.canvas.delete(item)
        self.preview_ids.clear()

    def draw_preview_box(self, mode):
        self.clear_preview()
        if len(self.live_points) < 2:
            return
        x1, y1 = self.image_to_canvas(self.live_points[0])
        x2, y2 = self.image_to_canvas(self.live_points[1])
        fn = self.canvas.create_rectangle if mode in ("Rectangle", "Square") else self.canvas.create_oval
        self.preview_ids.append(fn(x1, y1, x2, y2, outline="#ffffff", width=2, dash=(4, 3)))

    def draw_preview_polygon(self, close=True):
        self.clear_preview()
        if len(self.live_points) < 2:
            return
        flat = [v for p in self.live_points for v in self.image_to_canvas(p)]
        if close and len(self.live_points) >= 3:
            rid = self.canvas.create_polygon(*flat, outline="#ffffff", fill="", width=2, dash=(4, 3))
        else:
            rid = self.canvas.create_line(*flat, fill="#ffffff", width=2)
        self.preview_ids.append(rid)

    def finish_polygon(self):
        if self.mode.get() == "Polygon" and len(self.live_points) >= 3:
            self.add_region("Polygon", self.live_points.copy())
            self.live_points.clear()
            self.cancel_preview(redraw=False)
            self.redraw_all()
        elif self.mode.get() == "Polygon":
            self.status.set("A polygon needs at least three points.")

    def cancel_preview(self, redraw=True):
        self.start_image = None
        self.live_points.clear()
        self.clear_preview()
        if redraw:
            self.redraw_all()

    def add_region(self, kind, points):
        n = len(self.regions) + 1
        self.regions.append(Region(kind, points, "#", f"Region {n}", f"Region {n}"))
        self.selected_index = len(self.regions) - 1
        self.refresh_list()
        self.load_selected_details()
        self.update_html()
        self.status.set(f"Added {kind} region {n}.")

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        for i, region in enumerate(self.regions, 1):
            self.listbox.insert(tk.END, f"{i}. {region.kind} - {region.alt or '(no alt text)'}")
        if self.selected_index is not None and self.selected_index < len(self.regions):
            self.listbox.selection_set(self.selected_index)
            self.listbox.see(self.selected_index)

    def on_region_select(self, _event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        self.selected_index = sel[0]
        self.load_selected_details()
        self.redraw_all()

    def load_selected_details(self):
        if self.selected_index is None or self.selected_index >= len(self.regions):
            return
        r = self.regions[self.selected_index]
        self.href_var.set(r.href)
        self.alt_var.set(r.alt)
        self.title_var.set(r.title)

    def apply_details(self):
        if self.selected_index is None or self.selected_index >= len(self.regions):
            return
        r = self.regions[self.selected_index]
        r.href = self.href_var.get().strip() or "#"
        r.alt = self.alt_var.get().strip()
        r.title = self.title_var.get().strip()
        self.refresh_list()
        self.update_html()

    def delete_selected(self):
        if self.selected_index is None or self.selected_index >= len(self.regions):
            return
        del self.regions[self.selected_index]
        self.selected_index = min(self.selected_index, len(self.regions) - 1) if self.regions else None
        self.refresh_list()
        self.update_html()
        self.redraw_all()

    def clear_regions(self):
        if self.regions and messagebox.askyesno("Clear regions", "Delete every region?"):
            self.regions.clear()
            self.selected_index = None
            self.refresh_list()
            self.update_html()
            self.redraw_all()

    def set_zoom(self, new_zoom):
        if not self.original:
            return
        new_zoom = min(max(new_zoom, 0.1), 8.0)
        cx = self.canvas.winfo_width() / 2
        cy = self.canvas.winfo_height() / 2
        before = self.canvas_to_image(cx, cy, clamp=False)
        self.zoom = new_zoom
        self.offset_x = cx - before[0] * self.zoom
        self.offset_y = cy - before[1] * self.zoom
        self.redraw_all()
        self.status.set(f"Zoom: {self.zoom * 100:.0f}%")

    def on_mousewheel(self, event):
        self.set_zoom(self.zoom * (1.1 if event.delta > 0 else 1 / 1.1))

    @staticmethod
    def ellipse_polygon(p1, p2, steps=32):
        x1, y1 = p1
        x2, y2 = p2
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        rx, ry = abs(x2 - x1) / 2, abs(y2 - y1) / 2
        return [(cx + rx * math.cos(2 * math.pi * i / steps), cy + ry * math.sin(2 * math.pi * i / steps)) for i in range(steps)]

    def html_area(self, region):
        attrs = f'href="{html.escape(region.href, quote=True)}" alt="{html.escape(region.alt, quote=True)}" title="{html.escape(region.title, quote=True)}"'
        if region.kind in ("Rectangle", "Square"):
            (x1, y1), (x2, y2) = region.points[:2]
            coords = [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
            return f'  <area shape="rect" coords="{",".join(str(round(v)) for v in coords)}" {attrs}>'
        if region.kind == "Circle":
            (x1, y1), (x2, y2) = region.points[:2]
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            radius = min(abs(x2 - x1), abs(y2 - y1)) / 2
            return f'  <area shape="circle" coords="{round(cx)},{round(cy)},{round(radius)}" {attrs}>'
        points = self.ellipse_polygon(*region.points[:2]) if region.kind == "Ellipse" else region.points
        coords = ",".join(f"{round(x)},{round(y)}" for x, y in points)
        return f'  <area shape="poly" coords="{coords}" {attrs}>'

    def generate_html(self):
        image_name = os.path.basename(self.image_path) if self.image_path else "image.png"
        name = self.map_name.get().strip() or "image-map"
        lines = [f'<img src="{html.escape(image_name, quote=True)}" usemap="#{html.escape(name, quote=True)}" alt="">', "", f'<map name="{html.escape(name, quote=True)}">']
        lines.extend(self.html_area(r) for r in self.regions)
        lines.append("</map>")
        return "\n".join(lines)

    def update_html(self):
        self.code_text.delete("1.0", tk.END)
        self.code_text.insert("1.0", self.generate_html())

    def copy_html(self):
        code = self.code_text.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(code)
        self.status.set("HTML copied to the clipboard.")

    def save_html(self):
        if not self.original:
            messagebox.showinfo("No image", "Open an image first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".html", filetypes=[("HTML files", "*.html"), ("Text files", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.code_text.get("1.0", "end-1c"))
            self.status.set(f"Saved HTML: {path}")

    def region_mask(self, region):
        mask = Image.new("L", self.original.size, 0)
        draw = ImageDraw.Draw(mask)
        if region.kind in ("Rectangle", "Square"):
            p1, p2 = region.points[:2]
            box = [round(min(p1[0], p2[0])), round(min(p1[1], p2[1])), round(max(p1[0], p2[0])), round(max(p1[1], p2[1]))]
            draw.rectangle(box, fill=255)
        elif region.kind in ("Ellipse", "Circle"):
            p1, p2 = region.points[:2]
            box = [round(min(p1[0], p2[0])), round(min(p1[1], p2[1])), round(max(p1[0], p2[0])), round(max(p1[1], p2[1]))]
            draw.ellipse(box, fill=255)
        else:
            draw.polygon([(round(x), round(y)) for x, y in region.points], fill=255)
        return mask

    def save_cutout(self):
        if self.original is None or self.selected_index is None or self.selected_index >= len(self.regions):
            messagebox.showinfo("No selection", "Select a region first.")
            return
        region = self.regions[self.selected_index]
        mask = self.region_mask(region)
        bbox = mask.getbbox()
        if not bbox:
            messagebox.showerror("Empty selection", "The selected region is empty.")
            return
        transparent = Image.new("RGBA", self.original.size, (0, 0, 0, 0))
        transparent.paste(self.original, (0, 0), mask)
        cutout = transparent.crop(bbox)
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG image", "*.png")], initialfile="cutout.png")
        if path:
            cutout.save(path, "PNG")
            self.status.set(f"Saved transparent cutout: {path}")


if __name__ == "__main__":
    app = ImageMapStudio()
    app.mainloop()

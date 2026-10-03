import pygame

pygame.init()
WIDTH, HEIGHT = 760, 620
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("RGB + Lightness Color Chooser")
clock = pygame.time.Clock()
font = pygame.font.SysFont("consolas", 22)
small = pygame.font.SysFont("consolas", 16)
title_font = pygame.font.SysFont("consolas", 30, bold=True)

BG = (238, 242, 247)
CARD = (255, 255, 255)
TEXT = (30, 41, 59)
MUTED = (100, 116, 139)

class Slider:
    def __init__(self, x, y, w, label, value, maximum, color):
        self.x, self.y, self.w = x, y, w
        self.label, self.value = label, value
        self.maximum, self.color = maximum, color
        self.dragging = False
        self.track = pygame.Rect(x, y, w, 8)

    def knob_x(self):
        return self.x + int((self.value / self.maximum) * self.w)

    def set_from_x(self, mx):
        mx = max(self.x, min(self.x + self.w, mx))
        self.value = round((mx - self.x) / self.w * self.maximum)

    def handle(self, event):
        knob = pygame.Rect(self.knob_x() - 13, self.y - 10, 26, 28)
        hit = pygame.Rect(self.x - 8, self.y - 16, self.w + 16, 40)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and hit.collidepoint(event.pos):
            self.dragging = True
            self.set_from_x(event.pos[0])
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging = False
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            self.set_from_x(event.pos[0])

    def draw(self, surf):
        pygame.draw.rect(surf, (203, 213, 225), self.track, border_radius=4)
        filled = pygame.Rect(self.x, self.y, max(1, self.knob_x() - self.x), 8)
        pygame.draw.rect(surf, self.color, filled, border_radius=4)
        pygame.draw.circle(surf, (255,255,255), (self.knob_x(), self.y + 4), 13)
        pygame.draw.circle(surf, self.color, (self.knob_x(), self.y + 4), 13, 4)
        surf.blit(font.render(self.label, True, TEXT), (self.x - 45, self.y - 10))
        suffix = "%" if self.label == "L" else ""
        value_surface = font.render(f"{self.value}{suffix}", True, TEXT)
        surf.blit(value_surface, (self.x + self.w + 25, self.y - 10))

r = Slider(125, 355, 470, "R", 238, 255, (239, 68, 68))
g = Slider(125, 410, 470, "G", 78, 255, (34, 197, 94))
b = Slider(125, 465, 470, "B", 93, 255, (59, 130, 246))
l = Slider(125, 535, 470, "L", 50, 100, (71, 85, 105))
sliders = [r, g, b, l]

def clamp(v): return max(0, min(255, round(v)))
def final_rgb():
    rgb = [r.value, g.value, b.value]
    if l.value == 50: return tuple(rgb)
    if l.value < 50:
        f = l.value / 50
        return tuple(clamp(v * f) for v in rgb)
    f = (l.value - 50) / 50
    return tuple(clamp(v + (255-v)*f) for v in rgb)

def hex_value(rgb): return "#%02X%02X%02X" % rgb

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        for slider in sliders:
            slider.handle(event)

    screen.fill(BG)
    screen.blit(title_font.render("RGB + Lightness Color Chooser", True, TEXT), (40, 27))
    screen.blit(small.render("One color: RGB with lightness adjustment", True, MUTED), (42, 68))

    card = pygame.Rect(40, 105, 680, 480)
    pygame.draw.rect(screen, CARD, card, border_radius=22)

    color = final_rgb()
    preview = pygame.Rect(40, 105, 680, 195)
    pygame.draw.rect(screen, color, preview, border_top_left_radius=22, border_top_right_radius=22)

    hx = hex_value(color)
    label_rect = pygame.Rect(275, 225, 210, 48)
    pygame.draw.rect(screen, (15, 23, 42), label_rect, border_radius=12)
    hs = font.render(hx, True, (255,255,255))
    screen.blit(hs, hs.get_rect(center=label_rect.center))

    for slider in sliders:
        slider.draw(screen)

    screen.blit(small.render("BLACK", True, MUTED), (125, 565))
    screen.blit(small.render("ORIGINAL", True, MUTED), (322, 565))
    screen.blit(small.render("WHITE", True, MUTED), (545, 565))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()

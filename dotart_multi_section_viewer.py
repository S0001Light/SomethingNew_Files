import json
import random
import datetime
from pathlib import Path

import pygame

WIDTH = 640
HEIGHT = 640
SECTION_COUNT = 64
GRID_STEP = 10
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
YELLOW = (255, 230, 70)
GRAY = (145, 145, 145)

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("DOT Artwork Section Viewer")
clock = pygame.time.Clock()
font = pygame.font.Font(None, 28)
small_font = pygame.font.Font(None, 21)


def make_random_artwork():
    """Create 64 independent random sections."""
    sections = []

    for section_number in range(1, SECTION_COUNT + 1):
        offset = (section_number - 1) * GRID_STEP
        opposite = WIDTH - offset
        random_x = random.randrange(0, HEIGHT + 1, GRID_STEP)
        random_y = random.randrange(0, HEIGHT + 1, GRID_STEP)

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
        "width": WIDTH,
        "height": HEIGHT,
        "sections": sections
    }


def timestamp():
    return datetime.datetime.now().strftime("%m-%d-%Y-%I-%M-%S-%p")


def save_dotart(artwork):
    """Save editable artwork data in a .dotart JSON-based file."""
    filename = Path("DOTartwork_Rectangles_Rndm_" + timestamp() + ".dotart")
    with filename.open("w", encoding="utf-8") as output_file:
        json.dump(artwork, output_file, indent=2)
    return filename


def load_dotart(filename):
    with Path(filename).open("r", encoding="utf-8") as input_file:
        artwork = json.load(input_file)

    if artwork.get("format") != "WritersJumbler DOT Artwork":
        raise ValueError("This is not a supported DOT artwork file.")

    if len(artwork.get("sections", [])) != SECTION_COUNT:
        raise ValueError("The artwork must contain exactly 64 sections.")

    return artwork


def newest_dotart_file():
    files = list(Path(".").glob("*.dotart"))
    if not files:
        return None
    return max(files, key=lambda item: item.stat().st_mtime)


def section_points(section):
    left = section["offset"]
    right = section["opposite"]
    x = section["x"]
    y = section["y"]

    return (
        (left, y),
        (right, y),
        (right, x),
        (left, x)
    )


def draw_section(surface, section, color):
    p1, p2, p3, p4 = section_points(section)

    pygame.draw.line(surface, color, p1, p2, 1)
    pygame.draw.line(surface, color, p3, p2, 1)
    pygame.draw.line(surface, color, p3, p4, 1)
    pygame.draw.line(surface, color, p1, p4, 1)

    for point in (p1, p2, p3, p4):
        pygame.draw.circle(surface, color, point, 5, 1)


def draw_artwork(surface, artwork, selected_sections):
    surface.fill(BLACK)

    if not selected_sections:
        for section in artwork["sections"]:
            draw_section(surface, section, WHITE)
    else:
        for number in sorted(selected_sections):
            draw_section(surface, artwork["sections"][number - 1], YELLOW)


def draw_status(surface, selected_sections, cursor, message):
    panel = pygame.Surface((WIDTH, 58), pygame.SRCALPHA)
    panel.fill((0, 0, 0, 205))
    surface.blit(panel, (0, HEIGHT - 58))

    if not selected_sections:
        title = "Viewing: ALL 64 sections | Cursor {:02d}".format(cursor)
    else:
        nums = ",".join(str(n) for n in sorted(selected_sections))
        title = "Selected: " + nums + " | Cursor {:02d}".format(cursor)

    surface.blit(font.render(title, True, WHITE), (10, HEIGHT - 54))
    help_text = "Left/Right move | SPACE toggle | A all | C clear | R random | S save | L load | B BMP"
    surface.blit(small_font.render(help_text, True, GRAY), (10, HEIGHT - 29))

    if message:
        message_image = small_font.render(message, True, YELLOW)
        surface.blit(message_image, (WIDTH - message_image.get_width() - 10, 8))


def save_bmp(artwork, selected_sections):
    image = pygame.Surface((WIDTH, HEIGHT))
    draw_artwork(image, artwork, selected_sections)

    if not selected_sections:
        label = "ALL"
    else:
        label = "MULTI_" + "-".join(str(n) for n in sorted(selected_sections))

    filename = Path(
        "DOTartwork_{}_{}.bmp".format(label, timestamp())
    )
    pygame.image.save(image, str(filename))
    return filename


def number_key_to_section(key):
    number_keys = {
        pygame.K_1: 1,
        pygame.K_2: 8,
        pygame.K_3: 16,
        pygame.K_4: 24,
        pygame.K_5: 32,
        pygame.K_6: 40,
        pygame.K_7: 48,
        pygame.K_8: 56,
        pygame.K_9: 64,
    }
    return number_keys.get(key)


def main():
    artwork = make_random_artwork()
    cursor = 1
    selected_sections = set()
    message = "SPACE adds/removes the cursor section"
    running = True

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_RIGHT:
                    cursor = 1 if cursor >= SECTION_COUNT else cursor + 1
                    message = "Cursor section {:02d}".format(cursor)
                elif event.key == pygame.K_LEFT:
                    cursor = SECTION_COUNT if cursor <= 1 else cursor - 1
                    message = "Cursor section {:02d}".format(cursor)
                elif event.key == pygame.K_SPACE:
                    if cursor in selected_sections:
                        selected_sections.remove(cursor)
                        message = "Removed section {:02d}".format(cursor)
                    else:
                        selected_sections.add(cursor)
                        message = "Added section {:02d}".format(cursor)
                elif event.key == pygame.K_a:
                    selected_sections = set(range(1, SECTION_COUNT + 1))
                    message = "Selected all 64 sections"
                elif event.key in (pygame.K_c, pygame.K_0):
                    selected_sections.clear()
                    message = "Selection cleared; showing all"
                elif event.key == pygame.K_r:
                    artwork = make_random_artwork()
                    selected_sections.clear()
                    message = "New random artwork created"
                elif event.key == pygame.K_s:
                    filename = save_dotart(artwork)
                    message = "Saved " + filename.name
                elif event.key == pygame.K_l:
                    filename = newest_dotart_file()
                    if filename is None:
                        message = "No .dotart file found"
                    else:
                        try:
                            artwork = load_dotart(filename)
                            selected_sections.clear()
                            message = "Loaded " + filename.name
                        except (OSError, ValueError, json.JSONDecodeError) as error:
                            message = "Load error: " + str(error)
                elif event.key == pygame.K_b:
                    filename = save_bmp(artwork, selected_sections)
                    message = "Saved " + filename.name
                else:
                    chosen = number_key_to_section(event.key)
                    if chosen is not None:
                        cursor = chosen
                        message = "Cursor jumped to section {:02d}".format(chosen)

        draw_artwork(screen, artwork, selected_sections)

        # Cursor marker so you know which section SPACE will toggle.
        cursor_section = artwork["sections"][cursor - 1]
        for point in section_points(cursor_section):
            pygame.draw.circle(screen, (0, 200, 255), point, 7, 1)

        draw_status(screen, selected_sections, cursor, message)
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()


if __name__ == "__main__":
    main()

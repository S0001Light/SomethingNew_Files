from PIL import Image

INPUT_IMAGE = "image.jpg"
OUTPUT_GIF = "spinning.gif"

direction = "right"  # "right" or "left"

# Choose background color here
BACKGROUND_COLOR = "black"

# Other examples:
# BACKGROUND_COLOR = "white"
# BACKGROUND_COLOR = "red"
# BACKGROUND_COLOR = "#202020"
# BACKGROUND_COLOR = (30, 80, 160)

img = Image.open(INPUT_IMAGE).convert("RGBA")

frames = []
steps = 24

sequence = list(range(steps))

if direction == "left":
    sequence.reverse()

for i in sequence:
    progress = i / (steps - 1)
    scale = abs(1 - 2 * progress)

    new_width = max(1, int(img.width * scale))

    # Solid selectable background
    frame = Image.new(
        "RGBA",
        img.size,
        BACKGROUND_COLOR
    )

    resized = img.resize(
        (new_width, img.height),
        Image.Resampling.LANCZOS
    )

    x = (img.width - new_width) // 2

    # Keeps PNG transparency working correctly
    frame.alpha_composite(resized, (x, 0))

    frames.append(frame.convert("RGB"))

frames[0].save(
    OUTPUT_GIF,
    save_all=True,
    append_images=frames[1:],
    duration=50,
    loop=0
)

print(f"Created {OUTPUT_GIF}")

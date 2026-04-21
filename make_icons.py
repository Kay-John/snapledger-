from PIL import Image, ImageDraw, ImageFont
import os

def make_icon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background rounded square
    radius = size // 5
    draw.rounded_rectangle([0, 0, size, size], radius=radius, fill="#3B82F6")

    # Document shape
    m = size // 8
    w = size - m * 2
    h = int(w * 1.3)
    top = (size - h) // 2
    fold = w // 4
    # Main body
    draw.polygon([
        (m, top + fold),
        (m + w - fold, top),
        (m + w, top + fold),
        (m + w, top + h),
        (m, top + h),
    ], fill="white")
    # Fold triangle
    draw.polygon([
        (m + w - fold, top),
        (m + w - fold, top + fold),
        (m + w, top + fold),
    ], fill="#93C5FD")
    # Lines
    lm = m + w // 6
    lw = w - w // 3
    ls = size // 16
    ly = top + fold + ls * 2
    for _ in range(4):
        draw.rectangle([lm, ly, lm + lw, ly + max(2, size // 80)], fill="#3B82F6")
        ly += ls + max(2, size // 80)

    return img

os.makedirs("static", exist_ok=True)
make_icon(192).save("static/icon-192.png")
make_icon(512).save("static/icon-512.png")
print("Icons created: static/icon-192.png and static/icon-512.png")

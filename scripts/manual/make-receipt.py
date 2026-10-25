"""Create a clearly fictional receipt fixture and load it into IPA_Manual."""

import json
from datetime import date
from pathlib import Path

from android import ROOT, adb, assert_device
from PIL import Image, ImageDraw, ImageFont

assert_device()
fixture = json.loads((ROOT / ".context/manual/fixture.json").read_text())
image = Image.new("RGB", (1000, 1400), "#fffdf3")
draw = ImageDraw.Draw(image)
font_path = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
rows = [
    (fixture["establishment_name"].upper(), 90, 42),
    ("DOCUMENTO DE DEMOSTRACION", 170, 32),
    ("SIN VALOR FISCAL", 220, 28),
    (date.today().strftime("%d/%m/%Y"), 350, 32),
    ("Alimento                          Cantidad", 460, 32),
    ("Arroz blanco, crudo                 2 kg", 550, 32),
    (f"Recibido por: {fixture['accounts']['field_worker']['name']}", 900, 32),
    ("Datos ficticios para el manual de usuario", 1160, 27),
]
for text, y, size in rows:
    font = (
        ImageFont.truetype(str(font_path), size)
        if font_path.exists()
        else ImageFont.load_default(size=size)
    )
    draw.text((65, y), text, fill="#282a24", font=font)
draw.line((65, 420, 935, 420), fill="#777777", width=2)
draw.line((65, 650, 935, 650), fill="#777777", width=2)
target = ROOT / ".context/manual/recibo-demo.jpg"
image.save(target, quality=95)
adb("push", str(target), "/sdcard/Pictures/recibo-demo.jpg")
adb(
    "shell",
    "am",
    "broadcast",
    "-a",
    "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
    "-d",
    "file:///sdcard/Pictures/recibo-demo.jpg",
)
print(target)

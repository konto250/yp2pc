"""RSS用の1400px正方形カバーを生成します（開発時のみPillowを使用）。"""

from pathlib import Path
from PIL import Image, ImageDraw

image = Image.new("RGB", (1400, 1400), "#f6f5f0")
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((200, 200, 1200, 1200), radius=230, fill="#e8613a")
draw.arc((430, 350, 970, 890), 180, 360, fill="white", width=55)
draw.rounded_rectangle((390, 620, 530, 960), radius=65, fill="white")
draw.rounded_rectangle((870, 620, 1010, 960), radius=65, fill="white")
draw.polygon([(625, 560), (625, 880), (830, 720)], fill="white")
path = Path(__file__).resolve().parents[1] / "public" / "cover.png"
image.save(path, optimize=True)
print(f"カバーを生成しました: {path}")

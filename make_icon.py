# -*- coding: utf-8 -*-
"""生成应用图标 WordLookup.ico / .png。"""
from PIL import Image, ImageDraw

SIZE = 512
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 圆角方形背景（深蓝渐变感的纯色 + 高光）
bg = (30, 60, 140, 255)          # 深蓝
bg2 = (46, 92, 200, 255)
d.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=110, fill=bg)
# 顶部高光
d.rounded_rectangle([0, 0, SIZE - 1, int(SIZE * 0.55)], radius=110,
                    fill=(255, 255, 255, 22))

# 放大镜（外圈）
mx, my, mr = 250, 290, 120
d.ellipse([mx - mr, my - mr, mx + mr, my + mr], outline=(255, 255, 255, 255), width=42)
# 手柄
d.line([mx + mr * 0.72, my + mr * 0.72, mx + mr * 1.18, my + mr * 1.18],
       fill=(255, 255, 255, 255), width=46)
# 镜片高光
d.arc([mx - mr, my - mr, mx + mr, my + mr], start=220, end=300,
      fill=(255, 255, 255, 90), width=22)

# 镜片内一本书（代表词典）
bx0, by0, bx1, by1 = 195, 230, 305, 360
d.rounded_rectangle([bx0, by0, bx1, by1], radius=18, fill=(255, 255, 255, 255))
d.line([bx0 + 12, by0 + 12, bx1 - 12, by0 + 12], fill=bg2, width=10)
d.line([bx0 + 12, by0 + 40, bx1 - 12, by0 + 40], fill=(200, 210, 235, 255), width=10)
d.line([bx0 + 12, by0 + 64, bx0 + 70, by0 + 64], fill=(200, 210, 235, 255), width=10)
d.line([bx1 - 60, by0 + 88, bx1 - 16, by0 + 88], fill=(200, 210, 235, 255), width=10)

img.save("/root/oxford-lookup/assets/icon.png")

# 生成多尺寸 .ico
ico_sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
img.save("/root/oxford-lookup/assets/WordLookup.ico", sizes=[(s, s) for s in ico_sizes])
print("saved icon.png + WordLookup.ico")
import os
for f in ["assets/icon.png", "assets/WordLookup.ico"]:
    p = os.path.join("/root/oxford-lookup", f)
    print(f, os.path.getsize(p), "bytes")
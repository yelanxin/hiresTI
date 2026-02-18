import os
import sys
import base64
from PIL import Image

# ================= 配置 =================
OUTPUT_DIR = "icons/hicolor"
# Linux 标准图标尺寸
SIZES = [16, 24, 32, 48, 64, 128, 256, 512]
# =======================================

def generate_pngs(img, base_dir):
    print("🖼️  Generating PNGs...")
    for size in SIZES:
        # 创建对应的目录结构 (例如 icons/hicolor/256x256/apps)
        size_dir = os.path.join(base_dir, f"{size}x{size}", "apps")
        os.makedirs(size_dir, exist_ok=True)
        
        # 调整大小 (使用高质量重采样)
        resized_img = img.resize((size, size), Image.Resampling.LANCZOS)
        
        # 保存
        output_path = os.path.join(size_dir, "hiresti.png")
        resized_img.save(output_path, "PNG")
        print(f"   ✅ Generated {size}x{size}: {output_path}")

def generate_svg(source_path, base_dir):
    print("📐 Generating SVG (Embedded)...")
    svg_dir = os.path.join(base_dir, "scalable", "apps")
    os.makedirs(svg_dir, exist_ok=True)
    
    # 读取图片并转为 Base64
    with open(source_path, "rb") as f:
        img_data = f.read()
        b64_data = base64.b64encode(img_data).decode("utf-8")
        
    # 获取原始尺寸
    with Image.open(source_path) as img:
        w, h = img.size

    # 构建 SVG 内容 (嵌入位图，保留金属质感)
    svg_content = f"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg width="{w}" height="{h}" version="1.1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
 <image width="{w}" height="{h}" xlink:href="data:image/png;base64,{b64_data}"/>
</svg>"""

    output_path = os.path.join(svg_dir, "hiresti.svg")
    with open(output_path, "w") as f:
        f.write(svg_content)
    print(f"   ✅ Generated SVG: {output_path}")

def main():
    # 检查命令行参数
    if len(sys.argv) < 2:
        print("❌ Error: Missing filename argument.")
        print("Usage: python3 gen_icons.py <image_filename>")
        print("Example: python3 gen_icons.py my_logo.png")
        sys.exit(1)

    source_image = sys.argv[1]

    if not os.path.exists(source_image):
        print(f"❌ Error: File '{source_image}' not found!")
        sys.exit(1)

    # 打开源图片
    try:
        img = Image.open(source_image)
    except Exception as e:
        print(f"❌ Error opening image: {e}")
        return

    print(f"🚀 Processing: {source_image}")

    # 1. 生成 PNG 系列
    generate_pngs(img, OUTPUT_DIR)

    # 2. 生成 SVG (嵌入式)
    generate_svg(source_image, OUTPUT_DIR)

    print("\n🎉 All icons generated successfully!")
    print("👉 Now you can run './package.sh deb 1.0.0'")

if __name__ == "__main__":
    main()

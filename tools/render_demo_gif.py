"""
Render a terminal demo GIF from captured everybody-lies output.
Uses Pillow for both frame rendering AND GIF encoding (no ffmpeg needed).

Usage: python render_demo_v2.py <captured_output.txt> <output.gif>
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ── Terminal theme (Dracula-ish) ──────────────────────────────────────────
BG = (30, 31, 41)       # #1e1f29
FG = (248, 248, 242)    # #f8f8f2
GREEN = (80, 250, 123)  # #50fa7b
CYAN = (139, 233, 253)  # #8be9fd
YELLOW = (241, 250, 140) # #f1fa8c
RED = (255, 85, 85)     # #ff5555
ORANGE = (255, 184, 108) # #ffb86c
PURPLE = (189, 147, 249) # #bd93f9
GRAY = (98, 114, 164)    # #6272a4
BOLD_WHITE = (255, 255, 255)

# Layout
PADDING_X = 28
PADDING_Y = 20
LINE_HEIGHT = 20
FONT_SIZE = 14
WIDTH = 720
HEIGHT = 900  # Fixed — enough for 48 lines

def get_font():
    """Get a monospace font."""
    candidates = [
        "consola.ttf",
        "Cascadia Code",
        "Cascadia Mono",
        "Consolas",
        "Courier New",
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, FONT_SIZE)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def parse_lines(text: str) -> list[tuple[str, tuple]]:
    """Parse output text into (line_text, color) tuples."""
    result = []
    for line in text.split("\n"):
        stripped = line.rstrip()
        if not stripped:
            result.append(("", FG))
            continue

        color = FG
        if "=====" in stripped:
            color = YELLOW
        elif "[REJECTED]" in stripped:
            color = RED
        elif "[APPROVED]" in stripped:
            color = GREEN
        elif "[P1]" in stripped:
            color = RED
        elif "[P2]" in stripped:
            color = ORANGE
        elif "[P3]" in stripped:
            color = YELLOW
        elif "[P4]" in stripped:
            color = GRAY
        elif "[SCAN]" in stripped or "Deterministic" in stripped:
            color = CYAN
        elif "[CUDDY" in stripped:
            color = PURPLE
        elif "[FOREMAN]" in stripped or "[TAUB]" in stripped or "[CHASE]" in stripped or "[CAMERON]" in stripped or "[THIRTEEN]" in stripped:
            color = CYAN
        elif "[HOUSE]" in stripped and "Synthesizing" in stripped:
            color = PURPLE
        elif "[HOUSE]" in stripped:
            color = RED
        elif "[REPORT]" in stripped or "[RECORD]" in stripped:
            color = GRAY
        elif "[CONFIG]" in stripped:
            color = GRAY
        elif "Model:" in stripped:
            color = PURPLE
        elif "BLOCKER:" in stripped:
            color = RED
        elif "HOUSE GATEKEEPER" in stripped:
            color = BOLD_WHITE
        elif stripped.startswith("  Dr."):
            color = GRAY
        elif "->" in stripped and "chars received" in stripped:
            color = GREEN

        result.append((stripped, color))
    return result


def render_frame(lines: list[tuple[str, tuple]], visible_count: int, font) -> Image.Image:
    """Render a terminal frame with `visible_count` lines visible."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    y = PADDING_Y
    for i in range(min(visible_count, len(lines))):
        text, color = lines[i]
        if text:  # Skip empty lines? No — draw everything (empty = blank line)
            draw.text((PADDING_X, y), text, fill=color, font=font)
        y += LINE_HEIGHT

    return img


def build_gif(lines: list[tuple[str, tuple]], output_path: str):
    """Build animated GIF directly with Pillow."""
    font = get_font()
    total = len(lines)

    # ── Build schedule: (visible_count, duration_ms) ──────────────────
    schedule = [(0, 500)]  # Start with blank terminal for 500ms
    for i in range(1, total + 1):
        line_text = lines[i - 1][0] if i > 0 else ""
        delay = 120  # default

        if "=====" in line_text:
            delay = 180
        elif not line_text.strip():
            delay = 50
        elif "findings:" in line_text and "P1=" in line_text:
            delay = 1000
        elif "[P1]" in line_text or "[P2]" in line_text:
            delay = 350
        elif "[P3]" in line_text or "[P4]" in line_text:
            delay = 250
        elif "CUDDY" in line_text and "DIFFERENTIAL" in line_text:
            delay = 500
        elif "Ruling out" in line_text:
            delay = 350
        elif line_text.strip().startswith("Model:"):
            delay = 200
        elif "chars received" in line_text:
            delay = 350
        elif "[FOREMAN]" in line_text or "[TAUB]" in line_text or "[CHASE]" in line_text or "[CAMERON]" in line_text or "[THIRTEEN]" in line_text:
            delay = 200
        elif "[HOUSE]" in line_text and "Synthesizing" in line_text:
            delay = 400
        elif "[REPORT]" in line_text or "[RECORD]" in line_text:
            delay = 200
        elif "[CONFIG]" in line_text:
            delay = 180

        schedule.append((i, delay))

    # Extend final frame
    schedule.append((total, 3500))

    # ── Render frames ────────────────────────────────────────────────
    print(f"Rendering {len(schedule)} frames...")
    frames = []
    for idx, (show, delay) in enumerate(schedule):
        img = render_frame(lines, show, font)
        frames.append((img, delay))
        if idx % 10 == 0:
            print(f"  {idx}/{len(schedule)}")

    total_duration = sum(d for _, d in frames)
    print(f"Total duration: {total_duration/1000:.1f}s")

    # ── Save as animated GIF ─────────────────────────────────────────
    print("Converting frames & dedup...")
    gif_frames = []
    durations_ms = []
    prev_data = None
    dedup_count = 0
    for idx, (img, duration) in enumerate(frames):
        p_frame = img.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
        # Check if identical to previous
        data = p_frame.tobytes()
        if data == prev_data:
            # Merge duration into previous frame
            durations_ms[-1] += duration
            dedup_count += 1
        else:
            gif_frames.append(p_frame)
            durations_ms.append(duration)
            prev_data = data
        if idx % 10 == 0:
            print(f"  {idx}/{len(frames)}")

    print(f"  {len(gif_frames)} unique frames ({dedup_count} duplicates merged)")

    gif_frames[0].save(
        output_path,
        save_all=True,
        append_images=gif_frames[1:],
        duration=durations_ms,
        loop=0,
        dither=Image.Dither.FLOYDSTEINBERG,
    )

    size_kb = Path(output_path).stat().st_size / 1024
    print(f"GIF saved to {output_path}")
    print(f"Size: {size_kb:.0f} KB")


def main():
    if len(sys.argv) < 2:
        print("Usage: python render_demo_v2.py <captured_output.txt> [output.gif]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "demo.gif"

    text = Path(input_path).read_text(encoding="utf-8")
    lines = parse_lines(text)
    print(f"Parsed {len(lines)} lines from {input_path}")

    build_gif(lines, output_path)


if __name__ == "__main__":
    main()

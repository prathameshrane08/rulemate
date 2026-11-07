"""Build the walkthrough video: narration (macOS `say`), subtitles burned in and as .srt, frames from screenshots.

    python video/build.py                                   -> video/RuleTrace_walkthrough.mp4 and .srt
    python video/build.py --script script_2min.json --name RuleTrace_2min --voice Daniel --accuracy accuracy_2min.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
import wave
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
OUT = HERE / "build"
W, H = 1920, 1080
BAR = 170  # subtitle bar height
VOICE, RATE = "Samantha", "172"  # overridden by --voice / --rate
FF = imageio_ffmpeg.get_ffmpeg_exe()
FONT = "/System/Library/Fonts/Helvetica.ttc"
NAVY, TEAL = (11, 37, 69), (19, 138, 138)


def font(size, bold=False):
    return ImageFont.truetype(FONT, size, index=1 if bold else 0)


def run(*args):
    subprocess.run([*args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def tts(text: str, path: Path) -> float:
    aiff = path.with_suffix(".aiff")
    run("say", "-v", VOICE, "-r", RATE, "-o", str(aiff), text)
    # clean voice: keep only the speech band and level it, no reverb or room effect
    run(FF, "-y", "-i", str(aiff), "-af", "highpass=f=70,lowpass=f=9000,loudnorm=I=-16:TP=-1.5:LRA=7",
        "-ar", "44100", "-ac", "1", str(path))
    aiff.unlink()
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def base_frame(scene: dict) -> Image.Image:
    img = Image.new("RGB", (W, H), (244, 246, 248))
    d = ImageDraw.Draw(img)
    if "card" in scene:
        img.paste(NAVY, (0, 0, W, H))
        d.text((W // 2, H // 2 - 70), scene["card"], font=font(84, True), fill="white", anchor="mm")
        d.text((W // 2, H // 2 + 30), scene["sub"], font=font(34), fill=(185, 199, 216), anchor="mm")
        d.rectangle((W // 2 - 90, H // 2 + 90, W // 2 + 90, H // 2 + 96), fill=TEAL)
        return img
    shot = Image.open(HERE / "frames" / scene["frame"]).convert("RGB")
    top, avail_h = 64, H - BAR - 64 - 16
    k = min((W - 80) / shot.width, avail_h / shot.height)
    shot = shot.resize((int(shot.width * k), int(shot.height * k)), Image.LANCZOS)
    x = (W - shot.width) // 2
    d.rectangle((x - 2, top - 2, x + shot.width + 1, top + shot.height + 1), fill=(200, 208, 216))
    img.paste(shot, (x, top))
    d.rectangle((0, 0, W, 52), fill=NAVY)
    d.text((24, 26), scene["chapter"], font=font(28, True), fill="white", anchor="lm")
    d.text((W - 24, 26), "RuleTrace + RuleMate Copilot", font=font(24), fill=(185, 199, 216), anchor="rm")
    return img


def with_subtitle(img: Image.Image, text: str) -> Image.Image:
    img = img.copy()
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle((0, H - BAR, W, H), fill=(10, 20, 35, 235))
    lines = textwrap.wrap(text, 92)[:3]
    f = font(38 if len(lines) < 3 else 34)
    lh = 50 if len(lines) < 3 else 44
    y0 = H - BAR / 2 - (len(lines) - 1) * lh / 2
    for i, line in enumerate(lines):
        d.text((W // 2, y0 + i * lh), line, font=f, fill="white", anchor="mm")
    return img


def ts(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def main() -> int:
    global VOICE, RATE, OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", default="script.json")
    ap.add_argument("--name", default="RuleTrace_walkthrough")
    ap.add_argument("--voice", default=VOICE)
    ap.add_argument("--rate", default=RATE)
    ap.add_argument("--accuracy", default="accuracy_narration.json")
    a = ap.parse_args()
    VOICE, RATE, OUT = a.voice, a.rate, HERE / f"build_{a.name}"
    scenes = json.loads((HERE / a.script).read_text())
    acc = HERE / a.accuracy
    for old in OUT.glob("s*.*") if OUT.exists() else []:
        old.unlink()
    OUT.mkdir(exist_ok=True)
    clips, srt, t, n = [], [], 0.0, 0
    for si, sc in enumerate(scenes):
        says = sc["say"]
        if says == "ACCURACY":
            if not acc.exists() or not (HERE / "frames" / sc["frame"]).exists():
                continue
            says = json.loads(acc.read_text())
        base = base_frame(sc)
        for j, sentence in enumerate(says):
            n += 1
            wav = OUT / f"s{n:03d}.wav"
            dur = tts(sentence, wav) + (0.35 if j < len(says) - 1 else 0.8)  # pause after each sentence / scene
            png = OUT / f"s{n:03d}.png"
            with_subtitle(base, sentence).save(png)
            clip = OUT / f"s{n:03d}.mp4"
            run(FF, "-y", "-loop", "1", "-i", str(png), "-i", str(wav), "-t", f"{dur:.3f}", "-af", f"apad=whole_dur={dur:.3f}",
                "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", "25",
                "-c:a", "aac", "-b:a", "160k", "-ar", "44100", str(clip))
            clips.append(clip)
            srt.append(f"{n}\n{ts(t)} --> {ts(t + dur - 0.2)}\n{sentence}\n")
            t += dur
        print(f"scene {si + 1}/{len(scenes)}: {sc['chapter']}  ({t:.0f} s)", flush=True)
    lst = OUT / "clips.txt"
    lst.write_text("".join(f"file '{c.name}'\n" for c in clips))
    mp4 = HERE / f"{a.name}.mp4"
    run(FF, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(mp4))
    (HERE / f"{a.name}.srt").write_text("\n".join(srt), encoding="utf-8")
    print(f"wrote {mp4} ({t / 60:.1f} min) and {a.name}.srt")
    return 0


if __name__ == "__main__":
    sys.exit(main())

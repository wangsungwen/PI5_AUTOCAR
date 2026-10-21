"""Extract grouped video frames with FFmpeg before uploading to Roboflow."""
from __future__ import annotations

import argparse
import csv
import math
import re
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True,
                        help="CSV columns: video,clip_id,session,split,scene")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--max-per-video", type=int, default=0,
                        help="0 = whole video; positive limits the beginning of each clip")
    args = parser.parse_args()
    if not math.isfinite(args.interval) or args.interval <= 0 or args.max_per_video < 0:
        raise ValueError("interval must be finite and > 0; max-per-video must be >= 0")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("Install FFmpeg and add its bin directory to PATH.")
    if args.output.exists():
        raise FileExistsError("Choose a new output folder to avoid mixing frame versions.")
    with args.manifest.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("Manifest is empty")
    sessions, clips, paths = {}, set(), set()
    for row in rows:
        clip, session, split = row["clip_id"], row["session"], row["split"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", clip) or clip.casefold() in clips:
            raise ValueError(f"clip_id must be unique ASCII letters/digits/_/-: {clip}")
        if split not in {"train", "valid", "test"} or not session or not row["scene"]:
            raise ValueError(f"Invalid manifest row: {row}")
        if session in sessions and sessions[session] != split:
            raise ValueError(f"Session leakage across splits: {session}")
        video = Path(row["video"])
        if not video.is_absolute():
            video = args.manifest.resolve().parent / video
        video = video.resolve()
        if not video.is_file() or video in paths:
            raise ValueError(f"Missing or repeated source video: {video}")
        sessions[session], row["path"] = split, video
        clips.add(clip.casefold())
        paths.add(video)
    args.output.mkdir(parents=True)
    with (args.output / "frames.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["file", "clip_id", "session", "split", "scene", "video"])
        writer.writeheader()
        for row in rows:
            folder = args.output / row["split"]
            folder.mkdir(exist_ok=True)
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                       "-i", str(row["path"]), "-map", "0:v:0", "-vf",
                       f"fps=1/{args.interval}", "-q:v", "2"]
            if args.max_per_video:
                command += ["-frames:v", str(args.max_per_video)]
            command.append(str(folder / f"{row['clip_id']}_%06d.jpg"))
            subprocess.run(command, check=True)
            frame_pattern = re.compile(re.escape(row["clip_id"]) + r"_\d{6,}\.jpg")
            frames = sorted(p for p in folder.iterdir() if frame_pattern.fullmatch(p.name))
            if not frames:
                raise ValueError(f"No frames extracted: {row['path']}")
            for frame in frames:
                writer.writerow(dict(file=frame.name, clip_id=row["clip_id"], session=row["session"],
                                     split=row["split"], scene=row["scene"], video=str(row["path"])))
            stream.flush()
            print(f"{row['clip_id']}: {len(frames)} frames -> {folder}")


if __name__ == "__main__":
    main()

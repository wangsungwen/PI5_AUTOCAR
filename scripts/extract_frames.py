"""Extract frames from videos at a specified frame rate (e.g., 1 frame per second).

Designed for AutoCAR recordings (raw H.264 streams or standard MP4/MKV files).
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
LOG = logging.getLogger("extract_frames")

VIDEO_EXTENSIONS = {".h264", ".mp4", ".mkv", ".avi", ".mov", ".ts"}


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def extract_frames(
    video_path: Path,
    output_dir: Path,
    fps: float = 1.0,
    input_fps: float = 30.0,
    img_format: str = "jpg",
    quality: int = 2,
) -> int:
    """Extract frames from a video file using ffmpeg.

    Args:
        video_path: Path to the input video.
        output_dir: Output directory to store extracted images.
        fps: How many frames to extract per second of video (e.g. 1.0 = 1 frame/sec).
        input_fps: Input framerate assumption for raw H.264 elementary streams.
        img_format: Image file extension ('jpg' or 'png').
        quality: JPEG quality scale (1-31, 2 is high quality).

    Returns:
        Number of images extracted.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    out_pattern = output_dir / f"frame_%04d.{img_format}"

    cmd = ["ffmpeg", "-y"]

    # Raw H.264 elementary streams recorded by picamera2 do not have container framerate info,
    # so we supply input framerate (-r 30) before -i.
    if video_path.suffix.lower() == ".h264":
        cmd.extend(["-r", str(input_fps)])

    cmd.extend([
        "-i", str(video_path),
        "-vf", f"fps={fps}",
    ])

    if img_format.lower() in ("jpg", "jpeg"):
        cmd.extend(["-q:v", str(quality)])

    cmd.append(str(out_pattern))

    LOG.info("Processing: %s -> %s", video_path.name, output_dir)
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if proc.returncode != 0:
        LOG.error("ffmpeg failed for %s:\n%s", video_path, proc.stderr)
        return 0

    count = len(list(output_dir.glob(f"frame_*.{img_format}")))
    LOG.info("Extracted %d frames from %s", count, video_path.name)
    return count


def main():
    parser = argparse.ArgumentParser(description="Extract video frames (default: 1 frame/sec)")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "video",
        help="Path to video file or directory containing videos (default: ./video)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Directory to store extracted frames. Defaults to a subfolder per video in source dir.",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=1.0,
        help="Extracted frames per second (default: 1.0)",
    )
    parser.add_argument(
        "--input-fps",
        type=float,
        default=30.0,
        help="Assumed framerate for raw .h264 streams (default: 30.0)",
    )
    parser.add_argument(
        "--format",
        choices=["jpg", "png"],
        default="jpg",
        help="Output image format (default: jpg)",
    )

    args = parser.parse_args()

    if not check_ffmpeg():
        LOG.error("ffmpeg is not installed or not in PATH! Please install ffmpeg.")
        sys.exit(1)

    source_path = args.source
    if not source_path.exists():
        LOG.error("Source path does not exist: %s", source_path)
        sys.exit(1)

    if source_path.is_file():
        video_files = [source_path]
        base_dir = source_path.parent
    else:
        video_files = sorted([p for p in source_path.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS])
        base_dir = source_path

    if not video_files:
        LOG.warning("No video files found in %s", source_path)
        sys.exit(0)

    total_images = 0
    for video in video_files:
        out_folder = args.output / f"{video.stem}_frames" if args.output else base_dir / f"{video.stem}_frames"
        extracted = extract_frames(
            video,
            out_folder,
            fps=args.fps,
            input_fps=args.input_fps,
            img_format=args.format,
        )
        total_images += extracted

    LOG.info("Done! Processed %d videos, total %d frames extracted.", len(video_files), total_images)


if __name__ == "__main__":
    main()

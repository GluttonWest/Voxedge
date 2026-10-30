"""
record_enrollment.py — VoxEdge Step 1: Record voice samples for enrollment.

Run this script FIRST. It records 3 short (3-second) clips of your voice
using the default microphone and saves them to the enrollment/ folder.

Usage:
    python record_enrollment.py
"""

from pathlib import Path
import sys

import numpy as np
import sounddevice as sd   # to record audio from the microphone
import soundfile as sf     # to save the audio as a .wav file


def configure_console() -> None:
    """Use UTF-8 where supported so Windows consoles can print status symbols."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


configure_console()


# ── Configuration ────────────────────────────────────────────────────────────
SAMPLE_RATE       = 16_000   # 16 kHz — required by both Vosk and Resemblyzer
RECORDING_SECONDS = 3        # length of each enrollment clip
ENROLLMENT_FOLDER = Path("enrollment")  # folder where samples will be saved
# ─────────────────────────────────────────────────────────────────────────────


def record_clip(file_path: Path) -> bool:
    """Record one 3-second mono clip from the microphone, validate energy, and save."""
    print(f"  ▶  Recording for {RECORDING_SECONDS} seconds — SPEAK NOW...")

    audio = sd.rec(
        int(RECORDING_SECONDS * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
    )
    sd.wait()

    # Audio energy check: ensure recording captured audible speech, not silence
    rms = float(np.sqrt(np.mean(audio ** 2)))
    max_amp = float(np.max(np.abs(audio)))
    if rms < 0.005 or max_amp < 0.02:
        print(f"  ✖  WARNING: Audio is too quiet or silent (RMS={rms:.4f}, max={max_amp:.4f}).")
        print("     Please check your microphone volume and speak closer to the mic.")
        return False

    # Write NumPy array to WAV file on disk
    sf.write(file_path, audio, SAMPLE_RATE)
    print(f"  ✔  Saved valid sample ({rms:.4f} RMS): {file_path}")
    return True


def main() -> None:
    # Create enrollment folder
    ENROLLMENT_FOLDER.mkdir(exist_ok=True)

    print("=" * 55)
    print("  VoxEdge — Speaker Enrollment (Step 1 of 2)")
    print("=" * 55)
    print("We will record THREE short voice samples.")
    print("Say anything natural, e.g. 'Hello VoxEdge, I am the authorized user.'")
    print("Stay consistent — same tone and distance from mic each time.\n")

    sample_number = 1
    while sample_number <= 3:
        print(f"─── Sample {sample_number} / 3 ───────────────────────────")
        input("  Press Enter when you are ready...")
        output_path = ENROLLMENT_FOLDER / f"sample_{sample_number}.wav"
        success = record_clip(output_path)
        if success:
            if sample_number < 3:
                print("  Take a short breath before the next sample.\n")
            sample_number += 1
        else:
            retry = input("  Would you like to retry this sample? [Y/n]: ").strip().lower()
            if retry in ("n", "no"):
                print("  Enrollment recording aborted.")
                return

    print("\n" + "=" * 55)
    print("  Enrollment recordings COMPLETE.")
    print("  Next step → run:  python enroll.py")
    print("=" * 55)


if __name__ == "__main__":
    main()

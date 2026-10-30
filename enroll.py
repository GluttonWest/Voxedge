"""
enroll.py — VoxEdge Step 2: Build the enrolled speaker voice profile.

Run this AFTER record_enrollment.py. It:
  1. Loads the 3 WAV clips from enrollment/
  2. Uses Resemblyzer to turn each clip into a 256-dimensional "voice embedding"
     (a numeric fingerprint of the speaker's voice)
  3. Averages the three embeddings to get a stable, representative profile
  4. Saves the result to enrolled_voice.npy (loaded by main.py and the backend)
  5. Verifies the saved profile by loading and validating it before confirming.

Usage:
    python enroll.py
    python enroll.py --force
"""

from pathlib import Path
import sys

import numpy as np
from resemblyzer import VoiceEncoder, preprocess_wav


def configure_console() -> None:
    """Use UTF-8 where supported so Windows consoles can print status symbols."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


configure_console()


# ── Configuration ────────────────────────────────────────────────────────────
ENROLLMENT_FOLDER = Path("enrollment")   # folder containing sample_1/2/3.wav
OUTPUT_FILE       = Path("enrolled_voice.npy")  # where the embedding is saved
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    force = "--force" in sys.argv or "-f" in sys.argv

    # ── 0. Prevent accidental replacement of enrolled profile ─────────────────
    if OUTPUT_FILE.is_file() and not force:
        print("=" * 55)
        print("  WARNING: Enrolled voice profile already exists!")
        print(f"  Target file: {OUTPUT_FILE.resolve()}")
        print("=" * 55)
        choice = input("  Do you want to overwrite your existing profile? [y/N]: ").strip().lower()
        if choice not in ("y", "yes"):
            print("  Enrollment cancelled. Existing profile preserved.")
            return

    # ── 1. Find and validate the three enrollment WAV files ───────────────────
    recording_paths = sorted(ENROLLMENT_FOLDER.glob("sample_*.wav"))
    if len(recording_paths) != 3:
        raise SystemExit(
            f"ERROR: Found {len(recording_paths)} file(s) in {ENROLLMENT_FOLDER}/, "
            "but expected exactly 3.\n"
            "Please run:  python record_enrollment.py"
        )

    for p in recording_paths:
        if not p.is_file() or p.stat().st_size < 1000:
            raise SystemExit(f"ERROR: Enrollment file '{p}' is empty or corrupted.")

    # ── 2. Load the Resemblyzer encoder ─────────────────────────────────────
    print("=" * 55)
    print("  VoxEdge — Speaker Enrollment (Step 2 of 2)")
    print("=" * 55)
    print("\nLoading Resemblyzer voice encoder (may take a moment)...")
    encoder = VoiceEncoder()

    # ── 3. Generate an embedding for each sample ─────────────────────────────
    embeddings = []
    for recording_path in recording_paths:
        print(f"  Processing {recording_path.name}...")
        try:
            waveform = preprocess_wav(recording_path)
            if len(waveform) < 8000:
                raise ValueError("Too little voiced speech detected (< 0.5s).")
            embedding = encoder.embed_utterance(waveform)
            embeddings.append(embedding)
            print(f"    ✔ Embedding shape: {embedding.shape}, norm: {np.linalg.norm(embedding):.4f}")
        except Exception as err:
            raise SystemExit(f"ERROR processing {recording_path.name}: {err}")

    # ── 4. Average the three embeddings into one representative profile ───────
    enrolled_embedding = np.mean(np.stack(embeddings), axis=0)

    # Normalise to unit length so cosine similarity = simple dot product later
    norm = np.linalg.norm(enrolled_embedding)
    if norm == 0 or np.isnan(norm):
        raise SystemExit("ERROR: Failed to generate valid embedding (zero or NaN norm).")
    enrolled_embedding /= norm

    # ── 5. Save the profile to disk atomically ───────────────────────────────
    temp_file = OUTPUT_FILE.with_suffix(".tmp.npy")
    np.save(temp_file, enrolled_embedding)
    temp_file.replace(OUTPUT_FILE)

    # ── 6. Confirm enrollment only after successfully reloading and validating ─
    try:
        reloaded = np.load(OUTPUT_FILE)
        if reloaded.shape != (256,):
            raise ValueError(f"Invalid dimensions: expected (256,), got {reloaded.shape}")
        if np.isnan(reloaded).any() or np.isinf(reloaded).any():
            raise ValueError("Reloaded embedding contains NaN or Inf values.")
        reloaded_norm = np.linalg.norm(reloaded)
        if not np.isclose(reloaded_norm, 1.0, atol=1e-3):
            raise ValueError(f"Expected unit norm ~1.0, got {reloaded_norm:.4f}")
    except Exception as verify_err:
        OUTPUT_FILE.unlink(missing_ok=True)
        raise SystemExit(f"ERROR: Enrollment verification failed after saving: {verify_err}")

    print(f"\n  ✔  Average embedding saved to: {OUTPUT_FILE}")
    print(f"     Embedding dimensions: {reloaded.shape}")
    print(f"     Verification check  : PASSED (profile reloaded and validated)")
    print("\n" + "=" * 55)
    print("  Enrollment COMPLETE.")
    print("  Next step → run:  python main.py")
    print("=" * 55)


if __name__ == "__main__":
    main()

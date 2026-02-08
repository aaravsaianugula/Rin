#!/usr/bin/env python3
"""
Wake Word Training Script for Rin Agent.

Collects audio samples of you saying "Rin" and trains a custom
OpenWakeWord model for highly accurate wake word detection.

Usage:
    python scripts/train_wake_word.py

Requirements:
    - openwakeword[training]
    - sounddevice
    - numpy
"""

import os
import sys
import time
import wave
import json
from pathlib import Path

import numpy as np

# Configuration
SAMPLE_RATE = 16000
DURATION = 1.5  # seconds per sample
NUM_SAMPLES = 50
OUTPUT_DIR = Path("training_data/rin_samples")
MODEL_OUTPUT = Path("models/rin.onnx")


def record_sample(index: int) -> np.ndarray:
    """Record a single audio sample."""
    import sounddevice as sd
    
    print(f"\n[{index + 1}/{NUM_SAMPLES}] Say 'Rin' in 3... ", end="", flush=True)
    time.sleep(1)
    print("2... ", end="", flush=True)
    time.sleep(1)
    print("1... ", end="", flush=True)
    time.sleep(1)
    print("NOW!")
    
    audio = sd.rec(
        int(DURATION * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype=np.int16
    )
    sd.wait()
    
    return audio.flatten()


def save_sample(audio: np.ndarray, filepath: Path):
    """Save audio as WAV file."""
    with wave.open(str(filepath), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())


def collect_samples():
    """Collect wake word samples from user."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print("Rin Wake Word Training - Sample Collection")
    print("=" * 60)
    print()
    print(f"We'll record {NUM_SAMPLES} samples of you saying 'Rin'.")
    print("Speak clearly at a normal volume.")
    print("Try varying your tone slightly between samples.")
    print()
    print("Press Enter to begin...")
    input()
    
    samples = []
    for i in range(NUM_SAMPLES):
        audio = record_sample(i)
        
        # Check audio level
        level = np.abs(audio).mean()
        if level < 100:
            print("  ⚠ Audio too quiet - speak louder")
        else:
            print(f"  ✓ Good! (level: {level:.0f})")
        
        filepath = OUTPUT_DIR / f"rin_{i:03d}.wav"
        save_sample(audio, filepath)
        samples.append(filepath)
        
        # Brief pause between samples
        time.sleep(0.5)
    
    print()
    print(f"✓ Collected {len(samples)} samples in {OUTPUT_DIR}")
    return samples


def train_model():
    """Train OpenWakeWord model from collected samples."""
    print()
    print("=" * 60)
    print("Training Wake Word Model Locally")
    print("=" * 60)
    print()
    
    # Check if samples exist
    if not OUTPUT_DIR.exists():
        print(f"Error: No samples found at {OUTPUT_DIR}")
        print("Run option 1 first to collect samples.")
        return False
    
    wav_files = list(OUTPUT_DIR.glob("*.wav"))
    if len(wav_files) < 10:
        print(f"Error: Only {len(wav_files)} samples found. Need at least 10.")
        return False
    
    print(f"Found {len(wav_files)} samples")
    print()
    
    try:
        from openwakeword.train import train_model as oww_train
        from openwakeword.utils import download_models
        
        print("Downloading base models if needed...")
        download_models()
        
        print()
        print("Starting training (this may take a few minutes)...")
        print()
        
        # Create training config
        config = {
            "model_name": "rin",
            "target_phrase": "rin",
            "positive_examples": [str(f) for f in wav_files],
            "output_dir": str(Path("models")),
            "epochs": 10,
        }
        
        # Save config
        config_path = OUTPUT_DIR / "train_config.json"
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        # Run training
        oww_train(
            positive_audio_files=[str(f) for f in wav_files],
            model_name="rin",
            output_dir=str(Path("models")),
            epochs=10,
        )
        
        print()
        print(f"✓ Model trained and saved to {MODEL_OUTPUT}")
        return True
        
    except ImportError as e:
        print(f"Training module not available: {e}")
        print()
        print("Falling back to simple acoustic model...")
        return train_simple_model(wav_files)
    except Exception as e:
        print(f"Training error: {e}")
        print()
        print("Falling back to simple acoustic model...")
        return train_simple_model(wav_files)


def train_simple_model(wav_files):
    """
    Create a simple acoustic template model from the samples.
    This uses audio fingerprinting rather than neural networks.
    """
    print()
    print("Creating acoustic fingerprint model...")
    
    try:
        import librosa
    except ImportError:
        print("Installing librosa for audio processing...")
        os.system("pip install librosa")
        import librosa
    
    # Extract features from each sample
    features = []
    for wav_file in wav_files:
        try:
            # Load audio
            y, sr = librosa.load(str(wav_file), sr=SAMPLE_RATE)
            
            # Extract MFCC features (standard for speech)
            mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
            
            # Average across time to get a fixed-size feature vector
            mfcc_mean = np.mean(mfcc, axis=1)
            features.append(mfcc_mean)
        except Exception as e:
            print(f"  Warning: Could not process {wav_file.name}: {e}")
    
    if len(features) < 5:
        print("Error: Not enough valid samples")
        return False
    
    # Create template (average of all features)
    template = np.mean(features, axis=0)
    std = np.std(features, axis=0)
    
    # Save as a simple model
    model_data = {
        "type": "acoustic_template",
        "wake_word": "rin",
        "template": template.tolist(),
        "std": std.tolist(),
        "threshold": 0.7,
        "sample_rate": SAMPLE_RATE,
        "n_mfcc": 13,
    }
    
    # Save as JSON (simple format)
    simple_model_path = Path("models/rin_template.json")
    simple_model_path.parent.mkdir(parents=True, exist_ok=True)
    with open(simple_model_path, 'w') as f:
        json.dump(model_data, f, indent=2)
    
    print(f"✓ Acoustic template saved to {simple_model_path}")
    print()
    print("Note: This is a simple template model. For best accuracy,")
    print("use OpenWakeWord's full training pipeline or their Colab notebook.")
    
    return True


def test_detection():
    """Test wake word detection with the trained model."""
    print()
    print("=" * 60)
    print("Testing Wake Word Detection")
    print("=" * 60)
    print()
    
    # Check for trained model
    simple_model_path = Path("models/rin_template.json")
    
    if MODEL_OUTPUT.exists():
        print(f"Using trained ONNX model: {MODEL_OUTPUT}")
        test_with_openwakeword()
    elif simple_model_path.exists():
        print(f"Using acoustic template model: {simple_model_path}")
        test_with_template(simple_model_path)
    else:
        print("No trained model found.")
        print("Using OpenWakeWord default models for testing...")
        test_with_openwakeword()


def test_with_openwakeword():
    """Test using OpenWakeWord."""
    try:
        import openwakeword
        from openwakeword.model import Model
        import sounddevice as sd
        
        if MODEL_OUTPUT.exists():
            model = Model(wakeword_models=[str(MODEL_OUTPUT)])
        else:
            model = Model()
        
        print()
        print("Listening for wake words... (Ctrl+C to stop)")
        print("Try saying 'Rin' or similar words")
        print()
        
        chunk_size = 1280  # ~80ms at 16kHz
        
        def audio_callback(indata, frames, time_info, status):
            audio = indata.flatten().astype(np.float32) / 32768.0
            prediction = model.predict(audio)
            
            for name, scores in prediction.items():
                if isinstance(scores, np.ndarray):
                    score = float(scores.max()) if len(scores) > 0 else 0
                else:
                    score = float(scores)
                if score > 0.5:
                    print(f"  ✓ Detected: {name} ({score:.2f})")
        
        with sd.InputStream(
            samplerate=16000,
            channels=1,
            dtype=np.int16,
            blocksize=chunk_size,
            callback=audio_callback
        ):
            print("Listening... (press Ctrl+C to stop)")
            while True:
                time.sleep(0.1)
                
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as e:
        print(f"Test error: {e}")


def test_with_template(model_path: Path):
    """Test using simple acoustic template matching."""
    try:
        import librosa
    except ImportError:
        print("Installing librosa...")
        os.system("pip install librosa")
        import librosa
    
    import sounddevice as sd
    
    # Load model
    with open(model_path) as f:
        model = json.load(f)
    
    template = np.array(model["template"])
    std = np.array(model["std"])
    threshold = model["threshold"]
    
    print()
    print("Listening for 'Rin'... (Ctrl+C to stop)")
    print()
    
    # Collect audio in chunks and analyze
    buffer = []
    buffer_duration = 1.5  # seconds
    buffer_samples = int(buffer_duration * SAMPLE_RATE)
    
    def audio_callback(indata, frames, time_info, status):
        nonlocal buffer
        buffer.extend(indata.flatten())
        
        # Analyze when buffer is full
        if len(buffer) >= buffer_samples:
            audio = np.array(buffer[-buffer_samples:], dtype=np.float32) / 32768.0
            
            # Extract MFCC
            try:
                mfcc = librosa.feature.mfcc(y=audio, sr=SAMPLE_RATE, n_mfcc=13)
                mfcc_mean = np.mean(mfcc, axis=1)
                
                # Compute similarity (normalized correlation)
                diff = np.abs(mfcc_mean - template)
                similarity = 1.0 - np.mean(diff / (std + 0.1))
                
                if similarity > threshold:
                    print(f"  ✓ Detected 'Rin'! (confidence: {similarity:.2f})")
                    buffer = []  # Clear after detection
            except:
                pass
            
            # Keep only recent samples
            buffer = buffer[-buffer_samples//2:]
    
    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype=np.int16,
            blocksize=1024,
            callback=audio_callback
        ):
            print("Listening... (press Ctrl+C to stop)")
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopped.")


def main():
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║         Rin Wake Word Training Utility                   ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    
    print("Options:")
    print("  1. Collect samples (record your voice saying 'Rin')")
    print("  2. Train model (from collected samples)")
    print("  3. Test detection (test wake word detection)")
    print("  4. Full workflow (collect → train → test)")
    print()
    
    choice = input("Select option (1-4): ").strip()
    
    if choice == "1":
        collect_samples()
    elif choice == "2":
        train_model()
    elif choice == "3":
        test_detection()
    elif choice == "4":
        samples = collect_samples()
        if samples:
            train_model()
            test_detection()
    else:
        print("Invalid option")
        sys.exit(1)


if __name__ == "__main__":
    main()

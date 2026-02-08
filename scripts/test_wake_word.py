"""
Test script for Porcupine wake word detection.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import time
import numpy as np
import sounddevice as sd
import pvporcupine

from src.key_manager import get_porcupine_key

print('Initializing Porcupine...')

key = get_porcupine_key()
if not key:
    print("ERROR: No Porcupine key found!")
    print("Run: python src/key_manager.py set porcupine YOUR_KEY")
    sys.exit(1)

model = str(project_root / 'models' / 'porcupine' / 'Hey-Rin_en_windows_v4_0_0.ppn')

porcupine = pvporcupine.create(
    access_key=key,
    keyword_paths=[model],
    sensitivities=[0.5]
)

print()
print('Listening for "Hey Rin"... (say it!)')
print('Press Ctrl+C to stop')
print()

try:
    with sd.InputStream(samplerate=16000, channels=1, dtype=np.int16, blocksize=porcupine.frame_length) as stream:
        while True:
            audio, _ = stream.read(porcupine.frame_length)
            audio = audio.flatten()
            result = porcupine.process(audio)
            if result >= 0:
                print('  >>> DETECTED: Hey Rin! <<<')
except KeyboardInterrupt:
    print("\nStopped.")
finally:
    porcupine.delete()

"""Calibration test: measure VLM click accuracy. Requires llama-server running on 127.0.0.1:8080.
Run with: python -u scripts/click_calibration.py --runs 3   ( -u = unbuffered output, so you see progress )
"""
import os
import sys
import time
import random
import tkinter as tk
from pathlib import Path
import math
import argparse

# Add src to path
project_root = Path(__file__).parent.parent.absolute()
sys.path.append(str(project_root))

from src.capture import ScreenCapture
from src.inference import VLMClient
from src.coordinates import normalized_to_pixels

# Timeout for each VLM request (seconds). Increase if your model is slow.
VLM_TIMEOUT = 90

class CalibrationWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 1.0)
        
        # Target size
        self.size = 20
        self.canvas = tk.Canvas(self.root, width=self.size, height=self.size, bg='black', highlightthickness=0)
        self.canvas.pack()
        
        # Draw target
        self.canvas.create_oval(2, 2, self.size-2, self.size-2, fill='red', outline='white')
        self.canvas.create_oval(self.size//2-2, self.size//2-2, self.size//2+2, self.size//2+2, fill='white')

    def move_to_random(self, screen_w, screen_h):
        # Keep away from edges
        margin = 100
        x = random.randint(margin, screen_w - margin)
        y = random.randint(margin, screen_h - margin)
        self.root.geometry(f"+{x}+{y}")
        self.root.update()
        return x + self.size//2, y + self.size//2

    def close(self):
        self.root.destroy()

def run_calibration(num_runs=5):
    print(f"--- Starting Calibration Test ({num_runs} runs) ---", flush=True)
    
    print("Initializing capture and VLM client...", flush=True)
    capture = ScreenCapture()
    vlm = VLMClient(timeout=VLM_TIMEOUT)
    
    print("Checking VLM server at 127.0.0.1:8080...", flush=True)
    if not vlm.check_health():
        print("Error: VLM server is not running at 127.0.0.1:8080")
        print("Start it first: run main.py with a command, or start llama-server manually.")
        return None

    try:
        screen_w, screen_h = capture.get_screen_size()
    except Exception as e:
        print(f"Error getting screen size: {e}")
        return None
    print(f"Screen resolution: {screen_w}x{screen_h}", flush=True)
    
    print("Opening calibration target window...", flush=True)
    win = CalibrationWindow()
    errors = []
    latencies = []

    try:
        for i in range(num_runs):
            print(f"\nRun {i+1}/{num_runs}:", flush=True)
            
            print("  Moving target...", flush=True)
            target_x, target_y = win.move_to_random(screen_w, screen_h)
            time.sleep(0.5)
            
            print("  Capturing screenshot...", flush=True)
            try:
                b64_img, img_size = capture.get_base64_screenshot()
            except Exception as e:
                print(f"  Capture failed: {e}")
                continue
            
            print(f"  Sending to VLM (timeout {VLM_TIMEOUT}s, may take 30-90s)...", flush=True)
            start_time = time.time()
            from src.prompts import calibration_target_prompt
            prompt = calibration_target_prompt(
                "small red circular target with a white center (the exact center of the circle)"
            )
            if screen_w and screen_h:
                prompt = f"[Screen size: {screen_w}x{screen_h}. Coordinates normalized 0-1000.]\n\n{prompt}"
            response = vlm.send_request(prompt, image_base64=b64_img, max_tokens=128)
            latency = time.time() - start_time
            latencies.append(latency)
            result = response.parsed_json if response.success else None
            raw = response.raw_text or response.error or ""
            
            # Accept coordinates in standard shape or from bbox_2d center
            norm_x = norm_y = None
            if result and "coordinates" in result:
                c = result["coordinates"]
                if isinstance(c, dict) and "x" in c and "y" in c:
                    norm_x, norm_y = float(c["x"]), float(c["y"])
            if result and norm_x is None and "bbox_2d" in result:
                b = result["bbox_2d"]
                if isinstance(b, (list, tuple)) and len(b) >= 4:
                    norm_x = (float(b[0]) + float(b[2])) / 2
                    norm_y = (float(b[1]) + float(b[3])) / 2
            
            if norm_x is not None and norm_y is not None:
                # Convert back to pixels
                pred_x, pred_y = normalized_to_pixels(norm_x, norm_y, screen_w, screen_h)
                
                # Calculate error
                dist = math.sqrt((pred_x - target_x)**2 + (pred_y - target_y)**2)
                errors.append(dist)
                
                print(f"  Target: ({target_x}, {target_y})", flush=True)
                print(f"  VLM Predicted: ({pred_x}, {pred_y}) [Normalized: {norm_x}, {norm_y}]", flush=True)
                print(f"  Error: {dist:.2f} pixels", flush=True)
                print(f"  Inference Time: {latency:.2f}s", flush=True)
            else:
                print("  Failed to find target", flush=True)
                print(f"  Raw response: {raw[:200] if raw else 'none'}...", flush=True)

    finally:
        win.close()
        capture.close()

    # Results
    if errors:
        avg_error = sum(errors) / len(errors)
        avg_latency = sum(latencies) / len(latencies)
        success_rate = (len(errors) / num_runs) * 100
        
        print("\n" + "="*30)
        print("CALIBRATION RESULTS")
        print("="*30)
        print(f"Runs: {num_runs}")
        print(f"Success Rate: {success_rate:.1f}%")
        print(f"Average Error: {avg_error:.2f} pixels")
        print(f"Median Error: {sorted(errors)[len(errors)//2]:.2f} pixels")
        print(f"Average Speed: {avg_latency:.2f}s per inference")
        print("="*30)
    else:
        print("\nCalibration failed - no data collected.")
    return len(errors)  # return count so caller can exit 0/1

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calibration test: VLM accuracy for clicking on-screen targets.")
    parser.add_argument("--runs", type=int, default=5, help="Number of target positions to test")
    args = parser.parse_args()
    n = run_calibration(args.runs)
    sys.exit(0 if (n is not None and n > 0) else 1)

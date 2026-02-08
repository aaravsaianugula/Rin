"""
Interactive calibration script to measure and correct click offset.

This script:
1. Opens the test HTML page
2. Lets you manually click on buttons to record their actual positions
3. Captures screenshots and asks Qwen where it thinks the buttons are
4. Calculates the offset between actual and predicted positions
5. Saves the offset to config for automatic correction
"""

import os
import sys
import time
import json
from pathlib import Path
from typing import List, Tuple, Optional
import webbrowser

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pyautogui
from src.capture import ScreenCapture
from src.inference import VLMClient
from src.prompts import plan_action_prompt

# Disable PyAutoGUI failsafe for calibration
pyautogui.FAILSAFE = False


class MouseTracker:
    """Track mouse position when user clicks."""
    
    def __init__(self):
        self.positions: List[Tuple[int, int, str]] = []  # (x, y, label)
        self.tracking = False
        
    def start_tracking(self):
        """Start tracking mouse clicks."""
        self.positions.clear()
        self.tracking = True
        print("\n" + "="*60)
        print("MOUSE TRACKING ACTIVE")
        print("="*60)
        print("Click on each button in the browser window.")
        print("Press ENTER after clicking all buttons to finish.")
        print("="*60 + "\n")
        
    def record_click(self, x: int, y: int, label: str):
        """Record a click position."""
        if self.tracking:
            self.positions.append((x, y, label))
            print(f"  Recorded: {label} at ({x}, {y})")
            
    def get_positions(self) -> List[Tuple[int, int, str]]:
        """Get all recorded positions."""
        return self.positions.copy()


def get_mouse_position_on_click() -> Optional[Tuple[int, int]]:
    """Wait for user to click and return mouse position."""
    print("Waiting for mouse click...")
    try:
        # Get initial position
        initial_pos = pyautogui.position()
        
        # Wait for mouse to move (user clicked)
        start_time = time.time()
        while time.time() - start_time < 30:  # 30 second timeout
            current_pos = pyautogui.position()
            if current_pos != initial_pos:
                # Wait a moment to see if it's a click (mouse might move then click)
                time.sleep(0.1)
                final_pos = pyautogui.position()
                return (final_pos.x, final_pos.y)
            time.sleep(0.05)
        return None
    except KeyboardInterrupt:
        return None


def calibrate_buttons():
    """Main calibration routine."""
    print("="*60)
    print("RIN CLICK OFFSET CALIBRATION")
    print("="*60)
    
    # Setup
    project_root = Path(__file__).parent.parent
    test_file = project_root / "tests" / "test_ui.html"
    test_url = f"file:///{test_file.absolute()}".replace('\\', '/')
    
    capture = ScreenCapture()
    screen_w, screen_h = capture.get_screen_size()
    print(f"\nScreen resolution: {screen_w}x{screen_h}")
    
    # Open test page
    print(f"\nOpening test page: {test_url}")
    webbrowser.open(test_url)
    time.sleep(2)
    
    # Step 1: User manually clicks buttons and we record positions
    print("\n" + "="*60)
    print("STEP 1: MANUAL CLICK RECORDING")
    print("="*60)
    print("You will click on buttons in the browser window.")
    print("After each click, press ENTER here to record that position.")
    print("Click buttons in this order:")
    print("  1. 'Single Click' button")
    print("  2. 'Double Click' button") 
    print("  3. 'Right Click Me' button")
    print("  4. Text input field (for typing)")
    print("\nPress ENTER to start recording...")
    input()
    
    actual_positions = []
    button_labels = [
        "Single Click button",
        "Double Click button",
        "Right Click Me button",
        "Text input field"
    ]
    
    for i, label in enumerate(button_labels, 1):
        print(f"\n[{i}/{len(button_labels)}] Click on: {label}")
        print("Then press ENTER here to record...")
        input()
        
        pos = pyautogui.position()
        actual_positions.append((pos.x, pos.y, label))
        print(f"  ✓ Recorded: {label} at ({pos.x}, {pos.y})")
    
    print(f"\n✓ Recorded {len(actual_positions)} actual positions")
    
    # Step 2: Capture screenshot and ask Qwen where buttons are
    print("\n" + "="*60)
    print("STEP 2: QWEN PREDICTION")
    print("="*60)
    print("Capturing screenshot and asking Qwen where it thinks the buttons are...")
    
    # Ensure VLM is running
    vlm = VLMClient(timeout=120)
    print("Checking VLM server...")
    if not vlm.check_health():
        print("ERROR: VLM server not running!")
        print("Please start Rin first (it will start the VLM server).")
        return None
    
    # Capture current screen
    image = capture.capture_screen()
    image_b64 = capture.get_base64_from_image(image)
    img_w, img_h = image.size
    
    print(f"Captured image: {img_w}x{img_h} (screen: {screen_w}x{screen_h})")
    
    # Ask Qwen to locate each button
    predicted_positions = []
    
    button_descriptions = [
        ("Single Click", "the 'Single Click' button in the Mouse Actions section"),
        ("Double Click", "the 'Double Click' button in the Mouse Actions section"),
        ("Right Click Me", "the 'Right Click Me' button in the Mouse Actions section"),
        ("Text input", "the text input field labeled 'Type \"Rin is Awesome\" here:'")
    ]
    
    for desc, full_desc in button_descriptions:
        print(f"\nAsking Qwen to locate: {desc}...")
        task = f"Find {full_desc}. Output the pixel coordinates of its center."
        context = f"Screen Size: {img_w}x{img_h}"
        prompt = plan_action_prompt(task, context)
        
        response = vlm.send_request(prompt, image_base64=image_b64)
        
        if not response.success:
            print(f"  ✗ VLM failed: {response.error}")
            continue
            
        result = response.parsed_json
        if not result:
            print(f"  ✗ No valid JSON response")
            continue
        
        # Extract coordinates
        coords = result.get("coordinates") or {}
        x = coords.get("x") or result.get("x")
        y = coords.get("y") or result.get("y")
        
        if x is None or y is None:
            print(f"  ✗ No coordinates in response")
            continue
        
        # These are in image space, need to rescale to screen space
        screen_x = int(x * screen_w / max(img_w, 1))
        screen_y = int(y * screen_h / max(img_h, 1))
        
        predicted_positions.append((screen_x, screen_y, desc))
        print(f"  ✓ Qwen predicted: {desc} at ({screen_x}, {screen_y}) [image coords: ({x}, {y})]")
    
    if len(predicted_positions) != len(actual_positions):
        print(f"\nERROR: Mismatch - got {len(predicted_positions)} predictions but {len(actual_positions)} actual positions")
        return None
    
    # Step 3: Calculate offset
    print("\n" + "="*60)
    print("STEP 3: CALCULATING OFFSET")
    print("="*60)
    
    offsets = []
    for (actual_x, actual_y, actual_label), (pred_x, pred_y, pred_label) in zip(actual_positions, predicted_positions):
        offset_x = actual_x - pred_x
        offset_y = actual_y - pred_y
        offsets.append((offset_x, offset_y))
        print(f"{actual_label}:")
        print(f"  Actual:   ({actual_x}, {actual_y})")
        print(f"  Predicted: ({pred_x}, {pred_y})")
        print(f"  Offset:   ({offset_x:+d}, {offset_y:+d})")
    
    # Calculate average offset
    avg_offset_x = sum(o[0] for o in offsets) / len(offsets)
    avg_offset_y = sum(o[1] for o in offsets) / len(offsets)
    
    print(f"\nAverage offset: ({avg_offset_x:+.1f}, {avg_offset_y:+.1f})")
    
    # Step 4: Save to config
    print("\n" + "="*60)
    print("STEP 4: SAVING OFFSET")
    print("="*60)
    
    config_path = project_root / "config" / "settings.yaml"
    
    # Read existing config
    import yaml
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Add/update offset in coordinates section
    if "coordinates" not in config:
        config["coordinates"] = {}
    
    config["coordinates"]["click_offset_x"] = int(round(avg_offset_x))
    config["coordinates"]["click_offset_y"] = int(round(avg_offset_y))
    
    # Write back
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    
    print(f"✓ Saved offset to {config_path}")
    print(f"  Offset X: {config['coordinates']['click_offset_x']:+d}")
    print(f"  Offset Y: {config['coordinates']['click_offset_y']:+d}")
    print("\n" + "="*60)
    print("CALIBRATION COMPLETE!")
    print("="*60)
    print("The offset will be automatically applied to all future clicks.")
    print("Restart Rin for the changes to take effect.")
    print("="*60)
    
    return (avg_offset_x, avg_offset_y)


if __name__ == "__main__":
    try:
        result = calibrate_buttons()
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n\nCalibration cancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

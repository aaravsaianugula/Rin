"""
End-to-end tool validation script.
Launches the test UI and instructs the agent to exercise all primitives.
"""

import os
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from main import load_config, create_orchestrator, setup_logging

def main():
    # Setup paths
    project_root = Path(__file__).parent.parent
    test_file = project_root / "tests" / "test_ui.html"
    test_url = f"file:///{test_file.absolute()}".replace('\\', '/')
    
    # Load config and setup logging
    config = load_config()
    logger = setup_logging("INFO")
    
    # Initialize orchestrator
    orchestrator = create_orchestrator(config, logger)
    
    # Step 1: Open the test page
    logger.info(f"Opening test page: {test_url}")
    import webbrowser
    webbrowser.open(test_url)
    time.sleep(2) # Wait for browser to open
    
    # Step 2: Ensure VLM is running
    if not orchestrator.vlm_manager.start():
        logger.error("Failed to start VLM server")
        return
        
    if not orchestrator.vlm.wait_for_server(max_wait=60):
        logger.error("VLM server timeout")
        return

    # Step 3: Define the comprehensive validation task
    task = (
        "On the opened 'Rin GUI Automation Test Page', verify every tool by performing these steps:\n"
        "1. CLICK the 'Single Click' button.\n"
        "2. DOUBLE_CLICK the 'Double Click' button.\n"
        "3. RIGHT_CLICK the 'Right Click Me' button.\n"
        "4. TYPE 'Rin is Awesome' in the text field.\n"
        "5. SCROLL down in the scroll box until you see 'SCROLL TARGET REACHED'.\n"
        "6. DRAG the orange 'Drag' box into the dashed 'Drop Target' area.\n"
        "7. TRIPLE_CLICK the selecting text line to select it all.\n"
        "Check the status labels for 'Clicked!', 'Double Clicked!', etc. to confirm success."
    )
    
    logger.info("Starting tool validation task...")
    result = orchestrator.execute_task(task)
    
    # Step 4: Report results
    logger.info("=== TOOL VALIDATION RESULTS ===")
    logger.info(f"Success: {result.success}")
    logger.info(f"Steps Taken: {result.steps_taken}")
    logger.info(f"Message: {result.message}")
    
    if result.success:
        logger.info("[OK] All tools verified successfully!")
    else:
        logger.error(f"[FAIL] Task failed: {result.error or result.message}")

if __name__ == "__main__":
    main()

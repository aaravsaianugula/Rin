"""
Tests for autonomous and de-hardcoded logic.
Ensures the system no longer uses heuristics/macros.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.actions import (
    ActionType,
    Action,
    ActionError,
    create_action_from_dict,
)
from src.app_launcher import launch_app

class TestDeHardcodedActions:
    """Test that heuristics were correctly removed from actions."""

    def test_legacy_aliases_fail(self):
        """Verify that legacy aliases like GOTO_URL now raise ActionError."""
        legacy_data = [
            {"action": "GOTO_URL", "value": "https://google.com"},
            {"action": "WRITE", "value": "hello"},
            {"action": "START_APP", "value": "notepad"},
            {"action": "SEARCH_WEB", "value": "how to code"}
        ]
        for data in legacy_data:
            with pytest.raises(ActionError):
                create_action_from_dict(data)

    def test_no_target_key_extraction(self):
        """Verify that the system no longer extracts 'key' from 'target'."""
        data = {
            "action": "PRESS",
            "target": "the enter key",  # Old heuristic would extract "enter"
            "confidence": 1.0
        }
        action = create_action_from_dict(data)
        # Should be None because it's no longer extracted from target
        assert action.key is None

    def test_no_thought_key_extraction(self):
        """Verify that the system no longer extracts 'key' from 'thought'."""
        data = {
            "action": "PRESS",
            "thought": "I will press enter now.", # Old heuristic would extract "enter"
            "confidence": 1.0
        }
        action = create_action_from_dict(data)
        assert action.key is None

class TestDeHardcodedAppLauncher:
    """Test the simplified, model-driven app launcher logic."""

    @patch('src.app_launcher.launch_app_via_run_dialog')
    @patch('src.app_launcher.launch_app_via_start_menu')
    @patch('os.startfile')
    def test_launch_app_logic(self, mock_startfile, mock_start_menu, mock_run_dialog):
        """Verify launch_app chooses the correct method based on name characteristics."""
        
        # 1. Simple command (no spaces) -> Now defaults to Start Menu for reliability
        launch_app("notepad")
        mock_start_menu.assert_called_with("notepad")
        
        # 2. URI command (contains :) -> uses startfile
        launch_app("spotify:")
        mock_startfile.assert_called_with("spotify:")
        
        # 3. Human name (contains spaces) -> Start Menu
        launch_app("Google Chrome")
        mock_start_menu.assert_called_with("Google Chrome")

        # 4. Explicit method
        launch_app("notepad", method="run_dialog")
        mock_run_dialog.assert_called_with("notepad")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

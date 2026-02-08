"""
Tests for action executor module.
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
    ActionExecutor,
    ActionError,
    create_action_from_dict,
)


class TestActionType:
    """Test ActionType enum."""
    
    def test_all_types_exist(self):
        """Verify all expected action types exist."""
        expected = [
            "CLICK", "DOUBLE_CLICK", "RIGHT_CLICK",
            "TYPE", "PRESS", "HOTKEY",
            "SCROLL", "DRAG", "WAIT", "MOVE"
        ]
        for action in expected:
            assert hasattr(ActionType, action)


class TestAction:
    """Test Action dataclass."""
    
    def test_create_click_action(self):
        """Test creating a click action."""
        action = Action(
            action_type=ActionType.CLICK,
            x=100,
            y=200,
            confidence=0.95
        )
        assert action.action_type == ActionType.CLICK
        assert action.x == 100
        assert action.y == 200
        assert action.confidence == 0.95
    
    def test_create_type_action(self):
        """Test creating a type action."""
        action = Action(
            action_type=ActionType.TYPE,
            text="Hello World"
        )
        assert action.action_type == ActionType.TYPE
        assert action.text == "Hello World"


class TestActionExecutor:
    """Test ActionExecutor class."""
    
    @pytest.fixture
    def executor(self):
        """Create an executor with mocked PyAutoGUI."""
        with patch('src.actions.pyautogui') as mock_pyautogui:
            executor = ActionExecutor(
                screen_width=1920,
                screen_height=1080,
                confidence_threshold=0.8,
                action_delay=0.01,  # Fast for tests
                failsafe_enabled=True
            )
            executor._mock = mock_pyautogui
            yield executor
    
    def test_coordinate_validation_valid(self, executor):
        """Test valid coordinates pass validation."""
        x, y = executor._validate_coordinates(500, 500)
        assert x == 500
        assert y == 500
    
    def test_coordinate_validation_clamps_negative(self, executor):
        """Test negative coordinates are clamped."""
        x, y = executor._validate_coordinates(-100, -50)
        assert x == 0
        assert y == 0
    
    def test_coordinate_validation_clamps_overflow(self, executor):
        """Test overflow coordinates are clamped."""
        x, y = executor._validate_coordinates(2000, 1200)
        assert x == 1919
        assert y == 1079
    
    def test_confidence_check_passes(self, executor):
        """Test action with high confidence passes."""
        action = Action(ActionType.CLICK, confidence=0.9)
        assert executor._check_confidence(action) == True
    
    def test_confidence_check_fails(self, executor):
        """Test action with low confidence fails."""
        action = Action(ActionType.CLICK, confidence=0.5)
        assert executor._check_confidence(action) == False
    
    def test_click_calls_pyautogui(self, executor):
        """Test click method calls PyAutoGUI."""
        executor.click(500, 500)
        executor._mock.click.assert_called_once_with(500, 500)
    
    def test_type_text_calls_pyautogui(self, executor):
        """Test type_text method calls PyAutoGUI."""
        executor.type_text("Hello")
        executor._mock.write.assert_called_once()
    
    def test_action_history_tracking(self, executor):
        """Test actions are recorded in history."""
        action = Action(
            action_type=ActionType.CLICK,
            x=100,
            y=200,
            confidence=0.95,
            target_description="Test button"
        )
        executor.execute(action)
        
        history = executor.get_action_history()
        assert len(history) == 1
        assert history[0].action_type == ActionType.CLICK
    
    def test_clear_history(self, executor):
        """Test clearing action history."""
        action = Action(ActionType.CLICK, x=100, y=200, confidence=0.95)
        executor.execute(action)
        executor.clear_history()
        
        assert len(executor.get_action_history()) == 0


class TestCreateActionFromDict:
    """Test create_action_from_dict function."""
    
    def test_create_click_action(self):
        """Test creating click action from dict."""
        data = {
            "action": "CLICK",
            "coordinates": {"x": 450, "y": 320},
            "confidence": 0.95,
            "target": "Submit button"
        }
        action = create_action_from_dict(data)
        
        assert action.action_type == ActionType.CLICK
        assert action.x == 450
        assert action.y == 320
        assert action.confidence == 0.95
        assert action.target_description == "Submit button"
    
    def test_create_type_action(self):
        """Test creating type action from dict."""
        data = {
            "action": "TYPE",
            "value": "Hello World",
            "confidence": 0.9
        }
        action = create_action_from_dict(data)
        
        assert action.action_type == ActionType.TYPE
        assert action.text == "Hello World"
    
    def test_create_hotkey_action(self):
        """Test creating hotkey action from dict."""
        data = {
            "action": "HOTKEY",
            "keys": ["ctrl", "c"],
            "confidence": 1.0
        }
        action = create_action_from_dict(data)
        
        assert action.action_type == ActionType.HOTKEY
        assert action.keys == ["ctrl", "c"]
    
    def test_invalid_action_type_raises(self):
        """Test invalid action type raises error."""
        data = {"action": "INVALID_ACTION"}
        
        with pytest.raises(ActionError):
            create_action_from_dict(data)
    
    def test_case_insensitive_action(self):
        """Test action type is case-insensitive."""
        data = {"action": "click", "coordinates": {"x": 100, "y": 100}}
        action = create_action_from_dict(data)
        
        assert action.action_type == ActionType.CLICK


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

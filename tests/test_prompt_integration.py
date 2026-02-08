"""
Integration tests for the prompt and inference pipeline.

Tests for balanced prompting with:
- Efficient reasoning (not overthinking)
- Clear task completion signals
- Rich screen context
"""

import pytest


class TestPromptIntegration:
    """Test that prompts are correctly structured for Qwen3-VL."""
    
    def test_system_prompt_has_visual_grounding(self):
        from src.prompts import SYSTEM_PROMPT
        
        # Must reference screenshots
        assert "screenshot" in SYSTEM_PROMPT.lower()
    
    def test_system_prompt_has_all_actions(self):
        from src.prompts import SYSTEM_PROMPT
        
        required_actions = ["CLICK", "TYPE", "PRESS", "HOTKEY", "SCROLL", "LAUNCH_APP"]
        for action in required_actions:
            assert action in SYSTEM_PROMPT, f"Missing action: {action}"
    
    def test_system_prompt_has_json_examples(self):
        from src.prompts import SYSTEM_PROMPT
        
        # Must have proper JSON examples
        assert '"action"' in SYSTEM_PROMPT
        assert '"coordinates"' in SYSTEM_PROMPT
        assert '"task_complete"' in SYSTEM_PROMPT
    
    def test_system_prompt_has_completion_guidance(self):
        """Verify explicit task completion guidance."""
        from src.prompts import SYSTEM_PROMPT
        
        # Must guide when to set task_complete: true
        assert "task_complete" in SYSTEM_PROMPT
        assert "true" in SYSTEM_PROMPT
    
    def test_system_prompt_has_repeat_prevention(self):
        """Verify repeat prevention rules."""
        from src.prompts import SYSTEM_PROMPT
        
        assert "NEVER REPEAT" in SYSTEM_PROMPT or "DIFFERENT" in SYSTEM_PROMPT

    def test_action_prompt_includes_observation(self):
        from src.prompts import plan_action_prompt
        
        prompt = plan_action_prompt("Open Notepad", "Screen: 1920x1080")
        
        assert "<observation>" in prompt
    
    def test_action_prompt_includes_reasoning(self):
        from src.prompts import plan_action_prompt
        
        prompt = plan_action_prompt("Open Notepad", "Screen: 1920x1080")
        
        assert "<reasoning>" in prompt
    
    def test_action_prompt_asks_about_completion(self):
        """Verify prompt asks if task is already complete."""
        from src.prompts import plan_action_prompt
        
        prompt = plan_action_prompt("Open Notepad", "Screen: 1920x1080")
        
        # Must check for task completion in reasoning
        assert "COMPLETE" in prompt or "complete" in prompt
    
    def test_action_prompt_includes_history_warnings(self):
        from src.prompts import plan_action_prompt
        
        history = "- CLICK: Start button -> executed"
        prompt = plan_action_prompt("Open Notepad", "Screen: 1920x1080", history)
        
        assert "Start button" in prompt
        assert "DIFFERENT" in prompt
    
    def test_coordinate_system_explained(self):
        from src.prompts import SYSTEM_PROMPT
        
        # Must explain the 0-1000 coordinate system
        assert "0, 0" in SYSTEM_PROMPT or "(0, 0)" in SYSTEM_PROMPT
        assert "1000" in SYSTEM_PROMPT
    
    def test_recovery_prompt_exists(self):
        """Verify recovery prompt function exists."""
        from src.prompts import recovery_prompt
        
        prompt = recovery_prompt("CLICK on Start", 3)
        
        assert "3 times" in prompt
        assert "DIFFERENT" in prompt


class TestInferenceConfig:
    """Test inference configuration."""
    
    def test_sampling_parameters(self):
        from src.inference import VLMClient
        assert VLMClient is not None


class TestOrchestratorIntegration:
    """Test orchestrator configuration."""
    
    def test_orchestrator_accepts_stability_params(self):
        from src.orchestrator import Orchestrator
        import inspect
        
        sig = inspect.signature(Orchestrator.__init__)
        params = list(sig.parameters.keys())
        
        assert "screen_stability_enabled" in params
        assert "screen_stability_max_wait" in params
    
    def test_action_record_exists(self):
        from src.orchestrator import ActionRecord
        
        record = ActionRecord(
            action_type="CLICK",
            target="test button",
            x=500,
            y=300
        )
        
        assert "CLICK" in record.to_history_str()
        assert "test button" in record.to_history_str()
    
    def test_orchestrator_imports_window_context(self):
        """Verify orchestrator imports window context function."""
        import src.orchestrator as orchestrator_module
        
        assert hasattr(orchestrator_module, 'get_active_window_context')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

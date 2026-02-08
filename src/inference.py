"""
VLM inference engine for Qwen3-VL Computer Control System.
"""

import base64
import json
import logging
import time
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests

from .prompts import SYSTEM_PROMPT

@dataclass
class VLMResponse:
    raw_text: str
    parsed_json: Optional[Dict[str, Any]]
    success: bool
    error: Optional[str] = None

class VLMClient:
    """Client for communicating with llama-server."""
    
    def __init__(self, base_url: str = "http://127.0.0.1:8080", timeout: int = 120, logger: Optional[logging.Logger] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.logger = logger or logging.getLogger(__name__)
        self._session = requests.Session()
        self._abort_check = None  # Callable that returns True if we should abort
    
    def set_abort_check(self, callback):
        """Set a callback function that returns True if we should abort."""
        self._abort_check = callback
    
    def _should_abort(self) -> bool:
        """Check if we should abort the current request."""
        if self._abort_check:
            return self._abort_check()
        return False

    def check_health(self) -> bool:
        """Check if server is healthy."""
        try:
            resp = self._session.get(f"{self.base_url}/health", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    def wait_for_server(self, max_wait: int = 60) -> bool:
        """Wait for server to become available."""
        start = time.time()
        while time.time() - start < max_wait:
            if self.check_health():
                return True
            time.sleep(0.5)  # Faster polling (was 2s)
        return False

    def _parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parse JSON from model response, handling CoT reasoning blocks.
        """
        # 1. Extract JSON from code blocks first (most reliable)
        code_block_pattern = r"```(?:json)?\s*\n?([\s\S]*?)\n?```"
        matches = re.findall(code_block_pattern, text)
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue
        
        # 2. Fallback: Find first '{' and last '}'
        try:
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                json_str = text[start:end+1]
                return json.loads(json_str)
        except json.JSONDecodeError:
            pass
            
        return None

    def send_request(self, prompt: str, image_base64: Optional[str] = None, max_tokens: int = 1024) -> VLMResponse:
        """Send request to VLM with retry logic."""
        # Check for abort before starting
        if self._should_abort():
            return VLMResponse("", None, False, "Aborted")
        
        messages = [
            {
                "role": "system",
                "content": [{"type": "text", "text": SYSTEM_PROMPT}],
            },
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            },
        ]
        
        if image_base64:
            messages[1]["content"].insert(0, {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_base64}"}
            })
            
        payload = {
            "model": "qwen3-vl",
            "messages": messages,
            # Qwen3-VL works better with sampling than greedy decoding
            "temperature": 0.7,
            "top_p": 0.8,
            "max_tokens": max_tokens
        }
        
        # Retry with exponential backoff for transient failures
        max_retries = 2
        for attempt in range(max_retries + 1):
            # Check for abort at start of each attempt
            if self._should_abort():
                self.logger.info("VLM request aborted by user")
                return VLMResponse("", None, False, "Aborted")
            
            try:
                resp = self._session.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                    timeout=self.timeout
                )
                
                # Check for abort after request completes
                if self._should_abort():
                    self.logger.info("VLM request aborted by user after response")
                    return VLMResponse("", None, False, "Aborted")
                
                if resp.status_code != 200:
                    error_msg = f"API error {resp.status_code}: {resp.text}"
                    if attempt < max_retries:
                        self.logger.warning(f"Retry {attempt+1}/{max_retries}: {error_msg}")
                        time.sleep(1 * (attempt + 1))  # 1s, 2s backoff
                        continue
                    return VLMResponse("", None, False, error_msg)
                    
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = self._parse_json_response(content)
                    
                return VLMResponse(content, parsed, True)
            except requests.exceptions.Timeout:
                error_msg = "VLM request timed out. The model may be overloaded or processing a complex image."
                if attempt < max_retries:
                    self.logger.warning(f"Retry {attempt+1}/{max_retries}: Timeout")
                    time.sleep(1 * (attempt + 1))
                    continue
                return VLMResponse("", None, False, error_msg)
            except requests.exceptions.ConnectionError:
                error_msg = "Cannot connect to VLM server. Please check that the server is running."
                if attempt < max_retries:
                    self.logger.warning(f"Retry {attempt+1}/{max_retries}: Connection failed")
                    time.sleep(1 * (attempt + 1))
                    continue
                return VLMResponse("", None, False, error_msg)
            except requests.exceptions.RequestException as e:
                error_msg = f"Network error: {e}"
                if attempt < max_retries:
                    self.logger.warning(f"Retry {attempt+1}/{max_retries}: {error_msg}")
                    time.sleep(1 * (attempt + 1))
                    continue
                return VLMResponse("", None, False, error_msg)
            except json.JSONDecodeError as e:
                error_msg = f"Invalid response from VLM server (not valid JSON): {e}"
                return VLMResponse("", None, False, error_msg)
            except KeyError as e:
                error_msg = f"Unexpected response format from VLM: missing {e}"
                return VLMResponse("", None, False, error_msg)
            except Exception as e:
                error_msg = f"Unexpected error: {type(e).__name__}: {e}"
                if attempt < max_retries:
                    self.logger.warning(f"Retry {attempt+1}/{max_retries}: {error_msg}")
                    time.sleep(1 * (attempt + 1))
                    continue
                return VLMResponse("", None, False, error_msg)

    def analyze_screenshot(self, image_base64: str, task: str, context: str = "") -> Tuple[Optional[Dict[str, Any]], str]:
        """Convenience method for task analysis."""
        from .prompts import plan_action_prompt
        prompt = plan_action_prompt(task, context)
        response = self.send_request(prompt, image_base64=image_base64)
        return response.parsed_json, response.raw_text


class MockVLMClient(VLMClient):
    """Mock VLM client for testing."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mock_responses: List[Dict[str, Any]] = []
    
    def add_mock_response(self, response: Dict[str, Any]):
        self.mock_responses.append(response)
    
    def check_health(self) -> bool:
        return True
    
    def send_request(self, *args, **kwargs) -> VLMResponse:
        if self.mock_responses:
            mock_data = self.mock_responses.pop(0)
            return VLMResponse(json.dumps(mock_data), mock_data, True)
        return VLMResponse("{}", {}, True)
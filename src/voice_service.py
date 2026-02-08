"""
Voice Service for Rin Agent.

Provides wake word detection using Porcupine and speech-to-text using Moonshine.
Emits voice state updates to the WPF overlay via StatusServer.

Features:
- "Hey Rin" wake word detection (Porcupine)
- High-accuracy STT (Moonshine - 2x better than Vosk)
- Variable-length audio processing (no chunking)
- Silence-based utterance detection
- Prompt injection for mid-task commands
"""

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class VoiceConfig:
    """Configuration for voice service."""
    # Porcupine wake word model (custom trained)
    porcupine_model_path: str = "models/porcupine/Hey-Rin_en_windows_v4_0_0.ppn"
    porcupine_access_key: str = ""  # Get free key from Picovoice console
    
    # Moonshine STT model (base = best accuracy/speed balance)
    moonshine_model: str = "moonshine/base"  # Options: moonshine/tiny, moonshine/base
    
    # Audio settings
    sample_rate: int = 16000
    chunk_size: int = 512  # Porcupine frame size
    
    # Timing
    silence_timeout: float = 3.0  # Seconds of silence before finalizing
    silence_timeout_busy: float = 1.5  # Faster timeout during active tasks
    max_listen_time: float = 45.0  # Max listening time before timeout
    
    # Continuous listening settings
    enabled: bool = True  # Master enable/disable
    speech_start_threshold: float = 0.02  # Audio level to detect speech start


class VoiceState:
    """Voice service states."""
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"


# Priority commands that execute immediately (bypass normal processing)
PRIORITY_COMMANDS = {
    "stop": "abort",
    "cancel": "abort",
    "abort": "abort",
    "wait": "pause",
    "pause": "pause",
    "hold on": "pause",
    "resume": "resume",
    "continue": "resume",
    "go": "resume",
    "try again": "retry",
    "retry": "retry",
    "skip": "skip",
    "skip this": "skip",
    "next": "skip",
}

# Steering prefixes that inject into current task context
STEERING_PREFIXES = [
    "actually",
    "instead",
    "also",
    "but",
    "wait",  # When followed by more text, it's steering
    "no",
    "not that",
    "different",
]


class VoiceService:
    """
    Handles wake word detection and speech-to-text.
    
    Flow:
    1. Idle: Listening for wake word ("Hey Rin")
    2. Wake detected: Transition to LISTENING state
    3. Listening: Stream audio to Vosk for STT
    4. Silence detected: Finalize transcription
    5. Emit final text, return to IDLE
    """
    
    def __init__(
        self,
        config: VoiceConfig,
        status_server: Any = None,
        on_wake: Optional[Callable[[], None]] = None,
        on_partial: Optional[Callable[[str], None]] = None,
        on_final: Optional[Callable[[str], None]] = None,
        on_level: Optional[Callable[[float], None]] = None,
    ):
        self.config = config
        self.server = status_server
        
        # Callbacks
        self.on_wake = on_wake
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_level = on_level
        
        # State
        self._state = VoiceState.IDLE
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        # Audio processing
        self._porcupine = None
        self._moonshine = None
        self._tokenizer = None
        
        # Prompt injection
        self._inject_callback: Optional[Callable[[str], None]] = None
        self.task_queue: Optional[queue.Queue] = None
        
        # Audio buffer for STT
        self._audio_buffer = []
        self._last_speech_time = 0.0
        self._listen_start_time = 0.0
        
        # Continuous listening mode (no wake word when agent is busy)
        self._agent_busy = False
        self._orchestrator = None
        self._speech_detected = False  # Track if speech has started (for continuous mode)
        
    @property
    def state(self) -> str:
        return self._state
    
    def set_inject_callback(self, callback: Callable[[str], None]):
        """Set callback for prompt injection during active tasks."""
        self._inject_callback = callback
    
    def set_orchestrator(self, orchestrator):
        """Set orchestrator reference for bidirectional communication."""
        self._orchestrator = orchestrator
    
    def set_agent_busy(self, busy: bool):
        """
        Called by orchestrator to indicate task state.
        When busy, voice service enters continuous listening mode (no wake word needed).
        """
        was_busy = self._agent_busy
        self._agent_busy = busy
        
        if busy and not was_busy:
            logger.info("Agent busy - continuous listening mode ACTIVE (no wake word needed)")
            print("\n   🎧 [CONTINUOUS LISTENING] Speak anytime to steer or interrupt")
        elif not busy and was_busy:
            logger.info("Agent idle - wake word required")
            print("\n   💤 [IDLE] Say 'Hey Rin' to start\n")
    
    @property
    def agent_busy(self) -> bool:
        return self._agent_busy
    
    def _get_effective_silence_timeout(self) -> float:
        """Get silence timeout based on agent state."""
        if self._agent_busy:
            return self.config.silence_timeout_busy
        return self.config.silence_timeout
    
    def _classify_command(self, text: str) -> tuple:
        """
        Classify voice command into categories.
        
        Returns:
            (category, action): 
            - ("priority", "abort"|"pause"|"resume"|"retry"|"skip")
            - ("steering", text): Command to inject into current context
            - ("question", text): Read-only query
            - ("task", text): New task to queue
        """
        text_lower = text.lower().strip()
        
        # Check priority commands first (exact or fuzzy match)
        for trigger, action in PRIORITY_COMMANDS.items():
            if text_lower == trigger or text_lower.startswith(trigger + " "):
                return ("priority", action)
        
        # Check for steering prefixes (inject into context)
        for prefix in STEERING_PREFIXES:
            if text_lower.startswith(prefix):
                return ("steering", text)
        
        # Check for questions (read-only mode)
        question_starters = ["what", "where", "when", "why", "how", "is ", "are ", "can ", "does ", "do "]
        if any(text_lower.startswith(q) for q in question_starters) or text_lower.endswith("?"):
            return ("question", text)
        
        # Default: new task
        return ("task", text)
    
    def enable_wake_word(self):
        """Enable wake word detection."""
        self.config.enabled = True
        logger.info("Wake word detection ENABLED")
    
    def disable_wake_word(self):
        """Disable wake word detection."""
        self.config.enabled = False
        self._set_state(VoiceState.IDLE)
        logger.info("Wake word detection DISABLED")
    
    def _set_state(self, state: str):
        """Update state and notify server."""
        if state != self._state:
            self._state = state
            if self.server:
                self.server.emit_voice_state(state)
            logger.info(f"Voice state: {state}")
    
    def _init_porcupine(self) -> bool:
        """Initialize Porcupine wake word detector."""
        try:
            import pvporcupine
            
            model_path = Path(self.config.porcupine_model_path)
            if not model_path.exists():
                logger.error(f"Porcupine model not found: {model_path}")
                return False
            
            access_key = self.config.porcupine_access_key
            if not access_key:
                # Use secure key manager
                from .key_manager import get_porcupine_key
                access_key = get_porcupine_key()
            
            if not access_key:
                logger.error(
                    "Porcupine access key required. Get a free key from:\n"
                    "https://console.picovoice.ai/\n"
                    "Then run: python src/key_manager.py set porcupine YOUR_KEY"
                )
                return False
            
            self._porcupine = pvporcupine.create(
                access_key=access_key,
                keyword_paths=[str(model_path)],
                sensitivities=[0.5]  # 0-1, higher = more sensitive
            )
            
            logger.info(f"Porcupine initialized with 'Hey Rin' wake word")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Porcupine: {e}")
            return False
    
    def _init_moonshine(self) -> bool:
        """Initialize Moonshine STT (2x more accurate than Vosk)."""
        try:
            from moonshine_onnx import MoonshineOnnxModel, load_tokenizer
            
            self._moonshine = MoonshineOnnxModel(
                model_name=self.config.moonshine_model
            )
            self._tokenizer = load_tokenizer()
            
            logger.info(f"Moonshine STT initialized ({self.config.moonshine_model})")
            return True
            
        except ImportError:
            logger.error(
                "Moonshine not installed. Install with:\n"
                "pip install useful-moonshine-onnx"
            )
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Moonshine: {e}")
            return False
    
    def start(self) -> bool:
        """Start the voice service."""
        if self._running:
            return True
        
        # Initialize wake word
        if not self._init_porcupine():
            return False
        
        # Initialize STT (optional - can work without it)
        moonshine_ok = self._init_moonshine()
        if not moonshine_ok:
            logger.warning("STT not available - wake word only mode")
        
        # Start processing thread
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        
        logger.info("Voice service started")
        print("\n" + "="*50)
        print("🎤 VOICE CONTROL ACTIVE")
        print("="*50)
        print("Say 'Hey Rin' followed by your command")
        print("Example: 'Hey Rin, open notepad'")
        print("="*50 + "\n")
        return True
    
    def stop(self):
        """Stop the voice service."""
        self._running = False
        
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        
        if self._porcupine:
            self._porcupine.delete()
            self._porcupine = None
        
        logger.info("Voice service stopped")
    
    def _run(self):
        """Main processing loop with continuous listening support."""
        import sounddevice as sd
        
        frame_length = self._porcupine.frame_length if self._porcupine else 512
        
        try:
            with sd.InputStream(
                samplerate=self.config.sample_rate,
                channels=1,
                dtype=np.int16,
                blocksize=frame_length
            ) as stream:
                
                while self._running:
                    audio, overflowed = stream.read(frame_length)
                    if overflowed:
                        logger.warning("Audio buffer overflow")
                    
                    audio = audio.flatten()
                    
                    # Calculate audio level for visualization
                    level = np.abs(audio).mean() / 32768.0
                    if self.on_level:
                        self.on_level(level)
                    if self.server:
                        self.server.emit_voice_level(level)
                    
                    # Process based on state
                    if self._state == VoiceState.IDLE:
                        # In continuous mode (agent busy), detect speech start directly
                        if self._agent_busy and level > self.config.speech_start_threshold:
                            # Speech detected while agent is busy - start listening immediately
                            logger.info("Speech detected during task - listening without wake word")
                            print("\n   🎧 [HEARD YOU] Listening...")
                            self._set_state(VoiceState.LISTENING)
                            self._audio_buffer.clear()
                            self._audio_buffer.append(audio.astype(np.float32) / 32768.0)
                            self._last_speech_time = time.time()
                            self._listen_start_time = time.time()
                            self._speech_detected = True
                        else:
                            # Normal mode - require wake word
                            self._process_wake_word(audio)
                    elif self._state == VoiceState.LISTENING:
                        self._process_stt(audio, level)
                    
        except Exception as e:
            logger.error(f"Voice processing error: {e}")
            self._running = False
    
    def _process_wake_word(self, audio: np.ndarray):
        """Check for wake word detection."""
        if not self._porcupine:
            return
        
        try:
            keyword_index = self._porcupine.process(audio)
            
            if keyword_index >= 0:
                logger.info("Wake word detected: 'Hey Rin'")
                print("\n🎤 [WAKE WORD DETECTED] Hey Rin!")
                print("   Listening... (speak your command)\n")
                
                # Callback
                if self.on_wake:
                    self.on_wake()
                
                # Transition to listening
                self._set_state(VoiceState.LISTENING)
                self._audio_buffer.clear()
                self._last_speech_time = time.time()
                self._listen_start_time = time.time()
                
        except Exception as e:
            logger.error(f"Wake word error: {e}")
    
    def _process_stt(self, audio: np.ndarray, level: float):
        """Process audio for speech-to-text."""
        current_time = time.time()
        
        # Check for timeout
        if current_time - self._listen_start_time > self.config.max_listen_time:
            logger.info("Listen timeout - finalizing")
            self._finalize_transcription()
            return
        
        # Get effective silence timeout (faster during active tasks)
        silence_timeout = self._get_effective_silence_timeout()
        
        # Check for silence (finalization)
        if level > 0.01:  # Adjust threshold as needed
            self._last_speech_time = current_time
        elif current_time - self._last_speech_time > silence_timeout:
            self._finalize_transcription()
            return
        
        # Buffer audio for Moonshine (processes variable-length segments)
        self._audio_buffer.append(audio.astype(np.float32) / 32768.0)  # Normalize to float32
        
        # Show listening indicator with dynamic dots
        elapsed = len(self._audio_buffer) * 0.032
        dots = "." * (int(elapsed * 2) % 4 + 1)  # Animated dots
        level_bar = "█" * min(int(level * 20), 10)  # Voice level bar
        mode_indicator = "🎧" if self._agent_busy else "🎤"
        print(f"\r   {mode_indicator} Listening{dots:<4} [{level_bar:<10}] {elapsed:.1f}s", end="", flush=True)
        if self.server:
            self.server.emit_voice_partial(f"{mode_indicator} Listening{dots}")
    
    def _finalize_transcription(self):
        """Finalize and submit the transcription using Moonshine with smart command classification."""
        final_text = ""
        if self._moonshine and self._audio_buffer:
            try:
                # Concatenate all audio chunks
                audio_data = np.concatenate(self._audio_buffer)
                
                # Reshape to 2D (batch_size=1, samples) - required by ONNX
                audio_data = audio_data.reshape(1, -1)
                
                # Transcribe with Moonshine (returns token IDs)
                tokens = self._moonshine.generate(audio_data)
                
                # Decode token IDs to text using tokenizer
                if tokens is not None and len(tokens) > 0:
                    # tokens is a list of token IDs
                    if isinstance(tokens[0], list):
                        tokens = tokens[0]  # Unbatch if nested
                    final_text = self._tokenizer.decode(tokens, skip_special_tokens=True)
                    final_text = final_text.strip()
                
            except Exception as e:
                logger.error(f"Moonshine transcription error: {e}")
        
        self._audio_buffer.clear()
        self._speech_detected = False
        
        if final_text:
            logger.info(f"Final transcription: {final_text}")
            
            # Classify the command
            category, payload = self._classify_command(final_text)
            
            if category == "priority":
                # Priority commands execute immediately
                print(f"\n\n⚡ [PRIORITY] {payload.upper()}")
                logger.info(f"Priority command: {payload}")
                
                if self._orchestrator:
                    if payload == "abort":
                        print("   Stopping task...")
                        self._orchestrator.abort()
                    elif payload == "pause":
                        print("   Pausing task...")
                        if hasattr(self._orchestrator, 'pause'):
                            self._orchestrator.pause()
                    elif payload == "resume":
                        print("   Resuming task...")
                        if hasattr(self._orchestrator, 'resume'):
                            self._orchestrator.resume()
                    elif payload == "retry":
                        print("   Retrying last action...")
                        if hasattr(self._orchestrator, 'retry_last'):
                            self._orchestrator.retry_last()
                    elif payload == "skip":
                        print("   Skipping current step...")
                        if hasattr(self._orchestrator, 'skip_step'):
                            self._orchestrator.skip_step()
                
                # Don't transition through normal submission for priority commands
                self._set_state(VoiceState.IDLE)
                if self.server:
                    self.server.emit_voice_partial("")
                return
            
            elif category == "steering":
                # Steering commands inject into current task context
                print(f"\n\n🔄 [STEERING] {final_text}")
                print("   Adjusting current task...")
                
                if self._inject_callback:
                    self._inject_callback(final_text)
                elif self._orchestrator and hasattr(self._orchestrator, 'inject_context'):
                    self._orchestrator.inject_context(final_text)
                
                # Brief processing state then return
                self._set_state(VoiceState.PROCESSING)
                time.sleep(0.3)
                self._set_state(VoiceState.IDLE)
                if self.server:
                    self.server.emit_voice_partial("")
                return
            
            elif category == "question":
                # Questions trigger conversational/read-only mode
                print(f"\n\n❓ [QUESTION] {final_text}")
                print("   Thinking...")
                
                # Send as a question (orchestrator should handle read-only)
                if self.server:
                    self.server.emit_voice_partial(final_text)
                
                self._set_state(VoiceState.PROCESSING)
                
                if self.on_final:
                    self.on_final(final_text)
                
                # Queue with question prefix for special handling
                if self.task_queue and not self._agent_busy:
                    self.task_queue.put(f"[QUESTION] {final_text}")
                elif self._inject_callback:
                    self._inject_callback(f"[QUESTION] {final_text}")
                
            else:
                # Normal task command
                print(f"\n\n✅ [COMMAND RECEIVED] {final_text}")
                print("   Processing...\n")
                
                # Send final text to overlay BEFORE changing state
                if self.server:
                    self.server.emit_voice_partial(final_text)
                
                # Small delay to ensure overlay receives the text
                time.sleep(0.3)
                
                # Now change to processing state (triggers auto-submit in overlay)
                self._set_state(VoiceState.PROCESSING)
                
                if self.on_final:
                    self.on_final(final_text)
                
                # Submit to task queue or inject
                if self._agent_busy and self._inject_callback:
                    # If agent is busy, inject as context rather than queuing
                    self._inject_callback(final_text)
                elif self.task_queue:
                    self.task_queue.put(final_text)
                elif self._inject_callback:
                    self._inject_callback(final_text)
        else:
            logger.info("No speech detected")
            print("\n   (No speech detected)\n")
        
        # Keep processing state briefly so UI can complete submission
        time.sleep(0.3)
        
        # Return to idle
        self._set_state(VoiceState.IDLE)
        if self.server:
            self.server.emit_voice_partial("")  # Clear partial display


def init_voice_service(
    status_server: Any = None,
    config: Optional[VoiceConfig] = None
) -> VoiceService:
    """
    Factory function to create and configure VoiceService.
    
    Args:
        status_server: StatusServer instance for emitting events
        config: Voice configuration (uses defaults if None)
    
    Returns:
        Configured VoiceService instance
    """
    if config is None:
        config = VoiceConfig()
    
    return VoiceService(
        config=config,
        status_server=status_server
    )

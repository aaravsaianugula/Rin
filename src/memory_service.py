"""
Memory Service for Rin Agent.

Provides persistent, file-based memory that survives across sessions.
Inspired by OpenClaw's transparent markdown-based memory architecture.

Memory Types:
- SOUL.md: Agent personality and identity
- USER.md: User context and preferences  
- MEMORY.md: Long-term facts and learnings
- memory/YYYY-MM-DD.md: Daily conversation logs
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("qwen3vl.memory")


class MemoryService:
    """
    File-based memory service using Markdown files.
    
    All memory is stored as plain text files that are:
    - Human-readable and editable
    - Git-trackable for version history
    - Transparent (no black-box database)
    """
    
    def __init__(self, data_dir: Optional[str] = None):
        """
        Initialize memory service.
        
        Args:
            data_dir: Path to data directory. Defaults to project_root/data/
        """
        if data_dir is None:
            project_root = Path(__file__).parent.parent
            data_dir = project_root / "data"
        
        self.data_dir = Path(data_dir)
        self.memory_dir = self.data_dir / "memory"
        
        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        
        # File paths
        self.soul_path = self.data_dir / "SOUL.md"
        self.user_path = self.data_dir / "USER.md"
        self.memory_path = self.data_dir / "MEMORY.md"
        self.heartbeat_path = self.data_dir / "HEARTBEAT.md"
        
        logger.info(f"Memory service initialized at {self.data_dir}")
    
    # -------------------------------------------------------------------------
    # Core Identity Files
    # -------------------------------------------------------------------------
    
    def get_soul(self) -> str:
        """Read SOUL.md - the agent's personality and identity."""
        return self._read_file(self.soul_path, "# Rin's Soul\n\nI am a helpful AI assistant.")
    
    def get_user_context(self) -> str:
        """Read USER.md - context about the user."""
        return self._read_file(self.user_path, "# About You\n\n(No user context defined yet)")
    
    def get_long_term_memory(self) -> str:
        """Read MEMORY.md - long-term facts and learnings."""
        return self._read_file(self.memory_path, "# Long-Term Memory\n\n(No memories yet)")
    
    def get_heartbeat_checklist(self) -> str:
        """Read HEARTBEAT.md - proactive monitoring items."""
        return self._read_file(self.heartbeat_path, "# Heartbeat Checklist\n\n(No items)")
    
    # -------------------------------------------------------------------------
    # Context Assembly
    # -------------------------------------------------------------------------
    
    def get_full_context(self, include_recent_days: int = 3) -> str:
        """
        Assemble full context for VLM prompts.
        
        Args:
            include_recent_days: Number of recent daily logs to include
            
        Returns:
            Combined context string for injection into prompts
        """
        sections = []
        
        # Soul (identity)
        soul = self.get_soul()
        if soul:
            sections.append(f"## My Identity\n\n{soul}")
        
        # User context
        user = self.get_user_context()
        if user and "(No user context" not in user:
            sections.append(f"## About My User\n\n{user}")
        
        # Long-term memory
        memory = self.get_long_term_memory()
        if memory and "(No memories" not in memory:
            sections.append(f"## What I Remember\n\n{memory}")
        
        # Recent daily logs
        recent = self.get_recent_logs(include_recent_days)
        if recent:
            sections.append(f"## Recent Conversations\n\n{recent}")
        
        return "\n\n---\n\n".join(sections) if sections else ""
    
    def get_compact_context(self) -> str:
        """
        Get a compact context suitable for token-limited prompts.
        Only includes essential identity and key memories.
        """
        soul = self.get_soul()
        
        # Extract just the core identity section
        lines = soul.split('\n')
        compact_lines = []
        in_core = False
        for line in lines:
            if '## Core Identity' in line:
                in_core = True
            elif line.startswith('## ') and in_core:
                break
            elif in_core:
                compact_lines.append(line)
        
        core_identity = '\n'.join(compact_lines).strip()
        
        return f"You are Rin. {core_identity}" if core_identity else "You are Rin, a helpful AI assistant."
    
    # -------------------------------------------------------------------------
    # Daily Logs
    # -------------------------------------------------------------------------
    
    def get_today_log_path(self) -> Path:
        """Get path to today's conversation log."""
        today = datetime.now().strftime("%Y-%m-%d")
        return self.memory_dir / f"{today}.md"
    
    def append_to_daily_log(self, entry: str, entry_type: str = "conversation"):
        """
        Append an entry to today's daily log.
        
        Args:
            entry: The content to log
            entry_type: Type of entry (conversation, task, system)
        """
        log_path = self.get_today_log_path()
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Create file with header if doesn't exist
        if not log_path.exists():
            today = datetime.now().strftime("%Y-%m-%d")
            header = f"# Daily Log: {today}\n\n"
            log_path.write_text(header, encoding='utf-8')
        
        # Append entry
        formatted_entry = f"\n### [{timestamp}] {entry_type.title()}\n\n{entry}\n"
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(formatted_entry)
        
        logger.debug(f"Logged {entry_type} entry to {log_path.name}")
    
    def log_conversation(self, user_input: str, agent_response: str, task_result: str = None):
        """Log a complete conversation exchange."""
        entry_parts = [
            f"**User**: {user_input}",
            f"**Rin**: {agent_response}"
        ]
        if task_result:
            entry_parts.append(f"**Result**: {task_result}")
        
        self.append_to_daily_log("\n\n".join(entry_parts), "conversation")
    
    def log_task(self, task: str, result: str, steps: int, duration: float):
        """Log a completed task execution."""
        entry = f"""**Task**: {task}
**Result**: {result}
**Steps**: {steps} | **Duration**: {duration:.1f}s"""
        self.append_to_daily_log(entry, "task")
    
    def get_recent_logs(self, days: int = 3) -> str:
        """
        Get combined content from recent daily logs.
        
        Args:
            days: Number of days to include
            
        Returns:
            Combined log content, most recent first
        """
        logs = []
        log_files = sorted(self.memory_dir.glob("*.md"), reverse=True)
        
        for log_file in log_files[:days]:
            try:
                content = log_file.read_text(encoding='utf-8')
                # Trim to last N entries to avoid context explosion
                entries = content.split('\n### ')
                if len(entries) > 10:
                    content = entries[0] + '\n### ' + '\n### '.join(entries[-10:])
                logs.append(content)
            except Exception as e:
                logger.warning(f"Failed to read log {log_file}: {e}")
        
        return "\n\n---\n\n".join(logs) if logs else ""
    
    # -------------------------------------------------------------------------
    # Memory Updates
    # -------------------------------------------------------------------------
    
    def add_to_memory(self, section: str, content: str):
        """
        Add a new item to MEMORY.md under the specified section.
        
        Args:
            section: Section header (e.g., "Facts About User")
            content: Content to add
        """
        memory = self._read_file(self.memory_path, "")
        timestamp = datetime.now().strftime("%Y-%m-%d")
        
        # Find section and append
        section_pattern = f"## {section}"
        if section_pattern in memory:
            # Insert after section header
            parts = memory.split(section_pattern)
            if len(parts) >= 2:
                # Find end of section (next ## or end of file)
                rest = parts[1]
                next_section = rest.find('\n## ')
                if next_section > 0:
                    insert_point = next_section
                else:
                    insert_point = len(rest)
                
                new_content = f"\n- [{timestamp}] {content}"
                parts[1] = rest[:insert_point] + new_content + rest[insert_point:]
                memory = section_pattern.join(parts)
        else:
            # Create new section
            memory += f"\n\n## {section}\n\n- [{timestamp}] {content}"
        
        # Update last modified
        memory = self._update_last_modified(memory)
        
        self._write_file(self.memory_path, memory)
        logger.info(f"Added to memory section '{section}': {content[:50]}...")
    
    def extract_and_save_learnings(self, conversation: str, llm_summary: str = None):
        """
        Extract learnings from a conversation and save to memory.
        
        If llm_summary is provided (from VLM), use it directly.
        Otherwise, use simple heuristic extraction.
        """
        if llm_summary:
            # VLM provided a summary - save it
            self.add_to_memory("Learned Preferences", llm_summary)
            return
        
        # Simple heuristic extraction (fallback)
        # Look for explicit preferences
        patterns = [
            (r"I prefer (.+)", "Learned Preferences"),
            (r"I always (.+)", "Learned Preferences"),
            (r"Remember that (.+)", "Facts About User"),
            (r"I'm working on (.+)", "Project Context"),
        ]
        
        for pattern, section in patterns:
            matches = re.findall(pattern, conversation, re.IGNORECASE)
            for match in matches:
                self.add_to_memory(section, match.strip())
    
    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------
    
    def _read_file(self, path: Path, default: str = "") -> str:
        """Safely read a file, returning default if not found."""
        try:
            if path.exists():
                return path.read_text(encoding='utf-8')
        except Exception as e:
            logger.warning(f"Failed to read {path}: {e}")
        return default
    
    def _write_file(self, path: Path, content: str):
        """Safely write to a file."""
        try:
            path.write_text(content, encoding='utf-8')
        except Exception as e:
            logger.error(f"Failed to write {path}: {e}")
    
    def _update_last_modified(self, content: str) -> str:
        """Update the 'Last updated' timestamp in content."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        pattern = r"\*Last updated:.*\*"
        replacement = f"*Last updated: {timestamp}*"
        
        if re.search(pattern, content):
            return re.sub(pattern, replacement, content)
        else:
            return content + f"\n\n---\n\n{replacement}"


# Singleton instance
_memory_service: Optional[MemoryService] = None


def get_memory_service(data_dir: Optional[str] = None) -> MemoryService:
    """Get or create the memory service singleton."""
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService(data_dir)
    return _memory_service


def init_memory_service(data_dir: Optional[str] = None) -> MemoryService:
    """Initialize the memory service. Call at startup."""
    global _memory_service
    _memory_service = MemoryService(data_dir)
    return _memory_service

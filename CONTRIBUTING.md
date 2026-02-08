# Contributing to Rin

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

1. **Clone the repo** and run the setup script:
   ```powershell
   git clone https://github.com/YOUR_USERNAME/Rin.git
   cd Rin
   .\setup.ps1
   ```

2. **Build llama.cpp** (for GPU inference):
   ```powershell
   .\scripts\build_llama_cpp.ps1
   ```

3. **Download models**:
   ```powershell
   .\scripts\download_models.ps1
   ```

4. **Run tests**:
   ```powershell
   python -m pytest tests/ -v
   ```

## Code Style

- Python: follow PEP 8, type hints encouraged
- Use `logging.getLogger("qwen3vl.<module>")` for logging
- Keep imports organized: stdlib → third-party → local

## Running Tests

```powershell
# All tests
python -m pytest tests/ -v

# Security tests only
python -m pytest tests/test_security.py -v
```

## Pull Requests

1. Fork the repo and create a feature branch
2. Make your changes with clear commit messages
3. Add/update tests for new functionality
4. Ensure all tests pass before submitting
5. Open a PR with a description of what changed and why

## Architecture Overview

- `main.py` — Entry point, VLM lifecycle management
- `rin_service.py` — Always-on gateway service (port 8000)
- `src/` — Core modules (orchestrator, capture, inference, actions, etc.)
- `OverlayApp/` — WPF desktop overlay (C#)
- `mobile/` — React Native mobile app

See `README.md` for the full architecture diagram.

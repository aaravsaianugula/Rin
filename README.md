<p align="center">
  <h1 align="center">Rin</h1>
  <p align="center">
    A local, privacy-first AI assistant that controls your computer using vision.
    <br />
    <em>No cloud APIs. No data leaves your machine. 100% local.</em>
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/platform-Windows-lightgrey?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/GPU-Vulkan-red?style=flat-square" alt="GPU">
</p>

---

## What is Rin?

Rin is a **local AI agent** that sees your screen and controls your computer through natural language. Tell it what to do — it takes a screenshot, understands the UI, and performs clicks, typing, scrolling, and keyboard shortcuts to complete your task.

**Key Features:**
- 🖼️ **Vision-based UI understanding** — Sees and analyzes your screen in real-time
- 🎯 **Precise computer control** — Clicks, types, scrolls, drags, keyboard shortcuts
- 🔒 **Fully local** — Runs on your hardware, no data sent to the cloud
- 🗣️ **Voice control** — Optional wake-word activation ("Hey Rin")
- 💬 **Discord integration** — Send commands remotely via Discord
- 📱 **Mobile app** — Control and monitor Rin from your Android phone
- 🖥️ **Desktop overlay** — Always-on-top status indicator (WPF)
- 🧠 **Memory & personality** — Customizable assistant behavior and memory

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **GPU** | 6GB VRAM (Vulkan-compatible) | 8GB+ VRAM |
| **RAM** | 8GB | 16GB+ |
| **Storage** | 5GB free | 10GB free |
| **OS** | Windows 10 | Windows 11 |

> [!NOTE]
> Rin uses **Vulkan** for GPU acceleration. This works with both NVIDIA and AMD GPUs.
> AMD RDNA2 users (e.g., RX 6600 XT): use Vulkan, **not** ROCm.

## Quick Start

Open PowerShell and run:

```powershell
git clone <repo-url> Rin; cd Rin; powershell -ExecutionPolicy Bypass -File setup.ps1
```

That's it. The setup wizard handles **everything**:
- Python environment & dependencies
- AI model download (Qwen3-VL / Gemma 3)
- llama.cpp build with Vulkan GPU acceleration
- Desktop overlay & Start Menu shortcuts
- Background service registration
- API key generation

Once setup completes, Rin starts automatically. The API server runs on `http://localhost:8000`.

<details>
<summary>Manual setup (without wizard)</summary>

```powershell
# 1. Python environment
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Vulkan SDK: https://vulkan.lunarg.com/sdk/home (v1.3.283+)

# 3. Build llama.cpp
.\scripts\build_llama_cpp.ps1

# 4. Download models
.\scripts\download_models.ps1

# 5. Register service (admin PowerShell)
.\scripts\Install-RinService.ps1
```
</details>

## Usage

### CLI Mode
```powershell
# Interactive mode
python main.py --interactive

# Single command
python main.py --command "Open Chrome and search for weather"
```

### Desktop Overlay
The WPF overlay app provides an always-on-top status widget:
```powershell
# Build the overlay
.\scripts\Install-Rin.ps1
```

### Mobile App (Android)
See [Mobile App Setup](#mobile-app) below.

## Configuration

All settings are in `config/settings.yaml`:

```yaml
# AI Model
vlm:
  base_url: "http://127.0.0.1:8080"
  timeout: 90

# Safety
safety:
  confidence_threshold: 0.8   # Min confidence to execute actions
  max_iterations: 20          # Max attempts per task
  action_delay: 0.1           # Delay between actions (seconds)
  failsafe_enabled: true      # Mouse-to-corner abort

# Voice (optional)
voice:
  enabled: false               # Set to true to enable wake word

# Discord (optional)
discord:
  allowed_users: []            # Add your Discord user IDs
  require_approval: true
```

### Environment Variables (Optional)

Copy `.env.example` to `.env` and fill in your values:
```powershell
Copy-Item .env.example .env
```

| Variable | Description |
|----------|-------------|
| `DISCORD_BOT_TOKEN` | Discord bot token for remote commands |
| `PORCUPINE_ACCESS_KEY` | Picovoice key for wake-word detection |
| `RIN_HOST` | Server bind address (default: `0.0.0.0`) |
| `RIN_PORT` | Server port (default: `8000`) |

## Architecture

```
User Command (text / voice / Discord / mobile)
     ↓
┌─────────────────┐
│  Orchestrator    │ ← Main control loop
└─────────────────┘
     ↓
┌─────────────────┐
│ Screen Capture   │ ← mss library (<50ms)
└─────────────────┘
     ↓
┌─────────────────┐
│  VLM Analysis    │ ← Qwen3-VL via llama.cpp server
└─────────────────┘
     ↓
┌─────────────────┐
│  Coordinate      │ ← [0,1000] → screen pixels
│  Conversion      │
└─────────────────┘
     ↓
┌─────────────────┐
│ Action Execution │ ← PyAutoGUI
└─────────────────┘
     ↓
   Verification
```

## Project Structure

```
Rin/
├── main.py              # Entry point (interactive / single command)
├── rin_service.py        # Background service with API server
├── setup.ps1             # One-click setup script
├── requirements.txt      # Python dependencies
│
├── src/                  # Core modules
│   ├── orchestrator.py   # Main agent control loop
│   ├── capture.py        # Screenshot capture
│   ├── inference.py      # VLM client (llama.cpp)
│   ├── actions.py        # Computer control (click, type, scroll)
│   ├── coordinates.py    # Coordinate mapping
│   ├── server.py         # FastAPI backend server
│   ├── security.py       # Auth, rate limiting, CORS
│   ├── voice_service.py  # Wake word + speech-to-text
│   ├── discord_service.py# Discord bot integration
│   ├── memory_service.py # Persistent memory
│   └── prompts.py        # System prompts
│
├── config/
│   └── settings.yaml     # All configuration
│
├── models/               # GGUF model files (download separately)
├── scripts/              # Setup & utility scripts
├── tests/                # Pytest test suite
├── data/                 # Personality & user profile templates
│
├── OverlayApp/           # WPF desktop overlay (C#)
└── mobile/               # React Native mobile app
```

## Safety Features

| Feature | Description |
|---------|-------------|
| **Failsafe** | Move mouse to any screen corner to abort |
| **Confidence threshold** | Actions below 80% confidence are skipped |
| **Coordinate validation** | Out-of-bounds coordinates are clamped |
| **Iteration limit** | Stops after 20 attempts |
| **API key auth** | All remote endpoints require Bearer token |
| **Rate limiting** | 120 req/min normal, 10 req/min for lifecycle |
| **Body size limit** | 1MB max request body |

## Mobile App

The Rin mobile app lets you control and monitor the agent from your Android phone.

### Connecting to Your PC

#### Option A: Tailscale (Recommended)

[Tailscale](https://tailscale.com) creates a secure private network between your devices. Works from **anywhere** — home, office, or cellular data.

1. Install Tailscale on [your PC](https://tailscale.com/download/windows) and your phone (App Store / Google Play)
2. Sign in on both devices with the same account
3. Open Tailscale on your PC → note your machine's IP (e.g., `100.x.x.x`)
4. In the Rin app → **Settings** → **Server Host** → enter the Tailscale IP
5. **Port**: `8000` | **API Key**: from `config/secrets/api_key.txt`

#### Option B: Same Wi-Fi

If both devices are on the same network:

1. Find your PC's IP: `ipconfig` in PowerShell → look for "IPv4 Address"
2. In the Rin app → **Settings** → enter that IP
3. You may need to allow port 8000 through Windows Firewall:
   ```powershell
   # Run in Admin PowerShell
   New-NetFirewallRule -DisplayName 'Rin Service' -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
   ```

### Running the App

**Development mode** (with Expo Go):
```bash
cd mobile
npm install
npx expo start --lan
```
Scan the QR code with the Expo Go app on your phone.

**Build standalone APK:**
```bash
cd mobile
npx expo prebuild
cd android
.\gradlew.bat assembleRelease
```
APK will be at `android/app/build/outputs/apk/release/`. Transfer to your phone and install.

## Running Tests

```powershell
python -m pytest tests/ -v
```

## Troubleshooting

<details>
<summary><strong>VLM server not available</strong></summary>

- Ensure llama-server is running on port 8080
- Check: `curl http://127.0.0.1:8080/health`
- Verify firewall isn't blocking the port
</details>

<details>
<summary><strong>GPU not detected</strong></summary>

- Verify Vulkan SDK is installed: run `vulkaninfo`
- Update your GPU drivers
- AMD RDNA2: use Vulkan, not ROCm
</details>

<details>
<summary><strong>Actions click the wrong location</strong></summary>

- Run the calibration test: `python scripts/click_calibration.py --runs 5`
- Check coordinate offsets in `config/settings.yaml`
- Verify screen resolution hasn't changed
</details>

<details>
<summary><strong>Mobile app can't connect</strong></summary>

- **Using Tailscale?** Ensure both devices are signed in and connected
- **Same Wi-Fi?** Verify both devices are on the same network
- Check Settings in the app (Server Host, Port, API Key)
- Verify the backend is running: `curl http://YOUR_IP:8000/health`
- Check Windows Firewall allows port 8000:
  ```powershell
  New-NetFirewallRule -DisplayName 'Rin Service' -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
  ```
</details>

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes and add tests
4. Run the test suite: `python -m pytest tests/ -v`
5. Submit a pull request

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

- [Qwen3-VL](https://huggingface.co/Qwen) — Vision-language model by Alibaba
- [llama.cpp](https://github.com/ggerganov/llama.cpp) — Efficient C++ inference engine
- [PyAutoGUI](https://pyautogui.readthedocs.io/) — Cross-platform GUI automation
- [Picovoice Porcupine](https://picovoice.ai/) — Wake-word detection engine

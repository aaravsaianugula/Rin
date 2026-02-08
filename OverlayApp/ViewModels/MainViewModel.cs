using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using OverlayApp.Services;

namespace OverlayApp.ViewModels
{
    public partial class MainViewModel : ObservableObject
    {
        private readonly AgentStateService _agentStateService;
        private readonly OverlayService _overlayService;
        private MainOverlayWindow? _overlayWindow;

        public AgentStateService AgentStateService => _agentStateService;
        
        [ObservableProperty]
        private bool _isOverlayEnabled = true;

        [ObservableProperty]
        private bool _isWakeWordEnabled = true;

        [ObservableProperty]
        private string _backendStatus = "OFFLINE";

        [ObservableProperty]
        private string _backendStatusColor = "#FF4141";

        [ObservableProperty]
        private string _vlmStatus = "OFFLINE";

        [ObservableProperty]
        private string _vlmStatusColor = "#FFB3B3"; // Pastel Red

        [ObservableProperty]
        private string _currentDetails = "Ready to assist";

        [ObservableProperty]
        private string _currentAction = "Idle";

        [ObservableProperty]
        private string _currentView = "Home"; // Home, Intelligence, Workflows, Memory, System, Settings

        [ObservableProperty]
        private string _commandText = "";

        [ObservableProperty]
        private System.Collections.ObjectModel.ObservableCollection<string> _consoleLogs = new();

        // Config properties from backend
        [ObservableProperty]
        private int _configBackendPort = 8000;

        [ObservableProperty]
        private int _configVlmPort = 8080;

        [ObservableProperty]
        private string _configVlmModel = "Loading...";

        [ObservableProperty]
        private int _configGpuLayers = 0;

        [ObservableProperty]
        private int _configContextSize = 8192;

        [ObservableProperty]
        private int _configMaxIterations = 25;

        [ObservableProperty]
        private double _configActionDelay = 0.1;

        [ObservableProperty]
        private bool _configFailsafeEnabled = true;

        // Model selection
        [ObservableProperty]
        private string _selectedModelId = "qwen3-vl-4b";

        public bool IsQwen3Selected
        {
            get => SelectedModelId == "qwen3-vl-4b";
            set { if (value) SelectedModelId = "qwen3-vl-4b"; }
        }

        public bool IsGemma3Selected
        {
            get => SelectedModelId == "gemma-3-4b";
            set { if (value) SelectedModelId = "gemma-3-4b"; }
        }

        partial void OnSelectedModelIdChanged(string value)
        {
            OnPropertyChanged(nameof(IsQwen3Selected));
            OnPropertyChanged(nameof(IsGemma3Selected));
            
            // Trigger model switch when selection changes
            _ = SwitchModelAsync(value);
        }

        partial void OnIsWakeWordEnabledChanged(bool value)
        {
            _ = SetWakeWordEnabledAsync(value);
        }

        private async Task SetWakeWordEnabledAsync(bool enabled)
        {
            try
            {
                using var client = new System.Net.Http.HttpClient { BaseAddress = new Uri("http://127.0.0.1:8000/") };
                var endpoint = enabled ? "wake-word/enable" : "wake-word/disable";
                await client.PostAsync(endpoint, null);
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Failed to toggle wake word: {ex.Message}");
            }
        }

        private async Task SwitchModelAsync(string modelId)
        {
            if (string.IsNullOrEmpty(modelId) || _isSwitchingModel) return;
            _isSwitchingModel = true;
            
            CurrentAction = "Switching...";
            CurrentDetails = $"Switching to {modelId}...";
            
            try
            {
                using var client = new System.Net.Http.HttpClient { BaseAddress = new Uri("http://127.0.0.1:8000/") };
                var content = new System.Net.Http.StringContent(
                    System.Text.Json.JsonSerializer.Serialize(new { model_id = modelId }),
                    System.Text.Encoding.UTF8,
                    "application/json"
                );
                
                var response = await client.PostAsync("model/switch", content);
                var json = await response.Content.ReadAsStringAsync();
                var result = System.Text.Json.JsonSerializer.Deserialize<Dictionary<string, System.Text.Json.JsonElement>>(json);
                
                if (result != null && result.TryGetValue("status", out var status) && status.GetString() == "ok")
                {
                    CurrentAction = "Ready";
                    CurrentDetails = $"Switched to {result.GetValueOrDefault("display_name").GetString() ?? modelId}";
                    
                    // Refresh config to show updated model info
                    await FetchConfigAsync();
                }
                else
                {
                    var errorMsg = result?.GetValueOrDefault("message").GetString() ?? "Unknown error";
                    CurrentAction = "Error";
                    CurrentDetails = $"Failed: {errorMsg}";
                }
            }
            catch (Exception ex)
            {
                CurrentAction = "Error";
                CurrentDetails = $"Failed to switch: {ex.Message}";
            }
            finally
            {
                _isSwitchingModel = false;
            }
        }

        private bool _isSwitchingModel = false;

        private bool _isStarting = true;
        private int _startRetryCount = 0;
        public MainViewModel(OverlayService overlayService)
        {
            _overlayService = overlayService;
            _agentStateService = new AgentStateService();
            
            // Initial state for graceful boot
            BackendStatus = "INITIALIZING";
            BackendStatusColor = "#FFBD2E"; // Orange/Yellow
            CurrentDetails = "Launching Rin services...";
            CurrentAction = "Starting";

            _agentStateService.StateChanged += OnAgentStateChanged;

            // Auto-launch backend if not already running
            StartBackend();
            
            // Fetch config after a small delay to allow backend to start
            Task.Run(async () => {
                await Task.Delay(2000);
                await FetchConfigAsync();
                await FetchActiveModelAsync();
            });
        }

        /// <summary>
        /// Call this after the MainWindow is fully initialized to show the overlay.
        /// Must be called from the UI thread.
        /// </summary>
        public void InitializeOverlay()
        {
            if (IsOverlayEnabled)
            {
                ShowOverlay();
            }
        }

        private async Task FetchConfigAsync()
        {
            try
            {
                using var client = new System.Net.Http.HttpClient { BaseAddress = new Uri("http://127.0.0.1:8000/") };
                var response = await client.GetAsync("config");
                if (response.IsSuccessStatusCode)
                {
                    var json = await response.Content.ReadAsStringAsync();
                    var config = System.Text.Json.JsonSerializer.Deserialize<Dictionary<string, System.Text.Json.JsonElement>>(json);
                    if (config != null)
                    {
                        Application.Current.Dispatcher.Invoke(() =>
                        {
                            if (config.TryGetValue("backend_port", out var bp)) ConfigBackendPort = bp.GetInt32();
                            if (config.TryGetValue("vlm_port", out var vp)) ConfigVlmPort = vp.GetInt32();
                            if (config.TryGetValue("vlm_model", out var vm)) ConfigVlmModel = vm.GetString() ?? "Unknown";
                            if (config.TryGetValue("gpu_layers", out var gl)) ConfigGpuLayers = gl.GetInt32();
                            if (config.TryGetValue("context_size", out var cs)) ConfigContextSize = cs.GetInt32();
                            if (config.TryGetValue("max_iterations", out var mi)) ConfigMaxIterations = mi.GetInt32();
                            if (config.TryGetValue("action_delay", out var ad)) ConfigActionDelay = ad.GetDouble();
                            if (config.TryGetValue("failsafe_enabled", out var fe)) ConfigFailsafeEnabled = fe.GetBoolean();
                        });
                    }
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Failed to fetch config: {ex.Message}");
            }
        }

        private void StartBackend()
        {
            try
            {
                // Aggressive Cleanup of old instances
                string[] killList = { "python", "llama-server" };
                foreach (var name in killList)
                {
                    try
                    {
                        var processes = System.Diagnostics.Process.GetProcessesByName(name);
                        foreach (var p in processes)
                        {
                            try { p.Kill(); } catch { }
                        }
                    }
                    catch { }
                }

                string baseDir = System.AppDomain.CurrentDomain.BaseDirectory;
                string mainPyPath = "";
                
                // Search up for main.py
                var dir = new System.IO.DirectoryInfo(baseDir);
                for (int i = 0; i < 6; i++)
                {
                    if (System.IO.File.Exists(System.IO.Path.Combine(dir.FullName, "main.py")))
                    {
                        mainPyPath = dir.FullName;
                        break;
                    }
                    dir = dir.Parent;
                    if (dir == null) break;
                }

                if (string.IsNullOrEmpty(mainPyPath))
                {
                    mainPyPath = System.IO.Directory.GetCurrentDirectory(); // Fallback
                }

                var startInfo = new System.Diagnostics.ProcessStartInfo
                {
                    FileName = "python",
                    Arguments = "main.py --interactive",
                    WorkingDirectory = mainPyPath,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = false,
                    RedirectStandardError = false
                };

                System.Diagnostics.Process.Start(startInfo);
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Failed to start backend: {ex.Message}");
            }
        }

        private void OnAgentStateChanged(object? sender, AgentState state)
        {
            Application.Current.Dispatcher.Invoke(() =>
            {
                if (state.Connection == ConnectionStatus.Connected)
                {
                    _isStarting = false;
                    _startRetryCount = 0;
                    BackendStatus = "ONLINE";
                    BackendStatusColor = "#95E8D7"; // Pastel Mint Green
                    
                    VlmStatus = state.VlmStatus ?? "OFFLINE";
                    if (VlmStatus == "ONLINE") VlmStatusColor = "#95E8D7"; // Mint
                    else if (VlmStatus == "STARTING") VlmStatusColor = "#FFBD2E"; // Orange
                    else if (VlmStatus == "STANDBY") VlmStatusColor = "#BBBBBB"; // Gray
                    else VlmStatusColor = "#FFB3B3"; // Red

                    CurrentDetails =  state.Details ?? "System operational";
                    CurrentAction = state.CurrentAction ?? "Idle";

                    if (!string.IsNullOrEmpty(state.LastThought) && (ConsoleLogs.Count == 0 || ConsoleLogs.Last() != state.LastThought))
                    {
                        ConsoleLogs.Add($"[{System.DateTime.Now:HH:mm:ss}] {state.LastThought}");
                        if (ConsoleLogs.Count > 100) ConsoleLogs.RemoveAt(0);
                    }
                }
                else
                {
                    if (_isStarting && _startRetryCount < 10) // wait up to 5s for boot
                    {
                        _startRetryCount++;
                        BackendStatus = "INITIALIZING";
                        BackendStatusColor = "#FFBD2E";
                        CurrentDetails = "Connecting to agent...";
                        CurrentAction = "Linking";
                    }
                    else
                    {
                        _isStarting = false;
                        BackendStatus = "OFFLINE";
                        BackendStatusColor = "#FFB3B3"; // Pastel Red
                        VlmStatus = "OFFLINE";
                        VlmStatusColor = "#FFB3B3";
                        CurrentDetails = "Backend disconnected";
                        CurrentAction = "Disconnected";
                    }
                }
            });
        }

        partial void OnIsOverlayEnabledChanged(bool value)
        {
            if (value) ShowOverlay();
            else HideOverlay();
        }

        private void ShowOverlay()
        {
            if (_overlayWindow == null)
            {
                _overlayWindow = new MainOverlayWindow(_overlayService, _agentStateService);
            }
            _overlayWindow.Show();
            _overlayService.IsVisible = true;
        }

        private void HideOverlay()
        {
            _overlayWindow?.Hide();
            _overlayService.IsVisible = false;
        }

        [RelayCommand]
        public void NavTo(string view)
        {
            CurrentView = view;
        }

        [RelayCommand]
        public async Task SubmitTask()
        {
            if (string.IsNullOrWhiteSpace(CommandText)) return;
            string command = CommandText;
            CommandText = ""; // Clear input immediately for responsiveness
            
            CurrentAction = "Requesting...";
            CurrentDetails = $"Sending task: {command}";
            
            await _agentStateService.SubmitTaskAsync(command);
        }

        [RelayCommand]
        public void RestartServices()
        {
            try
            {
                // Kill python processes running main.py and llama-server
                var killList = new[] { "python", "llama-server" };
                foreach (var name in killList)
                {
                    var processes = System.Diagnostics.Process.GetProcessesByName(name);
                    foreach (var p in processes)
                    {
                        try { p.Kill(); } catch { }
                    }
                }

                System.Threading.Thread.Sleep(800);
                StartBackend();
                
                CurrentAction = "Ready";
                CurrentDetails = "Services restarted.";
                MessageBox.Show("Services restarted.", "Rin Control", MessageBoxButton.OK, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Failed to restart: {ex.Message}", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        [RelayCommand]
        public async Task SelectModel(string modelId)
        {
            if (string.IsNullOrEmpty(modelId) || modelId == SelectedModelId) return;
            
            CurrentAction = "Switching...";
            CurrentDetails = $"Switching to {modelId}...";
            
            try
            {
                using var client = new System.Net.Http.HttpClient { BaseAddress = new Uri("http://127.0.0.1:8000/") };
                var content = new System.Net.Http.StringContent(
                    System.Text.Json.JsonSerializer.Serialize(new { model_id = modelId }),
                    System.Text.Encoding.UTF8,
                    "application/json"
                );
                
                var response = await client.PostAsync("model/switch", content);
                var json = await response.Content.ReadAsStringAsync();
                var result = System.Text.Json.JsonSerializer.Deserialize<Dictionary<string, System.Text.Json.JsonElement>>(json);
                
                if (result != null && result.TryGetValue("status", out var status) && status.GetString() == "ok")
                {
                    SelectedModelId = modelId;
                    CurrentAction = "Ready";
                    CurrentDetails = $"Switched to {result.GetValueOrDefault("display_name").GetString() ?? modelId}";
                }
                else
                {
                    var errorMsg = result?.GetValueOrDefault("message").GetString() ?? "Unknown error";
                    CurrentAction = "Error";
                    CurrentDetails = $"Failed: {errorMsg}";
                }
            }
            catch (Exception ex)
            {
                CurrentAction = "Error";
                CurrentDetails = $"Failed to switch: {ex.Message}";
            }
        }

        private async Task FetchActiveModelAsync()
        {
            try
            {
                using var client = new System.Net.Http.HttpClient { BaseAddress = new Uri("http://127.0.0.1:8000/") };
                var response = await client.GetAsync("model/active");
                if (response.IsSuccessStatusCode)
                {
                    var json = await response.Content.ReadAsStringAsync();
                    var result = System.Text.Json.JsonSerializer.Deserialize<Dictionary<string, System.Text.Json.JsonElement>>(json);
                    if (result != null && result.TryGetValue("model_id", out var modelId))
                    {
                        Application.Current.Dispatcher.Invoke(() =>
                        {
                            SelectedModelId = modelId.GetString() ?? "qwen3-vl-4b";
                        });
                    }
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Failed to fetch active model: {ex.Message}");
            }
        }
    }
}


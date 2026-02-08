using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using OverlayApp.Services;
using OverlayApp.Widgets;
using System;
using System.Collections.ObjectModel;
using System.Linq;
using System.Windows;

namespace OverlayApp.ViewModels
{
    public partial class MainOverlayViewModel : ObservableObject
    {
        private readonly OverlayService _overlayService;
        private readonly AgentStateService _agentStateService;
        private readonly System.Windows.Threading.DispatcherTimer _typewriterTimer;
        private string _targetText = "";
        private int _charIndex = 0;
        private string _previousVoiceState = "idle";
        private string _previousStatus = "idle";

        [ObservableProperty]
        private AgentState _agentState;

        [ObservableProperty]
        private string _typewriterText = "";

        [ObservableProperty]
        private bool _hasAction;

        [ObservableProperty]
        private string _userQuery = "";

        [ObservableProperty]
        private string _systemStats = "CPU: 12% | RAM: 4.2GB";

        [ObservableProperty]
        private bool _hasContent;

        [ObservableProperty]
        private string _backendStatus = "OFFLINE";

        [ObservableProperty]
        private string _backendStatusColor = "#B57A7A"; // Dusty rose (offline)

        [ObservableProperty]
        private string _vlmStatus = "OFFLINE";

        [ObservableProperty]
        private string _vlmStatusColor = "#B57A7A"; // Dusty rose (offline)

        [ObservableProperty]
        private string _agentStateGlowColor = "#7A8B99"; // Steel blue-gray (idle)

        [ObservableProperty]
        private bool _wakeWordEnabled = true;

        public MainOverlayViewModel(OverlayService overlayService, AgentStateService agentStateService)
        {
            _overlayService = overlayService;
            _agentStateService = agentStateService;
            
            _typewriterTimer = new System.Windows.Threading.DispatcherTimer();
            _typewriterTimer.Interval = TimeSpan.FromMilliseconds(25); // Sleek typewriter speed
            _typewriterTimer.Tick += OnTypewriterTick;

            // Initial State (Sync)
            _agentState = _agentStateService.CurrentState;
            OnStateChanged(this, _agentState);
            InitializeWidgets();
            UpdateHasContent();

            // Subscribe to updates
            _agentStateService.StateChanged += OnStateChanged;
            
            // Forward visibility changes
            _overlayService.PropertyChanged += (s, e) =>
            {
                if (e.PropertyName == nameof(OverlayService.IsVisible))
                {
                    OnPropertyChanged(nameof(IsVisible));
                }
            };
        }

        private void OnTypewriterTick(object? sender, EventArgs e)
        {
            if (_charIndex < _targetText.Length)
            {
                TypewriterText += _targetText[_charIndex];
                _charIndex++;
            }
            else
            {
                _typewriterTimer.Stop();
            }
        }

        [ObservableProperty]
        private bool _isInputActive = true;

        private void OnStateChanged(object? sender, AgentState newState)
        {
            Application.Current.Dispatcher.Invoke(() =>
            {
                AgentState = newState;
                HasAction = !string.IsNullOrEmpty(newState.CurrentAction);
                UpdateHasContent();

                // Adaptive Input Bar: Only show when not busy
                IsInputActive = newState.Status == "idle" || 
                                newState.Status == "COMPLETE" || 
                                newState.Status == "ERROR" ||
                                string.IsNullOrEmpty(newState.Status) ||
                                newState.VoiceState == "listening"; // Allow input during voice

                // Auto-show command bar when voice becomes active
                if (newState.VoiceState == "listening" && _previousVoiceState != "listening")
                {
                    Console.WriteLine($"[VM] Voice LISTENING started - showing overlay and command bar");
                    // Wake word detected - show the overlay and command bar
                    if (!_overlayService.IsVisible)
                    {
                        _overlayService.ToggleVisibility();
                    }
                    // Make sure command bar is showing
                    if (!Widgets.OfType<CommandBarWidget>().Any())
                    {
                        ToggleCommandBar();
                    }
                    // Add voice aura effect
                    if (!Widgets.OfType<VoiceAuraWidget>().Any())
                    {
                        Console.WriteLine($"[VM] Adding VoiceAuraWidget");
                        Widgets.Insert(0, new VoiceAuraWidget { DataContext = this });
                    }
                }

                // Auto-submit when voice transcription finishes
                if (newState.VoiceState == "processing" && _previousVoiceState == "listening")
                {
                    Console.WriteLine($"[VM] Voice PROCESSING - auto-submitting: '{UserQuery}'");
                    // Voice input finalized - submit the command
                    if (!string.IsNullOrWhiteSpace(UserQuery) && !UserQuery.StartsWith("🎤"))
                    {
                        _ = SubmitAsync();
                    }
                    // Remove voice aura
                    var aura = Widgets.OfType<VoiceAuraWidget>().FirstOrDefault();
                    if (aura != null) Widgets.Remove(aura);
                }

                // Remove voice aura when going idle
                if (newState.VoiceState == "idle" && _previousVoiceState != "idle")
                {
                    var aura = Widgets.OfType<VoiceAuraWidget>().FirstOrDefault();
                    if (aura != null) Widgets.Remove(aura);
                }

                _previousVoiceState = newState.VoiceState;

                // Sync voice partial to input bar (update whenever we have real text, not placeholder)
                if (!string.IsNullOrEmpty(newState.VoicePartial) && 
                    !newState.VoicePartial.StartsWith("🎤"))  // Filter out "🎤 Listening..." placeholder
                {
                    UserQuery = newState.VoicePartial;
                }

                // Only hide during CAPTURING so agent doesn't see the overlay in screenshots
                // Keep visible during VERIFYING so user sees the animation
                if (newState.Status == "CAPTURING")
                {
                    if (_overlayService.IsVisible) _overlayService.ToggleVisibility();
                }
                // Re-show overlay when not capturing anymore
                else if (_previousStatus == "CAPTURING" && newState.Status != "CAPTURING")
                {
                    if (!_overlayService.IsVisible) _overlayService.ToggleVisibility();
                }

                // Show/hide working frame border based on agent activity
                bool isWorking = newState.Status == "loading" || 
                                newState.Status == "THINKING" || 
                                newState.Status == "ACTING" ||
                                newState.Status == "EXECUTING" ||  // Added EXECUTING!
                                newState.Status == "VERIFYING" ||
                                newState.Status == "CAPTURING";
                
                var workingFrame = Widgets.OfType<WorkingFrameWidget>().FirstOrDefault();
                
                if (isWorking && workingFrame == null)
                {
                    Console.WriteLine("[VM] Agent WORKING - showing frame border");
                    Widgets.Insert(0, new WorkingFrameWidget { DataContext = this });
                }
                else if (!isWorking && workingFrame != null)
                {
                    Console.WriteLine("[VM] Agent IDLE - hiding frame border");
                    Widgets.Remove(workingFrame);
                }

                if (newState.Status == "COMPLETE" && _previousStatus != "COMPLETE")
                {
                    // Announce completion!
                    TypewriterText = "✓ Task Complete!";
                    Console.WriteLine("[VM] Task COMPLETE - showing success message");
                    _ = ResetAfterDelayAsync();
                }
                else if (newState.Status == "ERROR" && _previousStatus != "ERROR")
                {
                    TypewriterText = "✗ Task encountered an error";
                    Console.WriteLine("[VM] Task ERROR");
                    _ = ResetAfterDelayAsync();
                }

                _previousStatus = newState.Status;

                // Handle Typewriter
                string newThought = newState.LastThought ?? "";
                if (newThought != _targetText)
                {
                    _targetText = newThought;
                    _charIndex = 0;
                    TypewriterText = ""; // Reset for new text
                    _typewriterTimer.Start();
                }
                
                // Update Status details
                bool isOnline = newState.Connection == ConnectionStatus.Connected;
                BackendStatus = isOnline ? "ONLINE" : "OFFLINE";
                BackendStatusColor = isOnline ? "#7BA58B" : "#B57A7A"; // Sage green / Dusty rose

                VlmStatus = newState.VlmStatus ?? "OFFLINE";
                if (VlmStatus == "ONLINE") VlmStatusColor = "#7BA58B";      // Sage green
                else if (VlmStatus == "STARTING") VlmStatusColor = "#D4A574"; // Warm amber
                else if (VlmStatus == "STANDBY") VlmStatusColor = "#8A8A8A";  // Neutral gray
                else VlmStatusColor = "#B57A7A";                              // Dusty rose

                // Update ambient glow based on agent activity state (soft, professional palette)
                AgentStateGlowColor = newState.Status switch
                {
                    "loading" or "THINKING" => "#E8DCC8",   // Warm ivory (working)
                    "EXECUTING" => "#E8DCC8",               // Warm ivory (working)
                    "CAPTURING" or "VERIFYING" => "#A8C5D9", // Soft blue (listening)
                    "COMPLETE" => "#9BB5A0",                // Sage green (success)
                    "ERROR" => "#C9A8A8",                   // Muted rose (error)
                    _ => "#A8C5D9"                          // Soft blue (idle)
                };

                // Mock Stat Update (Randomize slightly for liveness feel)
                var rnd = new Random();
                SystemStats = $"CPU: {rnd.Next(5, 25)}% | RAM: {rnd.Next(4, 8)}.2GB";
            });
        }

        private async Task ResetAfterDelayAsync()
        {
            await Task.Delay(5000); // Wait 5 seconds so user can see completion
            
            // Only reset if we are still in COMPLETE/ERROR state
            if (AgentState.Status == "COMPLETE" || AgentState.Status == "ERROR")
            {
                Application.Current.Dispatcher.Invoke(() =>
                {
                    TypewriterText = "";
                    _targetText = "";
                    AgentState.LastThought = "";
                    AgentState.CurrentAction = "";
                    AgentState.Status = "idle";
                    IsInputActive = true;
                    UpdateHasContent();
                    
                    // Auto-collapse command bar after task completes
                    // User can click the orb again to start a new task
                    Collapse();
                });
            }
        }

        private void UpdateHasContent()
        {
             // Show content area if we have a thought, status is not idle/waiting, or we have an action
             HasContent = !string.IsNullOrEmpty(AgentState.LastThought) && 
                          AgentState.LastThought != "Waiting for connection..." &&
                          AgentState.LastThought != "Waiting for input..." || 
                          HasAction;
                          
        }

        [RelayCommand]
        public async Task SubmitAsync()
        {
            if (string.IsNullOrWhiteSpace(UserQuery)) return;

            string command = UserQuery;
            UserQuery = ""; // Clear input for responsiveness

            // Immediate feedback
            AgentState.Status = "loading";
            AgentState.CurrentAction = "Queuing task...";
            AgentState.LastThought = $"Task received: {command}";
            
            // Force UI update
            IsInputActive = false;
            UpdateHasContent();
            OnPropertyChanged(nameof(AgentState));
            
            await _agentStateService.SubmitTaskAsync(command);
        }

        [RelayCommand]
        public async Task StopAsync()
        {
            await _agentStateService.StopTaskAsync();
            
            // Immediately restore input bar and clear state
            IsInputActive = true;
            AgentState = new AgentState 
            { 
                Status = "idle", 
                LastThought = "", 
                CurrentAction = "" 
            };
            UpdateHasContent();
        }

        [RelayCommand]
        public async Task ToggleWakeWordAsync()
        {
            if (WakeWordEnabled)
            {
                await _agentStateService.DisableWakeWordAsync();
                WakeWordEnabled = false;
            }
            else
            {
                await _agentStateService.EnableWakeWordAsync();
                WakeWordEnabled = true;
            }
            Console.WriteLine($"[VM] Wake word toggled: {(WakeWordEnabled ? "ENABLED" : "DISABLED")}");
        }

        public bool IsVisible => _overlayService.IsVisible;
        public ObservableCollection<object> Widgets => _overlayService.Widgets;

        [RelayCommand]
        public void Expand()
        {
            // If command bar is not present, add it. If it is, maybe toggle? 
            // User said "click on it then the searchbar... shoudl show up".
            // If they click again "just let me click the orb... again" to minimize.
            
            ToggleCommandBar();
        }

        private void ToggleCommandBar()
        {
            var existingBar = _overlayService.Widgets.FirstOrDefault(w => w is CommandBarWidget);
            if (existingBar != null)
            {
                // Remove command bar and voice aura
                _overlayService.RemoveWidget(existingBar);
                var aura = _overlayService.Widgets.FirstOrDefault(w => w is VoiceAuraWidget);
                if (aura != null) _overlayService.RemoveWidget(aura);
            }
            else
            {
                // Add voice aura behind command bar, then command bar
                _overlayService.AddWidget(new VoiceAuraWidget { DataContext = this });
                _overlayService.AddWidget(new CommandBarWidget { DataContext = this });
            }
        }

        private void ShowLaunchOrb()
        {
            // Ensure Orb is strictly added once
            if (!_overlayService.Widgets.Any(w => w is LaunchOrbWidget))
            {
                _overlayService.AddWidget(new LaunchOrbWidget { DataContext = this });
            }
        }

        // Initialize Call
        private void InitializeWidgets()
        {
            ShowLaunchOrb();
            // Start without command bar
        }

        [RelayCommand]
        public void Collapse()
        {
            // Explicitly remove command bar and voice aura
            var bar = _overlayService.Widgets.FirstOrDefault(w => w is CommandBarWidget);
            if (bar != null) _overlayService.RemoveWidget(bar);
            var aura = _overlayService.Widgets.FirstOrDefault(w => w is VoiceAuraWidget);
            if (aura != null) _overlayService.RemoveWidget(aura);
        }

        [RelayCommand]
        public void ToggleVisibility()
        {
            _overlayService.ToggleVisibility();
        }
    }
}

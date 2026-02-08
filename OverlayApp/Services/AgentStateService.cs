using System;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;
using System.Timers;

namespace OverlayApp.Services
{
    public enum ConnectionStatus
    {
        Disconnected,
        Connecting,
        Reconnecting,
        Connected
    }

    public class AgentState
    {
        [JsonPropertyName("status")]
        public string Status { get; set; } = "idle";

        [JsonPropertyName("details")]
        public string? Details { get; set; }

        [JsonPropertyName("last_thought")]
        public string LastThought { get; set; } = "Waiting for connection...";

        [JsonPropertyName("current_action")]
        public string? CurrentAction { get; set; }

        [JsonPropertyName("pid")]
        public int? Pid { get; set; }

        [JsonPropertyName("vlm_status")]
        public string? VlmStatus { get; set; }

        // Voice state properties
        [JsonPropertyName("voice_state")]
        public string VoiceState { get; set; } = "idle";

        [JsonPropertyName("voice_partial")]
        public string VoicePartial { get; set; } = "";

        [JsonPropertyName("voice_level")]
        public double VoiceLevel { get; set; } = 0.0;

        // Computed property for UI binding
        [JsonIgnore]
        public bool IsVoiceActive => VoiceState == "listening";

        public ConnectionStatus Connection { get; set; } = ConnectionStatus.Disconnected;
    }

    public class AgentStateService
    {
        private readonly HttpClient _httpClient;
        private readonly System.Timers.Timer _timer;
        private AgentState _currentState;
        
        // Reconnection state
        private int _consecutiveFailures = 0;
        private DateTime _nextRetryTime = DateTime.MinValue;
        private const int MaxBackoffSeconds = 30;

        public event EventHandler<AgentState>? StateChanged;

        public AgentState CurrentState
        {
            get => _currentState;
            private set
            {
                _currentState = value;
                StateChanged?.Invoke(this, _currentState);
            }
        }

        public AgentStateService()
        {
            _httpClient = new HttpClient 
            { 
                BaseAddress = new Uri("http://127.0.0.1:8000/"),
                Timeout = TimeSpan.FromSeconds(5) // Prevent hanging on unresponsive backend
            };
            _currentState = new AgentState();
            
            _timer = new System.Timers.Timer(200); // 200ms for faster voice state updates
            _timer.Elapsed += async (s, e) => await PollStateAsync();
            _timer.Start();
        }

        public void SetPollingInterval(double milliseconds)
        {
            _timer.Interval = milliseconds;
        }

        public async Task SubmitTaskAsync(string command)
        {
            try
            {
                var payload = new { command = command };
                var response = await _httpClient.PostAsJsonAsync("task", payload);
                if (!response.IsSuccessStatusCode)
                {
                    System.Diagnostics.Debug.WriteLine($"Failed to submit task: {response.StatusCode}");
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Error submitting task: {ex.Message}");
            }
        }

        public async Task StopTaskAsync()
        {
            try
            {
                await _httpClient.PostAsync("stop", null);
            }
            catch (Exception)
            {
                // Handle or log error
            }
        }

        /// <summary>
        /// Inject steering context into the currently active task.
        /// Use this to adjust what the agent is doing mid-task.
        /// </summary>
        public async Task<bool> SteerTaskAsync(string context)
        {
            try
            {
                var payload = new { context = context };
                var response = await _httpClient.PostAsJsonAsync("steer", payload);
                return response.IsSuccessStatusCode;
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Error steering task: {ex.Message}");
                return false;
            }
        }

        private async Task PollStateAsync()
        {
            // Check if we should wait before retrying (backoff)
            if (_consecutiveFailures > 0 && DateTime.Now < _nextRetryTime)
            {
                // Update UI with reconnecting countdown
                var secondsRemaining = (int)(_nextRetryTime - DateTime.Now).TotalSeconds;
                if (CurrentState.Connection != ConnectionStatus.Reconnecting || 
                    !CurrentState.LastThought.Contains($"{secondsRemaining}s"))
                {
                    CurrentState = new AgentState 
                    { 
                        Connection = ConnectionStatus.Reconnecting, 
                        LastThought = $"Reconnecting in {secondsRemaining}s..."
                    };
                }
                return;
            }
            
            try
            {
                var state = await _httpClient.GetFromJsonAsync<AgentState>("state");
                if (state != null)
                {
                    state.Connection = ConnectionStatus.Connected;
                    
                    // Reset failure tracking on successful connection
                    if (_consecutiveFailures > 0)
                    {
                        Console.WriteLine($"[AgentStateService] Reconnected after {_consecutiveFailures} failures");
                        _consecutiveFailures = 0;
                    }

                    // Check for changes to avoid unnecessary event firing
                    // VoiceLevel excluded from main check but always updates for smooth animations
                    bool hasStateChange = state.LastThought != CurrentState.LastThought || 
                        state.Status != CurrentState.Status ||
                        state.CurrentAction != CurrentState.CurrentAction ||
                        state.Connection != CurrentState.Connection ||
                        state.VlmStatus != CurrentState.VlmStatus ||
                        state.VoiceState != CurrentState.VoiceState ||
                        state.VoicePartial != CurrentState.VoicePartial;
                    
                    // Always update VoiceLevel for smooth audio-reactive animations
                    bool voiceLevelChanged = Math.Abs(state.VoiceLevel - CurrentState.VoiceLevel) > 0.01;
                    
                    if (hasStateChange || voiceLevelChanged)
                    {
                         if (hasStateChange)
                             Console.WriteLine($"[AgentStateService] State changed: {state.Status}, VLM: {state.VlmStatus}, Voice: {state.VoiceState}");
                         CurrentState = state;
                    }
                }
            }
            catch (Exception ex)
            {
                _consecutiveFailures++;
                
                // Calculate backoff: 1s, 2s, 4s, 8s... up to MaxBackoffSeconds
                int backoffSeconds = Math.Min((int)Math.Pow(2, _consecutiveFailures - 1), MaxBackoffSeconds);
                _nextRetryTime = DateTime.Now.AddSeconds(backoffSeconds);
                
                Console.WriteLine($"[AgentStateService] Poll error (attempt {_consecutiveFailures}): {ex.Message}. Retry in {backoffSeconds}s");
                
                var status = _consecutiveFailures == 1 ? ConnectionStatus.Disconnected : ConnectionStatus.Reconnecting;
                CurrentState = new AgentState 
                { 
                    Connection = status, 
                    LastThought = _consecutiveFailures == 1 
                        ? "Backend disconnected. Reconnecting..." 
                        : $"Reconnecting in {backoffSeconds}s..."
                };
            }
        }
        
        public async Task<bool> EnableWakeWordAsync()
        {
            try
            {
                var response = await _httpClient.PostAsync("wake-word/enable", null);
                return response.IsSuccessStatusCode;
            }
            catch { return false; }
        }
        
        public async Task<bool> DisableWakeWordAsync()
        {
            try
            {
                var response = await _httpClient.PostAsync("wake-word/disable", null);
                return response.IsSuccessStatusCode;
            }
            catch { return false; }
        }
        
        public async Task<bool> GetWakeWordStatusAsync()
        {
            try
            {
                var response = await _httpClient.GetStringAsync("wake-word/status");
                return response.Contains("true");
            }
            catch { return true; } // Default to enabled
        }
    }
}

using System;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;

// Use an alias to avoid conflict with System.Windows.Shapes.Path from global usings
using IOPath = System.IO.Path;
using IOFile = System.IO.File;
using IODirectory = System.IO.Directory;

namespace OverlayApp.Services
{
    /// <summary>
    /// User settings that persist between sessions.
    /// </summary>
    public class UserSettings
    {
        [JsonPropertyName("overlay_enabled")]
        public bool OverlayEnabled { get; set; } = true;

        [JsonPropertyName("wake_word_enabled")]
        public bool WakeWordEnabled { get; set; } = true;

        [JsonPropertyName("window_left")]
        public double WindowLeft { get; set; } = 100;

        [JsonPropertyName("window_top")]
        public double WindowTop { get; set; } = 100;

        [JsonPropertyName("window_width")]
        public double WindowWidth { get; set; } = 1200;

        [JsonPropertyName("window_height")]
        public double WindowHeight { get; set; } = 800;

        [JsonPropertyName("window_maximized")]
        public bool WindowMaximized { get; set; } = false;

        [JsonPropertyName("last_model_id")]
        public string? LastModelId { get; set; }

        [JsonPropertyName("minimize_to_tray_on_close")]
        public bool MinimizeToTrayOnClose { get; set; } = true;

        [JsonPropertyName("start_minimized")]
        public bool StartMinimized { get; set; } = true;
    }

    /// <summary>
    /// Service for persisting user settings to %AppData%\Rin\settings.json
    /// </summary>
    public class SettingsService
    {
        private static readonly string SettingsDir = IOPath.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "Rin"
        );
        
        private static readonly string SettingsPath = IOPath.Combine(SettingsDir, "settings.json");
        
        private static readonly JsonSerializerOptions JsonOptions = new()
        {
            WriteIndented = true,
            PropertyNameCaseInsensitive = true
        };

        private UserSettings _settings = new();
        private readonly object _lock = new();

        public UserSettings Settings => _settings;

        /// <summary>
        /// Load settings from disk. Creates default settings if file doesn't exist.
        /// </summary>
        public UserSettings Load()
        {
            lock (_lock)
            {
                try
                {
                    if (IOFile.Exists(SettingsPath))
                    {
                        var json = IOFile.ReadAllText(SettingsPath);
                        _settings = JsonSerializer.Deserialize<UserSettings>(json, JsonOptions) ?? new UserSettings();
                        Console.WriteLine($"[SettingsService] Loaded settings from {SettingsPath}");
                    }
                    else
                    {
                        _settings = new UserSettings();
                        Console.WriteLine("[SettingsService] No settings file found, using defaults");
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"[SettingsService] Error loading settings: {ex.Message}. Using defaults.");
                    _settings = new UserSettings();
                }
                
                return _settings;
            }
        }

        /// <summary>
        /// Save current settings to disk.
        /// </summary>
        public void Save()
        {
            lock (_lock)
            {
                try
                {
                    // Ensure directory exists
                    IODirectory.CreateDirectory(SettingsDir);
                    
                    var json = JsonSerializer.Serialize(_settings, JsonOptions);
                    IOFile.WriteAllText(SettingsPath, json);
                    Console.WriteLine($"[SettingsService] Saved settings to {SettingsPath}");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"[SettingsService] Error saving settings: {ex.Message}");
                }
            }
        }

        /// <summary>
        /// Save settings asynchronously (fire-and-forget safe).
        /// </summary>
        public Task SaveAsync()
        {
            return Task.Run(Save);
        }

        /// <summary>
        /// Update a single setting and save.
        /// </summary>
        public void Update(Action<UserSettings> updateAction)
        {
            lock (_lock)
            {
                updateAction(_settings);
            }
            Save();
        }
    }
}

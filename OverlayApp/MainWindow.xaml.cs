using OverlayApp.ViewModels;
using OverlayApp.Services;

namespace OverlayApp;

public partial class MainWindow : Window
{
    private readonly MainViewModel _viewModel;
    private readonly SettingsService _settingsService;
    private TrayMenuWindow? _trayMenu;
    private System.Windows.Forms.NotifyIcon? _notifyIcon;

    public MainViewModel ViewModel => _viewModel;

    public MainWindow()
    {
        InitializeComponent();
        
        // Load user settings
        _settingsService = new SettingsService();
        _settingsService.Load();
        
        var overlayService = new OverlayService();
        _viewModel = new MainViewModel(overlayService);
        DataContext = _viewModel;

        // Restore overlay and wake word from settings
        _viewModel.IsOverlayEnabled = _settingsService.Settings.OverlayEnabled;
        _viewModel.IsWakeWordEnabled = _settingsService.Settings.WakeWordEnabled;

        SetAppIcon();
        SetupTrayIcon();
        RestoreWindowPosition();
        
        this.StateChanged += MainWindow_StateChanged;
        this.Closing += MainWindow_Closing;
        this.LocationChanged += (_, _) => SaveWindowPosition();
        this.SizeChanged += (_, _) => SaveWindowPosition();
        
        // Keyboard shortcuts
        this.PreviewKeyDown += MainWindow_PreviewKeyDown;
    }

    private void MainWindow_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        // Escape - Stop current task
        if (e.Key == Key.Escape)
        {
            _ = _viewModel.AgentStateService.StopTaskAsync();
            e.Handled = true;
        }
        // Ctrl+O - Toggle overlay
        else if (e.Key == Key.O && Keyboard.Modifiers == ModifierKeys.Control)
        {
            _viewModel.IsOverlayEnabled = !_viewModel.IsOverlayEnabled;
            _settingsService.Update(s => s.OverlayEnabled = _viewModel.IsOverlayEnabled);
            e.Handled = true;
        }
        // Ctrl+, - Open settings (future)
        else if (e.Key == Key.OemComma && Keyboard.Modifiers == ModifierKeys.Control)
        {
            // TODO: Show settings panel
            e.Handled = true;
        }
    }

    private void RestoreWindowPosition()
    {
        var s = _settingsService.Settings;
        
        // Validate position is on a visible screen
        var left = s.WindowLeft;
        var top = s.WindowTop;
        var width = Math.Max(800, s.WindowWidth);
        var height = Math.Max(600, s.WindowHeight);
        
        this.Left = left;
        this.Top = top;
        this.Width = width;
        this.Height = height;
        
        if (s.WindowMaximized)
            this.WindowState = WindowState.Maximized;
    }

    private void SaveWindowPosition()
    {
        if (this.WindowState == WindowState.Normal)
        {
            _settingsService.Settings.WindowLeft = this.Left;
            _settingsService.Settings.WindowTop = this.Top;
            _settingsService.Settings.WindowWidth = this.Width;
            _settingsService.Settings.WindowHeight = this.Height;
        }
        _settingsService.Settings.WindowMaximized = this.WindowState == WindowState.Maximized;
        // Don't save immediately on every move - will save on close
    }

    private void MainWindow_Closing(object? sender, System.ComponentModel.CancelEventArgs e)
    {
        // Save settings before closing
        _settingsService.Settings.OverlayEnabled = _viewModel.IsOverlayEnabled;
        _settingsService.Settings.WakeWordEnabled = _viewModel.IsWakeWordEnabled;
        _settingsService.Save();
    }

    private void SetAppIcon()
    {
        try
        {
            // Use pack URI for resources or relative path for local file
            this.Icon = System.Windows.Media.Imaging.BitmapFrame.Create(new Uri("pack://application:,,,/rin_logo.ico"));
        }
        catch { }
    }

    private void SetupTrayIcon()
    {
        _notifyIcon = new System.Windows.Forms.NotifyIcon();
        try 
        {
            // Set tray icon from the logo ICO file
            string logoPath = System.IO.Path.Combine(System.AppDomain.CurrentDomain.BaseDirectory, "rin_logo.ico");
            if (System.IO.File.Exists(logoPath))
            {
                _notifyIcon.Icon = new System.Drawing.Icon(logoPath);
            }
            else
            {
                // Fallback to internal resource if file not in bin
                var iconStream = Application.GetResourceStream(new Uri("pack://application:,,,/rin_logo.ico"))?.Stream;
                if (iconStream != null) _notifyIcon.Icon = new System.Drawing.Icon(iconStream);
            }
        }
        catch 
        {
            _notifyIcon.Icon = System.Drawing.SystemIcons.Application;
        }
        
        _notifyIcon.Visible = true;
        _notifyIcon.Text = "Rin Agent Dashboard";
        _notifyIcon.DoubleClick += (s, e) => ShowWindow();
        
        // Handle right-click for custom WPF menu
        _notifyIcon.MouseClick += (s, e) => {
            if (e.Button == System.Windows.Forms.MouseButtons.Right)
            {
                ShowTrayMenu();
            }
        };

        _trayMenu = new TrayMenuWindow(this, _viewModel);
    }

    private void ShowTrayMenu()
    {
        if (_trayMenu == null) return;

        // Position menu near tray
        var cursor = System.Windows.Forms.Cursor.Position;
        _trayMenu.Left = cursor.X - _trayMenu.Width / 2;
        _trayMenu.Top = cursor.Y - _trayMenu.Height;
        
        // Ensure it doesn't go off screen
        if (_trayMenu.Top < 0) _trayMenu.Top = cursor.Y;
        
        _trayMenu.Show();
        _trayMenu.Activate();
    }

    private void MainWindow_StateChanged(object? sender, EventArgs e)
    {
        if (this.WindowState == WindowState.Minimized)
        {
            this.Hide();
            _viewModel.AgentStateService.SetPollingInterval(2000); // Save resources when idle
        }
        else if (this.WindowState == WindowState.Normal || this.WindowState == WindowState.Maximized)
        {
            _viewModel.AgentStateService.SetPollingInterval(500); // High performance when visible
        }
    }

    public void ShowWindow()
    {
        this.Show();
        if (this.WindowState == WindowState.Minimized)
            this.WindowState = WindowState.Normal;
            
        this.Topmost = true;
        this.Activate();
        this.Focus();
        this.Topmost = false;
    }

    private void ExitApp()
    {
        _notifyIcon?.Dispose();
        System.Windows.Application.Current.Shutdown();
    }

    private void TitleBar_MouseDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ChangedButton == MouseButton.Left)
        {
            this.DragMove();
        }
    }

    private void Close_Click(object sender, MouseButtonEventArgs e)
    {
        this.WindowState = WindowState.Minimized; // Triggers StateChanged -> Hide
    }

    private void Minimize_Click(object sender, MouseButtonEventArgs e)
    {
        this.WindowState = WindowState.Minimized; // Triggers StateChanged -> Hide
    }

    private void Maximize_Click(object sender, MouseButtonEventArgs e)
    {
        this.WindowState = this.WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;
    }

    private void ExampleCommand_Click(object sender, MouseButtonEventArgs e)
    {
        if (sender is FrameworkElement element && element.Tag is string command)
        {
            _viewModel.CommandText = command;
        }
    }
}

public class StringToBrushConverter : IValueConverter
{
    public string? MatchString { get; set; }
    public Brush? MatchBrush { get; set; }
    public Brush? DefaultBrush { get; set; }

    public object? Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
    {
        if (value?.ToString() == MatchString)
            return MatchBrush;
        
        return DefaultBrush;
    }

    public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture) => throw new NotImplementedException();
}

public class InverseBrushConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
    {
        if (value is SolidColorBrush brush && brush.Color == Color.FromRgb(229, 229, 229))
            return new SolidColorBrush(Color.FromRgb(0, 122, 255));
        return new SolidColorBrush(Color.FromRgb(85, 85, 85));
    }

    public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture) => throw new NotImplementedException();
}

public class ModelBorderConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
    {
        string selectedId = value?.ToString() ?? "";
        string targetId = parameter?.ToString() ?? "";
        
        if (selectedId == targetId)
            return new SolidColorBrush(Color.FromRgb(0, 122, 255)); // AccentBlue
        return new SolidColorBrush(Color.FromRgb(224, 224, 224)); // Light gray
    }

    public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture) => throw new NotImplementedException();
}

public class ModelBgConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
    {
        string selectedId = value?.ToString() ?? "";
        string targetId = parameter?.ToString() ?? "";
        
        if (selectedId == targetId)
            return new SolidColorBrush(Color.FromRgb(232, 244, 255)); // Light blue
        return new SolidColorBrush(Colors.White);
    }

    public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture) => throw new NotImplementedException();
}

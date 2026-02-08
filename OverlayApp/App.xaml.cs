using System.Configuration;
using System.Data;
using System.Threading;

namespace OverlayApp;

/// <summary>
/// Interaction logic for App.xaml
/// </summary>
public partial class App : Application
{
    private MainWindow? _mainWindow;
    private static Mutex? _instanceMutex;
    
    // Unique identifier matching the Python backend's GUID
    private const string MUTEX_GUID = "7a1b2c3d-4e5f-6789-abcd-ef0123456789";

    protected override void OnStartup(StartupEventArgs e)
    {
        // Single-instance check using named mutex
        const string mutexName = $"Global\\RinAgentOverlay-{MUTEX_GUID}";
        _instanceMutex = new Mutex(true, mutexName, out bool createdNew);
        
        if (!createdNew)
        {
            // Another instance is already running
            System.Windows.MessageBox.Show(
                "Rin Agent is already running!\n\nCheck your system tray for the existing instance.",
                "Rin Agent",
                MessageBoxButton.OK,
                MessageBoxImage.Information
            );
            Shutdown();
            return;
        }
        
        base.OnStartup(e);

        // Prevent app from closing when main window is hidden
        this.ShutdownMode = ShutdownMode.OnExplicitShutdown;

        _mainWindow = new MainWindow();
        // We don't call Show(), keeping it hidden (minimized to tray)
        // Explicitly hide it just in case logic elsewhere triggers it
        _mainWindow.Hide();
        
        // Initialize overlay after window is created (WPF is now ready)
        _mainWindow.ViewModel.InitializeOverlay();
    }
    
    protected override void OnExit(ExitEventArgs e)
    {
        // Release the mutex on exit
        if (_instanceMutex != null)
        {
            try
            {
                _instanceMutex.ReleaseMutex();
                _instanceMutex.Dispose();
            }
            catch { }
            _instanceMutex = null;
        }
        
        base.OnExit(e);
    }
}

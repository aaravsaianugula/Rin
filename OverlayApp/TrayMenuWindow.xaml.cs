using System;
using System.Diagnostics;
using System.Windows;
using OverlayApp.ViewModels;

namespace OverlayApp
{
    public partial class TrayMenuWindow : Window
    {
        private readonly MainViewModel _viewModel;
        private readonly MainWindow _mainWindow;

        public TrayMenuWindow(MainWindow mainWindow, MainViewModel viewModel)
        {
            InitializeComponent();
            _mainWindow = mainWindow;
            _viewModel = viewModel;
        }

        private void Window_Deactivated(object sender, EventArgs e)
        {
            this.Hide();
        }

        private void OpenDashboard_Click(object sender, RoutedEventArgs e)
        {
            _mainWindow.ShowWindow();
            this.Hide();
        }

        private void ToggleOverlay_Click(object sender, RoutedEventArgs e)
        {
            _viewModel.IsOverlayEnabled = !_viewModel.IsOverlayEnabled;
            this.Hide();
        }

        private void RestartAgent_Click(object sender, RoutedEventArgs e)
        {
            _viewModel.RestartServicesCommand.Execute(null);
            this.Hide();
        }

        private void Exit_Click(object sender, RoutedEventArgs e)
        {
            // Kill all backend processes before shutting down
            KillBackendProcesses();
            Application.Current.Shutdown();
        }

        /// <summary>
        /// Kills all Python and llama-server processes to ensure clean shutdown.
        /// </summary>
        private void KillBackendProcesses()
        {
            string[] killList = { "python", "llama-server" };
            
            foreach (var processName in killList)
            {
                try
                {
                    var processes = Process.GetProcessesByName(processName);
                    foreach (var process in processes)
                    {
                        try
                        {
                            process.Kill();
                            process.WaitForExit(2000); // Wait up to 2 seconds for graceful termination
                        }
                        catch (Exception ex)
                        {
                            Debug.WriteLine($"Failed to kill {processName} (PID {process.Id}): {ex.Message}");
                        }
                        finally
                        {
                            process.Dispose();
                        }
                    }
                }
                catch (Exception ex)
                {
                    Debug.WriteLine($"Failed to enumerate {processName} processes: {ex.Message}");
                }
            }
        }
    }
}

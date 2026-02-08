using System.Windows.Interop;
using OverlayApp.Helpers;
using OverlayApp.Services;
using OverlayApp.ViewModels;

namespace OverlayApp
{
    public partial class MainOverlayWindow : Window
    {
        private HotkeyService _hotkeyService;
        private readonly MainOverlayViewModel _viewModel;

        public MainOverlayWindow(OverlayService overlayService, AgentStateService agentStateService)
        {
            InitializeComponent();
            
            // Setup services
            _viewModel = new MainOverlayViewModel(overlayService, agentStateService);
            DataContext = _viewModel;
            
            _hotkeyService = new HotkeyService();
            Loaded += OnLoaded;
            Closed += OnClosed;
        }

        private void OnLoaded(object sender, RoutedEventArgs e)
        {
            var helper = new WindowInteropHelper(this);
            var source = HwndSource.FromHwnd(helper.Handle);
            
            // Set extended styles
            int exStyle = NativeMethods.GetWindowLong(helper.Handle, NativeMethods.GWL_EXSTYLE);
            // WS_EX_TOOLWINDOW | WS_EX_LAYERED
            // We rely on WM_NCHITTEST for click-through, so strictly speaking WS_EX_TRANSPARENT isn't needed
            // if we manipulate NCHITTEST. But user requested it.
            // If we use WS_EX_TRANSPARENT, we get NO events. 
            // So we will stick to TOOLWINDOW and handle HitTest manually.
            NativeMethods.SetWindowLong(helper.Handle, NativeMethods.GWL_EXSTYLE, exStyle | NativeMethods.WS_EX_TOOLWINDOW);

            // EXCLUDE FROM CAPTURE (Invisible to Agent screenshots)
            NativeMethods.SetWindowDisplayAffinity(helper.Handle, NativeMethods.WDA_EXCLUDEFROMCAPTURE);

            // Register Hotkey
            _hotkeyService.Register(helper.Handle, () => _viewModel.ToggleVisibility());
            
            // Hook WndProc
            source.AddHook(WndProc);
        }
        
        private IntPtr WndProc(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
        {
            if (msg == NativeMethods.WM_NCHITTEST)
            {
                // Selective Click-Through Logic
                // Convert screen coordinates to WPF coordinates
                short x = (short)(lParam.ToInt32() & 0xFFFF);
                short y = (short)((lParam.ToInt32() >> 16) & 0xFFFF);
                var screenPoint = new Point(x, y);
                var clientPoint = PointFromScreen(screenPoint);

                // Perform HitTest on the WPF Visual Tree
                var result = VisualTreeHelper.HitTest(this, clientPoint);

                if (result != null)
                {
                    // Check if the hit element (or its ancestors) has IsHitTestable="True"
                    var element = result.VisualHit as UIElement;
                    bool isHit = false;
                    while (element != null)
                    {
                        if (HitTestHelper.GetIsHitTestable(element))
                        {
                            isHit = true;
                            break;
                        }
                        element = VisualTreeHelper.GetParent(element) as UIElement;
                    }

                    if (!isHit)
                    {
                        // If not hitting a specific widget, let mouse pass through
                        handled = true;
                        return (IntPtr)NativeMethods.HTTRANSPARENT;
                    }
                }
                else
                {
                     handled = true;
                     return (IntPtr)NativeMethods.HTTRANSPARENT;
                }
            }

            return IntPtr.Zero;
        }

        private void OnClosed(object sender, EventArgs e)
        {
            _hotkeyService.Dispose();
        }
    }
}

using System;
using System.Windows.Input;
using System.Windows.Interop;

namespace OverlayApp.Services
{
    /// <summary>
    /// Manages global hotkey registration and handling.
    /// </summary>
    public class HotkeyService : IDisposable
    {
        private IntPtr _windowHandle;
        private HwndSource _source;
        private const int HOTKEY_ID = 9000;
        private Action? _onHotkeyTriggered;

        public void Register(IntPtr windowHandle, Action onTriggered)
        {
            _windowHandle = windowHandle;
            _onHotkeyTriggered = onTriggered;
            _source = HwndSource.FromHwnd(_windowHandle);

            if (_source != null)
            {
                _source.AddHook(HwndHook);
                // Register Ctrl+Shift+Space (VK_SPACE = 0x20)
                NativeMethods.RegisterHotKey(_windowHandle, HOTKEY_ID, NativeMethods.MOD_CONTROL | NativeMethods.MOD_SHIFT, 0x20);
            }
        }

        private IntPtr HwndHook(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
        {
            if (msg == NativeMethods.WM_HOTKEY && wParam.ToInt32() == HOTKEY_ID)
            {
                _onHotkeyTriggered?.Invoke();
                handled = true;
            }
            return IntPtr.Zero;
        }

        public void Dispose()
        {
            if (_source != null)
            {
                _source.RemoveHook(HwndHook);
                _source = null;
            }
            NativeMethods.UnregisterHotKey(_windowHandle, HOTKEY_ID);
        }
    }
}

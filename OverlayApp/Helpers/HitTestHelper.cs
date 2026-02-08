using System.Windows;

namespace OverlayApp.Helpers
{
    /// <summary>
    /// Provides attached properties for hit-testing logic in the overlay.
    /// </summary>
    public static class HitTestHelper
    {
        public static readonly DependencyProperty IsHitTestableProperty =
            DependencyProperty.RegisterAttached("IsHitTestable", typeof(bool), typeof(HitTestHelper), new PropertyMetadata(false));

        public static void SetIsHitTestable(UIElement element, bool value)
        {
            element.SetValue(IsHitTestableProperty, value);
        }

        public static bool GetIsHitTestable(UIElement element)
        {
            return (bool)element.GetValue(IsHitTestableProperty);
        }
    }
}

using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;

namespace OverlayApp.Services
{
    public partial class OverlayService : ObservableObject
    {
        [ObservableProperty]
        private bool _isVisible = true;

        public ObservableCollection<object> Widgets { get; } = new ObservableCollection<object>();

        public void ToggleVisibility()
        {
            IsVisible = !IsVisible;
        }

        public void AddWidget(object widget)
        {
            Widgets.Add(widget);
        }

        public void RemoveWidget(object widget)
        {
            Widgets.Remove(widget);
        }

        public void ClearWidgets()
        {
            Widgets.Clear();
        }
    }
}

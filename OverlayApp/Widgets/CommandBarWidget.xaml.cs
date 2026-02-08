using System.Windows.Controls;

namespace OverlayApp.Widgets
{
    public partial class CommandBarWidget : UserControl
    {
        public CommandBarWidget()
        {
            InitializeComponent();
        }

        private void TextBlock_SizeChanged(object sender, System.Windows.SizeChangedEventArgs e)
        {
            ThoughtScroll.ScrollToBottom();
        }
    }
}

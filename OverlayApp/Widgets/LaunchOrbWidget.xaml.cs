using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Effects;
using OverlayApp.Helpers;
using OverlayApp.ViewModels;

namespace OverlayApp.Widgets;

/// <summary>
/// Launch Orb Widget - REVAMPED
/// Features state-reactive colors and completion burst effect.
/// </summary>
public partial class LaunchOrbWidget : UserControl
{
    private string _previousState = "";
    
    public LaunchOrbWidget()
    {
        InitializeComponent();
        Console.WriteLine("[LaunchOrbWidget] CREATED with revamped animations");
        
        DataContextChanged += OnDataContextChanged;
        Loaded += OnLoaded;
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        // Initial state sync
        if (DataContext is MainOverlayViewModel vm)
        {
            UpdateColors(vm.AgentStateGlowColor);
        }
    }

    private void OnDataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (e.OldValue is MainOverlayViewModel oldVm)
        {
            oldVm.PropertyChanged -= OnViewModelPropertyChanged;
        }
        
        if (e.NewValue is MainOverlayViewModel newVm)
        {
            newVm.PropertyChanged += OnViewModelPropertyChanged;
            UpdateColors(newVm.AgentStateGlowColor);
        }
    }

    private void OnViewModelPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (DataContext is not MainOverlayViewModel vm) return;

        if (e.PropertyName == nameof(MainOverlayViewModel.AgentStateGlowColor))
        {
            UpdateColors(vm.AgentStateGlowColor);
        }
        
        if (e.PropertyName == nameof(MainOverlayViewModel.AgentState))
        {
            var newState = vm.AgentState?.Status ?? "idle";
            
            // Trigger completion burst on transition to COMPLETE
            if (newState == "COMPLETE" && _previousState != "COMPLETE")
            {
                TriggerCompletionBurst();
            }
            
            _previousState = newState;
        }
    }

    private void UpdateColors(string hexColor)
    {
        try
        {
            var color = AnimationHelper.ParseColor(hexColor);
            var duration = AnimationHelper.Normal;

            // Find the named elements inside the button template
            var button = FindChild<Button>(this);
            if (button?.Template?.FindName("AmbientGlowBrush", button) is SolidColorBrush ambientBrush)
            {
                var anim = AnimationHelper.CreateColorTransition(color);
                ambientBrush.BeginAnimation(SolidColorBrush.ColorProperty, anim);
            }
            
            if (button?.Template?.FindName("SecondaryGlowBrush", button) is SolidColorBrush secondaryBrush)
            {
                var anim = AnimationHelper.CreateColorTransition(color);
                secondaryBrush.BeginAnimation(SolidColorBrush.ColorProperty, anim);
            }

            if (button?.Template?.FindName("CenterDotGlow", button) is DropShadowEffect dotGlow)
            {
                var anim = AnimationHelper.CreateColorTransition(color);
                dotGlow.BeginAnimation(DropShadowEffect.ColorProperty, anim);
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[LaunchOrbWidget] Color update error: {ex.Message}");
        }
    }

    private void TriggerCompletionBurst()
    {
        Console.WriteLine("[LaunchOrbWidget] Triggering completion burst!");
        
        // Burst ring 1 - fast expansion
        var burstAnim1 = new Storyboard();
        
        var scaleX1 = new DoubleAnimation
        {
            From = 1,
            To = 2.5,
            Duration = TimeSpan.FromMilliseconds(500),
            EasingFunction = AnimationHelper.EaseOut
        };
        Storyboard.SetTarget(scaleX1, BurstRing1);
        Storyboard.SetTargetProperty(scaleX1, new PropertyPath("(UIElement.RenderTransform).(ScaleTransform.ScaleX)"));
        
        var scaleY1 = new DoubleAnimation
        {
            From = 1,
            To = 2.5,
            Duration = TimeSpan.FromMilliseconds(500),
            EasingFunction = AnimationHelper.EaseOut
        };
        Storyboard.SetTarget(scaleY1, BurstRing1);
        Storyboard.SetTargetProperty(scaleY1, new PropertyPath("(UIElement.RenderTransform).(ScaleTransform.ScaleY)"));
        
        var fadeIn1 = new DoubleAnimation
        {
            To = 0.8,
            Duration = TimeSpan.FromMilliseconds(100)
        };
        Storyboard.SetTarget(fadeIn1, BurstRing1);
        Storyboard.SetTargetProperty(fadeIn1, new PropertyPath(OpacityProperty));
        
        var fadeOut1 = new DoubleAnimation
        {
            To = 0,
            Duration = TimeSpan.FromMilliseconds(400),
            BeginTime = TimeSpan.FromMilliseconds(100)
        };
        Storyboard.SetTarget(fadeOut1, BurstRing1);
        Storyboard.SetTargetProperty(fadeOut1, new PropertyPath(OpacityProperty));
        
        burstAnim1.Children.Add(scaleX1);
        burstAnim1.Children.Add(scaleY1);
        burstAnim1.Children.Add(fadeIn1);
        burstAnim1.Children.Add(fadeOut1);
        
        // Burst ring 2 - delayed expansion
        var scaleX2 = new DoubleAnimation
        {
            From = 1,
            To = 3,
            Duration = TimeSpan.FromMilliseconds(600),
            BeginTime = TimeSpan.FromMilliseconds(100),
            EasingFunction = AnimationHelper.EaseOut
        };
        Storyboard.SetTarget(scaleX2, BurstRing2);
        Storyboard.SetTargetProperty(scaleX2, new PropertyPath("(UIElement.RenderTransform).(ScaleTransform.ScaleX)"));
        
        var scaleY2 = new DoubleAnimation
        {
            From = 1,
            To = 3,
            Duration = TimeSpan.FromMilliseconds(600),
            BeginTime = TimeSpan.FromMilliseconds(100),
            EasingFunction = AnimationHelper.EaseOut
        };
        Storyboard.SetTarget(scaleY2, BurstRing2);
        Storyboard.SetTargetProperty(scaleY2, new PropertyPath("(UIElement.RenderTransform).(ScaleTransform.ScaleY)"));
        
        var fadeIn2 = new DoubleAnimation
        {
            To = 0.6,
            Duration = TimeSpan.FromMilliseconds(100),
            BeginTime = TimeSpan.FromMilliseconds(100)
        };
        Storyboard.SetTarget(fadeIn2, BurstRing2);
        Storyboard.SetTargetProperty(fadeIn2, new PropertyPath(OpacityProperty));
        
        var fadeOut2 = new DoubleAnimation
        {
            To = 0,
            Duration = TimeSpan.FromMilliseconds(500),
            BeginTime = TimeSpan.FromMilliseconds(200)
        };
        Storyboard.SetTarget(fadeOut2, BurstRing2);
        Storyboard.SetTargetProperty(fadeOut2, new PropertyPath(OpacityProperty));
        
        burstAnim1.Children.Add(scaleX2);
        burstAnim1.Children.Add(scaleY2);
        burstAnim1.Children.Add(fadeIn2);
        burstAnim1.Children.Add(fadeOut2);
        
        burstAnim1.Begin();
    }

    /// <summary>
    /// Helper to find a child element by type in the visual tree.
    /// </summary>
    private static T? FindChild<T>(DependencyObject parent) where T : DependencyObject
    {
        int childCount = VisualTreeHelper.GetChildrenCount(parent);
        for (int i = 0; i < childCount; i++)
        {
            var child = VisualTreeHelper.GetChild(parent, i);
            if (child is T typedChild)
                return typedChild;
            
            var result = FindChild<T>(child);
            if (result != null)
                return result;
        }
        return null;
    }
}

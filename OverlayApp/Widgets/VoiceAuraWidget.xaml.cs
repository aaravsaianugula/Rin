using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using OverlayApp.Helpers;
using OverlayApp.ViewModels;

namespace OverlayApp.Widgets;

/// <summary>
/// VoiceAura widget - REVAMPED
/// Multi-ring resonance system with enhanced audio reactivity.
/// Uses CompositionTarget.Rendering for 60fps smooth animations.
/// </summary>
public partial class VoiceAuraWidget : UserControl
{
    private double _smoothedLevel = 0;
    private double _lastVoiceLevel = 0;
    private int _rippleIndex = 0;
    private DateTime _lastRippleTime = DateTime.MinValue;
    
    // Smoothing factors (0-1, higher = more responsive)
    private const double Ring1Smoothing = 0.25;  // Fast response
    private const double Ring2Smoothing = 0.15;  // Medium response  
    private const double Ring3Smoothing = 0.08;  // Slow response
    
    // Ring target values for lerping
    private double _ring1Target = 1.0;
    private double _ring2Target = 1.0;
    private double _ring3Target = 1.0;
    
    public VoiceAuraWidget()
    {
        InitializeComponent();
        Console.WriteLine("[VoiceAuraWidget] CREATED - Multi-ring resonance system initialized");
        
        DataContextChanged += OnDataContextChanged;
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        Console.WriteLine("[VoiceAuraWidget] LOADED - Starting CompositionTarget rendering");
        CompositionTarget.Rendering += OnFrame;
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        CompositionTarget.Rendering -= OnFrame;
        Console.WriteLine("[VoiceAuraWidget] UNLOADED - Stopped rendering");
    }

    private void OnDataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (e.OldValue is MainOverlayViewModel oldVm)
        {
            oldVm.PropertyChanged -= OnViewModelPropertyChanged;
        }
        
        if (e.NewValue is MainOverlayViewModel newVm)
        {
            Console.WriteLine("[VoiceAuraWidget] DataContext connected");
            newVm.PropertyChanged += OnViewModelPropertyChanged;
        }
    }

    private void OnViewModelPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(MainOverlayViewModel.AgentState) && DataContext is MainOverlayViewModel vm)
        {
            double level = Math.Clamp(vm.AgentState?.VoiceLevel ?? 0.0, 0.0, 1.0);
            
            // Check for voice peak to trigger ripple
            if (level > 0.5 && _lastVoiceLevel < 0.45)
            {
                TriggerRipple();
            }
            
            _lastVoiceLevel = level;
            
            // Set target values for each ring (with different intensities)
            _ring1Target = 1.0 + (level * 0.35);  // 1.0 to 1.35
            _ring2Target = 1.0 + (level * 0.25);  // 1.0 to 1.25
            _ring3Target = 1.0 + (level * 0.18);  // 1.0 to 1.18
        }
    }

    /// <summary>
    /// Called every frame (~60fps) for smooth animations.
    /// Uses lerping for organic, fluid motion.
    /// </summary>
    private void OnFrame(object? sender, EventArgs e)
    {
        if (DataContext is not MainOverlayViewModel vm) return;

        double level = Math.Clamp(vm.AgentState?.VoiceLevel ?? 0.0, 0.0, 1.0);
        
        // Update targets based on current level
        _ring1Target = 1.0 + (level * 0.35);
        _ring2Target = 1.0 + (level * 0.25);
        _ring3Target = 1.0 + (level * 0.18);
        
        // Lerp ring scales with different smoothing factors
        double ring1Current = Ring1Scale.ScaleX;
        double ring2Current = Ring2Scale.ScaleX;
        double ring3Current = Ring3Scale.ScaleX;
        
        double ring1New = AnimationHelper.Lerp(ring1Current, _ring1Target, Ring1Smoothing);
        double ring2New = AnimationHelper.Lerp(ring2Current, _ring2Target, Ring2Smoothing);
        double ring3New = AnimationHelper.Lerp(ring3Current, _ring3Target, Ring3Smoothing);
        
        Ring1Scale.ScaleX = ring1New;
        Ring1Scale.ScaleY = ring1New;
        Ring2Scale.ScaleX = ring2New;
        Ring2Scale.ScaleY = ring2New;
        Ring3Scale.ScaleX = ring3New;
        Ring3Scale.ScaleY = ring3New;
        
        // Modulate blur based on level
        Ring1Blur.Radius = 18 + (level * 12);
        Ring2Blur.Radius = 22 + (level * 10);
        Ring3Blur.Radius = 28 + (level * 8);
        
        // Ambient aura blur
        AuraBlur.Radius = 45 + (level * 20);
        
        // Smooth the overall level for ambient effects
        _smoothedLevel = AnimationHelper.Lerp(_smoothedLevel, level, 0.1);
    }

    private void TriggerRipple()
    {
        // Rate-limit ripples to avoid spam
        if ((DateTime.Now - _lastRippleTime).TotalMilliseconds < 200) return;
        _lastRippleTime = DateTime.Now;
        
        Console.WriteLine($"[VoiceAuraWidget] Ripple triggered (index: {_rippleIndex})");
        
        // Alternate between ripple elements
        var ripple = _rippleIndex % 2 == 0 ? Ripple1 : Ripple2;
        var rippleScale = _rippleIndex % 2 == 0 ? Ripple1Scale : Ripple2Scale;
        _rippleIndex++;
        
        // Create ripple animation
        var storyboard = new Storyboard();
        
        // Reset and expand
        var scaleX = new DoubleAnimation
        {
            From = 1.0,
            To = 1.5,
            Duration = TimeSpan.FromMilliseconds(350),
            EasingFunction = AnimationHelper.EaseOut
        };
        Storyboard.SetTarget(scaleX, ripple);
        Storyboard.SetTargetProperty(scaleX, new PropertyPath("(UIElement.RenderTransform).(ScaleTransform.ScaleX)"));
        
        var scaleY = new DoubleAnimation
        {
            From = 1.0,
            To = 1.5,
            Duration = TimeSpan.FromMilliseconds(350),
            EasingFunction = AnimationHelper.EaseOut
        };
        Storyboard.SetTarget(scaleY, ripple);
        Storyboard.SetTargetProperty(scaleY, new PropertyPath("(UIElement.RenderTransform).(ScaleTransform.ScaleY)"));
        
        // Fade in quickly, then fade out
        var fadeIn = new DoubleAnimation
        {
            To = 0.7,
            Duration = TimeSpan.FromMilliseconds(80)
        };
        Storyboard.SetTarget(fadeIn, ripple);
        Storyboard.SetTargetProperty(fadeIn, new PropertyPath(OpacityProperty));
        
        var fadeOut = new DoubleAnimation
        {
            To = 0,
            Duration = TimeSpan.FromMilliseconds(300),
            BeginTime = TimeSpan.FromMilliseconds(80)
        };
        Storyboard.SetTarget(fadeOut, ripple);
        Storyboard.SetTargetProperty(fadeOut, new PropertyPath(OpacityProperty));
        
        storyboard.Children.Add(scaleX);
        storyboard.Children.Add(scaleY);
        storyboard.Children.Add(fadeIn);
        storyboard.Children.Add(fadeOut);
        
        storyboard.Begin();
    }
}

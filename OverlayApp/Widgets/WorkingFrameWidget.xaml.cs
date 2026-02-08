using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using OverlayApp.Helpers;
using OverlayApp.ViewModels;

namespace OverlayApp.Widgets;

/// <summary>
/// Working Frame Widget - REVAMPED
/// Displays an animated border around the screen when the agent is actively processing.
/// Features:
/// - State-driven color transitions (THINKING = warm ivory, EXECUTING = lavender)
/// - Gradient sweep animation (traveling highlight around perimeter)
/// - Differentiated pulse speeds for each processing phase
/// </summary>
public partial class WorkingFrameWidget : UserControl
{
    private Storyboard? _currentPulseAnimation;
    private Storyboard? _sweepAnimation;
    private string _currentState = "";

    // State colors
    private static readonly Color ThinkingColor = AnimationHelper.ParseColor("#E8DCC8"); // Warm ivory
    private static readonly Color ExecutingColor = AnimationHelper.ParseColor("#8B7BA5"); // Muted lavender
    private static readonly Color CapturingColor = AnimationHelper.ParseColor("#A8C5D9"); // Soft blue
    
    public WorkingFrameWidget()
    {
        InitializeComponent();
        Console.WriteLine("[WorkingFrameWidget] CREATED - Frame border initialized with revamped animations");
        
        Loaded += OnLoaded;
        DataContextChanged += OnDataContextChanged;
    }
    
    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        Console.WriteLine("[WorkingFrameWidget] LOADED - Starting animations");
        
        // Start gradient sweep animation
        try
        {
            _sweepAnimation = (Storyboard)FindResource("GradientSweep");
            _sweepAnimation?.Begin(this, true);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[WorkingFrameWidget] Sweep animation error: {ex.Message}");
        }

        // Initial state check
        if (DataContext is MainOverlayViewModel vm)
        {
            UpdateForState(vm.AgentState?.Status ?? "THINKING");
        }
        else
        {
            // Default to thinking state
            StartThinkingAnimation();
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
            UpdateForState(newVm.AgentState?.Status ?? "THINKING");
        }
    }

    private void OnViewModelPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(MainOverlayViewModel.AgentState) && DataContext is MainOverlayViewModel vm)
        {
            UpdateForState(vm.AgentState?.Status ?? "THINKING");
        }
    }

    private void UpdateForState(string status)
    {
        if (status == _currentState) return;
        _currentState = status;

        Console.WriteLine($"[WorkingFrameWidget] State changed to: {status}");

        // Stop current animation
        _currentPulseAnimation?.Stop(this);

        // Determine color and animation based on state
        Color targetColor;
        string animationKey;

        switch (status)
        {
            case "EXECUTING":
            case "ACTING":
                targetColor = ExecutingColor;
                animationKey = "ExecutingPulse";
                break;
            case "CAPTURING":
            case "VERIFYING":
                targetColor = CapturingColor;
                animationKey = "ThinkingPulse"; // Use slower pulse for verification
                break;
            case "loading":
            case "THINKING":
            default:
                targetColor = ThinkingColor;
                animationKey = "ThinkingPulse";
                break;
        }

        // Animate colors smoothly
        AnimateColors(targetColor);

        // Start appropriate pulse animation
        try
        {
            _currentPulseAnimation = (Storyboard)FindResource(animationKey);
            _currentPulseAnimation?.Begin(this, true);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[WorkingFrameWidget] Pulse animation error: {ex.Message}");
        }
    }

    private void AnimateColors(Color targetColor)
    {
        var duration = AnimationHelper.Normal;

        // Create color with appropriate alpha for each gradient stop
        Color fullColor = Color.FromArgb(128, targetColor.R, targetColor.G, targetColor.B); // 50% alpha
        Color midColor = Color.FromArgb(64, targetColor.R, targetColor.G, targetColor.B);   // 25% alpha
        Color cornerColor = Color.FromArgb(80, targetColor.R, targetColor.G, targetColor.B); // 31% alpha

        // Animate top gradient
        AnimateGradientStop(TopGradientStart, fullColor, duration);
        AnimateGradientStop(TopGradientMid, midColor, duration);

        // Animate bottom gradient
        AnimateGradientStop(BottomGradientStart, fullColor, duration);
        AnimateGradientStop(BottomGradientMid, midColor, duration);

        // Animate side gradients
        AnimateGradientStop(LeftGradientStart, Color.FromArgb(96, targetColor.R, targetColor.G, targetColor.B), duration);
        AnimateGradientStop(RightGradientStart, Color.FromArgb(96, targetColor.R, targetColor.G, targetColor.B), duration);

        // Animate corners
        AnimateGradientStop(CornerTL, cornerColor, duration);
        AnimateGradientStop(CornerTR, cornerColor, duration);
        AnimateGradientStop(CornerBL, cornerColor, duration);
        AnimateGradientStop(CornerBR, cornerColor, duration);
    }

    private void AnimateGradientStop(GradientStop stop, Color targetColor, Duration duration)
    {
        var animation = new ColorAnimation
        {
            To = targetColor,
            Duration = duration,
            EasingFunction = AnimationHelper.EaseInOut
        };
        stop.BeginAnimation(GradientStop.ColorProperty, animation);
    }

    private void StartThinkingAnimation()
    {
        try
        {
            _currentPulseAnimation = (Storyboard)FindResource("ThinkingPulse");
            _currentPulseAnimation?.Begin(this, true);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[WorkingFrameWidget] Animation error: {ex.Message}");
        }
    }
    
    public void StopAnimation()
    {
        _currentPulseAnimation?.Stop(this);
        _sweepAnimation?.Stop(this);
    }
}

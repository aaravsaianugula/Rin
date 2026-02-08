using System;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace OverlayApp.Helpers
{
    /// <summary>
    /// Reusable animation utilities for GPU-optimized overlay effects.
    /// All animations target Opacity and RenderTransform for hardware acceleration.
    /// </summary>
    public static class AnimationHelper
    {
        // Standard durations matching FluidOverlay design system
        public static Duration Fast => new Duration(TimeSpan.FromMilliseconds(200));
        public static Duration Normal => new Duration(TimeSpan.FromMilliseconds(400));
        public static Duration Slow => new Duration(TimeSpan.FromMilliseconds(600));
        public static Duration Breathing => new Duration(TimeSpan.FromMilliseconds(2500));

        // Standard easing functions
        public static CubicEase EaseOut => new CubicEase { EasingMode = EasingMode.EaseOut };
        public static CubicEase EaseInOut => new CubicEase { EasingMode = EasingMode.EaseInOut };
        public static SineEase SineInOut => new SineEase { EasingMode = EasingMode.EaseInOut };
        public static BackEase BounceOut => new BackEase { EasingMode = EasingMode.EaseOut, Amplitude = 0.3 };

        /// <summary>
        /// Smooth linear interpolation for real-time animations.
        /// </summary>
        public static double Lerp(double current, double target, double factor)
        {
            return current + (target - current) * Math.Clamp(factor, 0, 1);
        }

        /// <summary>
        /// Creates a pulsing heartbeat animation for status indicators.
        /// Targets Opacity property.
        /// </summary>
        public static Storyboard CreateHeartbeat(double minOpacity = 0.6, double maxOpacity = 1.0, double cycleDurationMs = 1200)
        {
            var storyboard = new Storyboard
            {
                RepeatBehavior = RepeatBehavior.Forever,
                AutoReverse = true
            };

            var animation = new DoubleAnimation
            {
                From = minOpacity,
                To = maxOpacity,
                Duration = new Duration(TimeSpan.FromMilliseconds(cycleDurationMs / 2)),
                EasingFunction = SineInOut
            };

            Storyboard.SetTargetProperty(animation, new PropertyPath(UIElement.OpacityProperty));
            storyboard.Children.Add(animation);
            return storyboard;
        }

        /// <summary>
        /// Creates a radial burst effect for completion celebrations.
        /// Returns a Storyboard that animates Scale and Opacity.
        /// </summary>
        public static Storyboard CreateBurstAnimation(string scaleTransformName, double startScale = 1.0, double endScale = 2.0, double durationMs = 600)
        {
            var storyboard = new Storyboard();

            // Scale X
            var scaleXAnim = new DoubleAnimation
            {
                From = startScale,
                To = endScale,
                Duration = new Duration(TimeSpan.FromMilliseconds(durationMs)),
                EasingFunction = EaseOut
            };
            Storyboard.SetTargetName(scaleXAnim, scaleTransformName);
            Storyboard.SetTargetProperty(scaleXAnim, new PropertyPath(ScaleTransform.ScaleXProperty));

            // Scale Y
            var scaleYAnim = new DoubleAnimation
            {
                From = startScale,
                To = endScale,
                Duration = new Duration(TimeSpan.FromMilliseconds(durationMs)),
                EasingFunction = EaseOut
            };
            Storyboard.SetTargetName(scaleYAnim, scaleTransformName);
            Storyboard.SetTargetProperty(scaleYAnim, new PropertyPath(ScaleTransform.ScaleYProperty));

            storyboard.Children.Add(scaleXAnim);
            storyboard.Children.Add(scaleYAnim);

            return storyboard;
        }

        /// <summary>
        /// Creates a fade-out animation.
        /// </summary>
        public static DoubleAnimation CreateFadeOut(double durationMs = 400, double beginTimeMs = 0)
        {
            return new DoubleAnimation
            {
                To = 0,
                Duration = new Duration(TimeSpan.FromMilliseconds(durationMs)),
                BeginTime = TimeSpan.FromMilliseconds(beginTimeMs),
                EasingFunction = EaseOut
            };
        }

        /// <summary>
        /// Creates a fade-in animation.
        /// </summary>
        public static DoubleAnimation CreateFadeIn(double targetOpacity = 1.0, double durationMs = 300)
        {
            return new DoubleAnimation
            {
                To = targetOpacity,
                Duration = new Duration(TimeSpan.FromMilliseconds(durationMs)),
                EasingFunction = EaseOut
            };
        }

        /// <summary>
        /// Creates a smooth color transition animation.
        /// </summary>
        public static ColorAnimation CreateColorTransition(Color toColor, double durationMs = 400)
        {
            return new ColorAnimation
            {
                To = toColor,
                Duration = new Duration(TimeSpan.FromMilliseconds(durationMs)),
                EasingFunction = EaseInOut
            };
        }

        /// <summary>
        /// Parses a hex color string to a Color.
        /// </summary>
        public static Color ParseColor(string hex)
        {
            try
            {
                return (Color)ColorConverter.ConvertFromString(hex);
            }
            catch
            {
                return Colors.Gray;
            }
        }
    }
}

/**
 * Rin — Design System v5
 * Radical minimal. Nothing OS restraint meets magazine-like typography.
 * Near-black monochrome. Single warm accent. Layout-first thinking.
 */
import { Platform } from 'react-native';

const sans = Platform.select({
    ios: 'System',
    android: 'sans-serif',
    default: '-apple-system, "SF Pro Display", "Inter", "Segoe UI", sans-serif',
});
const mono = Platform.select({
    ios: 'Menlo',
    android: 'monospace',
    default: '"SF Mono", "JetBrains Mono", monospace',
});

/* ── Colors — monochrome + single warm accent ────────────── */
export const colors = {
    bg: '#0A0A0A',
    surface: '#141414',
    surfaceRaised: '#1C1C1C',
    surfaceHover: '#242424',
    surfaceBright: '#2E2E2E',

    // Single accent — warm off-white / cream for highlights
    // Everything else monochrome
    accent: '#E8E4DD',        // warm cream — used sparingly
    accentSoft: 'rgba(232, 228, 221, 0.08)',
    accentMuted: 'rgba(232, 228, 221, 0.15)',

    // Red dot — Nothing OS inspired, only for live/active state
    dot: '#E55050',
    dotSoft: 'rgba(229, 80, 80, 0.12)',

    // Text — monochrome hierarchy
    text: '#E8E4DD',          // warm off-white
    textSecondary: '#8A8A8A',
    textTertiary: '#555555',
    textMuted: '#333333',
    textGhost: '#1E1E1E',

    // Borders
    border: 'rgba(255, 255, 255, 0.05)',
    borderStrong: 'rgba(255, 255, 255, 0.10)',
    separator: 'rgba(255, 255, 255, 0.03)',

    // Functional — kept very muted
    success: '#5CB87A',
    successSoft: 'rgba(92, 184, 122, 0.10)',
    warning: '#D4A334',
    warningSoft: 'rgba(212, 163, 52, 0.10)',
    error: '#E55050',
    errorSoft: 'rgba(229, 80, 80, 0.10)',

    // Chat bubbles
    bubbleUser: '#E8E4DD',
    bubbleUserText: '#0A0A0A',
    bubbleAgent: '#141414',
    bubbleAgentText: '#E8E4DD',

    online: '#5CB87A',
    onlineSoft: 'rgba(92, 184, 122, 0.10)',
    offline: '#555555',
    offlineSoft: 'rgba(85, 85, 85, 0.10)',
    bgElevated: '#111111',
};

export const spacing = { xs: 4, sm: 8, md: 16, lg: 24, xl: 32, xxl: 48 };

export const radius = { xs: 6, sm: 10, md: 14, lg: 20, xl: 28, full: 9999 };

/* ── Typography — expressive hierarchy ───────────────────── */
export const typography = {
    // Display — oversized, striking
    display: { fontSize: 44, fontWeight: '700', letterSpacing: -2, color: colors.text, fontFamily: sans },
    // Large title — section hero
    hero: { fontSize: 32, fontWeight: '700', letterSpacing: -1.2, color: colors.text, fontFamily: sans },
    title: { fontSize: 20, fontWeight: '600', letterSpacing: -0.4, color: colors.text, fontFamily: sans },
    heading: { fontSize: 16, fontWeight: '600', color: colors.text, fontFamily: sans },
    body: { fontSize: 15, fontWeight: '400', lineHeight: 22, color: colors.text, fontFamily: sans },
    secondary: { fontSize: 14, fontWeight: '400', color: colors.textSecondary, fontFamily: sans },
    caption: { fontSize: 12, fontWeight: '500', color: colors.textTertiary, fontFamily: sans },
    small: { fontSize: 11, fontWeight: '500', color: colors.textTertiary, fontFamily: sans },
    label: { fontSize: 11, fontWeight: '600', color: colors.textTertiary, letterSpacing: 0.5, fontFamily: sans },
    mono: { fontSize: 12, fontFamily: mono, color: colors.textSecondary },
};

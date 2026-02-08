/**
 * Rin — Monitor Screen (v5 Radical)
 * Full-bleed viewer. Live reasoning feed.
 * Floating composer FAB for quick steering messages.
 * Fluid spring animations throughout.
 */
import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
    View, Text, Image, TouchableOpacity, TextInput, StyleSheet,
    StatusBar, ScrollView, Animated, Easing, KeyboardAvoidingView,
    Platform, Keyboard,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useSocket } from '../services/socket';
import api from '../services/api';
import { colors, spacing, radius, typography } from '../theme';

/* ── Double-buffered Image for smooth frame streaming ─────── */
function DoubleBufferedImage({ uri, style, resizeMode }) {
    const [prevUri, setPrevUri] = useState(null);
    const [currentUri, setCurrentUri] = useState(null);

    useEffect(() => {
        if (!uri) return;
        if (uri !== currentUri) {
            setCurrentUri(uri);
        }
    }, [uri]);

    const onCurrentLoaded = useCallback(() => {
        // New frame fully decoded — promote it to the background layer
        setPrevUri(currentUri);
    }, [currentUri]);

    const bgUri = prevUri ? `data:image/jpeg;base64,${prevUri}` : null;
    const fgUri = currentUri ? `data:image/jpeg;base64,${currentUri}` : null;

    return (
        <View style={[style, { overflow: 'hidden' }]}>
            {/* Previous frame — stays visible until new one loads */}
            {bgUri && (
                <Image source={{ uri: bgUri }}
                    style={StyleSheet.absoluteFill}
                    resizeMode={resizeMode}
                    fadeDuration={0}
                />
            )}
            {/* Current frame — renders on top, hides bg once loaded */}
            {fgUri && (
                <Image source={{ uri: fgUri }}
                    style={StyleSheet.absoluteFill}
                    resizeMode={resizeMode}
                    fadeDuration={0}
                    onLoad={onCurrentLoaded}
                />
            )}
        </View>
    );
}

/* ── Single Activity Entry with spring animation ─────────── */
function LogEntry({ item, index }) {
    const fade = useRef(new Animated.Value(0)).current;
    const slide = useRef(new Animated.Value(12)).current;
    const scale = useRef(new Animated.Value(0.95)).current;
    useEffect(() => {
        const delay = Math.min(index * 40, 200);
        Animated.parallel([
            Animated.timing(fade, {
                toValue: 1, duration: 300, delay,
                useNativeDriver: true, easing: Easing.out(Easing.cubic),
            }),
            Animated.spring(slide, {
                toValue: 0, delay, tension: 80, friction: 12,
                useNativeDriver: true,
            }),
            Animated.spring(scale, {
                toValue: 1, delay, tension: 100, friction: 10,
                useNativeDriver: true,
            }),
        ]).start();
    }, []);

    const isThought = item.type === 'thought';
    const age = formatAge(item.time);

    return (
        <Animated.View style={[ls.entry, {
            opacity: fade,
            transform: [{ translateY: slide }, { scale }],
        }]}>
            <View style={ls.entryHeader}>
                <View style={[ls.typeDot, isThought ? ls.dotThought : ls.dotAction]} />
                <Text style={ls.typeLabel}>{isThought ? 'Reasoning' : 'Action'}</Text>
                <Text style={ls.timeLabel}>{age}</Text>
            </View>
            <Text style={ls.entryText} numberOfLines={6}>{item.text}</Text>
        </Animated.View>
    );
}

function formatAge(ts) {
    const d = Math.floor((Date.now() - ts) / 1000);
    if (d < 5) return 'now';
    if (d < 60) return `${d}s ago`;
    if (d < 3600) return `${Math.floor(d / 60)}m ago`;
    return `${Math.floor(d / 3600)}h ago`;
}

/* ── Pulsing Live Dot ─────────────────────────────────────── */
function PulseDot({ active, style }) {
    const pulse = useRef(new Animated.Value(1)).current;
    useEffect(() => {
        if (active) {
            const anim = Animated.loop(Animated.sequence([
                Animated.timing(pulse, {
                    toValue: 0.3, duration: 800,
                    easing: Easing.inOut(Easing.ease),
                    useNativeDriver: true,
                }),
                Animated.timing(pulse, {
                    toValue: 1, duration: 800,
                    easing: Easing.inOut(Easing.ease),
                    useNativeDriver: true,
                }),
            ]));
            anim.start();
            return () => anim.stop();
        } else {
            pulse.setValue(1);
        }
    }, [active]);
    return (
        <Animated.View style={[style, { opacity: pulse }]} />
    );
}

/* ── Floating Composer FAB ────────────────────────────────── */
function FloatingComposer({ connected }) {
    const [expanded, setExpanded] = useState(false);
    const [showBar, setShowBar] = useState(false);
    const [text, setText] = useState('');
    const [sending, setSending] = useState(false);
    const inputRef = useRef(null);

    const barAnim = useRef(new Animated.Value(0)).current;
    const fabScale = useRef(new Animated.Value(1)).current;

    const open = useCallback(() => {
        setExpanded(true);
        setShowBar(true);
        Animated.parallel([
            Animated.spring(barAnim, { toValue: 1, tension: 65, friction: 11, useNativeDriver: true }),
            Animated.spring(fabScale, { toValue: 0.85, tension: 100, friction: 8, useNativeDriver: true }),
        ]).start(() => inputRef.current?.focus());
    }, []);

    const close = useCallback(() => {
        Keyboard.dismiss();
        Animated.parallel([
            Animated.spring(barAnim, { toValue: 0, tension: 65, friction: 11, useNativeDriver: true }),
            Animated.spring(fabScale, { toValue: 1, tension: 100, friction: 8, useNativeDriver: true }),
        ]).start(() => {
            setExpanded(false);
            setShowBar(false);
        });
    }, []);

    const toggle = useCallback(() => {
        expanded ? close() : open();
    }, [expanded, open, close]);

    const send = async () => {
        const msg = text.trim();
        if (!msg || sending) return;
        setSending(true);
        setText('');
        try {
            await api.sendChat(msg);
        } catch (e) { console.log(e); }
        finally {
            setSending(false);
            close();
        }
    };

    const barOpacity = barAnim.interpolate({
        inputRange: [0, 1], outputRange: [0, 1],
    });
    const barTranslate = barAnim.interpolate({
        inputRange: [0, 1], outputRange: [20, 0],
    });

    return (
        <View style={fc.wrap}>
            {/* Input bar — only mounted when visible */}
            {showBar && (
                <Animated.View style={[fc.inputBar, {
                    opacity: barOpacity,
                    transform: [{ translateY: barTranslate }],
                }]}>
                    <TextInput
                        ref={inputRef}
                        style={fc.input}
                        value={text}
                        onChangeText={setText}
                        placeholder="Steer the agent..."
                        placeholderTextColor={colors.textMuted}
                        maxLength={2000}
                        onSubmitEditing={send}
                        returnKeyType="send"
                    />
                    <TouchableOpacity
                        style={[fc.sendBtn, text.trim() && !sending && fc.sendBtnActive]}
                        onPress={send}
                        disabled={!text.trim() || sending}
                        activeOpacity={0.7}
                    >
                        <Ionicons name="arrow-up" size={14}
                            color={text.trim() && !sending ? colors.bg : colors.textMuted} />
                    </TouchableOpacity>
                </Animated.View>
            )}

            {/* FAB button */}
            <TouchableOpacity onPress={toggle} disabled={!connected}
                activeOpacity={0.8}>
                <Animated.View style={[fc.fab, {
                    transform: [{ scale: fabScale }],
                }]}>
                    <Ionicons
                        name={expanded ? 'close' : 'chatbubble-ellipses'}
                        size={20}
                        color={colors.bg}
                    />
                </Animated.View>
            </TouchableOpacity>
        </View>
    );
}


/* ── Screen ───────────────────────────────────────────────── */
export default function MonitorScreen() {
    const insets = useSafeAreaInsets();
    const { connected, agentState, latestFrame, activityLog } = useSocket();
    const [streaming, setStreaming] = useState(false);
    const [polledFrame, setPolledFrame] = useState(null);

    // Entry animation
    const screenFade = useRef(new Animated.Value(0)).current;
    const screenSlide = useRef(new Animated.Value(20)).current;
    useEffect(() => {
        Animated.parallel([
            Animated.timing(screenFade, {
                toValue: 1, duration: 400,
                easing: Easing.out(Easing.cubic),
                useNativeDriver: true,
            }),
            Animated.spring(screenSlide, {
                toValue: 0, tension: 60, friction: 12,
                useNativeDriver: true,
            }),
        ]).start();
    }, []);

    // Card animations for thought/action
    const thoughtFade = useRef(new Animated.Value(0)).current;
    const thoughtSlide = useRef(new Animated.Value(8)).current;
    const actionFade = useRef(new Animated.Value(0)).current;
    const actionSlide = useRef(new Animated.Value(8)).current;

    useEffect(() => {
        thoughtFade.setValue(0);
        thoughtSlide.setValue(8);
        Animated.parallel([
            Animated.timing(thoughtFade, {
                toValue: 1, duration: 250,
                easing: Easing.out(Easing.cubic),
                useNativeDriver: true,
            }),
            Animated.spring(thoughtSlide, {
                toValue: 0, tension: 80, friction: 12,
                useNativeDriver: true,
            }),
        ]).start();
    }, [agentState.lastThought]);

    useEffect(() => {
        actionFade.setValue(0);
        actionSlide.setValue(8);
        Animated.parallel([
            Animated.timing(actionFade, {
                toValue: 1, duration: 250,
                easing: Easing.out(Easing.cubic),
                useNativeDriver: true,
            }),
            Animated.spring(actionSlide, {
                toValue: 0, tension: 80, friction: 12,
                useNativeDriver: true,
            }),
        ]).start();
    }, [agentState.currentAction]);

    const toggleStream = async () => {
        try {
            if (streaming) { await api.stopStream(); setStreaming(false); setPolledFrame(null); }
            else { await api.startStream(); setStreaming(true); }
        } catch (e) { console.log(e); }
    };

    // Auto-detect streaming if we arrive from Chat auto-navigate
    useEffect(() => {
        // If the agent is active and we have no stream, start it
        const isActive = agentState.status === 'thinking' || agentState.status === 'working';
        if (isActive && !streaming && connected) {
            api.startStream().then(() => setStreaming(true)).catch(() => { });
        }
    }, []);

    // Poll for frames via REST when streaming (reliable fallback)
    useEffect(() => {
        if (!streaming) return;
        let alive = true;
        const poll = async () => {
            while (alive) {
                try {
                    const r = await api.getLatestFrame();
                    if (alive && r && r.image) setPolledFrame(r.image);
                } catch (_) { }
                await new Promise(ok => setTimeout(ok, 500));
            }
        };
        poll();
        return () => { alive = false; };
    }, [streaming]);

    // Use socket frame if available, otherwise polled frame
    const displayFrame = latestFrame || polledFrame;
    const isActive = agentState.status === 'thinking' || agentState.status === 'working';
    const vlmOk = agentState.vlmStatus === 'ONLINE' || agentState.vlmStatus === 'READY';
    const log = activityLog || [];

    return (
        <View style={[s.root, { paddingTop: insets.top }]}>
            <StatusBar barStyle="light-content" backgroundColor={colors.bg} />
            <KeyboardAvoidingView style={{ flex: 1 }}
                behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
                keyboardVerticalOffset={-15}>

                <Animated.ScrollView
                    contentContainerStyle={s.scroll}
                    showsVerticalScrollIndicator={false}
                    keyboardShouldPersistTaps="handled"
                    style={{ opacity: screenFade, transform: [{ translateY: screenSlide }] }}
                >

                    {/* Header */}
                    <View style={s.header}>
                        <Text style={s.title}>Monitor</Text>
                        <View style={s.headerRight}>
                            <PulseDot active={streaming} style={[s.dot, streaming && s.dotLive]} />
                            <Text style={s.headerLabel}>{streaming ? 'Live' : 'Idle'}</Text>
                        </View>
                    </View>

                    {/* Viewer */}
                    <View style={s.viewer}>
                        {displayFrame ? (
                            <DoubleBufferedImage
                                uri={displayFrame}
                                style={s.viewerImg}
                                resizeMode="contain"
                            />
                        ) : (
                            <View style={s.placeholder}>
                                <View style={s.phIconWrap}>
                                    <Ionicons name="desktop-outline" size={28} color={colors.textMuted} />
                                </View>
                                <Text style={s.phText}>No feed</Text>
                                <Text style={s.phSub}>Start streaming to see your desktop</Text>
                            </View>
                        )}
                    </View>

                    {/* Status badges + Controls row */}
                    <View style={s.statusControlRow}>
                        <View style={s.badges}>
                            <View style={s.badge}>
                                <PulseDot active={isActive} style={[s.badgeDot, isActive && { backgroundColor: colors.dot }]} />
                                <Text style={s.badgeText}>{agentState.status || 'idle'}</Text>
                            </View>
                            <View style={s.badge}>
                                <View style={[s.badgeDot, vlmOk && { backgroundColor: colors.success }]} />
                                <Text style={s.badgeText}>{agentState.vlmStatus || 'Offline'}</Text>
                            </View>
                        </View>
                        {isActive && (
                            <View style={s.secBtns}>
                                <TouchableOpacity style={s.secBtn}
                                    onPress={() => api.pause().catch(() => { })} activeOpacity={0.6}>
                                    <Ionicons name="pause" size={14} color={colors.textSecondary} />
                                </TouchableOpacity>
                                <TouchableOpacity style={s.secBtn}
                                    onPress={() => api.stop().catch(() => { })} activeOpacity={0.6}>
                                    <Ionicons name="square" size={11} color={colors.textSecondary} />
                                </TouchableOpacity>
                            </View>
                        )}
                    </View>

                    {/* Stream button */}
                    <TouchableOpacity style={[s.mainBtn, streaming && s.mainBtnStop]}
                        onPress={toggleStream} disabled={!connected} activeOpacity={0.7}>
                        <Ionicons name={streaming ? 'stop' : 'play'} size={14}
                            color={streaming ? '#FFF' : colors.bg} />
                        <Text style={[s.mainBtnText, !streaming && { color: colors.bg }]}>
                            {streaming ? 'Stop' : 'Start stream'}
                        </Text>
                    </TouchableOpacity>

                    {/* ── Live Reasoning Feed ───────────────────────── */}
                    <View style={s.feedSection}>
                        <View style={s.feedHeader}>
                            <Text style={s.feedTitle}>Activity</Text>
                            <PulseDot active={isActive} style={[s.feedDot, isActive && s.feedDotPulse]} />
                        </View>

                        {/* Current thought — animated */}
                        {agentState.lastThought && (
                            <Animated.View style={[s.currentCard, {
                                opacity: thoughtFade,
                                transform: [{ translateY: thoughtSlide }],
                            }]}>
                                <View style={s.currentHeader}>
                                    <View style={[ls.typeDot, ls.dotThought]} />
                                    <Text style={s.currentLabel}>
                                        {isActive ? 'Currently thinking' : 'Last thought'}
                                    </Text>
                                </View>
                                <Text style={s.currentBody} numberOfLines={6}>
                                    {agentState.lastThought}
                                </Text>
                            </Animated.View>
                        )}

                        {/* Current action — animated */}
                        {agentState.currentAction && (
                            <Animated.View style={[s.currentCard, s.actionCard, {
                                opacity: actionFade,
                                transform: [{ translateY: actionSlide }],
                            }]}>
                                <View style={s.currentHeader}>
                                    <View style={[ls.typeDot, ls.dotAction]} />
                                    <Text style={[s.currentLabel, { color: colors.dot }]}>Action</Text>
                                </View>
                                <Text style={s.currentBody} numberOfLines={3}>
                                    {agentState.currentAction}
                                </Text>
                            </Animated.View>
                        )}

                        {/* History log */}
                        {log.length > 0 && (
                            <View style={s.logSection}>
                                <Text style={s.logTitle}>Recent</Text>
                                {[...log].reverse().map((item, i) => (
                                    <LogEntry key={`${item.time}-${i}`} item={item} index={i} />
                                ))}
                            </View>
                        )}

                        {log.length === 0 && !agentState.currentAction && (
                            <View style={s.emptyFeed}>
                                <Ionicons name="chatbubble-ellipses-outline" size={20} color={colors.textMuted} />
                                <Text style={s.emptyFeedText}>
                                    Agent reasoning will appear here when working
                                </Text>
                            </View>
                        )}
                    </View>

                    {/* Bottom spacer for FAB */}
                    <View style={{ height: 80 }} />

                </Animated.ScrollView>

                {/* Floating Composer — inside KAV flow so keyboard pushes it up */}
                <View style={[s.fabContainer, { paddingBottom: Math.max(insets.bottom, 12) + 8 }]}>
                    <FloatingComposer connected={connected} />
                </View>
            </KeyboardAvoidingView>
        </View>
    );
}

/* ── Log Entry Styles ─────────────────────────────────────── */
const ls = StyleSheet.create({
    entry: {
        paddingVertical: 10, borderBottomWidth: 1,
        borderBottomColor: colors.border,
    },
    entryHeader: {
        flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 5,
    },
    typeDot: { width: 6, height: 6, borderRadius: 3 },
    dotThought: { backgroundColor: colors.accent },
    dotAction: { backgroundColor: colors.dot },
    typeLabel: { ...typography.small, fontWeight: '600', flex: 1 },
    timeLabel: { ...typography.small, color: colors.textMuted, fontSize: 10 },
    entryText: { ...typography.secondary, lineHeight: 18, fontSize: 12.5 },
});

/* ── Floating Composer Styles ─────────────────────────────── */
const fc = StyleSheet.create({
    wrap: {
        flexDirection: 'row', alignItems: 'center',
        justifyContent: 'flex-end', gap: 10,
        maxWidth: '100%',
    },
    inputBar: {
        flex: 1, flexDirection: 'row', alignItems: 'center',
        backgroundColor: colors.surface,
        borderRadius: radius.xl, borderWidth: 1, borderColor: colors.border,
        paddingHorizontal: 14, paddingVertical: 4,
        // Glassmorphic subtle shadow
        shadowColor: '#000', shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.3, shadowRadius: 12, elevation: 8,
    },
    input: {
        flex: 1, ...typography.body, fontSize: 14,
        paddingVertical: 10, color: colors.text,
    },
    sendBtn: {
        width: 30, height: 30, borderRadius: 15,
        backgroundColor: colors.surfaceBright,
        alignItems: 'center', justifyContent: 'center', marginLeft: 8,
    },
    sendBtnActive: { backgroundColor: colors.accent },
    fabOuter: {},
    fab: {
        width: 48, height: 48, borderRadius: 24,
        backgroundColor: colors.accent,
        alignItems: 'center', justifyContent: 'center',
        shadowColor: colors.accent, shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.3, shadowRadius: 12, elevation: 6,
    },
});

/* ── Screen Styles ────────────────────────────────────────── */
const s = StyleSheet.create({
    root: { flex: 1, backgroundColor: colors.bg },
    scroll: { padding: 20, paddingBottom: 20 },

    header: {
        flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end',
        marginBottom: 24,
    },
    title: { ...typography.hero, fontSize: 28 },
    headerRight: { flexDirection: 'row', alignItems: 'center', gap: 5, paddingBottom: 4 },
    dot: { width: 5, height: 5, borderRadius: 3, backgroundColor: colors.textMuted },
    dotLive: { backgroundColor: colors.dot },
    headerLabel: { ...typography.small },

    viewer: {
        aspectRatio: 16 / 9, backgroundColor: colors.surface,
        borderRadius: radius.xl, overflow: 'hidden',
        borderWidth: 1, borderColor: colors.border,
        justifyContent: 'center', alignItems: 'center',
    },
    viewerImg: { width: '100%', height: '100%' },
    placeholder: { alignItems: 'center', gap: 6 },
    phIconWrap: {
        width: 48, height: 48, borderRadius: 24, backgroundColor: colors.surfaceRaised,
        alignItems: 'center', justifyContent: 'center', marginBottom: 4,
    },
    phText: { ...typography.heading, color: colors.textSecondary },
    phSub: { ...typography.caption },

    /* Status + Controls inline */
    statusControlRow: {
        flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
        marginTop: 12,
    },
    badges: { flexDirection: 'row', gap: 6 },
    badge: {
        flexDirection: 'row', alignItems: 'center', gap: 6,
        paddingHorizontal: 12, paddingVertical: 8,
        backgroundColor: colors.surface, borderRadius: radius.full,
        borderWidth: 1, borderColor: colors.border,
    },
    badgeDot: { width: 5, height: 5, borderRadius: 3, backgroundColor: colors.textMuted },
    badgeText: { ...typography.small },
    secBtns: { flexDirection: 'row', gap: 6 },
    secBtn: {
        width: 36, height: 36, borderRadius: radius.md,
        alignItems: 'center', justifyContent: 'center',
        backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    },

    /* Stream button */
    mainBtn: {
        flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
        paddingVertical: 16, borderRadius: radius.xl, gap: 8,
        backgroundColor: colors.accent, marginTop: 16,
    },
    mainBtnStop: { backgroundColor: colors.error },
    mainBtnText: { fontSize: 14, fontWeight: '600', color: '#FFF' },

    /* ── Feed Section ─────── */
    feedSection: { marginTop: 28 },
    feedHeader: {
        flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 14,
    },
    feedTitle: { ...typography.heading, fontSize: 18 },
    feedDot: {
        width: 6, height: 6, borderRadius: 3, backgroundColor: colors.textMuted,
    },
    feedDotPulse: { backgroundColor: colors.dot },

    /* Current card — prominent */
    currentCard: {
        backgroundColor: colors.surface, borderRadius: radius.lg,
        padding: 16, marginBottom: 8,
        borderWidth: 1, borderColor: colors.border,
    },
    actionCard: {
        borderColor: `${colors.dot}30`,
    },
    currentHeader: {
        flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 8,
    },
    currentLabel: { ...typography.small, fontWeight: '600' },
    currentBody: { ...typography.secondary, lineHeight: 20 },

    /* Log history */
    logSection: { marginTop: 16 },
    logTitle: {
        ...typography.small, color: colors.textMuted,
        fontWeight: '600', marginBottom: 4, textTransform: 'uppercase',
        letterSpacing: 1,
    },

    /* Empty state */
    emptyFeed: {
        alignItems: 'center', gap: 8, paddingVertical: 32,
    },
    emptyFeedText: {
        ...typography.caption, textAlign: 'center', lineHeight: 18,
    },

    /* FAB container — NOT position:absolute so KAV can push it above keyboard */
    fabContainer: {
        paddingHorizontal: 20,
    },
});

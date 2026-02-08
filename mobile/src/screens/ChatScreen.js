/**
 * Rin — Chat Screen (v6 Modern)
 * Centered breathing hero. Contextual greeting. Low-profile suggestion chips.
 * No action card stacks. Purposeful minimalism with kinetic typography.
 */
import React, { useState, useRef, useEffect, useMemo } from 'react';
import {
    View, Text, TextInput, ScrollView, TouchableOpacity,
    StyleSheet, StatusBar, KeyboardAvoidingView, Platform,
    Animated, Dimensions, Easing,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { useSocket } from '../services/socket';
import api from '../services/api';
import { colors, spacing, radius, typography } from '../theme';

const { width: W, height: H } = Dimensions.get('window');

/* ── Greeting based on time of day ───────────────────────── */
function getGreeting() {
    const h = new Date().getHours();
    if (h < 5) return 'Late night?';
    if (h < 12) return 'Good morning.';
    if (h < 17) return 'Good afternoon.';
    if (h < 21) return 'Good evening.';
    return 'Late night?';
}

const SUGGESTIONS = [
    'What\'s on my screen?',
    'Open Spotify',
    'Search for something',
    'Help me with a task',
];

/* ── Breathing Orb — subtle animated presence ────────────── */
function BreathingOrb({ connected }) {
    const pulse = useRef(new Animated.Value(0)).current;
    useEffect(() => {
        if (connected) {
            Animated.loop(
                Animated.sequence([
                    Animated.timing(pulse, { toValue: 1, duration: 2400, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
                    Animated.timing(pulse, { toValue: 0, duration: 2400, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
                ])
            ).start();
        } else {
            pulse.setValue(0);
        }
    }, [connected]);

    const scale = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 1.15] });
    const opacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.3, 0.6] });

    return (
        <View style={es.orbWrap}>
            {connected && (
                <Animated.View style={[es.orbGlow, { transform: [{ scale }], opacity }]} />
            )}
            <View style={[es.orbCore, connected && es.orbCoreOn]} />
        </View>
    );
}


/* ── Message Bubble — inverted design ─────────────────────── */
function Bubble({ message, isUser }) {
    const fade = useRef(new Animated.Value(0)).current;
    const slide = useRef(new Animated.Value(8)).current;
    useEffect(() => {
        Animated.parallel([
            Animated.timing(fade, { toValue: 1, duration: 250, useNativeDriver: true }),
            Animated.timing(slide, { toValue: 0, duration: 250, useNativeDriver: true }),
        ]).start();
    }, []);

    return (
        <Animated.View style={[
            bs.row, isUser ? bs.rowUser : bs.rowAgent,
            { opacity: fade, transform: [{ translateY: slide }] },
        ]}>
            {!isUser && (
                <View style={bs.agentMark}>
                    <View style={bs.agentDot} />
                </View>
            )}
            <View style={[bs.bubble, isUser ? bs.bubbleUser : bs.bubbleAgent]}>
                <Text style={[bs.text, isUser && bs.textUser]}>{message.content || message.text}</Text>
            </View>
        </Animated.View>
    );
}

/* ── Typing indicator ─────────────────────────────────────── */
function Typing() {
    const dots = [useRef(new Animated.Value(0)).current, useRef(new Animated.Value(0)).current, useRef(new Animated.Value(0)).current];
    useEffect(() => {
        dots.forEach((d, i) => {
            Animated.loop(Animated.sequence([
                Animated.delay(i * 200),
                Animated.timing(d, { toValue: 1, duration: 350, useNativeDriver: true }),
                Animated.timing(d, { toValue: 0, duration: 350, useNativeDriver: true }),
                Animated.delay((2 - i) * 200),
            ])).start();
        });
    }, []);
    return (
        <View style={[bs.row, bs.rowAgent]}>
            <View style={bs.agentMark}><View style={bs.agentDot} /></View>
            <View style={[bs.bubble, bs.bubbleAgent, { flexDirection: 'row', gap: 5, paddingVertical: 16 }]}>
                {dots.map((d, i) => (
                    <Animated.View key={i} style={{
                        width: 4, height: 4, borderRadius: 2, backgroundColor: colors.textTertiary,
                        opacity: d.interpolate({ inputRange: [0, 1], outputRange: [0.25, 1] }),
                    }} />
                ))}
            </View>
        </View>
    );
}

/* ── Helpers: filter reasoning noise from chat ────────────── */
function isReasoningNoise(msg) {
    if (!msg || msg.role === 'user') return false;
    const t = (msg.content || msg.text || '').trim();
    if (/^\d+\.\s/.test(t) && t.split('\n').length > 2) return true;
    if (/^\[(?:CLICK|TYPE|SCROLL|MOVE|PRESS|WAIT)\]/.test(t)) return true;
    if (/^The active window is/.test(t)) return true;
    if (t.startsWith('Waking up the VLM engine')) return true;
    return false;
}

/* ── Screen ───────────────────────────────────────────────── */
export default function ChatScreen() {
    const insets = useSafeAreaInsets();
    const navigation = useNavigation();
    const { connected, chatMessages, setChatMessages, agentState } = useSocket();
    const [text, setText] = useState('');
    const [sending, setSending] = useState(false);
    const scrollRef = useRef(null);
    const inputRef = useRef(null);
    const thinking = agentState.status === 'thinking' || agentState.status === 'working';

    // Filter reasoning noise
    const visibleMessages = chatMessages.filter(m => !isReasoningNoise(m));
    const empty = visibleMessages.length === 0;

    // Hero entrance animation
    const heroFade = useRef(new Animated.Value(0)).current;
    const heroSlide = useRef(new Animated.Value(30)).current;
    useEffect(() => {
        Animated.parallel([
            Animated.timing(heroFade, { toValue: 1, duration: 800, easing: Easing.out(Easing.quad), useNativeDriver: true }),
            Animated.timing(heroSlide, { toValue: 0, duration: 800, easing: Easing.out(Easing.quad), useNativeDriver: true }),
        ]).start();
    }, []);

    // Contextual greeting
    const greeting = useMemo(() => getGreeting(), []);

    // Fetch chat history on mount
    useEffect(() => {
        (async () => {
            try {
                const res = await api.getChatHistory();
                if (res?.messages?.length) setChatMessages(res.messages);
            } catch (e) { console.log('History fetch failed:', e); }
        })();
    }, []);

    // Clear messages when agent goes idle after working
    const prevStatus = useRef(agentState.status);
    useEffect(() => {
        const wasActive = ['thinking', 'working', 'acting'].includes(prevStatus.current);
        const nowIdle = agentState.status === 'idle';
        if (wasActive && nowIdle) {
            const t = setTimeout(() => setChatMessages([]), 3000);
            return () => clearTimeout(t);
        }
        prevStatus.current = agentState.status;
    }, [agentState.status]);

    const send = async (m) => {
        const c = m || text.trim(); if (!c || sending) return;
        setSending(true); setText('');
        try {
            await api.sendChat(c);
            api.startStream().catch(() => { });
            navigation.navigate('Monitor');
        } catch (e) { console.log(e); }
        finally { setSending(false); }
    };

    const clearChat = () => setChatMessages([]);

    useEffect(() => {
        if (scrollRef.current && visibleMessages.length)
            setTimeout(() => scrollRef.current?.scrollToEnd?.({ animated: true }), 80);
    }, [visibleMessages.length]);

    return (
        <View style={[s.root, { paddingTop: insets.top }]}>
            <StatusBar barStyle="light-content" backgroundColor={colors.bg} />

            <KeyboardAvoidingView style={{ flex: 1 }}
                behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
                keyboardVerticalOffset={-15}>

                <ScrollView ref={scrollRef} style={{ flex: 1 }}
                    contentContainerStyle={[s.scroll, empty && { flex: 1 }]}
                    showsVerticalScrollIndicator={false} keyboardShouldPersistTaps="handled">

                    {empty ? (
                        /* ── Empty State: Centered breathing hero ── */
                        <View style={es.container}>
                            <View style={es.hero}>
                                <Animated.View style={{
                                    opacity: heroFade,
                                    transform: [{ translateY: heroSlide }],
                                    alignItems: 'center',
                                }}>
                                    <BreathingOrb connected={connected} />

                                    <Text style={es.greeting}>{greeting}</Text>
                                    <Text style={es.title}>What can I do</Text>
                                    <Text style={es.title}>for you?</Text>

                                    <View style={es.statusRow}>
                                        <View style={[es.statusDot, connected && es.statusDotOn]} />
                                        <Text style={es.statusText}>
                                            {connected ? 'Connected' : 'Offline'}
                                        </Text>
                                    </View>
                                </Animated.View>
                            </View>

                            {/* Suggestion chips */}
                            <Animated.View style={[es.chips, { opacity: heroFade }]}>
                                {SUGGESTIONS.map((s, i) => (
                                    <TouchableOpacity key={i} style={es.chip}
                                        onPress={() => send(s)} activeOpacity={0.6}>
                                        <Text style={es.chipText}>{s}</Text>
                                        <Ionicons name="arrow-forward" size={12} color={colors.textTertiary} />
                                    </TouchableOpacity>
                                ))}
                            </Animated.View>
                        </View>
                    ) : (
                        /* ── Messages ── */
                        <View style={s.msgArea}>
                            <View style={s.msgHeader}>
                                <View style={[s.statusDot, connected && s.statusDotOnline]} />
                                <Text style={s.msgHeaderTitle}>Rin</Text>
                                <View style={{ flex: 1 }} />
                                {!thinking && visibleMessages.length > 0 && (
                                    <TouchableOpacity onPress={clearChat} activeOpacity={0.6}
                                        style={{ paddingHorizontal: 8, paddingVertical: 4 }}>
                                        <Text style={s.clearBtn}>Clear</Text>
                                    </TouchableOpacity>
                                )}
                                {thinking && <Text style={s.msgHeaderStatus}>Working...</Text>}
                            </View>
                            {visibleMessages.map((msg, i) => (
                                <Bubble key={i} message={msg} isUser={msg.role === 'user'} />
                            ))}
                            {thinking && <Typing />}
                        </View>
                    )}
                </ScrollView>

                {/* Composer */}
                <View style={[s.composerWrap, { paddingBottom: Math.max(insets.bottom, 8) }]}>
                    <View style={s.composer}>
                        <TextInput ref={inputRef} style={s.input} value={text} onChangeText={setText}
                            placeholder="Message Rin..." placeholderTextColor={colors.textMuted}
                            multiline maxLength={5000} />
                        <TouchableOpacity style={[s.sendBtn, text.trim() && !sending && s.sendBtnActive]}
                            onPress={() => send()} disabled={!text.trim() || sending} activeOpacity={0.7}>
                            <Ionicons name="arrow-up" size={16}
                                color={text.trim() && !sending ? colors.bg : colors.textMuted} />
                        </TouchableOpacity>
                    </View>
                </View>
            </KeyboardAvoidingView>
        </View>
    );
}

/* ── Empty State Styles ──────────────────────────────────── */
const es = StyleSheet.create({
    container: { flex: 1, justifyContent: 'center' },

    hero: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
        paddingHorizontal: 40,
        paddingBottom: 20,
    },

    /* Breathing orb */
    orbWrap: {
        width: 48, height: 48, alignItems: 'center', justifyContent: 'center',
        marginBottom: 32,
    },
    orbGlow: {
        position: 'absolute',
        width: 48, height: 48, borderRadius: 24,
        backgroundColor: colors.accent,
    },
    orbCore: {
        width: 10, height: 10, borderRadius: 5,
        backgroundColor: colors.textMuted,
    },
    orbCoreOn: {
        backgroundColor: colors.accent,
    },

    /* Typography */
    greeting: {
        ...typography.secondary,
        fontSize: 14,
        color: colors.textSecondary,
        marginBottom: 12,
        letterSpacing: 0.3,
    },
    title: {
        fontSize: 32,
        fontWeight: '600',
        color: colors.text,
        letterSpacing: -1,
        lineHeight: 40,
        textAlign: 'center',
    },
    statusRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        marginTop: 20,
        paddingHorizontal: 14,
        paddingVertical: 6,
        borderRadius: radius.full,
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.border,
    },
    statusDot: {
        width: 5, height: 5, borderRadius: 3,
        backgroundColor: colors.offline,
    },
    statusDotOn: { backgroundColor: colors.online },
    statusText: {
        ...typography.small,
        color: colors.textTertiary,
    },

    /* Suggestion chips */
    chips: {
        paddingHorizontal: 20,
        paddingBottom: 12,
        gap: 6,
    },
    chip: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingVertical: 14,
        paddingHorizontal: 18,
        borderRadius: radius.lg,
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.border,
    },
    chipText: {
        ...typography.body,
        fontSize: 14,
        color: colors.textSecondary,
    },
});

/* ── Bubble Styles ────────────────────────────────────────── */
const bs = StyleSheet.create({
    row: { flexDirection: 'row', marginBottom: 6, maxWidth: '90%' },
    rowUser: { alignSelf: 'flex-end' },
    rowAgent: { alignSelf: 'flex-start' },
    agentMark: {
        width: 20, height: 20, borderRadius: 10, backgroundColor: colors.surface,
        alignItems: 'center', justifyContent: 'center', marginRight: 8, alignSelf: 'flex-end',
        borderWidth: 1, borderColor: colors.border,
    },
    agentDot: { width: 5, height: 5, borderRadius: 3, backgroundColor: colors.dot },
    bubble: { paddingHorizontal: 16, paddingVertical: 12, borderRadius: radius.xl, flexShrink: 1 },
    bubbleUser: { backgroundColor: colors.bubbleUser, borderBottomRightRadius: radius.xs },
    bubbleAgent: { backgroundColor: colors.surface, borderBottomLeftRadius: radius.xs, borderWidth: 1, borderColor: colors.border },
    text: { ...typography.body },
    textUser: { color: colors.bubbleUserText },
});

/* ── Screen Styles ────────────────────────────────────────── */
const s = StyleSheet.create({
    root: { flex: 1, backgroundColor: colors.bg },
    scroll: { paddingBottom: 4 },

    /* Messages */
    msgArea: { paddingHorizontal: 16, paddingTop: 8 },
    msgHeader: {
        flexDirection: 'row', alignItems: 'center', gap: 8,
        paddingVertical: 12, marginBottom: 8,
    },
    statusDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.offline },
    statusDotOnline: { backgroundColor: colors.online },
    msgHeaderTitle: { ...typography.heading },
    msgHeaderStatus: { ...typography.caption, color: colors.dot },
    clearBtn: { ...typography.small, color: colors.textMuted, fontSize: 12 },

    /* Composer */
    composerWrap: { paddingHorizontal: 16, paddingTop: 6, backgroundColor: colors.bg },
    composer: {
        flexDirection: 'row', alignItems: 'flex-end',
        backgroundColor: colors.surface, borderRadius: radius.xl,
        borderWidth: 1, borderColor: colors.border,
        paddingHorizontal: 16, paddingVertical: 6,
    },
    input: { flex: 1, ...typography.body, maxHeight: 100, paddingVertical: 10 },
    sendBtn: {
        width: 32, height: 32, borderRadius: 16, backgroundColor: colors.surfaceBright,
        alignItems: 'center', justifyContent: 'center', marginLeft: 8, marginBottom: 1,
    },
    sendBtnActive: { backgroundColor: colors.accent },
});

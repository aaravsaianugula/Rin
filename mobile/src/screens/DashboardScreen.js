/**
 * Rin — Dashboard Screen (v5 Radical)
 * Bold sections with large type. Inline status rows.
 * Power controls as full-width cards. Real-time state via Socket.IO.
 */
import React, { useState, useEffect } from 'react';
import {
    View, Text, ScrollView, TouchableOpacity, Switch,
    StyleSheet, StatusBar, RefreshControl,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useFocusEffect } from '@react-navigation/native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useSocket } from '../services/socket';
import api from '../services/api';
import { getApiUrl, DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT, DEFAULT_API_KEY } from '../config';
import { colors, spacing, radius, typography } from '../theme';

function Section({ title, children, style }) {
    return (
        <View style={[{ marginTop: 32 }, style]}>
            <Text style={s.sectionTitle}>{title}</Text>
            {children}
        </View>
    );
}

function Row({ icon, label, right, last }) {
    return (
        <View style={[s.row, !last && s.rowSep]}>
            <Ionicons name={icon} size={16} color={colors.textTertiary} style={{ marginRight: 12 }} />
            <Text style={s.rowLabel}>{label}</Text>
            <View style={{ flex: 1 }} />
            {typeof right === 'string' ? <Text style={s.rowValue}>{right}</Text> : right}
        </View>
    );
}

export default function DashboardScreen() {
    const insets = useSafeAreaInsets();
    const { connected, agentState } = useSocket();
    const [refreshing, setRefreshing] = useState(false);
    const [config, setConfig] = useState(null);
    const [models, setModels] = useState([]);
    const [activeModel, setActiveModel] = useState(null);
    const [wakeWord, setWakeWord] = useState(true);
    const [agentRunning, setAgentRunning] = useState(false);
    const [loading, setLoading] = useState(false);

    useEffect(() => { load(); }, []);

    // Reload saved config (especially API key) every time Dashboard gains focus
    useFocusEffect(
        React.useCallback(() => {
            (async () => {
                try {
                    const raw = await AsyncStorage.getItem('@rin_server_config');
                    if (raw) {
                        const c = JSON.parse(raw);
                        const h = c.host || DEFAULT_SERVER_HOST;
                        const p = c.port || DEFAULT_SERVER_PORT;
                        const k = c.apiKey || DEFAULT_API_KEY;
                        api.setBaseUrl(getApiUrl(h, p));
                        api.setApiKey(k);
                    }
                } catch { }
            })();
            load();
        }, [])
    );

    // ── Derive agentRunning from API polling (correct source of truth) ──
    // Socket.IO status is for task activity, not whether the process is alive
    useEffect(() => {
        if (!connected) {
            setAgentRunning(false);
            return;
        }
        // Poll agent status every 10s to catch crashes/stops
        const poll = () => {
            api.getAgentStatus().then(st => setAgentRunning(st.running ?? false)).catch(() => { });
        };
        poll(); // immediate check
        const interval = setInterval(poll, 10000);
        return () => clearInterval(interval);
    }, [connected]);

    // React to any socket terminal status — fast UI update when agent stops/crashes
    useEffect(() => {
        const st = agentState.status;
        const d = agentState.details || '';
        // Any idle status with stop/crash/exit/cancel context means agent is down
        if (st === 'idle' && (d.includes('exit') || d.includes('crash') || d.includes('stopped') || d.includes('cancel'))) {
            setAgentRunning(false);
        }
        // 'blocked' means circuit breaker or low memory prevented start
        if (st === 'blocked') {
            setAgentRunning(false);
        }
    }, [agentState.status, agentState.details]);

    const load = async () => {
        try {
            const [c, m, a, w, ag] = await Promise.all([
                api.getConfig().catch(() => null),
                api.getModels().catch(() => ({ models: [] })),
                api.getActiveModel().catch(() => ({})),
                api.getWakeWordStatus().catch(() => ({})),
                api.getAgentStatus().catch(() => ({})),
            ]);
            if (c && !c.error) setConfig(c);
            setModels(m.models || []);
            setActiveModel(a.model_id);
            setWakeWord(w.wake_word_enabled ?? true);
            setAgentRunning(ag.running ?? false);
        } catch (e) { console.log(e); }
    };

    const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };
    const toggleWakeWord = async (v) => { setWakeWord(v); try { await api.setWakeWord(v); } catch { setWakeWord(!v); } };
    const selectModel = async (id) => { const r = await api.setActiveModel(id).catch(() => null); if (r?.status === 'ok') setActiveModel(id); };

    const [alertMsg, setAlertMsg] = useState(null);

    const power = async (action) => {
        setLoading(true);
        setAlertMsg(null);
        try {
            let res;
            if (action === 'start') res = await api.startAgent();
            else if (action === 'stop') res = await api.stopAgent();
            else res = await api.restartAgent();

            // Handle blocked responses (circuit breaker, low memory)
            if (res?.status === 'blocked') {
                setAlertMsg(res.reason || 'Agent start blocked — too many crashes or low memory');
                setAgentRunning(false);
                return;
            }

            await new Promise(r => setTimeout(r, 2000));
            const st = await api.getAgentStatus().catch(() => ({}));
            setAgentRunning(st.running ?? false);
        } catch (e) {
            const msg = e?.data?.message || e?.message || 'Request failed';
            setAlertMsg(msg);
        } finally { setLoading(false); }
    };

    const vlmOk = agentState.vlmStatus === 'ONLINE' || agentState.vlmStatus === 'READY';

    return (
        <View style={[s.root, { paddingTop: insets.top }]}>
            <StatusBar barStyle="light-content" backgroundColor={colors.bg} />
            <ScrollView contentContainerStyle={s.scroll} showsVerticalScrollIndicator={false}
                refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh}
                    tintColor={colors.textSecondary} progressBackgroundColor={colors.surface} />}>

                {/* Hero header */}
                <Text style={s.heroTitle}>Dashboard</Text>

                {/* Agent power — big visual card */}
                <View style={s.powerCard}>
                    <View style={s.powerTop}>
                        <View style={s.powerDotWrap}>
                            <View style={[s.powerDot, agentRunning && s.powerDotOn]} />
                        </View>
                        <View>
                            <Text style={s.powerLabel}>Rin Agent</Text>
                            <Text style={s.powerStatus}>{agentRunning ? 'Running' : 'Stopped'}</Text>
                        </View>
                    </View>
                    <View style={s.powerBtns}>
                        {!agentRunning ? (
                            <TouchableOpacity style={s.accentBtn} onPress={() => power('start')} disabled={loading} activeOpacity={0.7}>
                                <Ionicons name="power" size={14} color={colors.bg} />
                                <Text style={s.accentBtnText}>{loading ? 'Starting...' : 'Start'}</Text>
                            </TouchableOpacity>
                        ) : (
                            <TouchableOpacity style={s.dangerBtn} onPress={() => power('stop')} disabled={loading} activeOpacity={0.7}>
                                <Ionicons name="stop-circle-outline" size={14} color="#FFF" />
                                <Text style={s.dangerBtnText}>{loading ? 'Stopping...' : 'Stop'}</Text>
                            </TouchableOpacity>
                        )}
                        <TouchableOpacity style={s.ghostBtn} onPress={() => power('restart')} disabled={loading} activeOpacity={0.6}>
                            <Ionicons name="refresh" size={14} color={colors.textSecondary} />
                        </TouchableOpacity>
                    </View>
                </View>

                {/* Alert banner for blocked start */}
                {alertMsg && (
                    <View style={s.alertBanner}>
                        <Ionicons name="warning-outline" size={16} color="#F59E0B" />
                        <Text style={s.alertText}>{alertMsg}</Text>
                        <TouchableOpacity onPress={() => setAlertMsg(null)}>
                            <Ionicons name="close" size={16} color={colors.textTertiary} />
                        </TouchableOpacity>
                    </View>
                )}

                {/* Status */}
                <Section title="Status">
                    <View style={s.card}>
                        <Row icon="wifi" label="Server" right={
                            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                                <Text style={s.rowValue}>{connected ? 'Online' : 'Offline'}</Text>
                                <View style={[s.smlDot, connected && { backgroundColor: colors.success }]} />
                            </View>} />
                        <Row icon="hardware-chip-outline" label="Vision" right={
                            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                                <Text style={s.rowValue}>{agentState.vlmStatus || 'Offline'}</Text>
                                <View style={[s.smlDot, vlmOk && { backgroundColor: colors.success }]} />
                            </View>} />
                        <Row icon="pulse" label="State" right={agentState.status || 'idle'} />
                        <Row icon="mic-outline" label="Wake word" last right={
                            <Switch value={wakeWord} onValueChange={toggleWakeWord}
                                trackColor={{ false: colors.surfaceBright, true: colors.accent }}
                                thumbColor={wakeWord ? colors.bg : '#FFF'} />
                        } />
                    </View>
                </Section>

                {/* Models */}
                {models.length > 0 && (
                    <Section title="Models">
                        <View style={s.card}>
                            {models.map((m, i) => (
                                <TouchableOpacity key={i} style={[s.row, i < models.length - 1 && s.rowSep]}
                                    onPress={() => selectModel(m.id)} activeOpacity={0.6}>
                                    <View style={[s.radio, m.id === activeModel && s.radioOn]}>
                                        {m.id === activeModel && <View style={s.radioInner} />}
                                    </View>
                                    <Text style={s.rowLabel}>{m.name || m.id}</Text>
                                </TouchableOpacity>
                            ))}
                        </View>
                    </Section>
                )}

                {/* Config — only show when agent is running and we have config data */}
                {config && Object.keys(config).length > 0 && (
                    <Section title="Config">
                        <View style={s.card}>
                            {Object.entries(config).slice(0, 6).map(([k, v], i, a) => (
                                <Row key={k} icon="settings-outline" label={k} right={String(v)} last={i === a.length - 1} />
                            ))}
                        </View>
                    </Section>
                )}

                <View style={{ height: 60 }} />
            </ScrollView>
        </View>
    );
}

const s = StyleSheet.create({
    root: { flex: 1, backgroundColor: colors.bg },
    scroll: { padding: 20 },

    heroTitle: { ...typography.hero, fontSize: 28, marginBottom: 24 },

    /* Power card — the hero element */
    powerCard: {
        backgroundColor: colors.surface, borderRadius: radius.xl,
        padding: 20, borderWidth: 1, borderColor: colors.border,
    },
    powerTop: { flexDirection: 'row', alignItems: 'center', gap: 14, marginBottom: 20 },
    powerDotWrap: {
        width: 40, height: 40, borderRadius: 20, backgroundColor: colors.surfaceRaised,
        alignItems: 'center', justifyContent: 'center',
        borderWidth: 1, borderColor: colors.border,
    },
    powerDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.textMuted },
    powerDotOn: { backgroundColor: colors.dot },
    powerLabel: { ...typography.heading },
    powerStatus: { ...typography.caption, marginTop: 2 },
    powerBtns: { flexDirection: 'row', gap: 8 },
    accentBtn: {
        flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
        paddingVertical: 14, borderRadius: radius.lg, gap: 6, backgroundColor: colors.accent,
    },
    accentBtnText: { fontSize: 13, fontWeight: '600', color: colors.bg },
    dangerBtn: {
        flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
        paddingVertical: 14, borderRadius: radius.lg, gap: 6, backgroundColor: colors.error,
    },
    dangerBtnText: { fontSize: 13, fontWeight: '600', color: '#FFF' },
    ghostBtn: {
        width: 48, alignItems: 'center', justifyContent: 'center',
        borderRadius: radius.lg, backgroundColor: colors.surfaceRaised,
        borderWidth: 1, borderColor: colors.border,
    },

    /* Sections */
    sectionTitle: { ...typography.label, marginBottom: 10, marginLeft: 2 },
    card: {
        backgroundColor: colors.surface, borderRadius: radius.lg,
        borderWidth: 1, borderColor: colors.border, overflow: 'hidden',
    },
    row: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 14 },
    rowSep: { borderBottomWidth: 1, borderBottomColor: colors.separator },
    rowLabel: { ...typography.body, fontSize: 14 },
    rowValue: { ...typography.secondary, fontSize: 13 },
    smlDot: { width: 5, height: 5, borderRadius: 3, backgroundColor: colors.textMuted },

    radio: {
        width: 18, height: 18, borderRadius: 9, borderWidth: 1.5,
        borderColor: colors.textMuted, marginRight: 12,
        alignItems: 'center', justifyContent: 'center',
    },
    radioOn: { borderColor: colors.accent },
    radioInner: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.accent },

    /* Alert banner */
    alertBanner: {
        flexDirection: 'row', alignItems: 'center', gap: 10,
        backgroundColor: 'rgba(245, 158, 11, 0.12)',
        borderWidth: 1, borderColor: 'rgba(245, 158, 11, 0.25)',
        borderRadius: radius.lg, padding: 14, marginTop: 12,
    },
    alertText: {
        flex: 1, fontSize: 13, color: '#F59E0B', lineHeight: 18,
    },
});

/**
 * Rin — Settings Screen (v5 Radical)
 * Clean grouped rows. Matches dashboard card style.
 * Includes self-update checker with APK download.
 */
import React, { useState, useEffect } from 'react';
import {
    View, Text, TextInput, ScrollView, TouchableOpacity,
    StyleSheet, StatusBar, ActivityIndicator, Alert, Linking, Platform,
    KeyboardAvoidingView,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import api from '../services/api';
import { getApiUrl, getSocketUrl, DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT, DEFAULT_API_KEY } from '../config';
import { colors, spacing, radius, typography } from '../theme';

const STORAGE_KEY = '@rin_server_config';

// Current app version — must match version.json on the server after a build
const APP_VERSION = '1.1.0';
const APP_VERSION_CODE = 2;

function Section({ title, children }) {
    return <View style={{ marginTop: 24 }}><Text style={s.sectionTitle}>{title}</Text><View style={s.card}>{children}</View></View>;
}

function Field({ label, value, onChangeText, placeholder, last, secureTextEntry, right }) {
    return (
        <View style={[s.field, !last && s.sep]}>
            <Text style={s.fieldLabel}>{label}</Text>
            <TextInput style={s.fieldInput} value={value} onChangeText={onChangeText}
                placeholder={placeholder} placeholderTextColor={colors.textMuted}
                autoCapitalize="none" autoCorrect={false} secureTextEntry={secureTextEntry} />
            {right}
        </View>
    );
}

function InfoRow({ label, value, last, right }) {
    return (
        <View style={[s.infoRow, !last && s.sep]}>
            <Text style={s.infoLabel}>{label}</Text>
            {right || <Text style={s.infoValue} numberOfLines={1}>{value}</Text>}
        </View>
    );
}

export default function SettingsScreen() {
    const insets = useSafeAreaInsets();
    const [host, setHost] = useState(DEFAULT_SERVER_HOST);
    const [port, setPort] = useState(String(DEFAULT_SERVER_PORT));
    const [apiKey, setApiKey] = useState(DEFAULT_API_KEY || '');
    const [testing, setTesting] = useState(false);
    const [saving, setSaving] = useState(false);
    const [testResult, setTestResult] = useState(null);
    const [showKey, setShowKey] = useState(false);

    // Update state
    const [checking, setChecking] = useState(false);
    const [updateInfo, setUpdateInfo] = useState(null); // null = not checked, object = result

    useEffect(() => {
        (async () => {
            try {
                const raw = await AsyncStorage.getItem(STORAGE_KEY);
                if (raw) {
                    const c = JSON.parse(raw);
                    if (c.host) setHost(c.host);
                    if (c.port) setPort(String(c.port));
                    if (c.apiKey !== undefined) setApiKey(c.apiKey);
                }
            } catch (e) { /* ignore */ }
        })();
    }, []);

    const testConn = async () => {
        setTesting(true); setTestResult(null);
        try {
            api.setBaseUrl(getApiUrl(host, port));
            api.setApiKey(apiKey);
            await api.getHealth();
            setTestResult('ok');
        } catch (e) { setTestResult('fail'); }
        finally { setTesting(false); }
    };

    const save = async () => {
        setSaving(true);
        try {
            const config = { host, port, apiKey };
            await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(config));
            api.setBaseUrl(getApiUrl(host, port));
            api.setApiKey(apiKey);
            setTestResult('saved');
        } catch (e) { setTestResult('fail'); }
        finally { setSaving(false); }
    };

    const reset = () => {
        setHost(DEFAULT_SERVER_HOST);
        setPort(String(DEFAULT_SERVER_PORT));
        setApiKey(DEFAULT_API_KEY || '');
        setTestResult(null);
        setUpdateInfo(null);
    };

    // ── Update check ──
    const checkUpdate = async () => {
        setChecking(true); setUpdateInfo(null);
        try {
            const info = await api.checkForUpdate();
            const serverCode = info.versionCode || 0;
            setUpdateInfo({
                ...info,
                hasUpdate: serverCode > APP_VERSION_CODE,
                upToDate: serverCode <= APP_VERSION_CODE,
            });
        } catch (e) {
            setUpdateInfo({ error: true, message: 'Could not reach server' });
        } finally {
            setChecking(false);
        }
    };

    const downloadUpdate = () => {
        const url = api.getApkUrl();
        if (Platform.OS === 'web') {
            // On web, open in new tab
            window.open(url, '_blank');
        } else {
            // On native, open link which triggers browser download
            Linking.openURL(url).catch(() => {
                Alert.alert('Download Error', 'Could not open download link');
            });
        }
    };

    const formatSize = (bytes) => {
        if (!bytes) return '';
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    };

    return (
        <View style={[s.root, { paddingTop: insets.top }]}>
            <StatusBar barStyle="light-content" backgroundColor={colors.bg} />
            <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
                <ScrollView contentContainerStyle={s.scroll} showsVerticalScrollIndicator={false} keyboardShouldPersistTaps="handled">
                    <Text style={s.heroTitle}>Settings</Text>

                    <Section title="Server">
                        <Field label="Host" value={host} onChangeText={setHost} placeholder="192.168.x.x" />
                        <Field label="Port" value={port} onChangeText={setPort} placeholder="8000" />
                        <Field label="Key" value={apiKey} onChangeText={setApiKey} placeholder="API key from server" last secureTextEntry={!showKey}
                            right={
                                <TouchableOpacity onPress={() => setShowKey(k => !k)} style={s.eyeBtn} activeOpacity={0.6}>
                                    <Ionicons name={showKey ? 'eye-off-outline' : 'eye-outline'} size={18} color={colors.textSecondary} />
                                </TouchableOpacity>
                            } />
                    </Section>

                    <View style={s.btnRow}>
                        <TouchableOpacity style={s.accentBtn} onPress={testConn} disabled={testing} activeOpacity={0.7}>
                            {testing ? <ActivityIndicator size="small" color={colors.bg} /> :
                                <><Ionicons name="pulse" size={14} color={colors.bg} /><Text style={s.accentBtnText}>Test</Text></>}
                        </TouchableOpacity>
                        <TouchableOpacity style={s.ghostBtn} onPress={save} disabled={saving} activeOpacity={0.7}>
                            <Ionicons name="checkmark" size={14} color={colors.textSecondary} />
                            <Text style={s.ghostBtnText}>{saving ? 'Saving' : 'Save'}</Text>
                        </TouchableOpacity>
                        <TouchableOpacity style={s.ghostBtn} onPress={reset} activeOpacity={0.6}>
                            <Ionicons name="refresh" size={14} color={colors.textSecondary} />
                            <Text style={s.ghostBtnText}>Reset</Text>
                        </TouchableOpacity>
                    </View>

                    {testResult && (
                        <View style={[s.result, testResult === 'ok' || testResult === 'saved' ? s.resultOk : s.resultFail]}>
                            <Ionicons name={testResult === 'ok' || testResult === 'saved' ? 'checkmark-circle' : 'close-circle'}
                                size={14} color={testResult === 'ok' || testResult === 'saved' ? colors.success : colors.error} />
                            <Text style={[s.resultText, { color: testResult === 'ok' || testResult === 'saved' ? colors.success : colors.error }]}>
                                {testResult === 'ok' ? 'Connected' : testResult === 'saved' ? 'Saved' : 'Connection failed'}
                            </Text>
                        </View>
                    )}

                    <Section title="Endpoints">
                        <InfoRow label="API" value={getApiUrl(host, port)} />
                        <InfoRow label="Socket" value={getSocketUrl(host, port)} last />
                    </Section>

                    <Section title="About">
                        <InfoRow label="App" value="Rin Mobile" />
                        <InfoRow label="Version" value={`${APP_VERSION} (${APP_VERSION_CODE})`} />
                        <InfoRow label="Update" last right={
                            <TouchableOpacity style={s.checkBtn} onPress={checkUpdate} disabled={checking} activeOpacity={0.7}>
                                {checking ? (
                                    <ActivityIndicator size="small" color={colors.textSecondary} />
                                ) : (
                                    <><Ionicons name="cloud-download-outline" size={14} color={colors.textSecondary} />
                                        <Text style={s.checkBtnText}>Check</Text></>
                                )}
                            </TouchableOpacity>
                        } />
                    </Section>

                    {/* Update result */}
                    {updateInfo && (
                        <View style={[s.updateCard, updateInfo.error && s.updateCardError]}>
                            {updateInfo.error ? (
                                <View style={s.updateRow}>
                                    <Ionicons name="cloud-offline-outline" size={16} color={colors.error} />
                                    <Text style={[s.updateText, { color: colors.error }]}>{updateInfo.message}</Text>
                                </View>
                            ) : updateInfo.upToDate ? (
                                <View style={s.updateRow}>
                                    <Ionicons name="checkmark-circle" size={16} color={colors.success} />
                                    <Text style={[s.updateText, { color: colors.success }]}>You're up to date</Text>
                                </View>
                            ) : (
                                <>
                                    <View style={s.updateRow}>
                                        <Ionicons name="arrow-up-circle" size={16} color={colors.accent} />
                                        <View style={{ flex: 1 }}>
                                            <Text style={s.updateTitle}>
                                                v{updateInfo.version} available
                                            </Text>
                                            {updateInfo.changelog && (
                                                <Text style={s.updateChangelog} numberOfLines={2}>
                                                    {updateInfo.changelog}
                                                </Text>
                                            )}
                                            {updateInfo.apk_size && (
                                                <Text style={s.updateSize}>{formatSize(updateInfo.apk_size)}</Text>
                                            )}
                                        </View>
                                    </View>
                                    {updateInfo.apk_available && (
                                        <TouchableOpacity style={s.downloadBtn} onPress={downloadUpdate} activeOpacity={0.7}>
                                            <Ionicons name="download-outline" size={14} color={colors.bg} />
                                            <Text style={s.downloadBtnText}>Download APK</Text>
                                        </TouchableOpacity>
                                    )}
                                </>
                            )}
                        </View>
                    )}

                    <View style={{ height: 60 }} />
                </ScrollView>
            </KeyboardAvoidingView>
        </View>
    );
}

const s = StyleSheet.create({
    root: { flex: 1, backgroundColor: colors.bg },
    scroll: { padding: 20 },
    heroTitle: { ...typography.hero, fontSize: 28 },

    sectionTitle: { ...typography.label, marginBottom: 10, marginLeft: 2 },
    card: {
        backgroundColor: colors.surface, borderRadius: radius.lg,
        borderWidth: 1, borderColor: colors.border, overflow: 'hidden',
    },
    sep: { borderBottomWidth: 1, borderBottomColor: colors.separator },

    field: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 13 },
    fieldLabel: { ...typography.label, width: 44 },
    fieldInput: { flex: 1, ...typography.body, padding: 0, fontSize: 14 },
    eyeBtn: { padding: 6, marginLeft: 4 },

    infoRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 13 },
    infoLabel: { ...typography.label },
    infoValue: { ...typography.secondary, fontSize: 13, maxWidth: '65%', textAlign: 'right' },

    btnRow: { flexDirection: 'row', gap: 8, marginTop: 16 },
    accentBtn: {
        flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
        paddingVertical: 14, borderRadius: radius.lg, gap: 6, backgroundColor: colors.accent,
    },
    accentBtnText: { fontSize: 13, fontWeight: '600', color: colors.bg },
    ghostBtn: {
        flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
        paddingVertical: 14, borderRadius: radius.lg, gap: 6,
        backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    },
    ghostBtnText: { fontSize: 13, fontWeight: '500', color: colors.textSecondary },

    result: {
        flexDirection: 'row', alignItems: 'center', gap: 8,
        paddingHorizontal: 14, paddingVertical: 10, borderRadius: radius.md, marginTop: 10,
    },
    resultOk: { backgroundColor: colors.successSoft },
    resultFail: { backgroundColor: colors.errorSoft },
    resultText: { ...typography.caption },

    // Check button (inline in About row)
    checkBtn: {
        flexDirection: 'row', alignItems: 'center', gap: 5,
        paddingHorizontal: 12, paddingVertical: 6,
        borderRadius: radius.md,
        backgroundColor: colors.surfaceRaised,
        borderWidth: 1, borderColor: colors.border,
    },
    checkBtnText: { ...typography.small, color: colors.textSecondary },

    // Update result card
    updateCard: {
        marginTop: 12,
        padding: 16,
        borderRadius: radius.lg,
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.border,
    },
    updateCardError: {
        backgroundColor: colors.errorSoft,
        borderColor: 'rgba(229, 80, 80, 0.2)',
    },
    updateRow: {
        flexDirection: 'row', alignItems: 'flex-start', gap: 10,
    },
    updateText: { ...typography.body, fontSize: 14 },
    updateTitle: { ...typography.heading, fontSize: 14, color: colors.accent },
    updateChangelog: { ...typography.secondary, fontSize: 13, marginTop: 4 },
    updateSize: { ...typography.caption, marginTop: 4 },

    downloadBtn: {
        flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
        gap: 6, marginTop: 14, paddingVertical: 12,
        borderRadius: radius.lg, backgroundColor: colors.accent,
    },
    downloadBtnText: { fontSize: 13, fontWeight: '600', color: colors.bg },
});

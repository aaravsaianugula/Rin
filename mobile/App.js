/**
 * Rin — App (v5 Radical)
 * Monochrome shell. Minimal chrome. Nothing OS dot in tab.
 */
import React, { useEffect, useState } from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { View, Text, StyleSheet, Platform, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';

import { SocketProvider, useSocket } from './src/services/socket';
import api from './src/services/api';
import { getApiUrl, getSocketUrl, DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT, DEFAULT_API_KEY } from './src/config';
import { colors, radius, typography } from './src/theme';

import ChatScreen from './src/screens/ChatScreen';
import MonitorScreen from './src/screens/MonitorScreen';
import DashboardScreen from './src/screens/DashboardScreen';
import SettingsScreen from './src/screens/SettingsScreen';

const Tab = createBottomTabNavigator();
const STORAGE_KEY = '@rin_server_config';

const ICONS = {
  Chat: { on: 'chatbubble', off: 'chatbubble-outline' },
  Monitor: { on: 'tv', off: 'tv-outline' },
  Dashboard: { on: 'grid', off: 'grid-outline' },
  Settings: { on: 'settings', off: 'settings-outline' },
};

function Banner() {
  const { connected } = useSocket();
  if (connected) return null;
  return (
    <View style={t.banner}>
      <View style={t.bannerDot} />
      <Text style={t.bannerText}>Not connected</Text>
    </View>
  );
}

function Tabs() {
  return (
    <>
      <Banner />
      <Tab.Navigator screenOptions={({ route }) => ({
        headerShown: false,
        tabBarIcon: ({ focused, color }) => (
          <Ionicons name={focused ? ICONS[route.name].on : ICONS[route.name].off} size={20} color={color} />
        ),
        tabBarActiveTintColor: colors.text,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarStyle: t.tabBar,
        tabBarLabelStyle: t.tabLabel,
      })}>
        <Tab.Screen name="Chat" component={ChatScreen} />
        <Tab.Screen name="Monitor" component={MonitorScreen} />
        <Tab.Screen name="Dashboard" component={DashboardScreen} />
        <Tab.Screen name="Settings" component={SettingsScreen} />
      </Tab.Navigator>
    </>
  );
}

function Shell({ children }) {
  if (Platform.OS !== 'web') return children;
  return (
    <View style={t.webOuter}>
      <View style={t.webInner}>{children}</View>
    </View>
  );
}

export default function App() {
  const [serverUrl, setServerUrl] = useState(null);
  const [apiKey, setApiKey] = useState(DEFAULT_API_KEY);

  useEffect(() => {
    (async () => {
      try {
        const st = await AsyncStorage.getItem(STORAGE_KEY);
        let host = DEFAULT_SERVER_HOST, port = DEFAULT_SERVER_PORT, key = DEFAULT_API_KEY;
        if (st) {
          const c = JSON.parse(st);
          host = c.host || host;
          port = c.port || port;
          key = c.apiKey || key;
        }
        api.setBaseUrl(getApiUrl(host, port));
        api.setApiKey(key);
        setApiKey(key);
        setServerUrl(getSocketUrl(host, port));
      } catch {
        api.setBaseUrl(getApiUrl(DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT));
        api.setApiKey(DEFAULT_API_KEY);
        setServerUrl(getSocketUrl(DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT));
      }
    })();
  }, []);

  if (!serverUrl) {
    return (
      <Shell>
        <View style={t.splash}>
          <Text style={t.splashTitle}>Rin.</Text>
        </View>
      </Shell>
    );
  }

  return (
    <Shell>
      <SafeAreaProvider>
        <SocketProvider serverUrl={serverUrl} apiKey={apiKey}>
          <NavigationContainer>
            <Tabs />
          </NavigationContainer>
        </SocketProvider>
      </SafeAreaProvider>
    </Shell>
  );
}

const t = StyleSheet.create({
  webOuter: { flex: 1, backgroundColor: '#000', alignItems: 'center', justifyContent: 'center' },
  webInner: {
    width: '100%', maxWidth: 412, height: '100%', maxHeight: 915,
    backgroundColor: colors.bg, overflow: 'hidden',
    borderRadius: Platform.OS === 'web' ? 20 : 0,
    ...(Platform.OS === 'web' ? {
      borderWidth: 1, borderColor: 'rgba(255,255,255,0.04)',
    } : {}),
  },

  tabBar: {
    backgroundColor: colors.bg, borderTopWidth: 0, elevation: 0,
    height: 70, paddingBottom: 14, paddingTop: 4,
  },
  tabLabel: { fontSize: 10, fontWeight: '500' },

  banner: {
    backgroundColor: colors.errorSoft, paddingVertical: 5,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
  },
  bannerDot: { width: 5, height: 5, borderRadius: 3, backgroundColor: colors.error },
  bannerText: { ...typography.small, color: colors.error },

  splash: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: colors.bg },
  splashTitle: { ...typography.display },
});

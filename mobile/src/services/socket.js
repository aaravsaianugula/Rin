/**
 * Rin Mobile — Socket.IO Real-Time Service
 * Manages WebSocket connection for live events.
 * Cleans up stale state when agent goes idle.
 */

import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import { io } from 'socket.io-client';

const SocketContext = createContext(null);

export function SocketProvider({ serverUrl, apiKey, children }) {
    const socketRef = useRef(null);
    const [connected, setConnected] = useState(false);
    const [agentState, setAgentState] = useState({
        status: 'idle',
        details: null,
        lastThought: null,
        currentAction: null,
        vlmStatus: 'OFFLINE',
        voiceState: 'idle',
        voicePartial: '',
        voiceLevel: 0,
    });
    const [latestFrame, setLatestFrame] = useState(null);
    const [chatMessages, setChatMessages] = useState([]);
    const [activityLog, setActivityLog] = useState([]);

    // Track previous status for idle-transition cleanup
    const prevStatusRef = useRef('idle');

    const connect = useCallback((url, key) => {
        if (socketRef.current) {
            socketRef.current.disconnect();
        }

        const socketOpts = {
            transports: ['websocket'],
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 5000,
            timeout: 10000,
        };

        if (key) {
            socketOpts.auth = { token: key };
        }

        const socket = io(url, socketOpts);

        socket.on('connect', () => {
            console.log('Socket connected');
            setConnected(true);
        });

        socket.on('disconnect', () => {
            console.log('Socket disconnected');
            setConnected(false);
        });

        socket.on('connect_error', (err) => {
            console.log('Socket error:', err.message);
            setConnected(false);
        });

        // ── Agent status — the core real-time event ──
        socket.on('status', (data) => {
            const newStatus = data.state || data.status || 'idle';
            const prevStatus = prevStatusRef.current;

            // Determine transition types
            const ACTIVE_STATES = ['thinking', 'working', 'acting', 'running', 'RUNNING', 'THINKING', 'PAUSED'];
            const TERMINAL_STATES = ['idle', 'DONE', 'ABORTED', 'ERROR', 'COMPLETE', 'blocked'];
            const wasActive = ACTIVE_STATES.includes(prevStatus);
            const nowTerminal = TERMINAL_STATES.includes(newStatus);
            const nowIdle = newStatus === 'idle';

            setAgentState(prev => ({
                ...prev,
                status: newStatus,
                details: data.details ?? null,
                vlmStatus: data.vlm_status || prev.vlmStatus,
                // Clear reasoning/action when transitioning to any terminal state
                ...(wasActive && nowTerminal ? {
                    lastThought: null,
                    currentAction: null,
                } : {}),
            }));

            // Clean up stale activity on any terminal transition from active
            if (wasActive && nowTerminal) {
                setActivityLog([]);
                setLatestFrame(null);
            }

            // On full idle (not DONE/ABORTED which show briefly), also clear everything
            if (nowIdle) {
                setAgentState(prev => ({
                    ...prev,
                    lastThought: null,
                    currentAction: null,
                    // If details mention crash/exit/offline, force VLM offline
                    ...(data.details && (data.details.includes('exit') || data.details.includes('crash') || data.details.includes('stopped'))
                        ? { vlmStatus: 'OFFLINE' } : {}),
                }));
                setActivityLog([]);
                setLatestFrame(null);
            }

            prevStatusRef.current = newStatus;
        });

        // ── Thought events ──
        socket.on('thought', (data) => {
            if (!data.text) return;
            setAgentState(prev => ({
                ...prev,
                lastThought: data.text,
            }));
            setActivityLog(prev => [...prev.slice(-29), {
                type: 'thought', text: data.text, time: Date.now(),
            }]);
        });

        // ── Action events ──
        socket.on('action', (data) => {
            const desc = `[${data.type}] ${data.description}`;
            setAgentState(prev => ({
                ...prev,
                currentAction: desc,
            }));
            setActivityLog(prev => [...prev.slice(-29), {
                type: 'action', text: desc, time: Date.now(),
            }]);
        });

        // ── Screen frame ──
        socket.on('frame', (data) => {
            if (data.image) {
                setLatestFrame(data.image);
            }
        });

        // ── Voice ──
        socket.on('voice_state', (data) => {
            setAgentState(prev => ({
                ...prev,
                voiceState: data.state,
                voicePartial: data.partial || '',
            }));
        });

        socket.on('voice_partial', (data) => {
            setAgentState(prev => ({
                ...prev,
                voicePartial: data.text,
            }));
        });

        socket.on('voice_level', (data) => {
            setAgentState(prev => ({
                ...prev,
                voiceLevel: data.level,
            }));
        });

        // ── Chat messages from agent ──
        socket.on('chat_message', (msg) => {
            setChatMessages(prev => [...prev.slice(-199), msg]);
        });

        socketRef.current = socket;
    }, []);

    useEffect(() => {
        if (serverUrl) {
            connect(serverUrl, apiKey);
        }
        return () => {
            if (socketRef.current) {
                socketRef.current.disconnect();
            }
        };
    }, [serverUrl, apiKey, connect]);

    const value = {
        socket: socketRef.current,
        connected,
        agentState,
        latestFrame,
        chatMessages,
        setChatMessages,
        activityLog,
        connect,
    };

    return (
        <SocketContext.Provider value={value}>
            {children}
        </SocketContext.Provider>
    );
}

export function useSocket() {
    return useContext(SocketContext);
}

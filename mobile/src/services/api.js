/**
 * Rin Mobile — REST API Service
 * Wraps all HTTP endpoints from server.py
 */

class ApiService {
    constructor() {
        this.baseUrl = '';
        this.apiKey = '';
    }

    setBaseUrl(url) {
        this.baseUrl = url.replace(/\/$/, '');
    }

    setApiKey(key) {
        this.apiKey = (key || '').trim();
    }

    async _fetch(path, options = {}) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 10000);

        try {
            const headers = {
                'Content-Type': 'application/json',
                ...options.headers,
            };
            // Include API key if configured
            if (this.apiKey) {
                headers['Authorization'] = `Bearer ${this.apiKey}`;
            }

            const res = await fetch(`${this.baseUrl}${path}`, {
                ...options,
                signal: controller.signal,
                headers,
            });
            return await res.json();
        } catch (err) {
            if (err.name === 'AbortError') {
                throw new Error('Request timed out');
            }
            throw err;
        } finally {
            clearTimeout(timeout);
        }
    }

    // Health & State
    async getHealth() {
        return this._fetch('/health');
    }

    async getState() {
        return this._fetch('/state');
    }

    // Task Management
    async submitTask(command) {
        return this._fetch('/task', {
            method: 'POST',
            body: JSON.stringify({ command }),
        });
    }

    async steer(context) {
        return this._fetch('/steer', {
            method: 'POST',
            body: JSON.stringify({ context }),
        });
    }

    async stop() {
        return this._fetch('/stop', { method: 'POST' });
    }

    async pause() {
        return this._fetch('/pause', { method: 'POST' });
    }

    async resume() {
        return this._fetch('/resume', { method: 'POST' });
    }

    // Chat (Mobile)
    async getChatHistory() {
        return this._fetch('/chat/history');
    }

    async sendMessage(message) {
        return this._fetch('/chat/send', {
            method: 'POST',
            body: JSON.stringify({ message }),
        });
    }

    // Alias used by ChatScreen
    async sendChat(message) {
        return this.sendMessage(message);
    }

    // Screen Streaming
    async startStream() {
        return this._fetch('/stream/start', { method: 'POST' });
    }

    async stopStream() {
        return this._fetch('/stream/stop', { method: 'POST' });
    }

    async getLatestFrame() {
        return this._fetch('/frame/latest');
    }

    // Config
    async getConfig() {
        return this._fetch('/config');
    }

    // Models
    async getModels() {
        return this._fetch('/models');
    }

    async switchModel(modelId) {
        return this._fetch('/model/switch', {
            method: 'POST',
            body: JSON.stringify({ model_id: modelId }),
        });
    }

    async getActiveModel() {
        return this._fetch('/model/active');
    }

    // Wake Word
    async enableWakeWord() {
        return this._fetch('/wake-word/enable', { method: 'POST' });
    }

    async disableWakeWord() {
        return this._fetch('/wake-word/disable', { method: 'POST' });
    }

    async getWakeWordStatus() {
        return this._fetch('/wake-word/status');
    }

    // Convenience: DashboardScreen calls setWakeWord(bool)
    async setWakeWord(enabled) {
        return enabled ? this.enableWakeWord() : this.disableWakeWord();
    }

    // Alias used by DashboardScreen
    async setActiveModel(modelId) {
        return this.switchModel(modelId);
    }

    // Agent Lifecycle (via rin_service.py)
    async getAgentStatus() {
        return this._fetch('/agent/status');
    }

    async startAgent() {
        return this._fetch('/agent/start', { method: 'POST' });
    }

    async stopAgent() {
        return this._fetch('/agent/stop', { method: 'POST' });
    }

    async restartAgent() {
        return this._fetch('/agent/restart', { method: 'POST' });
    }

    // Update check
    async checkForUpdate() {
        return this._fetch('/mobile/version');
    }

    getApkUrl() {
        return `${this.baseUrl}/mobile/apk`;
    }

    // Generic POST for MonitorScreen (pause/interrupt)
    async post(path) {
        return this._fetch(path, { method: 'POST' });
    }

    // Interrupt (used by MonitorScreen stop button)
    async interrupt() {
        return this._fetch('/stop', { method: 'POST' });
    }
}

export default new ApiService();


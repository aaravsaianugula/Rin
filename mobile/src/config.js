/**
 * Rin Mobile — Configuration
 */

// Default server address — user configures this in Settings
export const DEFAULT_SERVER_HOST = '192.168.1.X';  // Replace with your PC's LAN IP
export const DEFAULT_SERVER_PORT = 8000;
export const DEFAULT_API_KEY = '';  // Set after first backend run

export const getApiUrl = (host, port) => `http://${host}:${port}`;
export const getSocketUrl = (host, port) => `http://${host}:${port}`;

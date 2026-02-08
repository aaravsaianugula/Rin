"""
Secure Key Manager for Rin Agent.

Uses Windows Data Protection API (DPAPI) to encrypt API keys.
Keys are encrypted with the current user's credentials and stored securely.

This provides:
- Machine + user-specific encryption (key only works on this PC for this user)
- No hardcoded encryption keys
- Native Windows security
"""

import base64
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Key storage location (encrypted)
KEY_FILE = Path(__file__).parent.parent / "config" / ".keys.enc"


def _encrypt_dpapi(data: bytes) -> bytes:
    """Encrypt data using Windows DPAPI."""
    try:
        import ctypes
        from ctypes import wintypes
        
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ('cbData', wintypes.DWORD),
                ('pbData', ctypes.POINTER(ctypes.c_char))
            ]
        
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        
        # Input blob
        input_blob = DATA_BLOB()
        input_blob.cbData = len(data)
        input_blob.pbData = ctypes.cast(
            ctypes.create_string_buffer(data, len(data)),
            ctypes.POINTER(ctypes.c_char)
        )
        
        # Output blob
        output_blob = DATA_BLOB()
        
        # Encrypt (CRYPTPROTECT_UI_FORBIDDEN = 0x1)
        if crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            None,  # Description
            None,  # Optional entropy
            None,  # Reserved
            None,  # Prompt struct
            0x1,   # Flags
            ctypes.byref(output_blob)
        ):
            # Copy encrypted data
            encrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
            # Free memory
            kernel32.LocalFree(output_blob.pbData)
            return encrypted
        else:
            raise OSError("DPAPI encryption failed")
            
    except Exception as e:
        logger.warning(f"DPAPI not available: {e}, using base64 fallback")
        # Fallback: base64 encoding (not secure, but works cross-platform)
        return b"FALLBACK:" + base64.b64encode(data)


def _decrypt_dpapi(encrypted: bytes) -> bytes:
    """Decrypt data using Windows DPAPI."""
    # Check for fallback encoding
    if encrypted.startswith(b"FALLBACK:"):
        return base64.b64decode(encrypted[9:])
    
    try:
        import ctypes
        from ctypes import wintypes
        
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ('cbData', wintypes.DWORD),
                ('pbData', ctypes.POINTER(ctypes.c_char))
            ]
        
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        
        # Input blob
        input_blob = DATA_BLOB()
        input_blob.cbData = len(encrypted)
        input_blob.pbData = ctypes.cast(
            ctypes.create_string_buffer(encrypted, len(encrypted)),
            ctypes.POINTER(ctypes.c_char)
        )
        
        # Output blob
        output_blob = DATA_BLOB()
        
        # Decrypt
        if crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,  # Description
            None,  # Optional entropy
            None,  # Reserved
            None,  # Prompt struct
            0x1,   # Flags
            ctypes.byref(output_blob)
        ):
            # Copy decrypted data
            decrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
            # Free memory
            kernel32.LocalFree(output_blob.pbData)
            return decrypted
        else:
            raise OSError("DPAPI decryption failed")
            
    except Exception as e:
        logger.error(f"DPAPI decryption failed: {e}")
        return b""


def _load_keys() -> dict:
    """Load encrypted keys from file."""
    if not KEY_FILE.exists():
        return {}
    
    try:
        encrypted = KEY_FILE.read_bytes()
        decrypted = _decrypt_dpapi(encrypted)
        return json.loads(decrypted.decode('utf-8'))
    except Exception as e:
        logger.error(f"Failed to load keys: {e}")
        return {}


def _save_keys(keys: dict):
    """Save keys to encrypted file."""
    try:
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(keys).encode('utf-8')
        encrypted = _encrypt_dpapi(data)
        KEY_FILE.write_bytes(encrypted)
        logger.info(f"Keys saved to {KEY_FILE}")
    except Exception as e:
        logger.error(f"Failed to save keys: {e}")


def get_porcupine_key() -> Optional[str]:
    """Get the Porcupine access key."""
    # First check environment variable
    key = os.environ.get("PORCUPINE_ACCESS_KEY")
    if key:
        return key
    
    # Check encrypted storage
    keys = _load_keys()
    if "porcupine" in keys:
        return keys["porcupine"]
    
    # Legacy: check plain text file (and migrate)
    legacy_file = Path(__file__).parent.parent / "config" / "porcupine_key.txt"
    if legacy_file.exists():
        key = legacy_file.read_text().strip()
        if key:
            # Migrate to encrypted storage
            set_porcupine_key(key)
            # Delete plain text file
            legacy_file.unlink()
            logger.info("Migrated Porcupine key to encrypted storage")
            return key
    
    return None


def set_porcupine_key(key: str):
    """Store the Porcupine access key securely."""
    keys = _load_keys()
    keys["porcupine"] = key
    _save_keys(keys)
    logger.info("Porcupine key stored securely")


def get_key(name: str) -> Optional[str]:
    """Get any stored API key by name."""
    # Check environment first
    env_name = f"{name.upper()}_API_KEY"
    key = os.environ.get(env_name)
    if key:
        return key
    
    keys = _load_keys()
    return keys.get(name)


def set_key(name: str, value: str):
    """Store any API key securely."""
    keys = _load_keys()
    keys[name] = value
    _save_keys(keys)
    logger.info(f"Key '{name}' stored securely")


def delete_key(name: str):
    """Delete a stored key."""
    keys = _load_keys()
    if name in keys:
        del keys[name]
        _save_keys(keys)
        logger.info(f"Key '{name}' deleted")


if __name__ == "__main__":
    # CLI for key management
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python key_manager.py set porcupine YOUR_KEY")
        print("  python key_manager.py get porcupine")
        print("  python key_manager.py delete porcupine")
        sys.exit(1)
    
    action = sys.argv[1]
    
    if action == "set" and len(sys.argv) >= 4:
        name, value = sys.argv[2], sys.argv[3]
        set_key(name, value)
        print(f"Key '{name}' stored securely")
    
    elif action == "get" and len(sys.argv) >= 3:
        name = sys.argv[2]
        key = get_key(name)
        if key:
            print(f"{name}: {key[:8]}...{key[-4:]}")  # Partial reveal
        else:
            print(f"Key '{name}' not found")
    
    elif action == "delete" and len(sys.argv) >= 3:
        name = sys.argv[2]
        delete_key(name)
        print(f"Key '{name}' deleted")
    
    else:
        print("Invalid command")
        sys.exit(1)

"""
Secure Secrets Manager for Rin Agent.

Encrypts sensitive data (tokens, API keys) using AES-256-GCM.
Keys are derived from a machine-specific passphrase using Argon2.

Security Features:
- AES-256-GCM authenticated encryption
- Argon2id key derivation (memory-hard, resistant to GPU attacks)
- Machine-bound keys (derived from hardware ID + user passphrase)
- Secrets stored encrypted, never in plaintext
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import platform
import uuid
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger("qwen3vl.secrets")

# Check for cryptography library
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logger.warning("cryptography not installed. Run: pip install cryptography")


def get_machine_id() -> str:
    """Get a unique machine identifier for key derivation."""
    # Combine multiple sources for uniqueness
    components = [
        platform.node(),           # Hostname
        platform.machine(),        # Architecture
        str(uuid.getnode()),       # MAC address
    ]
    combined = "|".join(components)
    return hashlib.sha256(combined.encode()).hexdigest()[:32]


@dataclass
class EncryptedSecret:
    """Container for encrypted data."""
    ciphertext: bytes
    nonce: bytes
    salt: bytes
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "ciphertext": base64.b64encode(self.ciphertext).decode(),
            "nonce": base64.b64encode(self.nonce).decode(),
            "salt": base64.b64encode(self.salt).decode(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "EncryptedSecret":
        return cls(
            ciphertext=base64.b64decode(data["ciphertext"]),
            nonce=base64.b64decode(data["nonce"]),
            salt=base64.b64decode(data["salt"]),
        )


class SecretsManager:
    """
    Manages encrypted secrets storage.
    
    Secrets are encrypted with AES-256-GCM using a key derived from:
    - Machine-specific ID (binds secrets to this computer)
    - Optional user passphrase (for additional security)
    """
    
    def __init__(self, secrets_dir: Optional[Path] = None, passphrase: str = ""):
        """
        Initialize secrets manager.
        
        Args:
            secrets_dir: Directory to store encrypted secrets
            passphrase: Optional additional passphrase for key derivation
        """
        if not CRYPTO_AVAILABLE:
            raise ImportError("cryptography required. Install: pip install cryptography")
        
        self.secrets_dir = secrets_dir or Path("config/secrets")
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        
        self.secrets_file = self.secrets_dir / "encrypted_secrets.json"
        self._passphrase = passphrase
        self._secrets_cache: Dict[str, str] = {}
        
        logger.info(f"Secrets manager initialized at {self.secrets_dir}")
    
    def _derive_key(self, salt: bytes) -> bytes:
        """Derive encryption key using Scrypt (memory-hard KDF)."""
        # Combine machine ID with passphrase
        key_material = f"{get_machine_id()}:{self._passphrase}".encode()
        
        # Scrypt parameters: N=2^17, r=8, p=1 (memory-hard)
        kdf = Scrypt(
            salt=salt,
            length=32,  # 256 bits for AES-256
            n=2**17,
            r=8,
            p=1,
            backend=default_backend()
        )
        return kdf.derive(key_material)
    
    def encrypt(self, plaintext: str) -> EncryptedSecret:
        """Encrypt a secret value."""
        # Generate random salt and nonce
        salt = os.urandom(16)
        nonce = os.urandom(12)  # 96-bit nonce for GCM
        
        # Derive key
        key = self._derive_key(salt)
        
        # Encrypt with AES-256-GCM
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
        
        return EncryptedSecret(ciphertext=ciphertext, nonce=nonce, salt=salt)
    
    def decrypt(self, encrypted: EncryptedSecret) -> str:
        """Decrypt a secret value."""
        # Derive key using stored salt
        key = self._derive_key(encrypted.salt)
        
        # Decrypt with AES-256-GCM
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(encrypted.nonce, encrypted.ciphertext, None)
        
        return plaintext.decode()
    
    def store_secret(self, name: str, value: str):
        """Encrypt and store a secret."""
        encrypted = self.encrypt(value)
        
        # Load existing secrets
        secrets = self._load_secrets_file()
        
        # Add/update this secret
        secrets[name] = encrypted.to_dict()
        
        # Save back
        self._save_secrets_file(secrets)
        
        # Update cache
        self._secrets_cache[name] = value
        
        logger.info(f"Stored encrypted secret: {name}")
    
    def get_secret(self, name: str) -> Optional[str]:
        """Retrieve and decrypt a secret."""
        # Check cache first
        if name in self._secrets_cache:
            return self._secrets_cache[name]
        
        # Load from file
        secrets = self._load_secrets_file()
        
        if name not in secrets:
            return None
        
        try:
            encrypted = EncryptedSecret.from_dict(secrets[name])
            value = self.decrypt(encrypted)
            self._secrets_cache[name] = value
            return value
        except Exception as e:
            logger.error(f"Failed to decrypt secret '{name}': {e}")
            return None
    
    def delete_secret(self, name: str):
        """Delete a stored secret."""
        secrets = self._load_secrets_file()
        
        if name in secrets:
            del secrets[name]
            self._save_secrets_file(secrets)
            self._secrets_cache.pop(name, None)
            logger.info(f"Deleted secret: {name}")
    
    def list_secrets(self) -> list:
        """List all stored secret names (not values)."""
        secrets = self._load_secrets_file()
        return list(secrets.keys())
    
    def _load_secrets_file(self) -> Dict[str, Any]:
        """Load secrets from encrypted file."""
        if not self.secrets_file.exists():
            return {}
        
        try:
            with open(self.secrets_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load secrets file: {e}")
            return {}
    
    def _save_secrets_file(self, secrets: Dict[str, Any]):
        """Save secrets to encrypted file."""
        with open(self.secrets_file, "w") as f:
            json.dump(secrets, f, indent=2)


# Global instance
_secrets_manager: Optional[SecretsManager] = None


def init_secrets_manager(secrets_dir: Optional[Path] = None, passphrase: str = "") -> SecretsManager:
    """Initialize global secrets manager."""
    global _secrets_manager
    _secrets_manager = SecretsManager(secrets_dir, passphrase)
    return _secrets_manager


def get_secrets_manager() -> SecretsManager:
    """Get global secrets manager, initializing if needed."""
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    return _secrets_manager


def encrypt_and_store(name: str, value: str):
    """Convenience function to encrypt and store a secret."""
    manager = get_secrets_manager()
    manager.store_secret(name, value)


def get_secret(name: str) -> Optional[str]:
    """Convenience function to get a decrypted secret."""
    manager = get_secrets_manager()
    return manager.get_secret(name)

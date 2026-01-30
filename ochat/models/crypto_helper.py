"""
Helper module for RSA encryption/decryption in O'Chat
Uses hybrid encryption: RSA for key exchange, AES for data
Using pycryptodome for better compatibility across Odoo versions
"""
import base64
import json
import logging
import os

from Crypto.PublicKey import RSA
from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.Random import get_random_bytes
from Crypto.Hash import SHA256
from Crypto.Util.Padding import pad, unpad

_logger = logging.getLogger(__name__)

# Taille maximale des attachments: 100 MB
MAX_ATTACHMENT_SIZE = 100 * 1024 * 1024


def generate_rsa_keypair():
    """
    Generates an RSA keypair (4096 bits for maximum security)

    Returns:
        tuple: (private_key_pem, public_key_pem) in PEM string format
    """
    _logger.info("🔐 Generating RSA keypair (4096 bits)...")

    # Generate the private key with pycryptodome
    key = RSA.generate(4096)

    # Export to PEM
    private_pem = key.export_key('PEM').decode('utf-8')
    public_pem = key.publickey().export_key('PEM').decode('utf-8')

    _logger.info("✅ RSA keypair generated successfully")
    return private_pem, public_pem


def encrypt_message_hybrid(content, attachments, recipient_public_key_pem):
    """
    Encrypts a message and its attachments using hybrid encryption:
    - Generates a random AES key
    - Encrypts data with AES (fast)
    - Encrypts the AES key with RSA (secure)

    Args:
        content: The message content (str)
        attachments: List of attachments (list of dict)
        recipient_public_key_pem: Recipient's public key (str)

    Returns:
        dict: Encrypted data ready to be sent
    """
    try:
        # Validate attachment size
        total_size = 0
        for att in attachments:
            # Data is in base64, calculate the decoded size
            data_size = len(base64.b64decode(att.get('datas', '')))
            total_size += data_size
            if data_size > MAX_ATTACHMENT_SIZE:
                raise ValueError(f"Attachment '{att.get('name')}' exceeds max size of 100MB")

        if total_size > MAX_ATTACHMENT_SIZE * 5:  # Max 5 fichiers de 100MB
            raise ValueError(f"Total attachments size exceeds maximum (500MB)")

        # 1. Generate a random AES-256 key
        aes_key = get_random_bytes(32)  # 256 bits

        # 2. Prepare data to encrypt (JSON)
        data_to_encrypt = {
            'content': content or '',
            'attachments': attachments
        }
        plaintext = json.dumps(data_to_encrypt).encode('utf-8')

        # 3. Encrypt with AES-256-CBC
        cipher_aes = AES.new(aes_key, AES.MODE_CBC)
        iv = cipher_aes.iv

        # PKCS7 padding
        padded_plaintext = pad(plaintext, AES.block_size)
        ciphertext = cipher_aes.encrypt(padded_plaintext)

        # 4. Load recipient's public key
        recipient_public_key = RSA.import_key(recipient_public_key_pem.encode('utf-8'))

        # 5. Encrypt the AES key with RSA-OAEP
        cipher_rsa = PKCS1_OAEP.new(recipient_public_key, hashAlgo=SHA256)
        encrypted_aes_key = cipher_rsa.encrypt(aes_key)

        # 6. Return encrypted data in base64
        result = {
            'encrypted': True,
            'encrypted_aes_key': base64.b64encode(encrypted_aes_key).decode('utf-8'),
            'iv': base64.b64encode(iv).decode('utf-8'),
            'ciphertext': base64.b64encode(ciphertext).decode('utf-8')
        }

        _logger.info(f"🔒 Message encrypted (size: {len(ciphertext)} bytes, {len(attachments)} attachments)")
        return result

    except Exception as e:
        _logger.error(f"❌ Encryption failed: {str(e)}")
        raise


def decrypt_message_hybrid(encrypted_data, private_key_pem):
    """
    Decrypts a message encrypted with hybrid encryption

    Args:
        encrypted_data: The encrypted data (dict)
        private_key_pem: Private key for decryption (str)

    Returns:
        dict: {'content': str, 'attachments': list}
    """
    try:
        # 1. Load the private key
        private_key = RSA.import_key(private_key_pem.encode('utf-8'))

        # 2. Decrypt the AES key with RSA-OAEP
        encrypted_aes_key = base64.b64decode(encrypted_data['encrypted_aes_key'])
        cipher_rsa = PKCS1_OAEP.new(private_key, hashAlgo=SHA256)
        aes_key = cipher_rsa.decrypt(encrypted_aes_key)

        # 3. Decrypt data with AES
        iv = base64.b64decode(encrypted_data['iv'])
        ciphertext = base64.b64decode(encrypted_data['ciphertext'])

        cipher_aes = AES.new(aes_key, AES.MODE_CBC, iv)
        padded_plaintext = cipher_aes.decrypt(ciphertext)

        # Remove PKCS7 padding
        plaintext = unpad(padded_plaintext, AES.block_size)

        # 4. Parse the JSON
        decrypted_data = json.loads(plaintext.decode('utf-8'))

        _logger.info(f"🔓 Message decrypted successfully ({len(decrypted_data.get('attachments', []))} attachments)")
        return decrypted_data

    except Exception as e:
        _logger.error(f"❌ Decryption failed: {str(e)}")
        raise

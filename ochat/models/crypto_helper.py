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

# Taille maximale des attachments: 25 MB
MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024


def generate_rsa_keypair():
    """
    Génère une paire de clés RSA (4096 bits pour sécurité maximale)

    Returns:
        tuple: (private_key_pem, public_key_pem) en format PEM string
    """
    _logger.info("🔐 Generating RSA keypair (4096 bits)...")

    # Générer la clé privée avec pycryptodome
    key = RSA.generate(4096)

    # Exporter en PEM
    private_pem = key.export_key('PEM').decode('utf-8')
    public_pem = key.publickey().export_key('PEM').decode('utf-8')

    _logger.info("✅ RSA keypair generated successfully")
    return private_pem, public_pem


def encrypt_message_hybrid(content, attachments, recipient_public_key_pem):
    """
    Chiffre un message et ses pièces jointes avec chiffrement hybride:
    - Génère une clé AES aléatoire
    - Chiffre les données avec AES (rapide)
    - Chiffre la clé AES avec RSA (sécurisé)

    Args:
        content: Le contenu du message (str)
        attachments: Liste des pièces jointes (list of dict)
        recipient_public_key_pem: Clé publique du destinataire (str)

    Returns:
        dict: Données chiffrées prêtes à être envoyées
    """
    try:
        # Valider la taille des attachments
        total_size = 0
        for att in attachments:
            # Les données sont en base64, calculer la taille décodée
            data_size = len(base64.b64decode(att.get('datas', '')))
            total_size += data_size
            if data_size > MAX_ATTACHMENT_SIZE:
                raise ValueError(f"Attachment '{att.get('name')}' exceeds max size of 25MB")

        if total_size > MAX_ATTACHMENT_SIZE * 5:  # Max 5 fichiers de 25MB
            raise ValueError(f"Total attachments size exceeds maximum (125MB)")

        # 1. Générer une clé AES-256 aléatoire
        aes_key = get_random_bytes(32)  # 256 bits

        # 2. Préparer les données à chiffrer (JSON)
        data_to_encrypt = {
            'content': content or '',
            'attachments': attachments
        }
        plaintext = json.dumps(data_to_encrypt).encode('utf-8')

        # 3. Chiffrer avec AES-256-CBC
        cipher_aes = AES.new(aes_key, AES.MODE_CBC)
        iv = cipher_aes.iv

        # Padding PKCS7
        padded_plaintext = pad(plaintext, AES.block_size)
        ciphertext = cipher_aes.encrypt(padded_plaintext)

        # 4. Charger la clé publique du destinataire
        recipient_public_key = RSA.import_key(recipient_public_key_pem.encode('utf-8'))

        # 5. Chiffrer la clé AES avec RSA-OAEP
        cipher_rsa = PKCS1_OAEP.new(recipient_public_key, hashAlgo=SHA256)
        encrypted_aes_key = cipher_rsa.encrypt(aes_key)

        # 6. Retourner les données chiffrées en base64
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
    Déchiffre un message chiffré avec le chiffrement hybride

    Args:
        encrypted_data: Les données chiffrées (dict)
        private_key_pem: Clé privée pour déchiffrer (str)

    Returns:
        dict: {'content': str, 'attachments': list}
    """
    try:
        # 1. Charger la clé privée
        private_key = RSA.import_key(private_key_pem.encode('utf-8'))

        # 2. Déchiffrer la clé AES avec RSA-OAEP
        encrypted_aes_key = base64.b64decode(encrypted_data['encrypted_aes_key'])
        cipher_rsa = PKCS1_OAEP.new(private_key, hashAlgo=SHA256)
        aes_key = cipher_rsa.decrypt(encrypted_aes_key)

        # 3. Déchiffrer les données avec AES
        iv = base64.b64decode(encrypted_data['iv'])
        ciphertext = base64.b64decode(encrypted_data['ciphertext'])

        cipher_aes = AES.new(aes_key, AES.MODE_CBC, iv)
        padded_plaintext = cipher_aes.decrypt(ciphertext)

        # Retirer le padding PKCS7
        plaintext = unpad(padded_plaintext, AES.block_size)

        # 4. Parser le JSON
        decrypted_data = json.loads(plaintext.decode('utf-8'))

        _logger.info(f"🔓 Message decrypted successfully ({len(decrypted_data.get('attachments', []))} attachments)")
        return decrypted_data

    except Exception as e:
        _logger.error(f"❌ Decryption failed: {str(e)}")
        raise

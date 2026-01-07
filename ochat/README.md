# O'Chat - Odoo Module

Inter-instance communication module for Odoo with end-to-end encryption.

## Features

- 🔒 **End-to-End Encryption** - RSA-4096 + AES-256 hybrid encryption
- 💬 **Real-time Messaging** - Instant communication between Odoo instances
- 📎 **File Attachments** - Send encrypted files up to 25MB
- ✅ **Delivery Status** - WhatsApp-like message status indicators
- 🔄 **Auto-Retry** - Exponential backoff retry system
- 🎯 **Slash Commands** - `/help`, `/status`, `/ticket` for quick actions
- 📊 **Message Tracking** - Track pending, delivered, and read status

## Requirements

### System Requirements

- Odoo 18.0
- Python 3.8+
- PostgreSQL 12+

### Python Dependencies

The module requires these Python packages (automatically installed from `requirements.txt`):

- `pycryptodome>=3.19.0` - Cryptography library
- `requests>=2.31.0` - HTTP client

### External Dependencies

- **O'Chat FastAPI Server** - Central message routing server (required)

## Installation

### 1. Install Python Dependencies

```bash
# Navigate to the module directory
cd /path/to/addons/ochat

# Install dependencies in Odoo's Python environment
pip3 install -r requirements.txt
```

**For Odoo.sh:**
Add the dependencies to your `requirements.txt` at the repository root.

### 2. Install the Module

1. Copy the `ochat` folder to your Odoo addons directory
2. Restart Odoo server
3. Update the apps list: Settings → Apps → Update Apps List
4. Search for "O'Chat" and click Install

### 3. Configure the Module

Go to **Settings → O'Chat Configuration**:

1. **Central Server URL**: URL of your FastAPI server (e.g., `http://server:8000`)
2. Click **"Register This Instance"** to get an API key
3. The system will automatically generate encryption keys

## Usage

### Creating O'Chat Connections

1. Go to **Discuss → O'Chat Connections**
2. Click **Create**
3. Enter the remote instance UUID (get it from the remote instance's settings)
4. Enter a name for the connection
5. Save

A new channel will be created in Discuss for this connection.

### Sending Messages

1. Open the O'Chat channel in Discuss
2. Type your message
3. Press Enter to send
4. Message status indicators will show delivery progress:
   - ⏱️ Pending
   - ✓ Sent
   - ✓✓ Delivered (blue)
   - ✓✓ Read (blue + eye icon)

### Sending Files

1. Click the attachment button in Discuss
2. Select your file (max 25MB)
3. Files are automatically encrypted before sending

### Slash Commands

Available commands in O'Chat channels:

- `/help` - Show available commands
- `/status` - Show connection status and encryption info
- `/ticket` - Create a helpdesk ticket from conversation
- `/who` - List channel members
- `/leave` - Leave the conversation

## Configuration

### Settings Location

Settings → O'Chat Configuration

### Available Settings

| Setting | Description | Default |
|---------|-------------|---------|
| Central Server URL | FastAPI server URL | - |
| Instance UUID | Unique instance identifier | Auto-generated |
| API Key | Authentication key | Auto-generated |
| Webhook Secret | Webhook authentication | Auto-generated |
| Public Key | RSA public key (4096-bit) | Auto-generated |
| Private Key | RSA private key (encrypted) | Auto-generated |

### Security

- **Keys are auto-generated** on first registration
- **Private keys** are stored encrypted in Odoo
- **API keys** are required for all server communication
- **Webhook secrets** verify incoming messages

## Architecture

```
┌─────────────────┐                ┌─────────────────┐
│   Odoo A        │                │   Odoo B        │
│                 │                │                 │
│  ┌───────────┐  │                │  ┌───────────┐  │
│  │  O'Chat   │  │                │  │  O'Chat   │  │
│  │  Module   │  │                │  │  Module   │  │
│  └─────┬─────┘  │                │  └─────┬─────┘  │
│        │        │                │        │        │
│    Encrypt      │                │    Decrypt      │
│        │        │                │        │        │
└────────┼────────┘                └────────┼────────┘
         │                                  │
         │         ┌──────────────┐         │
         └────────▶│   FastAPI    │◀────────┘
                   │   Server     │
                   │              │
                   │  • Routing   │
                   │  • Retry     │
                   │  • Status    │
                   └──────────────┘
```

## Message Flow

### Sending a Message

1. User types message in Odoo A
2. O'Chat module encrypts with Odoo B's public key
3. Encrypted message sent to FastAPI server
4. FastAPI routes to Odoo B's webhook
5. Odoo B decrypts with its private key
6. Message appears in Discuss

### Delivery Confirmation

1. FastAPI sends delivery notification to Odoo A
2. Status icon updates in real-time
3. User sees ✓✓ (delivered)

### Read Receipt

1. User in Odoo B opens the message
2. Read notification sent to FastAPI
3. FastAPI notifies Odoo A
4. Status updates to ✓✓ + 👁️ (read)

## Retry System

Messages are automatically retried with exponential backoff:

| Attempt | Delay |
|---------|-------|
| 1 | 1 minute |
| 2 | 5 minutes |
| 3 | 15 minutes |
| 4 | 1 hour |
| 5 | 4 hours |
| 6 | 12 hours |
| 7 | 24 hours |

After 7 attempts, the message is marked as failed and the sender is notified.

## Troubleshooting

### Messages not sending

1. Check FastAPI server is running: `curl http://server:8000/health`
2. Verify API key in Settings → O'Chat
3. Check Odoo logs for errors

### Encryption errors

1. Verify both instances have generated keys
2. Check public key is accessible: `http://server:8000/api/v1/instances/{uuid}/public_key`
3. Re-register the instance if needed

### Webhooks not working

1. Verify webhook URL is accessible from FastAPI server
2. Check webhook secret matches in both systems
3. Test webhook manually:
   ```bash
   curl -X POST http://odoo:8069/ochat/webhook \
     -H "Authorization: Bearer YOUR_SECRET" \
     -H "Content-Type: application/json" \
     -d '{"source_instance_uuid":"test","content":"test"}'
   ```

### Status not updating

1. Clear browser cache and reload
2. Check bus notifications are working (other Discuss features work?)
3. Verify `_to_store()` method is being called (check logs)

## Development

### Running Tests

```bash
# Unit tests
python -m pytest tests/

# Integration tests
python -m pytest tests/integration/
```

### Code Structure

```
ochat/
├── __init__.py
├── __manifest__.py
├── requirements.txt
├── README.md
├── models/
│   ├── __init__.py
│   ├── discuss_channel.py      # Channel & messaging logic
│   ├── mail_message.py          # Message status tracking
│   ├── ochat_connection.py      # Connection management
│   ├── crypto_helper.py         # Encryption/decryption
│   └── res_config_settings.py  # Configuration
├── controllers/
│   ├── __init__.py
│   └── webhook.py               # Webhook endpoints
├── views/
│   ├── ochat_views.xml
│   └── res_config_settings_views.xml
├── security/
│   └── ir.model.access.csv
└── static/
    └── src/
        ├── core/
        │   ├── common/
        │   │   ├── message_status.xml    # Status icons
        │   │   └── thread_icon_patch.xml
        │   └── web/
        │       └── discuss_sidebar_category_item_patch.xml
        └── css/
            └── ochat_status.css
```

## Security Considerations

### Encryption

- **RSA-4096**: Industry-standard key size
- **AES-256-CBC**: Symmetric encryption for data
- **PKCS7 Padding**: Standard padding for AES
- **SHA-256**: Hash function for RSA-OAEP

### Best Practices

1. **Never share private keys** between instances
2. **Rotate API keys** periodically
3. **Use HTTPS** for FastAPI server in production
4. **Keep dependencies updated**
5. **Monitor failed messages** for security anomalies

## License

LGPL-3

## Support

For issues and feature requests:
- GitHub: https://github.com/your-org/ochat
- Documentation: See FastAPI server docs at http://server:8000/docs

## Changelog

### Version 1.0 (2026-01-06)

- ✨ Initial release
- 🔒 End-to-end encryption
- 💬 Real-time messaging
- 📎 File attachments
- ✅ Delivery status tracking
- 🔄 Auto-retry system
- 🎯 Slash commands

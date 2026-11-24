# LocalTransfer

Send pictures from your phone (Android or iPhone) to your PC over your home Wi-Fi.
There's no app to install on the phone. It works in the phone's browser.

- **10 pictures or fewer:** each picture is uploaded as its own file.
- **More than 10 pictures:** the phone packs them into a single `.zip` before uploading,
  for example `photos_2026-11-24_192922_12.zip`.

Files are saved to `~/Pictures/LocalTransfer/<date>/` on the PC.

## Requirements

- Python 3.9+ on the PC. Nothing else is required.
- Optional: `pip install qrcode` shows a QR code in the terminal for quick scanning.

## Usage

1. On the PC:

   ```bash
   python3 localtransfer.py
   ```

   (On Windows: `py localtransfer.py`)

2. Make sure the phone is on the **same Wi-Fi network** as the PC.
3. When asked for an access code, type your own (for example `myhome`) to get the same
   link every time, or press Enter for a random one.
4. Open the printed link (e.g. `http://192.168.1.20:8765/?t=Ab3xYz`) on the phone, or scan the QR code.
5. Tap **Choose pictures**, select your photos, then tap **Send to PC**.

### Options

| Option | Meaning |
| --- | --- |
| `-p, --port 8765` | Port to listen on |
| `-o, --output DIR` | Folder to save into |
| `--code CODE` | Set the access code without being asked (4–64 letters, digits, `-` or `_`) |

## Notes

- **Access code:** the `?t=…` part of the link is a random code. It stops other devices
  on your network from uploading to your PC. If you reuse the same code (typed at the
  prompt or passed with `--code`), the link stays the same, so you can bookmark it on
  your phone. Leave it empty to get a new random code each run.
- **Firewall:** the first time you run it, Windows or macOS may ask you to allow incoming
  connections. Allow it on *private* networks. If the phone can't connect, check this first.
- **iPhone:** iOS usually converts HEIC photos to JPEG when uploading through the browser.
  This is normal.
- Very large batches (about 4 GB or more) are sent as individual files instead of a zip.
- The transfer uses plain HTTP and is meant for a trusted home network.

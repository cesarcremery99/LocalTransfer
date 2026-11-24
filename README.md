# LocalTransfer

Send pictures from your phone (Android or iPhone) to your PC over your home Wi-Fi.
There's no app to install on the phone. It works in the phone's browser.

Pictures are saved directly into `~/Pictures/LocalTransfer/<date>/` on the PC, with their
original file names and dates.

Built for large transfers (thousands of pictures):

- 4 pictures upload at the same time, and each failed upload is retried automatically.
- **Pictures already on the PC are skipped.** If a transfer stops, choose the same pictures
  and tap Send again, and it continues where it stopped. You can also send a big library
  in several smaller selections without getting duplicates.
- The phone's screen stays on while sending (on browsers that support it, including
  iPhone Safari on iOS 16.4 and later). A **Stop** button and a time-left estimate are shown.

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

## Sending thousands of pictures (e.g. a whole iPhone library)

- **Selecting on iPhone:** the photo picker in the browser has no "Select All" button. Put
  your finger on the first photo, slide *sideways* along the row first, then down without
  lifting your finger. That selects whole rows and the picker scrolls by itself.
- **Or skip selecting entirely with an iPhone Shortcut** (see below).
- **Send in parts of about 500 to 1,000.** For each picture you select, the iPhone first
  copies it, converting it to JPEG if needed, before the upload starts. Selecting thousands
  at once can take a long time and uses a lot of free space on the phone. Because pictures
  already sent are skipped, overlapping selections are fine.
- Keep Safari open with the page visible until it finishes. iOS pauses web pages that are
  in the background. If that happens, come back and tap Send again.
- Use 5 GHz Wi-Fi and keep the phone near the router. That speed is the main limit.
- To know which pictures it already received, the PC keeps a list in
  `.localtransfer-received.txt` in the output folder. Delete that file if you want to
  send the same pictures again.

## iPhone Shortcut: send all photos without selecting

The Shortcuts app can find photos by itself, for example all photos or only those from the
last month, and send each one the PC doesn't have yet. On the phone page, open
**"iPhone: send ALL photos without selecting (Shortcut)"**. It lists the steps with your
PC's address and access code filled in, plus Copy buttons. In short:

1. **Find Photos** (Media Type is Image; optionally a Creation Date filter)
2. **Repeat with Each**, and inside it:
   1. **Get Details of Images** → Name, then again → Date Taken
   2. **Format Date** with the custom format `yyyyMMdd-HHmmss`
   3. **Get Contents of URL** `http://<PC>:8765/has?t=<code>` with the headers
      `X-Name` = Name and `X-Taken` = Formatted Date. The PC answers `yes` or `no`.
   4. **If** the result is `no`: **Get Contents of URL** `http://<PC>:8765/upload?t=<code>`,
      method POST, the same headers, Request Body **File** = Repeat Item.

Because the PC remembers what it has, you can run the shortcut again whenever you want
and it only sends new photos. Use a fixed access code (`--code`) so the URLs stay valid.
Photos arrive in their original format (usually HEIC). Add a **Convert Image** (JPEG) step
if you want JPEG. Photos sent by the shortcut and photos sent from the browser page are
tracked separately, so use one method for a given set of photos to avoid duplicates.

## Notes

- **Access code:** the `?t=…` part of the link is a random code. It stops other devices
  on your network from uploading to your PC. If you reuse the same code (typed at the
  prompt or passed with `--code`), the link stays the same, so you can bookmark it on
  your phone. Leave it empty to get a new random code each run.
- **Firewall:** the first time you run it, Windows or macOS may ask you to allow incoming
  connections. Allow it on *private* networks. If the phone can't connect, check this first.
- **iPhone:** iOS usually converts HEIC photos to JPEG when uploading through the browser.
  This is normal.
- The transfer uses plain HTTP and is meant for a trusted home network.

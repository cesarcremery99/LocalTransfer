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

The iPhone app **Shortcuts** (Dutch: **Opdrachten**) can find all photos by itself and send
them, so you don't have to select anything. On the phone page, open **"iPhone: send ALL
photos without selecting them"**. It shows the steps with your PC's link filled in and a
Copy button. The shortcut has only three actions:

1. **Find Photos** (NL: *Zoek foto's*)
2. **Repeat with Each** (NL: *Herhaal met elk*)
3. Inside the repeat: **Get Contents of URL** (NL: *Haal inhoud van URL op*) with the URL
   `http://<PC>:8765/upload?t=<code>`, method **POST**, request body **File** (NL: *Bestand*)
   = **Repeat Item** (NL: *Herhaalobject*).

The PC handles the rest:

- It names each photo after the date it was taken (e.g. `IMG_20230714_182205.heic`) and
  gives the file that date.
- **It never keeps the same photo twice.** It recognises a photo by its content, whether it
  came from the shortcut or the browser page, so running the shortcut again is safe.
  It does upload everything again, though, so for a large library send one period at a
  time with the *Creation Date* (NL: *Aanmaakdatum*) filter in Find Photos.
- Use a fixed access code (`--code`) so the pasted link keeps working.
- Photos arrive in their original format, usually HEIC. Windows can open these with
  Microsoft's free "HEIF Image Extensions".

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

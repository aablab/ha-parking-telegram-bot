# Parking Telegram Bot for Home Assistant OS

Home Assistant add-on repository for a Telegram bot that sends snapshots from a Home Assistant camera to approved neighbors.

## Installation

Upload **repository.yaml** and the **parking_bot/** directory to the ROOT of this GitHub repository (not inside another folder). In Home Assistant open **Settings → Add-ons → Add-on Store → ⋮ → Repositories** and add `https://github.com/aablab/ha-parking-telegram-bot`. Refresh the store and install **Parking Telegram Bot**.

In the add-on configuration, supply the **bot_token** obtained from BotFather. The default administrator ID is `509227228` and camera is `camera.192_168_31_87`. Turn on **Start on boot**, then start the add-on. In Telegram send `/start` to the bot.

- Approved users see the **📸 Що там парковка?** button.
- New users require approval by the administrator through inline buttons.
- `/users` lists approved Telegram IDs; `/revoke ID` removes access.
- One RAM-cached image shared across all approved users, refreshed on demand no more often than every 300 seconds.
- Available from 06:00 (inclusive) to 22:00 (exclusive) Kyiv time.
- No public camera URL, webhook, Home Assistant long-lived access token, or Frigate detector is required. The add-on uses the Supervisor-provided token and internal Home Assistant API camera proxy.

## Security

Never commit bot tokens or passwords. Images sent to recipients can be saved and forwarded. Delete the test `/config/www/parking_test.jpg` file if it exists because `/local/` may expose it without Home Assistant authentication.

## Diagnostics

Check **Add-on → Logs** if image delivery fails; verify that the camera supports camera proxy access. This add-on has not yet been tested on the user's Home Assistant installation.

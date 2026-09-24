from __future__ import annotations


APP_VERSION = "0.4.164-beta"
APP_REPOSITORY = "KNIGHT-AI-AV/talk-dat-releases"
APP_PRODUCT_URL = "https://www.talkdat.app/"
APP_RELEASES_URL = f"https://github.com/{APP_REPOSITORY}/releases"
# The update check's API URLs are built in updater.py from
# official_build.update_repository(), which is "" in a build from source, so
# no second copy of them may live here.
WINDOWS_INSTALLER_ASSET_NAME = "Talk-Dat-Setup.exe"
# Matched by suffix rather than by exact name: build-mac.sh stamps the version
# into the disk image, so the asset is Talk-DAT-0.4.39-beta.dmg.
MAC_INSTALLER_ASSET_SUFFIX = ".dmg"

# The updater asks for this by exact name. On macOS that name is a Windows
# executable, and asking for it there is how a Mac silently downloads a 118MB
# .exe it can never run -- auto-download is on by default, so nobody would even
# be asked first. macOS resolves its asset by suffix instead; see
# updater._select_release_assets.
INSTALLER_ASSET_NAME = WINDOWS_INSTALLER_ASSET_NAME
PORTABLE_ASSET_NAME = "Talk-Dat-Windows-Portable.zip"

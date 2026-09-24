# X-148: the industry-standard drag-to-install window, built HEADLESSLY.
#
# dmgbuild writes the .DS_Store directly (ds_store + mac_alias libraries), so
# no AppleScript, no Finder, no TCC Automation grant -- the exact failure that
# ruled out create-dmg. The window a downloader sees: the brand backdrop, the
# app icon on the left ring, the Applications folder on the right, a gold
# arrow saying what to do.
#
# Invoked by build-mac.sh as:
#   dmgbuild -s packaging/dmg_settings.py -D app=<bundle> -D version=<v> "Talk DAT!" <out.dmg>
import os.path

application = defines.get("app", "dist-mac/Talk DAT!.app")  # noqa: F821 - dmgbuild injects `defines`
appname = os.path.basename(application)

# Open source (2026-09-23): the licences travel at the root of the disk image
# as well as inside the bundle. build-mac.sh writes all three into
# Contents/Resources before signing; a bundle without them is not one this
# repository built, and dmgbuild failing on the missing file is the right
# answer. Placed below the drag-to-install window's visible area so X-148's
# layout is unchanged; they are in the volume root for anyone who looks.
LICENSE_FILES = ("LICENSE.txt", "NOTICE.txt", "THIRD_PARTY_LICENSES.txt")
licenses = [os.path.join(application, "Contents", "Resources", name) for name in LICENSE_FILES]

format = "UDZO"
size = None
files = [application, *licenses]
symlinks = {"Applications": "/Applications"}

badge_icon = None
icon_locations = {
    appname: (165, 240),
    "Applications": (495, 240),
    "LICENSE.txt": (110, 560),
    "NOTICE.txt": (330, 560),
    "THIRD_PARTY_LICENSES.txt": (550, 560),
}

background = "packaging/dmg-background.png"
window_rect = ((200, 140), (660, 420))
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False

arrange_by = None
grid_offset = (0, 0)
grid_spacing = 100
scroll_position = (0, 0)
label_pos = "bottom"
text_size = 13
icon_size = 110

#!/usr/bin/env bash
#
# Build Talk DAT! for macOS. The counterpart to build-exe.ps1.
#
#   ./build-mac.sh              build into dist-mac/
#   ./build-mac.sh --install    build, then replace /Applications/Talk DAT!.app
#   ./build-mac.sh --dmg        build, then package dist-mac/Talk-DAT-<version>.dmg
#   ./build-mac.sh --sign       deep-sign the bundle with the hardened runtime
#   ./build-mac.sh --notarize   sign, package, submit to Apple, staple the DMG
#   ./build-mac.sh --no-local-id   skip the local identity and stay ad-hoc
#
# Signing and notarising need two things this repository cannot contain:
#
#   TALK_DAT_SIGN_IDENTITY   the Developer ID Application certificate, as shown
#                            by `security find-identity -v -p codesigning`
#   TALK_DAT_NOTARY_PROFILE  a notarytool keychain profile, created once with
#                            `xcrun notarytool store-credentials`
#
# Until an app is signed with a Developer ID *and* notarised, Gatekeeper refuses
# it on every Mac except the one that built it. An ad-hoc build is a local
# build, whatever else is true of it.
#
# OFFICIAL or SOURCE (open source, 2026-09-23): scripts/write_build_flags.py
# bakes the answer into knight_flow/_build_flags.py right before PyInstaller and
# the module is deleted again afterwards, exactly as build-exe.ps1 does. A
# checkout carrying scripts/publish_release.py builds OFFICIAL; every other one
# builds SOURCE unless TALKDAT_OFFICIAL_BUILD=1/0 says otherwise. --notarize is
# the release path and refuses a SOURCE build, like publish_release.py does on
# Windows. See knight_flow/official_build.py and docs/NETWORK.md.
#
# Every build carries its licences: LICENSE.txt, NOTICE.txt and a generated
# THIRD_PARTY_LICENSES.txt (scripts/collect_licenses.py --strict) inside
# Contents/Resources, and the same three at the root of the disk image.
#
# Produces dist-mac/Talk DAT!.app, ad-hoc signed. Distribution needs a
# Developer ID Application certificate and notarisation -- see the end of this
# script, which says so rather than pretending the build is shippable.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

APP_NAME="Talk DAT!"
BUNDLE="dist-mac/${APP_NAME}.app"
# Homebrew moved `python3` from 3.13 to 3.14 and the new one has no PyInstaller,
# so a build that had worked for months died with "PyInstaller is not installed
# for python3" -- on a release night, after the Windows half had published. The
# repo's own .venv IS the interpreter this build is provisioned against, so
# prefer it, exactly as the dmgbuild step further down already prefers
# .venv-dmg. TALK_DAT_PYTHON still overrides everything.
_here="$(cd "$(dirname "$0")" && pwd)"
if [ -n "${TALK_DAT_PYTHON:-}" ]; then
    PYTHON="$TALK_DAT_PYTHON"
elif [ -x "$_here/.venv/bin/python" ] && "$_here/.venv/bin/python" -c "import PyInstaller" 2>/dev/null; then
    PYTHON="$_here/.venv/bin/python"
else
    PYTHON="python3"
fi

install_after_build=0
make_dmg=0
do_sign=0
do_notarize=0
use_local_id=1
for arg in "$@"; do
    case "$arg" in
        --install) install_after_build=1 ;;
        --dmg) make_dmg=1 ;;
        --sign) do_sign=1 ;;
        --notarize) do_notarize=1; do_sign=1; make_dmg=1 ;;
        --no-local-id) use_local_id=0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done
# A Developer ID supersedes the local identity entirely.
[ "$do_sign" -eq 1 ] && use_local_id=0

# --- A stable signature for local builds -------------------------------------
#
# macOS binds Accessibility, Microphone and Input Monitoring to an app's
# DESIGNATED REQUIREMENT, and for an ad-hoc signature that requirement is
#
#     designated => cdhash H"b149f528..."
#
# which is a hash of the build. Every rebuild produces a different one, so macOS
# sees a different app, and every permission has to be granted again -- roughly
# thirty times during this port, by hand, by the owner of the machine.
#
# Signing with any stable certificate replaces that with
#
#     designated => identifier "com.knightaiav.talkdat" and certificate leaf = H"..."
#
# which is identical across builds. Verified by signing two different binaries
# and diffing the requirement. A self-signed certificate is enough for this: the
# grant survives because the requirement matches, not because anyone trusts the
# certificate.
#
# This is NOT a substitute for a Developer ID. Gatekeeper still refuses this
# build on every other Mac, and nothing here makes it distributable. It only
# stops the machine that builds it from being asked the same question forever.
LOCAL_ID_DIR="$HOME/.talkdat-signing"
LOCAL_ID_NAME="Talk DAT Local Build"
LOCAL_KEYCHAIN="$LOCAL_ID_DIR/talkdat-build.keychain"
BUNDLE_ID="com.knightaiav.talkdat"

ensure_local_identity() {
    if [ -f "$LOCAL_KEYCHAIN" ] && [ -f "$LOCAL_ID_DIR/keychain.pass" ]; then
        return 0
    fi
    echo "==> Creating a local signing identity (one time)"
    mkdir -p "$LOCAL_ID_DIR"
    chmod 700 "$LOCAL_ID_DIR"
    # The keychain password is generated here and never leaves this directory.
    # It protects a self-signed certificate that can sign local builds and
    # nothing else, so it is not a credential in any meaningful sense -- and it
    # is emphatically not the login password, which this script never touches.
    local pass; pass="$(/usr/bin/openssl rand -hex 24)"
    printf '%s' "$pass" > "$LOCAL_ID_DIR/keychain.pass"
    chmod 600 "$LOCAL_ID_DIR/keychain.pass"

    cat > "$LOCAL_ID_DIR/cert.cnf" << CNF
[req]
distinguished_name=dn
x509_extensions=v3
prompt=no
[dn]
CN=$LOCAL_ID_NAME
O=Knight AI+AV
[v3]
basicConstraints=critical,CA:false
keyUsage=critical,digitalSignature
extendedKeyUsage=critical,codeSigning
CNF
    openssl req -x509 -newkey rsa:2048 -days 3650 -nodes \
        -keyout "$LOCAL_ID_DIR/key.pem" -out "$LOCAL_ID_DIR/cert.pem" \
        -config "$LOCAL_ID_DIR/cert.cnf" 2>/dev/null
    # -legacy: openssl 3 defaults to a PKCS12 MAC that Apple's security tool
    # rejects outright, with an error that reads like a wrong password.
    openssl pkcs12 -export -legacy \
        -inkey "$LOCAL_ID_DIR/key.pem" -in "$LOCAL_ID_DIR/cert.pem" \
        -out "$LOCAL_ID_DIR/identity.p12" -passout pass:x -name "$LOCAL_ID_NAME" 2>/dev/null
    chmod 600 "$LOCAL_ID_DIR"/key.pem "$LOCAL_ID_DIR"/identity.p12

    security create-keychain -p "$pass" "$LOCAL_KEYCHAIN" 2>/dev/null || true
    security unlock-keychain -p "$pass" "$LOCAL_KEYCHAIN"
    security set-keychain-settings "$LOCAL_KEYCHAIN"   # no auto-lock timeout
    security import "$LOCAL_ID_DIR/identity.p12" -k "$LOCAL_KEYCHAIN" -P x \
        -T /usr/bin/codesign -A >/dev/null
    # Without this, codesign triggers a GUI password prompt on every use --
    # which is the exact thing this whole mechanism exists to stop.
    security set-key-partition-list -S apple-tool:,apple:,codesign: \
        -s -k "$pass" "$LOCAL_KEYCHAIN" >/dev/null 2>&1
    rm -f "$LOCAL_ID_DIR/identity.p12"
    echo "    $LOCAL_ID_DIR  (delete this directory to undo)"
}

sign_with_local_identity() {
    local pass; pass="$(cat "$LOCAL_ID_DIR/keychain.pass")"
    security unlock-keychain -p "$pass" "$LOCAL_KEYCHAIN"
    # The keychain is put on the search list only for the duration of signing,
    # and taken off again below. Leaving a developer's search list permanently
    # altered by a build script is not this script's business.
    local previous; previous="$(security list-keychains -d user | sed 's/"//g' | tr -d ' ' | tr '\n' ' ')"
    # shellcheck disable=SC2086
    security list-keychains -d user -s $previous "$LOCAL_KEYCHAIN"
    local failed=0
    find "$BUNDLE" -type f \( -name "*.so" -o -name "*.dylib" \) -print0 2>/dev/null |
        while IFS= read -r -d '' item; do
            codesign --force --keychain "$LOCAL_KEYCHAIN" \
                --sign "$LOCAL_ID_NAME" "$item" >/dev/null 2>&1 || true
        done
    codesign --force --keychain "$LOCAL_KEYCHAIN" --identifier "$BUNDLE_ID" \
        --sign "$LOCAL_ID_NAME" "$BUNDLE/Contents/MacOS/$APP_NAME" >/dev/null 2>&1 || failed=1
    codesign --force --keychain "$LOCAL_KEYCHAIN" --identifier "$BUNDLE_ID" \
        --sign "$LOCAL_ID_NAME" "$BUNDLE" >/dev/null 2>&1 || failed=1
    # shellcheck disable=SC2086
    security list-keychains -d user -s $previous
    return $failed
}

# Credentials are checked before anything is built. Discovering a missing
# certificate after a sixty-second build and a twenty-second probe launch is a
# minute of nothing, and it is the failure most likely to be hit repeatedly.
if [ "$do_sign" -eq 1 ] && [ -z "${TALK_DAT_SIGN_IDENTITY:-}" ]; then
    echo "TALK_DAT_SIGN_IDENTITY is not set." >&2
    echo "  security find-identity -v -p codesigning   # to see what you have" >&2
    echo "  export TALK_DAT_SIGN_IDENTITY='Developer ID Application: ...'" >&2
    exit 1
fi
if [ "$do_notarize" -eq 1 ] && [ -z "${TALK_DAT_NOTARY_PROFILE:-}" ]; then
    echo "TALK_DAT_NOTARY_PROFILE is not set. Create one once with:" >&2
    echo "  xcrun notarytool store-credentials talk-dat \\" >&2
    echo "    --key <AuthKey_XXXX.p8> --key-id <KEY_ID> --issuer <ISSUER_UUID>" >&2
    exit 1
fi

echo "==> Python: $("$PYTHON" --version)"
"$PYTHON" -c "import PyInstaller" 2>/dev/null || {
    echo "PyInstaller is not installed for $PYTHON." >&2
    echo "  $PYTHON -m pip install pyinstaller" >&2
    exit 1
}

# tkinter is the whole interface, and Homebrew's python ships without it. A
# build that omits it succeeds and then produces an app that dies on launch, so
# it is worth one second to find out here instead.
"$PYTHON" -c "import tkinter" 2>/dev/null || {
    echo "tkinter is missing for $PYTHON. On Homebrew python that is a separate package:" >&2
    echo "  brew install python-tk@3.13" >&2
    exit 1
}

echo "==> Generating the icon from knight_flow/assets/app_icon.png"
ICONSET="build-mac/TalkDat.iconset"
rm -rf "$ICONSET" build-mac/TalkDat.icns
mkdir -p "$ICONSET"
"$PYTHON" - <<'PY'
from PIL import Image
src = Image.open("knight_flow/assets/app_icon.png").convert("RGBA")
for size in (16, 32, 128, 256, 512):
    src.resize((size, size), Image.LANCZOS).save(f"build-mac/TalkDat.iconset/icon_{size}x{size}.png")
    src.resize((size * 2, size * 2), Image.LANCZOS).save(
        f"build-mac/TalkDat.iconset/icon_{size}x{size}@2x.png"
    )
PY
iconutil -c icns "$ICONSET" -o build-mac/TalkDat.icns

echo "==> Build flags (official or source)"
# The receipt write_build_flags.py leaves in build/talk-dat-build-flags.json is
# what --require-official below, and scripts/build_mac_remote.py after a
# release build, read. BUILD_STARTED ties the check to THIS build's receipt.
BUILD_STARTED="$(date +%s)"
BUILD_FLAGS_SCRIPT="scripts/write_build_flags.py"
clean_build_flags() { "$PYTHON" "$BUILD_FLAGS_SCRIPT" --clean || true; }
trap clean_build_flags EXIT
"$PYTHON" "$BUILD_FLAGS_SCRIPT"
if [ "$do_notarize" -eq 1 ]; then
    # Before the build, not after it: a source build must not cost a build,
    # a signature and a notary round trip before being refused.
    "$PYTHON" "$BUILD_FLAGS_SCRIPT" --require-official --not-before "$BUILD_STARTED"
fi

echo "==> Building the app bundle"
rm -rf "$BUNDLE"
"$PYTHON" -m PyInstaller --noconfirm --clean \
    --distpath dist-mac --workpath build-mac/work \
    TalkDat-mac.spec
# The generated module is baked into the bundle now; the tree stays clean.
clean_build_flags
trap - EXIT

echo "==> Third-party licenses"
# Generated from the packages PyInstaller actually collected (its Analysis TOC)
# and the native libraries in the bundle. --strict fails the build on anything
# unresolved, on a GPL-only helper that slipped in, or on a PyAV library with
# no licence row. Written into the bundle BEFORE any signing below, so the
# signature seals them; the ad-hoc re-seal covers --no-local-id builds, whose
# PyInstaller signature adding files would otherwise break.
ANALYSIS_TOC="build-mac/work/TalkDat-mac/Analysis-00.toc"
if [ ! -f "$ANALYSIS_TOC" ]; then
    echo "Missing $ANALYSIS_TOC: cannot list exactly what the bundle carries." >&2
    exit 1
fi
RESOURCES="$BUNDLE/Contents/Resources"
"$PYTHON" scripts/collect_licenses.py --bundle "$BUNDLE" --analysis "$ANALYSIS_TOC" \
    --spec TalkDat-mac.spec --output "$RESOURCES/THIRD_PARTY_LICENSES.txt" --strict
cp LICENSE "$RESOURCES/LICENSE.txt"
cp NOTICE "$RESOURCES/NOTICE.txt"
if ! codesign --force --sign - "$BUNDLE" >/dev/null 2>&1; then
    echo "    WARNING: could not re-seal the bundle after adding the licences" >&2
fi

if [ "$use_local_id" -eq 1 ]; then
    ensure_local_identity
    echo "==> Signing with the local identity"
    if sign_with_local_identity; then
        requirement="$(codesign -d -r- "$BUNDLE" 2>&1 | grep -c 'cdhash' || true)"
        if [ "$requirement" -eq 0 ]; then
            echo "    requirement is identifier-based: permissions carry over"
        else
            echo "    WARNING: still cdhash-bound; permissions will reset again" >&2
        fi
    else
        echo "    local signing failed; the build stays ad-hoc" >&2
    fi
fi

# The build reporting success is not evidence the app runs: 0.4.35 shipped a
# bundle that exited immediately because PyInstaller dropped cryptography's
# compiled binding, and the build said nothing. Launch it and require it to
# still be alive afterwards. It runs AFTER signing, so what is probed is what
# gets installed -- a probe of the unsigned bundle proves nothing about the
# signed one, and re-signing is exactly the step that can break a launch.
# A Tk app cannot open a window without a logged-in GUI session, and the way
# that failure PRESENTS is a lie: Tk 9 (Homebrew moved tcl-tk to 9.0.4) computes
# `expr {[tk scaling] * 75}` inside ::tk::ScalingPct, `tk scaling` is NaN with no
# window server, and the probe dies spewing a Tcl trace through icons.tcl that
# reads like a Tk bug in the app. It is not. It is nobody being logged in.
# Say so before the probe, so the next release night does not spend an hour on it.
_console_user="$(stat -f '%Su' /dev/console 2>/dev/null || echo root)"
if [ "$_console_user" = "root" ] || [ -z "$_console_user" ]; then
    echo "" >&2
    echo "PROBE CANNOT RUN: nobody is logged in at this Mac's screen." >&2
    echo "  /dev/console belongs to '$_console_user' (root means the login window)." >&2
    echo "  The app is BUILT and SIGNED -- only the launch probe needs a desktop." >&2
    echo "  Log in on the Mac, then re-run this script." >&2
    echo "" >&2
    exit 1
fi

echo "==> Probe launch"
# The probe runs against its own app directory. Two reasons: the single-instance
# lock lives there, so probing while the installed copy is running would exit
# immediately and look like a crash; and a build should not write to the
# developer's real config, history or audio spool. The model cache is linked
# rather than copied so the probe warms from it instead of downloading 640MB.
PROBE_HOME="$(mktemp -d)"
REAL_HOME="$HOME/Library/Application Support/TalkDat"
if [ -d "$REAL_HOME/models" ]; then
    ln -s "$REAL_HOME/models" "$PROBE_HOME/models"
fi
trap 'rm -rf "$PROBE_HOME"' EXIT
TALK_DAT_HOME="$PROBE_HOME" "$BUNDLE/Contents/MacOS/$APP_NAME" >build-mac/probe.log 2>&1 &
probe_pid=$!
sleep 20
if kill -0 "$probe_pid" 2>/dev/null; then
    kill "$probe_pid" 2>/dev/null || true
    wait "$probe_pid" 2>/dev/null || true
    echo "    still running after 20s -- good"
else
    echo "PROBE LAUNCH FAILED: the app exited on its own." >&2
    echo "--- build-mac/probe.log ---" >&2
    tail -40 build-mac/probe.log >&2
    exit 1
fi

VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$BUNDLE/Contents/Info.plist")"
echo "==> Built ${APP_NAME} ${VERSION}  ($(du -sh "$BUNDLE" | cut -f1))"

if [ "$do_sign" -eq 1 ]; then
    if [ -z "${TALK_DAT_SIGN_IDENTITY:-}" ]; then
        echo "TALK_DAT_SIGN_IDENTITY is not set." >&2
        echo "  security find-identity -v -p codesigning   # to see what you have" >&2
        echo "  export TALK_DAT_SIGN_IDENTITY='Developer ID Application: ...'" >&2
        exit 1
    fi
    echo "==> Signing with ${TALK_DAT_SIGN_IDENTITY}"
    # --deep is deprecated and does not sign nested code correctly for
    # notarisation. Every Mach-O inside the bundle is signed individually,
    # innermost first, and the bundle last -- that ordering is what the notary
    # service checks.
    find "$BUNDLE" \( -name "*.so" -o -name "*.dylib" -o -perm +111 -type f \) -print0 2>/dev/null \
      | while IFS= read -r -d '' item; do
            if file "$item" 2>/dev/null | grep -q "Mach-O"; then
                codesign --force --timestamp --options runtime \
                    --entitlements mac-entitlements.plist \
                    --sign "$TALK_DAT_SIGN_IDENTITY" "$item" >/dev/null 2>&1 || true
            fi
        done
    codesign --force --timestamp --options runtime \
        --entitlements mac-entitlements.plist \
        --sign "$TALK_DAT_SIGN_IDENTITY" "$BUNDLE"
    echo "    verifying"
    codesign --verify --deep --strict --verbose=2 "$BUNDLE"
    # Gatekeeper's own answer, which is the one that matters. Before
    # notarisation it will still say "rejected"; after stapling it accepts.
    spctl --assess --type execute --verbose=4 "$BUNDLE" 2>&1 | sed 's/^/    /' || true
fi

if [ "$make_dmg" -eq 1 ]; then
    DMG="dist-mac/Talk-DAT-${VERSION}.dmg"
    echo "==> Packaging $DMG"
    rm -f "$DMG" dist-mac/rw.*.dmg
    # hdiutil rather than create-dmg on purpose. create-dmg arranges the window
    # with an AppleScript to Finder, which needs Automation permission; on a
    # machine that has not granted it the step fails with
    # "Not authorized to send Apple events to Finder (-1743)" and leaves a
    # multi-hundred-MB rw.*.dmg behind. A build should not depend on a TCC grant
    # for a cosmetic layout.
    # X-148, his spec: the drag-to-install dashboard every modern Mac app
    # ships. dmgbuild writes the .DS_Store directly -- no Finder, no
    # AppleScript, no TCC grant (the trap that ruled out create-dmg).
    # X-171: the fallback below shipped SILENTLY for every release since X-148.
    # dmgbuild was never installed, Homebrew's python3 is PEP 668 externally
    # managed so it could not be, and the one-line warning scrolled past in a
    # 300-line build log. Result: the settings file describing the
    # drag-to-Applications window existed and was never once used, and every
    # downloader got a bare Finder window instead.
    #
    # Two changes. The interpreter is the dedicated venv that HAS dmgbuild
    # (system python3 cannot, and pretending otherwise is what hid this), and a
    # missing layout is now a loud, explicit downgrade rather than a footnote.
    DMG_PY=""
    for candidate in ".venv-dmg/bin/python" "python3"; do
        if "$candidate" -c "import dmgbuild" 2>/dev/null; then DMG_PY="$candidate"; break; fi
    done
    if [ -n "$DMG_PY" ]; then
        "$DMG_PY" -m dmgbuild -s packaging/dmg_settings.py -D "app=$BUNDLE" "Talk DAT!" "$DMG" >build-mac/dmg.log 2>&1
        echo "    drag-to-Applications window: yes ($DMG_PY)"
    else
        echo ""
        echo "    #########################################################"
        echo "    ##  NO DRAG-TO-APPLICATIONS WINDOW IN THIS DMG         ##"
        echo "    ##  dmgbuild is missing. Downloaders will see a bare   ##"
        echo "    ##  Finder window with no background and no arrow.     ##"
        echo "    ##  Fix:  python3 -m venv .venv-dmg                    ##"
        echo "    ##        .venv-dmg/bin/pip install dmgbuild           ##"
        echo "    #########################################################"
        echo ""
        STAGE="build-mac/dmg-stage"
        rm -rf "$STAGE"
        mkdir -p "$STAGE"
        cp -R "$BUNDLE" "$STAGE/"
        ln -s /Applications "$STAGE/Applications"
        # The same three licence files dmg_settings.py puts at the root.
        cp "$RESOURCES/LICENSE.txt" "$RESOURCES/NOTICE.txt" "$RESOURCES/THIRD_PARTY_LICENSES.txt" "$STAGE/"
        hdiutil create -volname "Talk DAT!" -srcfolder "$STAGE"             -ov -format UDZO "$DMG" >build-mac/dmg.log 2>&1
        rm -rf "$STAGE"
    fi
    echo "    $(du -sh "$DMG" | cut -f1)  $DMG"
    echo "    NOTE: unsigned and un-notarised. Gatekeeper will refuse this on"
    echo "          any Mac that downloads it. Signing needs a Developer ID."
fi

if [ "$do_notarize" -eq 1 ]; then
    if [ -z "${TALK_DAT_NOTARY_PROFILE:-}" ]; then
        echo "TALK_DAT_NOTARY_PROFILE is not set. Create one once with:" >&2
        echo "  xcrun notarytool store-credentials talk-dat \\" >&2
        echo "    --key <AuthKey_XXXX.p8> --key-id <KEY_ID> --issuer <ISSUER_UUID>" >&2
        exit 1
    fi
    echo "==> Submitting to Apple for notarisation (this takes minutes, not seconds)"
    xcrun notarytool submit "$DMG" \
        --keychain-profile "$TALK_DAT_NOTARY_PROFILE" --wait
    echo "==> Stapling the ticket"
    # Stapling matters: without it the ticket is only visible to a Mac that can
    # reach Apple, and a first launch offline is refused.
    xcrun stapler staple "$DMG"
    xcrun stapler validate "$DMG"
    echo "==> Gatekeeper's verdict on the notarised bundle"
    spctl --assess --type execute --verbose=4 "$BUNDLE" 2>&1 | sed 's/^/    /' || true
fi

if [ "$install_after_build" -eq 1 ]; then
    echo "==> Installing to /Applications"
    # Quit a running copy first; replacing the bundle underneath it leaves the
    # old process running against files that no longer exist.
    pkill -f "/Applications/${APP_NAME}.app" 2>/dev/null || true
    sleep 2
    rm -rf "/Applications/${APP_NAME}.app"
    cp -R "$BUNDLE" /Applications/
    echo "    installed: /Applications/${APP_NAME}.app"
    if [ "$use_local_id" -eq 1 ] && [ -f "$LOCAL_KEYCHAIN" ]; then
        cat <<'NOTE'

    macOS ties Accessibility, Microphone and Input Monitoring to the app's
    signature. This build is signed with a stable local identity, so those
    grants now carry across every rebuild instead of being cleared by each one.

    The change of identity invalidates whatever was granted to the previous
    ad-hoc builds, so each permission needs granting ONCE more -- and then not
    again. Talk DAT! opens the permission page by itself when one is missing,
    and Status > Permissions goes straight to the right settings pane.

    This is still a local build. Gatekeeper refuses it on any other Mac until
    it is signed with a Developer ID and notarised.
NOTE
    else
        cat <<'NOTE'

    This build is ad-hoc signed, so its signature changes every time and every
    macOS permission has to be granted again after each build. Drop
    --no-local-id to sign with a stable local identity instead.
NOTE
    fi
fi

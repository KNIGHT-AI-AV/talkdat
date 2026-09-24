from __future__ import annotations

import sys

from . import mac_support

import time
from dataclasses import dataclass
from typing import Any


ONBOARDING_VERSION = 3

# X-428: terms are shown once, on the last setup step, above the button that
# finishes setup. "Continued use implies acceptance" (browsewrap) is enforced in
# roughly 14% of US cases against ~70% for an affirmative click, and modern
# privacy law wants consent to be an act rather than an inference -- so the act
# is the Finish press the person was making anyway, and what it accepted is
# recorded here. Bump TERMS_VERSION only when the terms change materially; the
# wizard re-asks when the recorded version is older.
TERMS_VERSION = "2026-09-22"
TERMS_URL = "https://www.talkdat.app/terms.html"
PRIVACY_URL = "https://www.talkdat.app/privacy.html"


@dataclass(frozen=True)
class OnboardingStep:
    id: str
    label: str
    title: str
    description: str


ONBOARDING_STEPS = (
    # X-149, from a real first launch: the wizard used to open on "choose
    # how you want to begin" -- decisions before a hello. One simple page
    # now leads: the logo, the pill, what the product does, nothing to
    # decide.
    OnboardingStep(
        "intro",
        "Hello",
        "Talk DAT!",
        "Hold your shortcut, talk, and the text appears where you're typing.",
    ),
    # X-484: the "access" step is REMOVED. It asked for a trial, a plan or an
    # account before the person had spoken a word, and the trial was for a
    # managed cloud that no longer exists. Restoring a licence, its one real
    # job, lives in the Pill menu under "Account & license" and is reachable
    # at any time instead of being demanded up front.
    OnboardingStep(
        "welcome",
        "Welcome",
        "What stays on your computer",
        "See what is off by default, what is kept safe, and where your speech goes.",
    ),
    # X-484: not a choice any more, a statement. There are two routes, local
    # and the person's own key, and local is the default that already works.
    # Asking somebody to pick when one answer is right and costs nothing is a
    # page to click past, so this tells them where their voice goes and
    # mentions the other route without demanding a decision about it.
    OnboardingStep(
        "voice",
        "Voice",
        "Your voice stays here",
        "Speech becomes text on this machine, with no account and no internet. You can point Talk DAT! at your own provider key later if you want to.",
    ),
    *(
        (
            OnboardingStep(
                # X-23, macOS only. It sits here deliberately: every page after
                # this one trips one of these gates. The mic meter needs the
                # microphone, the trigger rehearsal needs Input Monitoring, and
                # the closing dictation test needs Accessibility to deliver a
                # single character. Asked afterwards, each looks like a bug.
                "permissions",
                # Not "Access": the first step already wears that label, and two
                # identical dots on a ten-step rail read as a mistake -- caught
                # on a screenshot of the rail, not in any review of this file.
                "Allow",
                "Three permissions macOS will ask for",
                "macOS shows each of these once, and each one is a real dialog you have to click. "
                "This page tells you what is coming before it appears, so none of it is a surprise.",
            ),
        )
        if mac_support.IS_MAC
        else ()
    ),
    OnboardingStep(
        "microphone",
        "Mic",
        "Test your microphone",
        "Choose an input, start the local level check, and confirm a clean voice signal.",
    ),
    OnboardingStep(
        "controls",
        "Controls",
        "Test your shortcut",
        # Field report #6: he did not know WHICH key or that HOLDING is the
        # gesture. Never say "press" for a hold trigger.
        "Hold the key shown. It lights while you hold it. Let go to finish. Try it before you dictate."
        if mac_support.IS_MAC
        else "Press the configured trigger and watch every key respond before your first dictation.",
    ),
    OnboardingStep(
        "menu",
        "Menu",
        "Your menu",
        f"{mac_support.SECONDARY_CLICK_PHRASE} the Pill, the small bar on your screen, for routes, writing style, history, settings and app controls.",
    ),
    OnboardingStep(
        # After "menu" deliberately: these are the powers that LIVE behind the
        # right-click, shown the moment the right-click has been learned. A
        # feature nobody is shown is a feature that does not exist for them.
        "superpowers",
        "Powers",
        "What else it does",
        "Six tools help you clean up, protect, change and recover your text.",
    ),
    OnboardingStep(
        "writing",
        "Writing",
        "Choose a writing style",
        "Pick a starting point now. You can change any setting later.",
    ),
    OnboardingStep(
        "test",
        "Test",
        "Make your first dictation",
        "Hold the shortcut, talk, and let go. Your text appears here, inside setup.",
    ),
)


# 2026-09-22: "trial" and "plans" are gone with the prices. A saved choice of
# either reads back as "private", which is what it always meant for dictation.
ACCESS_CHOICES = {"private", "restore", "account"}


@dataclass(frozen=True)
class PermissionPage:
    """One macOS permission, pre-announced in the words a person would use.

    `dialog_title` and `dialog_button` describe the real system dialog, because
    the point of the page is that the pop-up which appears next is recognised
    rather than dismissed. `breaks` is what silently stops working without it --
    each of these fails without an error, which is why they need announcing at
    all: a denied microphone on macOS returns digital silence rather than an
    error, and a missing Accessibility grant makes CGEventPost report success
    while nothing arrives.
    """

    key: str
    label: str
    title: str
    why: str
    dialog_title: str
    dialog_button: str
    breaks: str
    settings_path: str


MAC_PERMISSION_PAGES: tuple[PermissionPage, ...] = (
    PermissionPage(
        mac_support.PERMISSION_MICROPHONE,
        "Microphone",
        "First: your microphone",
        "Talk DAT! listens only while you hold the trigger. Nothing is recorded before that "
        "or after you let go.",
        '"Talk DAT!" would like to access the microphone.',
        "Allow",
        "Without it, dictation records perfect silence and blames you for not speaking -- "
        "macOS answers a refused microphone with an empty signal rather than an error.",
        "Privacy & Security > Microphone",
    ),
    PermissionPage(
        mac_support.PERMISSION_ACCESSIBILITY,
        "Accessibility",
        "Second: typing into other apps",
        "This is how your words land in the app you were already typing in. macOS treats "
        "one app typing into another as a privilege, so it has to be granted by hand.",
        '"Talk DAT!" would like to control this computer using accessibility features.',
        "Open System Settings",
        "Without it, dictation finishes, the text is ready, and not one character arrives "
        "anywhere -- macOS reports the keystroke as sent and drops it.",
        "Privacy & Security > Accessibility",
    ),
    PermissionPage(
        mac_support.PERMISSION_INPUT_MONITORING,
        "Input Monitoring",
        "Third: hearing the trigger",
        "Talk DAT! watches for your trigger keys and nothing else. It is not a keylogger and "
        "keeps no record of what you type.",
        '"Talk DAT!" would like to receive keystrokes from any application.',
        "Open System Settings",
        "Without it, the trigger does nothing at all, anywhere except inside Talk DAT!'s own "
        "windows.",
        "Privacy & Security > Input Monitoring",
    ),
)


# Shown on the checklist rather than pre-announced: by the time any of this runs
# the dialog is already behind the user, and explaining it after the fact is
# still worth doing because it is the one that looks most alarming.
GATEKEEPER_NOTE = (
    "You already passed one: the warning about an app downloaded from the internet. "
    "That is Gatekeeper checking the signature, and it appears only on first open."
)


def permission_pages() -> tuple[PermissionPage, ...]:
    """The permission pages for this platform -- none anywhere but macOS."""
    return MAC_PERMISSION_PAGES if mac_support.IS_MAC else ()


def permission_is_satisfied(state: str) -> bool:
    """Only a confirmed grant earns a completed checklist mark."""
    return state == "granted"


def permissions_outstanding(report: dict[str, str]) -> tuple[str, ...]:
    """Known missing grants, without presenting an unavailable check as denial."""
    return tuple(
        page.key
        for page in permission_pages()
        if report.get(page.key, "unknown") in {"denied", "not asked"}
    )


WRITING_PRESETS: dict[str, dict[str, Any]] = {
    "smart": {
        "title": "Smart & faithful",
        "badge": "RECOMMENDED",
        "description": "Cleans speech, removes filler, and adds structure only when your intent clearly calls for it.",
        "cleanup": {
            "level": "high",
            "auto_rewrite": True,
            "remove_fillers": True,
            "backtrack": True,
            "smart_newlines": True,
            "smart_format": True,
            "format_mode": "auto",
            "preserve_meaning": True,
        },
    },
    "fast": {
        "title": "Fast clean",
        "badge": "LOW LATENCY",
        "description": "Deterministic cleanup and punctuation with no wait for the local formatting model.",
        "cleanup": {
            "level": "medium",
            "auto_rewrite": False,
            "remove_fillers": True,
            "backtrack": True,
            "smart_newlines": True,
            "smart_format": True,
            "format_mode": "off",
            "preserve_meaning": True,
        },
    },
    "verbatim": {
        "title": "Near verbatim",
        "badge": "MINIMAL EDITS",
        "description": "Keeps filler and sentence flow close to the transcript with only basic spacing cleanup.",
        "cleanup": {
            "level": "none",
            "auto_rewrite": False,
            "remove_fillers": False,
            "backtrack": False,
            "smart_newlines": False,
            "smart_format": False,
            "format_mode": "off",
            "preserve_meaning": True,
        },
    },
}


KEY_LABELS = {
    "ctrl": "Ctrl",
    "cmd": "Win",
    "alt": "Alt",
    "shift": "Shift",
    "space": "Space",
    "esc": "Esc",
    "enter": "Enter",
    "mouse4": "Mouse 4",
    "mouse5": "Mouse 5",
    "middle": "Middle click",
}

# "cmd" is the Windows key on Windows and Command on a Mac, and these labels are
# drawn as full-size keycaps in the onboarding Controls step. Leaving the
# Windows spelling told a Mac user to hold a key their keyboard does not have,
# next to a prompt waiting for them to press it. Ctrl and Option are also
# spelled differently on Apple keyboards.
if sys.platform == "darwin":
    KEY_LABELS.update({
        "ctrl": "Control",
        "cmd": "Command",
        "alt": "Option",
        "esc": "Esc",
        "fn": "\U0001F310 Fn",
    })


def onboarding_is_complete(config: dict[str, Any]) -> bool:
    onboarding = config.get("onboarding", {})
    if not isinstance(onboarding, dict):
        return False
    try:
        version = int(onboarding.get("version", 0) or 0)
    except (TypeError, ValueError):
        version = 0
    return onboarding.get("completed") is True and version >= ONBOARDING_VERSION


# Three successful dictations is the app's own mark for "settled in" -- it is
# what X-137 uses to decide someone has used the thing for real.
REAL_DICTATIONS_SETTLED = 3


def onboarding_blocks_update_reminders(config: dict[str, Any]) -> bool:
    """X-536: is this person genuinely still setting up, right now?

    `onboarding_is_complete` answers "should the wizard run", and update
    reminders used to be gated on its inverse. That is a different question,
    and using it for this cost the founder every update reminder he should
    have had: he closed the wizard at step two, dictated for months, and every
    `update reminder:` line in his log says `reason=onboarding`. With reminders
    muted the manual check is the only way he ever updates -- the path that
    then failed silently in X-535.

    It also mutes an entire install base on a constant change. `version >=
    ONBOARDING_VERSION` means bumping that number retroactively marks every
    older graduate "incomplete", so they quietly stop hearing about updates.
    Finishing ANY version counts here.

    The block it replaces is still worth having, so this stays true for a
    genuinely new install: a window during setup takes something away instead
    of offering it. It only lifts once the person has actually used the app.
    """
    onboarding = config.get("onboarding") or {}
    if not isinstance(onboarding, dict):
        return True
    if onboarding.get("completed"):
        return False
    if onboarding.get("finish_prompt_2_done"):
        return False
    try:
        used = int(onboarding.get("real_dictations", 0) or 0)
    except (TypeError, ValueError):
        # Unreadable state protects the person rather than interrupting them.
        return True
    return used < REAL_DICTATIONS_SETTLED


def mark_onboarding_complete(
    config: dict[str, Any],
    *,
    route: str,
    microphone_tested: bool,
    hotkey_rehearsed: bool,
    dictation_tested: bool,
    access_choice: str = "private",
) -> None:
    selected_access = str(access_choice or "private").strip().lower()
    if selected_access not in ACCESS_CHOICES:
        selected_access = "private"
    config["onboarding"] = {
        **config.get("onboarding", {}),
        "completed": True,
        "version": ONBOARDING_VERSION,
        "completed_at": int(time.time()),
        "route": str(route or "local"),
        "access_choice": selected_access,
        "microphone_tested": bool(microphone_tested),
        "hotkey_rehearsed": bool(hotkey_rehearsed),
        "dictation_tested": bool(dictation_tested),
        "terms_version": TERMS_VERSION,
        "terms_accepted_at": int(time.time()),
    }
    # X-102: the mid-setup bookmark has served its purpose. Left behind, a
    # finished config still looks resumable to anything that reads it.
    config["onboarding"].pop("resume_step", None)
    config["onboarding"].pop("resume_step_id", None)
    config["onboarding"].pop("resume_flags", None)


def terms_acceptance(config: dict[str, Any]) -> tuple[str, int]:
    """The terms version this config accepted, and when. ("", 0) if never."""
    onboarding = config.get("onboarding", {}) or {}
    version = str(onboarding.get("terms_version", "") or "")
    try:
        accepted_at = int(onboarding.get("terms_accepted_at", 0) or 0)
    except (TypeError, ValueError):
        accepted_at = 0
    return version, accepted_at


def terms_are_current(config: dict[str, Any]) -> bool:
    """False when the terms were never accepted, or accepted under older terms."""
    version, accepted_at = terms_acceptance(config)
    return bool(version) and version >= TERMS_VERSION and accepted_at > 0


def selected_access_choice(config: dict[str, Any]) -> str:
    selected = str(config.get("onboarding", {}).get("access_choice", "private")).strip().lower()
    return selected if selected in ACCESS_CHOICES else "private"


def primary_hotkey(config: dict[str, Any]) -> tuple[str, ...]:
    shortcuts = config.get("hotkeys", {}).get("push_to_talk", [])
    if isinstance(shortcuts, list) and shortcuts:
        first = shortcuts[0]
        if isinstance(first, list):
            chord = tuple(str(key).strip().lower() for key in first if str(key).strip())
            if chord:
                return chord
    return ("ctrl", "cmd")


def hotkey_labels(chord: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(KEY_LABELS.get(key, key.replace("_", " ").title()) for key in chord)


def selected_writing_preset(config: dict[str, Any]) -> str:
    onboarding = config.get("onboarding", {})
    stored = str(onboarding.get("writing_preset", "")).strip().lower()
    if stored in WRITING_PRESETS:
        return stored
    cleanup = config.get("cleanup", {})
    if not bool(cleanup.get("smart_format", True)) and str(cleanup.get("level", "")).lower() == "none":
        return "verbatim"
    if str(cleanup.get("format_mode", "auto")).lower() == "off":
        return "fast"
    return "smart"


def apply_writing_preset(config: dict[str, Any], preset: str) -> str:
    selected = preset if preset in WRITING_PRESETS else "smart"
    config.setdefault("cleanup", {}).update(WRITING_PRESETS[selected]["cleanup"])
    config.setdefault("onboarding", {})["writing_preset"] = selected
    return selected


def microphone_quality(level: float) -> tuple[str, str]:
    clean = max(0.0, float(level or 0.0))
    if clean < 0.006:
        return "Waiting for your voice", "quiet"
    if clean < 0.025:
        return "Voice detected - a little quiet", "quiet"
    if clean < 0.38:
        return "Voice level looks good", "good"
    return "Strong signal - move back if it clips", "hot"


def chord_label(config: dict[str, Any], action: str, fallback: tuple[str, ...]) -> str:
    """The chord for `action` spelled the way this platform's keyboards spell it.

    The idle line on the Pill said "Hold Ctrl+Win to talk. Toggle only with
    Ctrl+Win+Space" as a literal string, in six places. On a Mac that named a
    key the keyboard does not have, and -- because the macOS defaults move
    hands-free off Ctrl+Cmd+Space, which is the system Character Viewer -- it
    also named a chord that is not bound to anything at all.
    """
    hotkeys = config.get("hotkeys", {}) if isinstance(config, dict) else {}
    chords = hotkeys.get(action)
    chord: tuple[str, ...] = fallback
    if isinstance(chords, list) and chords:
        first = chords[0]
        if isinstance(first, list) and first:
            cleaned = tuple(str(k).strip().lower() for k in first if str(k).strip())
            if cleaned:
                chord = cleaned
    return "+".join(hotkey_labels(chord))

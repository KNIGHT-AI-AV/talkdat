# Changelog

All notable product changes to Talk DAT! are recorded here. The project uses beta
versions while broader field verification remains in progress.

## 0.4.164-beta

Fewer old-style windows.

- After your third dictation, the choice between Chill and Executive now
  opens on the Writing page, in the same design as the rest of Talk DAT!. It
  shows your own last dictation finished both ways, side by side.
- An update now opens one window, not two. Home already shows what changed,
  so the separate What's New window no longer opens on top of it.

## 0.4.163-beta

Long dictations keep their sentences together.

- When you pause for breath in a long dictation, Talk DAT! no longer drops a
  full stop into the middle of your sentence. "We are PC and Mac only. for
  this project" now comes out as "We are PC and Mac only for this project".
- A word after that pause no longer gets a stray capital. "building
  necessarily And then make sure" now reads "building necessarily and then
  make sure".

## 0.4.162-beta

Names come out right, and Talk DAT! stays out of the way when Windows restarts.

- Names the speech engine wasn't sure of are put back. If you have Kaelyn in
  your words list and the engine hears "Kalen", you get Kaelyn. This only
  happens when the engine itself was unsure of that word and it sounds like
  a name you gave it (from your words list, or a name on screen if screen
  names are on). Words it heard clearly are never changed.
- Fix a name by hand once and Talk DAT! learns the mishearing too. After you
  correct "Kalen" to Kaelyn and the word is saved, "Kalen" becomes Kaelyn
  from then on.
- Talk DAT! no longer holds up a Windows restart or shutdown. Before, an open
  right-click menu or Settings window could make Windows wait on it.
- "press enter" in the middle of a sentence is written "press Enter".
- "The price is nineteen ninety nine" becomes 19.99, while "we met in
  nineteen ninety nine" still becomes 1999.
- "One on one" becomes one-on-one and "fifty fifty" becomes 50/50.
- "First we open settings and then we check privacy" stays one sentence.
- Near-verbatim mode starts with a capital and keeps every other word as you
  said it.
- On a Mac, chat apps drop a lone full stop Talk DAT! added, the same as on
  Windows. A full stop you say out loud stays.

## 0.4.161-beta

Talk DAT! now knows what kind of box you are typing into.

- Password boxes: your words go in exactly as you said them. Nothing is shown
  on the Pill, nothing is saved to History, and the text is typed, never put
  on the clipboard.
- Terminals: commands come out as commands. "git checkout dash b fix slash
  login" becomes git checkout -b fix/login, with no capital, no full stop and
  your corrections applied. Talk DAT! never presses Enter in a terminal; the
  Pill tells you to press it yourself.
- One-line boxes such as search bars and email subjects never get a line
  break. A list you dictate there becomes "milk, eggs, and bread".
- In chat apps a full stop you say out loud now stays.
- Your clipboard stays yours. When Talk DAT! borrows it to paste, that text is
  kept out of Windows clipboard history and never syncs to the cloud
  clipboard, and a password you copy from a password manager is never learned
  as a new word.
- Fixed: after the first right-click menu, the Pill could stop following you
  between monitors.

## 0.4.160-beta

Three fixes for things you could see.

- Your first word keeps its capital. In chat apps such as the Claude app,
  Talk DAT! was reading the app's own buttons as the text before your cursor,
  took every take for the middle of a sentence and lowercased its first word.
  It now reads only the box you are typing in.
- Smart formatting is fast again: about half a second instead of two to three.
  Every request now goes straight to the local engine's address, 127.0.0.1, so
  Windows no longer tries a dead IPv6 address first on each one.
- The right-click menu opens on top of the Pill every time, including the first
  time after Talk DAT! starts or updates.

## 0.4.159-beta

Your words stay yours.

- Executive, the light polish, no longer swaps your words for fancier ones. It
  fixes grammar, turns "gonna" into "will", drops filler like "so basically",
  and keeps every other word as you said it.
- Fewer formatting slips in every style: a correction such as "actually, make
  it Wednesday" replaces what it corrects, a greeting gets its comma and its
  own line, and numbers stay the way you said them.
- Mac: Settings can now set up smart formatting in one click. Talk DAT!
  installs the Ollama app through Homebrew if you have it, or from Ollama's own
  download after checking it is signed by Ollama. Macs with 16 GB of memory or
  more get the larger model; smaller Macs keep the lighter one.

## 0.4.158-beta

A cleaner, clearer Talk DAT!.

- The Pill now tells you how a dictation went. A short teal glow means your
  text landed; a warm red tint means something went wrong, with a message that
  says what to do. With reduced motion on, you get a still tint instead.
- Fixed: after saving a setting, the Pill could shrink to the wrong size on a
  high-resolution screen.
- Home: "Check for updates" now really checks and shows the answer right there,
  with an install button when a new version is out. "What's new" shows whole
  sentences instead of cutting them at line ends. The shortcut tiles line up in
  full rows.
- Every menu row has its own icon, and each place in the app has one name
  (Tools, Local models, Quit Talk DAT!).
- Settings help text is easier to read, the speech model name no longer gets
  cut off, and the default writing style shown matches the real default.
- The small "Connected" note is gone; you only see a message if the window
  loses its link to the app, with what to do.
- Plain words throughout the app and the website.

## 0.4.157-beta

Talk DAT! is getting ready to be open source under the Apache 2.0 licence. The
name and logo stay ours; the code will be yours to read, build and change.

- A new setting, "Share anonymous usage counts", in Settings > Privacy. It
  shares four anonymous events (first open, first dictation, still in use, day
  7) and never your audio or text. It is on by default in our releases and you
  can turn it off in one click. Local-only privacy now covers exactly what you
  dictate.
- The installer now carries every third-party licence the app ships with, and
  the licence agreement no longer forbids what those licences allow.
- Builds made from source never contact Talk DAT! services unless you point
  them at your own.

## 0.4.156-beta

Formatting now follows a written standard: produce what you meant to write,
not a record of every hesitation, and not a rewrite of your message.

- New installs start on the Chill finish, which formats your words without
  rewriting them. It measured best on our 229-case test set. Executive stays one
  click away in Settings, and anyone already using Talk DAT! keeps the finish
  they chose.
- When you correct yourself mid-sentence, the later words win: "all of the,
  some of the tests failed" is "Some of the tests failed."
- A correction that flips a negative is settled: "don't send it today,
  actually, send it today" is "Send it today."
- Hedges and small words stay: "kind of", "I think", "and", "but", "so".
- "uh-uh" is a word, not a filler. "New paragraph" in the middle of a sentence
  stays as words.
- Text inserted after a period or comma gets exactly one space.
- The local formatter's answer is now checked against what you actually said,
  so it cannot quietly drop a word, change a number, add a currency sign or
  change who did what.

## 0.4.155-beta

Talk DAT! keeps more of what you actually said.

- Command words only act as commands. "Please delete that file from the
  server", "cancel that order" or a song called "Scratch That" are now typed as
  you said them. "Scratch that" still takes back what you just said when you use
  it on its own.
- "Press enter" only presses Enter when it is the command at the end of a
  finished message, never in "to submit the form, just press enter".
- Say "literally" or "the words" to type a command word: "the subject line
  should literally say new paragraph" keeps "new paragraph".
- Real repetition stays: "had had", "very, very", "no, no, no". C++ and C# come
  out right.
- Ranges and negatives: "three to four thousand dollars" is "$3,000 to $4,000",
  and "negative five degrees" is "-5 degrees".
- "dash dash save dev" after a tool name is "--save-dev".
- The formatter can no longer translate your words, remove profanity you said,
  or drop your sign-off, and it never follows a dictated AI prompt; it formats it.

## 0.4.154-beta

Old settings from the retired Talk DAT! cloud are cleaned up automatically. If
your saved settings still pointed at the old cloud service for speech, writing
or translation, Talk DAT! now moves them to this computer, or to your own
provider if you set one up. Your own keys and choices are left exactly as they
were.

On iPhone, the app now runs on iPad too, with content kept to a comfortable
reading width, and the keyboard is available there.

## 0.4.153-beta

Every new install can now get smart formatting in one click. Setup offers to
download the formatting engine and a writing model to your computer (about
2.5 GB on a computer with a capable graphics card, about 1.4 GB otherwise). It
runs in the background, never holds up finishing setup, and the next dictation
uses it as soon as it is ready. Before, a new install without the engine only
ever got the basic rules.

You can set it up, watch it download, or retry it later from Settings >
Formatting.

On a Mac, Talk DAT! now finds an Ollama you already installed from the app or
Homebrew.

## 0.4.152-beta

Formatting is much smarter, and it all still happens on your computer.

Your local formatting model now finishes almost every dictation. Before, short
dictations skipped it entirely and longer ones often gave up waiting for it, so
most of what you saw was the basic rules. On a real week of dictations the model
now formats about 85 in 100, up from about 30.

What that looks like:
- Self-corrections are applied: "at five, actually make it six" becomes "at 6",
  and "Tuesday, no wait, Wednesday" becomes "Wednesday".
- Spoken lists become real lists: "three things, milk, eggs and bread".
- A dictated email or note gets its greeting, paragraphs and sign-off laid out.
- Names are capitalised, and "Q3", "$1.2 million", "555-1234" and "config.json"
  come out written, not spelled.
- "New paragraph" is always honoured.

Chill and Executive now read clearly differently. Chill formats your words as you
said them. Executive formats and gives a light professional polish, in plain
words, without inventing anything.

The model stays loaded so it is ready when you talk, and a startup error that
could stop the speech model from warming up on some computers is fixed.

## 0.4.151-beta

Talk DAT! is free. There is no trial, no weekly word limit, no plan and nothing
to buy, on any device. Every feature that used to need Local Forever or Pro is
now simply part of the app, and long recordings are no longer cut short by plan.

Nothing you dictate goes to Knight. Speech is recognised on your own computer,
and if you add your own provider key, your text goes to that provider, not to
us. Talk DAT! no longer counts your words or sends a word total anywhere.

An account is optional. Signing in only syncs your preferences between
computers, and you can dictate without one. The Terms, Privacy notice and
licence have been rewritten to match, effective 2026-09-22.

If you use OpenRouter with your own key, the key box in Settings could not be
typed into. It works now.

## 0.4.150-beta

Talk DAT! now opens on a Home screen. Previously a launch reopened whichever
Settings page you happened to close on last, which is not a welcome and told you
nothing. Home greets you, shows the shortcut to hold, says whether speech is
running on this computer or through a provider, totals the words you have
dictated and the typing time that saved, and lists what changed in this version.
History, Scratchpad, Translate and Settings are one click from it. You can turn
Home off at launch in Settings.

Launching is faster. The window that opens at startup was built from cold only
after the app had finished loading its audio runtime, so the two waits ran end to
end. The window is now prepared in the background while the audio loads, the way
the Pill menu already was, which brings Home up about a third sooner -- measured
at 6.5 seconds, from 9.3.

One pause is left and it is deliberate: a couple of seconds while your local
speech model loads onto the graphics card. That is what makes your first
dictation instant instead of slow, so it is being kept.

## 0.4.149-beta

The Pill menu now opens centered directly above the Pill, with display scaling handled consistently. It uses one narrow column with labeled actions, clear Speech and Formatting choices, and tools that open in the same column. Short screens use Previous and Next buttons without scrolling. Motion respects your reduced-motion preference.

Settings opens directly from the menu and restores its window. Failed menu actions keep their error visible. Navigation and menu icons now use a generated line-art set with consistent padding, including Help.

Theme materials use enhanced local images and continuous backgrounds without repeated stamps. Upscaling happens during asset preparation; Talk DAT does not run an upscaling model on your computer.

## 0.4.148-beta

Spoken digit sequences now stay numeric, including leading zeros. Clear labels guide phone, card and social-security formatting without inventing missing digits. The same local number rules support iPhone dictation.

The compact menu keeps its actions visible without scrolling, with paired rows in shorter windows. Fire Opal now uses smooth smoked glass and precise amber facets.

Installed wake models can load their required runtime dependencies and companion models. Missing local model files show a specific preparation message before the microphone opens.

Fixed a Mac startup race that could stop an input listener. Crash reports now follow your selected app data folder, including portable installations.

Diagnostic logs keep a bounded recent history. Oversized logs retain recent entries, and logging failures no longer prevent Talk DAT from starting.

Clear local data now previews your choices, protects unselected items and shows what completed. Talk DAT pauses recording and background work during a confirmed reset, then closes safely.

Installed plugins now run separately from dictation. Failed, empty or stalled filters keep the preceding text, and Advanced settings show loading, issues, Reload and Open folder controls. Turning plugins off closes their hosts; failed extensions no longer leave partially registered actions behind.

Wake listening now follows your selected microphone, yields before ordinary dictation, and stays stopped after Panic Stop until you re-enable it. Restart and Quit wait for registered audio devices to close. Missing wake models are reported without an automatic download.

Scribe now opens in Writing with a clear recording source, complete notes, saved-file receipts and a local recording library. Edited drafts survive restarts, failed saves keep your words, and retry preserves an earlier notes copy. Opening a saved recording leaves the microphone and system audio off.

Meeting recordings preserve earlier notes, report unavailable audio sources, and keep original audio and completed transcription sections for recovery. Scribe marks incomplete sections, retains unsaved drafts, and stops through Panic Stop. Live meeting notes respect Local-only privacy.

Getting started now uses four short sections in the shared interface, with your selected theme, optional microphone and trigger checks, and practice words kept inside setup. Mac permissions show what could actually be verified. Local-only privacy remains active when other settings change.

Setup keeps microphone and provider choices consistent, preserves previous settings when saving fails, and reports practice results without overstating what completed.

Ideas and language requests now open in Help, keep your draft while you move between pages, and show a receipt only when delivery is confirmed. Formatting logs require an explicit choice, and email drafts stay a separate option.

App preferences now have a clear home in Writing. Set formatting, tone, language and spoken Enter behavior for each app, with visible priority and default inheritance. Search results stay in place during background refreshes, and failed saves keep your draft.

History exports save in the background and keep earlier files intact. Saved-file receipts provide Open and Show folder actions. Text and Markdown preserve original spacing; subtitle drafts clearly identify their estimated timing. Damaged dates no longer hide readable entries.

Mic Doctor and Speech check now open in the shared interface. They test your selected input, show when recording is active, and stop safely when cancelled or closed. Speech check reports the local model's words and recognition time.

Stats now opens in Tools, with a seven-day activity view, clearer speech estimates and reliable refresh. Saved translations and rewrites no longer inflate estimated dictation time.

Live Captions now tracks microphone startup and shutdown, respects Panic Stop, handles microphone format fallbacks, and reports interrupted audio or a model that cannot keep up.

Ramble now opens in Writing, with an editable draft, original text, document style previews and explicit save controls. Failed finishing or saves keep your words available to retry or copy.

PDF exports preserve multilingual text and joined emoji, with readable page numbering and a complete text attachment. Ramble titles retain punctuation and prices.

Rambles and report exports preserve earlier saves. Word, Markdown and text exports retain your paragraph spacing.

The iPhone keyboard keeps its top controls compact in landscape. Theme previews are larger and scrollable, and haptic settings stay readable and easy to tap on smaller phones.

The iPhone emoji picker keeps taps in order while dictation finishes, prevents late words from entering another field, and gives emoji larger touch targets. Categories share one compact menu, landscape shows complete rows, and Recents preserves longer combined emoji.

Translation now opens inside Writing, with source and result panes, language swapping, cancellation, local-model setup and a typed glossary editor. Drafts survive page changes, and results are checked against the current passage before entering History.

Translation keeps signed numbers, prices, links and literal text intact, preserves surrounding spacing, and stops incomplete or unexpectedly repeated results. Repeated passages keep their original count. Mac setup now recognises Ollama in Applications.

Words, replacements and voice snippets now have searchable editors in the shared interface. Vocabulary packs keep pronunciation spellings, imports preview their changes, and Ask before adding asks before learning a copied word. Pronunciation practice uses your selected microphone, can be cancelled, and keeps distinct non-Latin names separate.

Settings now use six clear sections, with search across settings and tools. Themes show their materials before you choose them, with separate light and dark views. The Pill menu keeps daily actions together and puts app controls in a compact footer.

History, Scratchpad and Recovery now open inside the same desktop interface. Read and copy complete transcripts, pin entries, import or export notes, and recover saved recordings. Scratchpad keeps your draft when a save fails and offers Save a copy when a note changed elsewhere.

Backups now include both history formats, notes and transcript archives. Restore shows what will be replaced before you confirm, checks the files before changing current data, and quits Talk DAT so restored settings cannot be overwritten by the old session.

Protected voice-session recovery now preserves the original playback speed and channels when recording metadata is missing or incomplete. Valid older recordings with extra metadata remain intact.

Startup also honors your configured protected-recording limit and can recover valid audio even when its separate metadata is damaged.

Local automation on Windows now keeps its control port exclusive to one listener, while retaining normal stop-and-restart behavior.

The iPhone keyboard keeps your letters, deletes and Return in order when dictation lands. Resuming typing keeps the words already received, and delayed finishing cannot overwrite a changed field or insert the same result twice.

Keyboard suggestions now respond across the visible row. Moving the cursor, choosing a suggestion and switching fields preserve your typing while dictation finishes.

Landscape keeps the keyboard's intended key height. Keyboard themes gain matching material previews, while High Contrast stays plain.

On iPhone, Settings has a compact menu and the selected theme carries into Talk, Notes, History and Settings. Notes saves before you leave, keeps failed saves available to retry or copy, and asks before deleting. The update sheet exposes separate Update and Later buttons to accessibility tools.

Prepare keyboard dictation is available in Shortcuts. Assign it to your Action Button or Back Tap to open Talk DAT and prepare a keyboard session. Open notes and recordings take priority.

## 0.4.147-beta

- New desktop settings, menus and help share a smoother interface on Windows and Mac, with searchable settings, 80 color themes and clear Save/Discard choices.
- Dictation formatting handles more spoken numbers, times, addresses, punctuation and contractions, with stronger protection for names, links and literal text.
- Short, already complete dictations can skip heavier finishing. Longer local dictations can begin formatting while you speak.
- Personal vocabulary can guide recognition on supported speech engines. Accepted corrections can contribute to future word suggestions.
- The Model Guide keeps search and combined filters for local, cloud, ready and research models.
- Mac shortcut settings preserve Fn/Globe. Preparing a Windows installer no longer stops the installed app unnecessarily.
- Maintenance checks identify the installed copy correctly. The recent History menu reopening repair remains included.

This is a beta milestone. The full feature comparison and physical-device acceptance work remain in progress.

## 0.4.146-beta

- The History menu stays closed when you close it. Opening it on hover, added
  last version, also reopened it the moment the pointer crossed the button on
  the way out, so it came straight back and then sat open under the pointer.
- A crash mid-dictation no longer takes the next sentence with it. The audio
  from the interrupted take was kept and replayed into the following one, so
  the sentence after a crash could come out with the previous one's words
  inside it.
- Your settings cannot be lost to bad timing. Saving rewrote the settings file
  in place, so an interruption at the wrong moment -- a crash, a forced
  shutdown, a full disk -- could leave it half written and unreadable, taking
  every preference, custom word and snippet with it. The file is now replaced
  whole, in one step, and two parts of the app can no longer write it at once.
- A failed card no longer switches the paid features off without warning. A
  payment Stripe is still retrying now keeps your access while it retries, and
  only a subscription that genuinely ends stops it.

## 0.4.145-beta

- Every menu, panel and label now takes its size from the shared type scale.
  Settings used to render 155 sizes chosen one at a time, 61 of them below the
  10pt floor the app sets for itself, so nothing read as a heading and nothing
  read as body.
- Text sits on the page properly. Long passages gain line spacing that follows
  the size, and a page you write into is set looser than a settings row.
- Buttons forgive a slip. A click that lands just outside one still counts, and
  a button lets go while you are still holding the mouse if you drag away, so
  you can change your mind before you let go.
- Talk DAT! now follows the Windows setting for reduced animation. If you have
  asked Windows to stop animating, you no longer have to ask again here.
- Fifteen new colour themes: Amber Lantern, Brass Lamp, Fire Opal, Sunset Coast,
  Rust Belt, Bone China, Paper Press, Moss Stone, Olive Grove, Jade Garden,
  Rose Quartz, Emerald Vault, Neon Wire, Ultraviolet Hour and Plum Velvet.
  Forty families, light and dark, and every one measured for readability.
- The colour swatch and "Something wrong?" button have left the title bar. Both
  were second ways into Settings that overlapped the window buttons. Colours
  live under Settings, Colors; feedback under Settings, General.
- The History menu opens on hover as well as on click, and closes when you move
  away from it.
- Fixed a crash while closing Settings that could leave an error in the log.

## 0.4.144-beta

- **Windows open at a size that fits your screen.** A window could be restored
  to the size it had on a different monitor, at a different display scale, or
  after the app had grown it to fit a long page. Nothing checked that against
  the screen it was opening on, so on a 4K display at 150 percent the setup
  window opened taller than the screen itself. Every window is now measured
  against the monitor it opens on, and a remembered size that no longer fits is
  dropped rather than squashed into a shape you never chose.
- **Setup opens at the size it was designed for.** It used to grow to fit its
  longest page, remember that, and then open that big on page one forever.

## 0.4.143-beta

- **Fixed: the "Your key" side of the route switch did nothing you could see.**
  Tapping it saved your choice and then stopped short, so the Pill never
  confirmed it and never said which provider it was going to use. Both sides of
  the switch confirm what they did now, and if you choose "Your key" without
  having saved one, it tells you it is still running on your PC rather than
  leaving you to guess.
- **If your own provider fails three times in a row, dictation now stays on your
  PC until it recovers.** That was always the intent and it had quietly stopped
  working, so every dictation went back to trying the provider first and making
  you wait for it to fail again.
- **The permanent "using local model" tag above the Pill is gone.** It made
  sense when local was the thing the app fell back to. Local is what most
  people run now, so the tag spent its life telling you your own setting, and
  on any screen above 100 percent it was cut off at both ends while doing it.
  Nothing changed about what runs where. Your route is still one right click
  away on the Pill.

## 0.4.142-beta

- **Settings stopped being a menu inside a menu.** Account & license, Words &
  phrases and Mic Doctor each had two doors: they are pages in the sidebar, and
  they were also buttons on a Tools page inside Settings. That Tools page held
  no settings at all, only buttons that opened other windows, so it is gone.
  Everything it listed already had a home, except Share an idea, which now sits
  on General. Settings is six sections instead of seven.
- Speech no longer describes a cloud route. It reads "On this machine, or your
  own key", which is what the app does.

## 0.4.141-beta

- **The speech route switch on the pill now shows the two routes that exist.**
  Right-clicking the pill offered Cloud, Auto and Local. Cloud and Auto stopped
  doing anything when the managed service was removed, so tapping either
  changed nothing and said nothing, and anyone running on their own provider
  key was shown "Auto" instead of their own route. The switch now reads Local
  and Your key, which is what the app has actually been doing.
- The AI rewrite provider list no longer offers a managed option that cannot
  run, signing out no longer suggests you need one to keep dictating, and the
  setup screens describe the two real routes.

## 0.4.140-beta

- **Nothing you say or write leaves your computer.** Talk DAT! used to be able
  to transcribe, rewrite and translate on our servers. That is gone, and not
  switched off: the code was removed. Dictation now runs on your own machine,
  or at a provider you gave us a key for, where the request goes straight from
  your computer to them and we are not in the path.
- Four things were still sending your words to us and are now fixed: the
  translation retry, the right-click rewrite on Mac, the speed Race, which
  uploaded eight seconds of audio, and live captions, which streamed your
  microphone continuously on a paid plan.
- **Your free 1,000 words a week now run on the on-device models**, which is
  where they ran before. The number has not changed.
- The route picker offers two lanes instead of three, on this computer or your
  own provider key, and first run opens on the local one.
- Translation runs on this computer. If you had the managed engine selected,
  it moves to local.

## 0.4.139-beta

- **The cloud lane is called Talk DAT! Managed now.** It used to be called
  Talk DAT! Cloud, which collided with the plan name: the subscription is
  Talk DAT! Pro, and the same words were doing both jobs. Nothing about how
  it works has changed, and your free 1,000 words a week still run on it.
- Where a screen meant your subscription rather than the engine, it now says
  Talk DAT! Pro, so the app, the website and your receipt all use one name
  for the thing you pay for.

## 0.4.138-beta

- **Rewriting stopped answering you and started doing the work.** If you
  had taught Talk DAT! your writing style, the instruction telling it to
  return only your rewritten words was being replaced by that style, so it
  sometimes replied like a chat assistant instead: a line of
  "Certainly, here is the rewritten text" above your own sentences. Your
  style now sits alongside that instruction rather than in place of it, and
  anything conversational that still arrives is stripped before it reaches
  your document.
- **Executive does more than Chill again.** Choosing Executive was meant to
  buy a deeper rewrite, and for some time it only changed the wording of
  the request rather than the work behind it. A full professional rewrite
  now runs on a stronger model; a light cleanup keeps the quick one,
  because Chill is meant to be fast.
- **Two ways to pay: monthly, or once.** Monthly is now $4.99, down from
  $11.99. Lifetime stays $29 and still covers every on-device model with no
  subscription and no usage charges. The annual plan is gone; nobody was on
  it, and a middle rung between a cheap monthly and a cheap lifetime only
  made the choice harder. If you already subscribe, you keep the price you
  signed up on.
- **The separate cloud add-on is retired.** Local Forever owners were
  shown a button offering managed cloud as a monthly extra. It had
  stopped working, so the button is gone and the add-on is no longer
  sold. Local Forever already covers the app and every on-device model,
  so there is nothing further to buy. If you already pay for the add-on,
  your subscription is unchanged.
- On iPhone, the keyboard's suggestion bar no longer empties the moment you
  finish a word. It offers the next word, splits words you ran together,
  and shows autocorrect's options with your own spelling first so you can
  keep it with one tap. It never inserts a dash where you meant a space.
- The iPhone app has an opening and a short set of cards on first run that
  show you what it does and how to work it.

## 0.4.137-beta

- **Rewrite, Fix That, Scribe, Live captions and Ramble no longer need an
  account.** They ask for a model to write with, and either a local model or
  your own provider key will do. If neither is set up they say so, and say
  where to set one, instead of asking you to buy something.
- **Your graphics card is used when it can actually be used.** A card that
  reported itself ready and then could not run was taking dictation down with
  it. The first failure now falls back to the processor and stays there for
  the session, so one bad start does not cost you a take. The extra libraries
  it needs are fetched when you ask for the GPU and are not carried inside the
  installer, which keeps the download the size it was.
- **The speech model is chosen by timing your machine**, not by guessing from
  the model's name. You can still pick one yourself, and anything that cannot
  run on your machine is no longer offered at all.
- **Two speech routes, and both are yours: this machine, or your own provider
  key.** Whichever you pick, formatting follows the same route your speech
  took, so text can no longer travel somewhere your audio did not.
- **Setup explains the product instead of selling it**, and the step that
  asked for an account before you had heard a word of your own dictation is
  gone.
- **On iPhone, what you record in the app stays on the phone.** All three
  places the app records, the pill, a take rescued after a crash, and Ramble,
  are transcribed on the phone now. On a phone that cannot do it, Talk DAT!
  stops and says so rather than sending your voice somewhere else.
- **The iPhone keyboard corrects your typing.** Mistyped words are fixed as
  you go, with a tap to put back what you actually typed, and the suggestion
  bar fills in from the first letter.
- **The app introduces itself.** There is an opening now, and a short set of
  cards on the first run that show you what the app does and how to work it.
- On the Ramble screen, Back sits at the top where you can see it. It used to
  be below the fold, under the button that starts recording.

## 0.4.136-beta

- **Talk DAT! runs on your machine now.** Speech, formatting and
  translation all happen here, and your words are not sent anywhere. The
  only things that use the network are signing in, checking your licence
  and checking for updates, and none of those carries what you said or
  wrote. There is a switch in Settings if you ever want the cloud back,
  and it is off.
- **When the local model cannot run, it says so.** Before, a PC without
  the local engine quietly used the cloud, which is how text left
  machines whose owners believed it never did. Now nothing leaves, and if
  Chill or Executive could not run you are told which formatter wrote
  your text and why, once.
- Copying a word twice no longer adds it to your dictionary on its own.
  Copying a name or an address twice is ordinary use, not a correction, and
  the dictionary was filling up with it. Words with a shape nobody types by
  accident, like SAHVVV or B2B, still learn on sight. Anything else now asks
  first, and nothing is saved unless you say yes.
- Paste Last pastes again. It is bound to Shift+Alt+Z, and it ran while you
  were still holding those keys, so the paste it sent arrived at the app as
  Ctrl+Shift+Alt+V. Nothing has that shortcut, so nothing was pasted and the
  text stayed on the clipboard. It now waits for you to let go of the keys,
  and lets go for you if you are still leaning on them.
- Setup folds its decorative band on a step that would not otherwise fit, and
  its steps no longer measure themselves as taller than they are.
- iPhone (build 125): the keyboard fixes your typos. Type a word wrong and
  it is corrected when you finish it, the way every other keyboard does.
  Backspace right after puts back exactly what you typed. It leaves alone
  the things that were never mistakes: passwords, addresses, web links,
  names you taught it, anyone in your contacts, and anything in capitals.
- iPhone (build 125): Rewrite runs on your phone. It used to be the one
  thing on the keyboard that sent your words away, and now the app does the
  work on the device and hands the result back. Open Talk DAT! once so it
  can answer.

## 0.4.135-beta

- Setup no longer makes you scroll. Each step measures what it needs and the
  window grows to fit it, as far as your screen allows, instead of hiding the
  bottom of the step behind a scrollbar. The route cards put their badge
  above the title, so "Talk DAT! Cloud" and "Private on-device" read whole.
- The Colors tab is a grid of material tiles. One tile per material, and the
  tile is the app itself painted in that material: the photograph, the
  caption strip and the pill in its own colours, with the name under the
  tile. Dark and Light are one control at the top. The chosen tile wears a
  ring and a check, and the arrow keys walk the grid. The fifty full-width
  colour bars are gone.
- The colour brush in a window's header sits where it belongs, just left of
  "Something wrong?", on the windows that draw their own header, such as
  Setup. It used to float in the middle of the title bar there.

## 0.4.134-beta

- Hold-to-talk on the desktop starts formatting sooner after you let go. The
  on-device route transcribes while you talk, in segments, and the release
  only pays for whatever is left after the last one. Segments now close after
  four seconds of speech and a short pause instead of five and a longer one,
  and a clause that runs past nine seconds without a pause closes on the next
  breath, so a fast talker no longer leaves the whole take for the release.
- iPhone (build 121): the "mic on" screen is two cards. The first says your
  mic is on and offers Next or OK; the second has the way back, the privacy
  facts and End the session, and its own arrow back. The app scales its type
  to the phone it is on and caps large text sizes so lines never run into
  each other.
- iPhone (build 121): the keyboard notices when Talk DAT! has been closed. A
  start the app never answers within two seconds stands the pill down, says
  so, and lets your keys through; the next tap opens the app again. Before
  this, a force-quit app left the pill listening to nothing and swallowed
  every key for up to two and a half minutes.
- iPhone (build 122): the suggestion lane above the keyboard is always there,
  like Apple's, with its dividers, and an email field offers your own address
  the way Apple's keyboard does: the account you signed in with, and
  addresses you have typed on this keyboard before. Email fields also get
  the @ and . keys beside the space bar. Nothing is looked up anywhere.
- iPhone (build 121): a dictation lands about a quarter sooner after you stop
  talking. The pause that ends it is 2.4 seconds instead of 3.2, and both the
  engine and the keyboard check for it more often.

## 0.4.133-beta

- Mac: signing in works at last. The Mac build was shipping without the
  library that reaches the login keychain, so every sign-in ended with "your
  macOS Keychain could not save the signed license". The library is in the
  bundle now.
- Mac: the on-device engine no longer asks for a CUDA graphics path that a Mac
  cannot have, which put a traceback in the log at every warm before falling
  back to the CPU.

## 0.4.132-beta

- Executive formatting can no longer invent a word. It may still raise the
  register, which is its job, but an output word with an inner capital that
  you never said, the way "I boot up" once came back as "IPad up" from the
  on-device finisher, is refused and your own words are kept instead.
- The right-click rewrite chip is off, for everyone. 0.4.131 was the first
  build that actually installed its mouse hook, and a mouse hook inside the
  app makes the whole PC's pointer wait for it whenever the app is busy: the
  lag reported within the hour. Windows also gives no way to put our entries
  inside other apps' right-click menus, which is what the chip was standing in
  for. Rewrite stays on the Fix That chord; on the Mac it stays in the native
  Services menu.

## 0.4.131-beta

- Local live captions now actually run. The switch under Settings > Voice
  (words as you speak on the on-device route) was saved but never reached the
  dictation session, so the Live captions strip stayed empty until you let go.
  It fills while you hold now, about a second behind your voice.
- The right-click rewrite chip (highlight text anywhere, right-click) is back.
  Its hook never installed next to the hotkey listener, quietly, since the two
  were first shipped together.

## 0.4.130-beta

- Mac and Windows: sign in or create your account from the Account window
  itself. Type your email, we send a six-digit code, type the code, done. The
  website stays one click away on the same card if you prefer it. On the
  Mac, the signed licence is kept in the login keychain.
- Words & Phrases now has a switch for learning the words you fix by hand,
  right above the list it fills, and says in plain words that it reads only
  what you copy and sends it nowhere. Words it learned are marked, so the
  list never shows an entry you do not remember making.
- Setup ends by accepting the Terms and the Privacy Notice, with both linked
  from the last step, and the app remembers which version you accepted.
  Nothing is sent anywhere to do it.
- Fixed: restoring a minimized Settings, History or other utility window could
  show its sidebar re-arranging itself after the window was already on screen.
  The rail's queued layout now finishes while the window is still hidden on
  every restore path, not only on the fast one. Most people saw this as a brief
  half-drawn sidebar when restoring a window on a busy machine (X-429).

## 0.4.129-beta

- Sign-in is an emailed code. On the website and on iPhone you type your
  address, we send six digits, and the code is the sign-in: no password to
  make, nothing to verify later. Sign in with Apple remains on iPhone. Google
  sign-in is gone, along with every Google service behind the account.
- Continue with Apple is on the website too (2026-09-04). It opens the same
  account as the iPhone's Sign in with Apple and the emailed code.
- Fixed: the website's account panel had stopped working. Sign-in, the three
  checkout buttons, the forever code and device activation all did nothing
  from 2026-09-03 until 2026-09-04. One leftover line from the password
  removal stopped the page's script before any of them was connected.
- iPhone: the app tells you when a new build is out, at the moments that
  matter and never during a recording, and the button opens TestFlight or
  the App Store depending on where your copy came from. It also reads its
  own build number correctly again, which it had not been doing since the
  SDK move; the keyboard's Restart notice depends on that too.
- iPhone: build 115 was withdrawn. It could end a dictation early and lose
  the words, and it made the keyboard miss taps. Build 116 puts the
  keyboard back to what shipped before it.
- The website has a typeface of its own on every device: the Knight display
  serif for headlines and Inter for everything else, both served from
  talkdat.app. One type scale, one set of shadows and radii, one brand colour
  across every page. The phone splash screen is gone, the hero is first on
  every device, and the nav shows one download button for your platform.
- The setup wizard has proper window controls, a real progress bar, and text
  set on a scale instead of caption-sized labels. Settings is called Settings,
  file paths are shown as short chips with a Show in Explorer button, actions
  look like buttons, and every theme name sits on a readable chip.
- The iPhone app reads like a native app: regular weight for body text, Apple's
  text sizes, a small set of corner radii, and Reduce Motion honoured on every
  screen including the Pill.
- On a cloud route with a capable machine, the local rescue model is warmed at
  launch, so the first dictation after a connection drop no longer waits for
  the engine to build.
- Finishing on a local model works, and is fast. The local route used to
  send the same 4,000-token rulebook the cloud gets, which a small model
  on your PC paid for on every dictation and then answered by returning
  your words unchanged. It now gets a compact contract written for it:
  Chill or Executive prose in about a second and a half on a GPU. A PC
  that cannot finish text in time says so in Settings instead of making
  you wait; the built-in rules take over.
- Executive keeps more of its good rewrites. The safety check that refuses
  a rewrite with an invented or missing number was counting a spoken "one"
  ("the old one") and an "oh, and" as numbers, and reading "the twelfth"
  written as "the 12th" as a new fact, so about a third of correct
  Executive rewrites were silently replaced by the plain rules, on the
  cloud as well as locally. Real numbers are still checked exactly.
- The rainbow waits for you to let go. While you hold the trigger, Talk
  DAT! keeps transcribing in the background so the finish is quick, but
  the Pill stays in its listening state the whole time. The rainbow now
  means one thing: the mic has closed and your words are being finished.
- The website leads with the three lanes: Local Forever first, with the
  cloud lane and your own key beside it. The comparison pages say the same
  above the fold. Words & Phrases, on the site and in the app, now says
  that a word you fix by hand and copy is learned for your next dictation.
- iPhone: sign in and see your plan. Settings > Account now shows what the
  account pays for, whichever way it paid: Free with the week's words used,
  Free trial with days left, Pro with its renewal, Local Forever. The App
  Store doors (Talk DAT! Pro, Local Forever, Restore purchases) sit under
  it, and on the United States storefront a Buy on the website row too.
  Manage opens the App Store or the website, whichever billed you.
- iPhone keyboard: haptics you can feel. Off, light, medium or heavy, in
  the app's Settings and in the keyboard's own settings; every key taps
  back. The board returns to letters by itself after a space, an
  apostrophe or return on the number and symbol planes, the way the system
  keyboard does, and stays put in a field that asked for numbers.
- iPhone keyboard: the swipe back finds the mic listening. After the
  Pill's hop to the app to arm the microphone, coming back to your app
  starts the dictation on its own, with a little more room before a pause
  ends it. A panel left open can no longer greet you as a black sheet, and
  the keyboard is capped at half the screen.
- iPhone keyboard: while your words are being finished, the Pill turns
  dark metal with the word formatting cut out of it and the rainbow
  flashing through the letters. Listening stays the full rainbow bar.
- See your words as you say them, on your PC. With a local model, the Pill
  can show the words so far while you hold the trigger (Settings > Voice >
  Local models, off by default). The finished text on release is unchanged.
  About 1.2 seconds behind your voice on this PC, on the GPU or the CPU.
- iPhone: a take with nothing in it says "Nothing heard" and closes the
  mic, instead of an upload error in developer words.
- iPhone keyboard: the Pill says Update when a newer build is out, and
  Restart when iOS is still running an older keyboard than the app. Tap
  Update and it opens TestFlight or the App Store, whichever installed
  this copy; tap Restart and it tells you the ten-second keyboard switch.

## 0.4.128-beta

- Dictation lands much sooner after you let go. On a PC with a DirectX 12 GPU
  the on-device Parakeet model now runs on the GPU: a 67-second take that took
  32 seconds to transcribe now takes under 4, and a short sentence appears in
  well under a second once the model is warm. A slow GPU falls back to the CPU
  on its own.
- A minute of speech is one pass through the speech model instead of thirty.
  Long takes used to be chopped into two-second pieces before transcription,
  which cost more time than the transcription itself and sometimes lost the
  first word of a piece. The model reads several minutes in one call now.
- Local finishing with Ollama sees its whole instruction set. The request
  window was too small for the Executive instructions, so the local model
  never saw them and echoed your words back; it now has room for the
  instructions, your dictation and its answer.
- Long dictations are transcribed while you are still talking. Each pause
  closes a segment that transcribes in the background, so the release only
  pays for the last few seconds. This existed before but never triggered,
  because the microphone auto-gain hid every pause from it.
- Dictation starts the moment you press the trigger, and the text lands the
  moment it is ready. A check that looks for a running meeting app (so the
  chime stays quiet on a call) used to run inline before the start chime and
  again before the finish chime, and it took one to two seconds each time on
  a busy PC. It runs in the background now and never delays you.
- Pasting is instant even when an image or rich text is on your clipboard.
  Talk DAT! keeps a copy of what was there, pastes through the clipboard, and
  puts your copy back, instead of typing every character one key at a time.
- Executive and Chill work again on PCs activated before the move to
  talkdat.app. Those installs still carried the old service address, and every
  finishing request was answered with an error page. The address is corrected
  automatically at launch.
- Setup wizard: the help chip no longer overlaps the window buttons, the
  speech-route step fits without scrolling, and the finish switch in the Pill
  menu says when it needs a sign-in to take effect.
- iPhone: History keeps its tab bar at the bottom when it is empty.

## 0.4.127-beta

- The setup wizard's test step now tells the truth about finishing. When Talk DAT!
  Cloud is not signed in on this PC, it says the result is the built-in tidy only
  and points you to Account, instead of reporting that formatting completed.
- Mac: the app bundle ships the theme materials, the brand font and the runtime
  icons, so Colors and the Pill Panel look the same as on Windows.
- Website: the home page loads faster on phones, and the Try it live and Theme
  controls read correctly to screen readers.

## 0.4.126-beta

- Talk DAT! has a new home: talkdat.app. The app now talks to api.talkdat.app for
  sign-in, activation and cloud features, and the website lives at www.talkdat.app.
  The old address keeps working and forwards to the new one.
- Licences are signed with a new key. If you had activated this PC before, sign in
  once more and the licence comes back; Local Forever purchases are unaffected.
- Sign-in accounts, purchases and device activations were carried over unchanged.

## 0.4.125-beta

- Settings pages are calmer. The pill geometry fields on General, the two raw JSON
  editors (Advanced options under Speech, Custom transforms under Formatting) and
  Voice shortcuts now open folded behind "Show details" with a one-line summary.
  Nothing moved and no default changed; the specialist controls simply wait to be
  asked for.
- If the cloud service cannot be reached, Talk DAT! now stays on the local engine
  for the rest of the day instead of retrying every three minutes, so dictation
  never stalls waiting on a service that is down.
- Service checks now ask the service whether it is healthy instead of only checking
  that its port answers, so a half-started service no longer shows as online.
- Checking the local rewrite engine no longer probes it twice.
- Groundwork for optional usage measurement is in this build. It is switched off,
  collects nothing and sends nothing.

## 0.4.124-beta

- Fixed a freeze that could ghost the whole app ("not responding") when pressing the
  trigger during setup's Learn-the-trigger page -- the interface no longer waits on
  the dictation engine, ever: status readouts now answer instantly even while a
  session is starting on a slow machine.
- Fixed a false "The microphone did not start" alarm that could fire a fraction of a
  second into a dictation instead of after the intended 2.5-second grace period.

## 0.4.123-beta

- Right-click any text in any app to rewrite it with Talk DAT! -- clean it up, make it
  shorter, make it friendlier, or type your own instruction. On Mac the same options
  appear in the system Services menu.
- Every theme in the picker now shows a real photographed-style material background --
  Roman Clay looks like troweled clay, Slate Quarry like split stone -- generated
  artwork, not flat colour bars.
- The Features menu now slides out to the side instead of growing down, and every menu
  feels lighter and faster.
- Local (on-device) transcription is significantly faster.
- When you choose the Local route, Talk DAT! is now locked to your machine -- nothing is
  sent to the cloud, guaranteed, and a small "Using local model" flag sits above the pill
  while it is on.
- Auto now stays on the cloud and only falls back to your PC after several failures in a
  row, switching back automatically once the cloud recovers.
- The finishing sound now plays exactly when your words are pasted, not before.
- Live Captions gained an always-visible close button and font-size controls you can
  change while it is running.
- Choosing which local model to use no longer switches your route to Local on its own.

## 0.4.122-beta

- Every Windows download is now digitally signed by Knight AI+AV LLC
  (Azure Trusted Signing, timestamped). Installers and the portable app
  identify their publisher to Windows instead of arriving as "Unknown
  publisher", and download reputation now builds on the company
  certificate across releases instead of resetting with each version.
  No feature changes; this release exists so signed binaries replace
  the unsigned ones immediately.

## 0.4.121-beta

- Fixed the crash when clicking or dragging the app's windows (Home, Setup,
  Settings). Window drags no longer borrow Windows' native move loop, which
  could kill the whole app mid-click on real hardware; the app now moves its
  windows itself. Drags may trail very slightly on heavy pages; the app
  surviving every click is the trade.

## 0.4.120-beta

- Fixed the crash on every tray menu click, for real this time, with the cause
  read out of the crash dump itself: Python's garbage collector was freeing
  interface objects on the tray's background thread, which the UI toolkit
  answers by killing the process. Menu clicks now hand their work to the UI
  thread over a plain queue, and cleanup of interface objects only ever runs
  on the UI thread. The 0.4.119 fix moved the click handling but not the
  cleanup, which is why the crash survived it.

## 0.4.119-beta

- Fixed the freeze-and-crash class traced to the system tray: every tray menu
  click now crosses to the UI thread before it runs. Tray interactions could
  previously corrupt the interface from a background thread, which is the
  access-violation signature in captured crash logs.
- Redesigned the tray menu around real use: double-click the tray icon to open
  Talk DAT!; everyday actions first (Hands-free, Pause/Resume, Cancel), places
  second (History, Scratchpad, Translate, Settings), rarely used rooms under
  More, and Panic stop / Quit fenced at the bottom.
- Windows crash reports now leave a full memory dump for support when the app
  dies outside its own logging.

## 0.4.118-beta

**A security review found nine things. All nine are fixed.**

- **"Local" now genuinely keeps your words on this PC.** Speech already stayed here, but the automatic finishing pass asked only whether your PC was activated, never where your speech had gone, so on the Local route the finished text was still sent to Talk DAT! Cloud and on to a formatting provider. The same happened if you brought your own transcription key. Both now use the on-device finisher, which is what the pill said all along. The default Auto and Cloud routes are unchanged.
- **A web page can no longer start your microphone.** The optional local control API answered any program on this machine, and a browser is a program on this machine, so any site you visited could quietly turn dictation on or paste your last transcript into whatever window had focus. Requests that a browser labels as coming from a page are now refused. Scripts, Stream Deck, AutoHotkey and the browser extension are unaffected.
- **Sign out now signs you out.** It never removed the stored entitlement, on any Windows machine, and reported that Credential Manager was unavailable when it was working perfectly. Anyone who was given or sold that PC inherited the activation.
- **"Start completely over" now actually starts over.** Two separate faults: your saved provider keys were left in Windows Credential Manager for the next person, and every settings section you asked to clear was restored from disk moments later. Custom words, snippets, settings and onboarding all survived a full reset that reported success.
- **Four files holding your dictated text are now included in the reset.** The searchable history database, your pinned transcripts, the formatting journal, and the pre-tabs scratchpad were all left behind by a factory reset.
- **The plaintext transcript log is now bounded.** It recorded every dictation forever, ignored your history limit, and nothing in the app ever trimmed it.
- **A provider key too large for Windows Credential Manager is no longer written to a settings file in plain text.** It used to fall through silently while Settings still said the key was protected.
- **Your licence token is no longer sent in a web address.** On live captions it travelled in the URL, which cloud hosting records in its request logs.
- **Four cost controls that could be walked around have been closed.** Sending any made-up authorisation header gave a caller a brand new rate-limit allowance; free trial transcription counted usage against a name the caller chose; live captions were billed only after the audio had already been used, and a refusal was ignored; and the public website demo asked its provider for eight times the output it can display.

## 0.4.117-beta

**"Reduce motion" now actually stops all of the motion.**

- **The Features menu no longer animates when you have asked it not to.** Switching motion off skipped the pill's own animation but not the menu's, so the accordion still slid open every time. If you turn motion off, it is usually for a reason, and "most of it" is not the setting you asked for.
- **A window near the edge of the screen no longer grows off it.** The previous release made each page take the room it needs, and a window sitting at the bottom-right could expand past the screen edge, carrying its buttons with it. Measured at 615 pixels off-screen before the fix.

## 0.4.116-beta

**Reset layout actually works now, by mouse and by keyboard.**

- **"Reset layout" in the pill menu did nothing when clicked.** It was drawn, it was styled, and the code that would have handled it was never connected to anything, so clicking it fell straight through. A button that ignores you is worse than one that is not there, because there is nothing to find and nothing to report.
- **You can now reach it with the keyboard too.** Arrow down past the last row and press Enter. Arrowing away cancels the confirmation, the same as tapping elsewhere does.

## 0.4.115-beta

**Reading your settings no longer switches your microphone on.**

- **The level meter stops starting just because you opened the Dictation page.** Browsing your options is not the same as asking to be listened to, and the only sign it had happened was a level bar moving. Choosing an input device still starts it, because that is when you actually want to see whether the microphone hears you, and leaving the page still stops it.
- **The meter now appears in Status and answers to Panic Stop.** It was one of the surfaces that made the old claim about the microphone untrue.

## 0.4.114-beta

**Three more settings that looked like they saved and did not.**

- **Trigger style, the Chill/Executive finish switch, and the Translation engine now save.** Each one changed the app the moment you touched it and was then thrown away when you closed Settings, unless you happened to change something else at the same time. That is why it would have felt random rather than broken.
- These were found by checking every setting that gets written to disk against the list that notices changes, instead of waiting for each one to be reported. Nothing else in Settings has the problem.

## 0.4.113-beta

**Long dictations stop cutting off at five minutes, Scribe is findable, and two pages you could not scroll now scroll.**

- **Paid accounts really do get the longer recording limit now.** The five-minute cut-off was supposed to have been lifted for paid plans a while ago. It never was: the app compared your setting against the plan's limit and took the smaller, and since the five-minute value ships in every install, it always won. Long dictations were being cut short exactly as before, with nothing in the interface to explain it.
- **Scribe is in the Features menu.** It has been built and working for a long time and there was no way to reach it from anywhere in the app.
- **Account & license scrolls.** It sits in the shared window, so it gets whatever size that window happens to be, and anything past the bottom edge was simply unreachable: no scrollbar, no mouse wheel, no resize edge. The activation code and sign-out live down there.
- **Offline speech lands on the right section again** instead of jumping to the bottom of the page.
- **Translate no longer calls itself a "private local" workspace.** It defaults to the cloud route, so that word was promising something the default does not do.

## 0.4.112-beta

**Setup can no longer type into another app, and Scratchpad really does save when you close it.**

- **The setup microphone test stays in the setup window.** It promises on screen that your test goes into the box instead of the app behind it. Leaving that step took the box away without stopping the recording, so what you had just said was delivered to whatever application was behind the wizard. It now stops the recording first and throws it away.
- **Starting the test with the trigger, rather than the button, is handled too.** The old cleanup only knew about the button.
- **Scratchpad's last edits survive the X.** The previous release added a save on close, and it did not run: closing a window destroys everything inside it before the save gets its turn, so the save found the editor already gone and quietly did nothing. Verified by typing, closing, and reading the file back.

## 0.4.111-beta

**Pages stop shrinking to fit whatever you opened first.**

- **Every page now gets the room it was designed for.** All the main pages share one window, and that window kept the size of whichever page you happened to open first. Open Stats and then Settings, and Settings arrived at less than half its width, with its own minimum size never applied. It was never random; it depended entirely on the order you opened things in.
- **Resizable pages can be resized again after switching pages.** The resize corner is part of the page, so it disappeared every time you moved to another one.
- **The window still does not jump.** Pages only grow to fit; they never shrink and never move, so a window you have sized and placed stays where you put it.

## 0.4.110-beta

**Two windows had buttons you could not click, because they were not on the window.**

- **What's New shows View release and Close again.** With release notes of any normal length, the notes filled the window and the button row was pushed off the bottom entirely. There is no system close button on that window, so Escape was the only way out and nothing looked wrong enough to report.
- **Stats shows Refresh and Close again.** Same cause, every time it opened.

## 0.4.109-beta

**The theme you pick now sticks, the pill sizes hold what you type, and two hidden features are findable.**

- **Choosing a colour theme now saves.** The Colors page repainted the app instantly and then never wrote the choice down, so it came back on the next launch. It only stuck if something else on another page happened to be unsaved at the same moment, which is why it seemed random rather than broken.
- **The six pill size boxes can hold your own numbers again.** Typing a width and pressing Save gave you the preset back every time. Picking Small, Medium or Large still rewrites all six together, and now you can see it happen the moment you click.
- **Fix that and Read back last appear in Settings.** Both have worked for a long time and had default shortcuts, and neither was listed anywhere, so there was no way to find them, change them, or turn them off.

## 0.4.108-beta

**Three shortcuts that saved and then did nothing now work.**

- **Translate last, Pin last and Meeting mode respond to their shortcuts.** All three were listed in Settings, accepted a key combination, and saved it without complaint. Nothing was listening for them, so the keys did nothing at all, with no error to find. A shortcut that saves and then does nothing is worse than one that is missing, because it makes you doubt your keyboard rather than look for another way.

## 0.4.107-beta

**Scratchpad stops losing your last sentence, and History stops offering to copy everything.**

- **Every way of closing Scratchpad now saves first.** Only the footer Close button did. The X, Escape and the window's own close button went straight to closing, and the pending autosave was cancelled on the way out, so the last half second of typing was dropped without a word.
- **History no longer has a "Copy selection" button that copies everything.** It sat directly beside "Copy all" and did the identical thing: one click put every transcript you have ever dictated on the clipboard, from a button whose label promised the opposite.

## 0.4.106-beta

**Closing Translate no longer sends your words somewhere else, and setup stops promising things the app does not do.**

- **Speaking into Translate can no longer escape it.** "Translate now" starts a real dictation and routes the result into the translation box. Closing the window took that route away without stopping the recording, so whatever you had just said arrived with nowhere to go and was pasted into whichever application happened to be in front of you. Closing or leaving now ends the recording first and throws it away.
- **Setup no longer says your voice never leaves this PC when it does.** That line appeared on every route, including the cloud routes whose whole job is sending audio to a transcription service. It now tells you the truth for the route you actually picked.
- **"Never loses a dictation" is gone.** The fallback is real but it is not seamless: a cloud failure can still cost you the phrase, and the retry uses audio already recorded rather than switching engines mid-sentence. It now says what it does.
- **"Free forever" is gone from the local route.** The models are yours forever and the audio does stay local, but free use is capped weekly after the trial and Local Forever is what removes the cap.

## 0.4.105-beta

**The microphone now stops when you close the thing that opened it.**

- **Closing Live Captions actually stops listening.** The stop lived only on the START/STOP button inside the captions window, and that window had five different ways to close: the Features toggle, two separate X buttons, Escape, and the window's own close button. Every one of them removed the window and left the microphone running, with nothing on screen to turn it off. Reopening then showed START while it was still listening, so the next press stopped a microphone the label said was idle.
- **Panic Stop now stops everything.** It ended the dictation session and nothing else. Live captions, the level meter in Settings, Mic Doctor, Race, pronunciation practice, Translate's Speak and the setup rehearsal all open the microphone on their own, and Panic left every one of them running while the pill went quiet and looked like it had worked.
- **The diagnostics page told you something untrue.** It said the microphone is only active during a dictation session. It now lists every surface actually holding the microphone, what each one is doing, and for how long.
- **Leaving a Settings page stops its level meter, and leaving Mic Doctor closes its stream.** Moving between pages inside one window never counted as closing, so these kept recording with their meters gone from the screen.
- **A failed start no longer pretends it worked.** Live captions flipped its button to STOP even when the engine refused to start.

## 0.4.104-beta

**It stops translating your dictation, and the pill stops fighting your keyboard.**

- **Auto-translate can no longer stay on behind your back.** The Translate workspace opens with a full-width "Auto-translate, tap to turn on" bar, and one click on it used to write that choice to disk permanently. Every dictation after that arrived in Spanish, across restarts, with nothing on screen saying so. It is now a switch for the session you are in: turn it on and it works exactly as before, close Talk DAT! and it is off again. Off is the only state a new install or a restart can be in.
- **The pill no longer starves your keyboard.** When a frame took longer than its budget, the animation queued the next one 4ms later and kept doing that, so drawing took over 90% of the interface thread and every hover, click and trigger waited behind it. Measured on a machine running a game: 16 frames a second at 44ms each, now 31 frames a second at 17ms. That backlog is why holding the trigger sometimes did nothing.
- **The pill drops its heaviest effect by itself when your machine is busy, and picks it back up when it is not.** Decided from measured frame cost, not from a setting, and deliberately slow to change its mind so it cannot flicker between two looks.
- **Features in the pill menu unfolds instead of rebuilding.** Opening it used to destroy the menu window and build a new one a few rows taller, re-rendering the whole blurred panel each time, in both directions. The same menu now grows in place in about a tenth of a second.
- **Three pill sizes.** Small, medium and large, in Settings under Overlay, with the spacing above your taskbar kept in proportion. Small is the default.
- **Talk DAT! now tells us how many people are actually using it.** An anonymous check-in carrying an install id, a version and an operating system, once a day, and nothing else.

## 0.4.103-beta

**Faster, and it answers the moment you press.**

- **The pill turns grey the instant you press, every time.** It used to open a network connection first and only then react, so on a slow link the press looked ignored and the pill jumped late. Now the grey is the first thing that happens and the pill only grows once the microphone is genuinely open.
- **The pill menu is dramatically lighter.** Moving between rows was redrawing the entire menu, blur and all, on every mouse move. It now reuses what it already drew, which is the difference between a menu and a slideshow on a modest machine.
- **The Mic Doctor button is back on the setup microphone page.** It was never drawing: that page asked Tk to lay out one row a way it refuses, so the page stopped rendering right before the button and said nothing about it.
- **Dragging a window can no longer freeze the app.** A synthetic click, from an accessibility tool or a macro, could put the app inside a Windows drag loop that nothing ended.
- **Em dashes are gone from the interface.** Thirty-four of them, including the trial and purchase text.
- The pill menu's first row is now **Settings**, matching the tray. It was called Home while its own description said settings.

## 0.4.102-beta

- **The Colors tab works.** Clicking it in Settings did nothing at all: the page was built and the rail offered it, but the two were never connected, so every click was discarded.

## 0.4.101-beta

- The hello page now sits in the middle of the window. The logo, the pill and the two lines float as one centred block instead of stacking at the top over a dead half-screen.

## 0.4.100-beta

**Fixes a crash that stopped 0.4.99 starting at all on Windows.** If 0.4.99
closed instantly or never appeared, this is the fix. Nothing else changed.

## 0.4.99-beta

The first thing a new user sees is a hello, not a decision.

- **A proper introduction leads the setup.** One simple page - the name, the pill, and what it does in two sentences - before any choices appear. Get started when you're ready.
- **Setup is a guided corridor now.** The sidebar no longer opens during onboarding (it also rendered broken on macOS there); it appears once you're in the app proper.
- **On a Mac, the app pins itself to the Dock on first launch** from Applications - once, and never again if you remove it.
- **The Mac download opens as a proper install window** - the app, an arrow, your Applications folder. Drag, done.

## 0.4.98-beta

The pill menu switches render whole, and Colors is the one home of color.

- **Fixed the collapsed switches in the pill menu.** A pre-layout width of one pixel slipped past a lazy fallback and both pinned switches rendered as slivers with clipped labels. One honest width source now feeds every menu measurement, with a test keeping the whole bug class extinct.
- **The theme list works on every monitor.** The color picker clamped itself to the primary display; on a monitor mounted above it, where coordinates run negative, it teleported off-screen and reads as a dead click. It now opens on the monitor you clicked on.
- **One home for color.** The theme row on General is gone; the Colors tab, where every theme is painted as itself, is the single place. Click a bar and the whole window re-themes instantly, the finish switch included.

## 0.4.97-beta

The finish is a real switch now, and pasting got faster.

- **Chill / Executive is a proper two-sided switch.** In the pill menu it sits pinned at the top next to the Cloud/Auto/Local switch, both sides labeled with icons and the active side visibly on. On the Home page it is a real control at the top of General, not a settings row pretending to be a menu. One tap flips it, everywhere the same.
- **Pasting is 40% faster.** The new sector benchmark found the vocabulary matcher doing repeated work; a cache cut the local pipeline from 153ms to 91ms per dictation with every correction guard intact.

## 0.4.96-beta

Hotfix: the slow CPU climb is gone.

- **Fixed a leak that made Talk DAT! use more CPU the longer it ran.** An internal timer registered a new bookkeeping entry forty times a second and never cleaned up; after a few hours the cleanup scan was costing a full CPU core. Found from the founder's own "why is it using 12%?" report, profiled live, fixed at the root, and pinned with a test. Restart onto this build and it stays flat.

## 0.4.95-beta

Your MIDI gear can drive the mic, and the glow finally matches the metal.

- **MIDI triggers.** Any note on any connected MIDI device works as a dictation trigger, alone or in chords, with the same styles and conflict rules as keys and gamepad buttons. Plug in, press capture, play the note.
- **The processing glow emanates the spectrum itself.** Every halo now samples the same smoked color loop the pill's body scrolls, so the light bleeding past the edge is the rainbow emerging, not a second brighter one.

## 0.4.94-beta

The click answers instantly, and the finish is yours to choose.

- **Click feedback, exactly as designed.** The moment you press the trigger, the compact pill drains to gray - same design, no motion, instant receipt. It expands into full color only when the microphone is actually listening. No more premature animation.
- **Chill and Executive, by name.** The two finishes are now Chill (your voice, tidied) and Executive (boardroom-ready). The pill menu carries a one-click switch that names the finish you'd flip to.
- **You choose your finish with your own words.** The setup test now shows your test dictation finished BOTH ways, side by side - pick your default on the spot. A few dictations later, the app asks once more with your real words, then never again. The pill menu flips it forever after.
- **Settings can no longer lose sections.** A saving process carries forward anything on disk it never loaded - the class of bug that twice switched off the formatting journal is closed.

## 0.4.93-beta

An accidental press costs a heartbeat, not thirty seconds. And the thinking rainbow becomes one loop of smoked metal.

- **Accidental activations end instantly.** Press the trigger, say nothing, let go: the mic closes and the pill returns to rest immediately. No more waiting out a silence timeout watching a loading state.
- **The thinking rainbow is one continuous loop.** The old art spent a quarter of its length in reds, so the loop showed red meeting red; the new spectrum travels the whole color wheel exactly once, seamlessly, over a darker smoked-metal finish. Smoother, richer, no visible bands.
- **Executive carries everything you said.** A closing joke stays a joke, a trailing cost question stays a question, and anything you read aloud is kept word for word inside quotation marks.
- **Em dashes are gone from every output.** The AI's favorite punctuation mark is banned in the prompt and scrubbed deterministically on the way out. Hyphens and ranges are untouched.
- **Every install counts itself.** A one-time anonymous ping - a random id, a version, a platform, nothing else - so the business numbers include the installs that never sign in.

## 0.4.92-beta

The best formatting is now the default. And send the evidence with the report, only if you choose to.

- **Executive is the default formatting level.** The full-logic, boardroom-grade pass is what everyone gets out of the box, your words still land instantly, and the polished version follows in about a second. Prefer your own voice kept as-is? Standard is one click away in Settings → General → Formatting level, and once you pick it, it stays.
- **The settings window is one piece now.** The sidebar and the pages share a single surface, no more bolted-on module look, and dragging the window hands the move to Windows itself, so everything glides as one, exactly like a native titlebar drag.
- **Fix That completes on release.** Holding the Fix That chord opened the mic but releasing it never applied the change, the release half was never wired. It is now, with a test that covers every hold-style shortcut's release.

- **"Include my formatting log" on Share an idea.** When your PC keeps a formatting log, the feedback window offers a checkbox to attach the recent entries to your report, so "the formatting messed up" arrives with the before-and-after that proves it. Unchecked by default, a View first button shows the exact file, and the privacy line changes to say plainly that dictated text is included. No checkbox, nothing leaves the machine, ever.
- **The formatting log is now a setting.** Settings → General → "Keep a local formatting log", no more editing config files to turn the diagnostic on.

## 0.4.91-beta

Executive mode: the boardroom rewrite, on demand.

- **A second formatting level.** Standard stays exactly what you know, your voice, cleaned. The new Executive level rewrites everything you say into polished, boardroom-ready prose: casual speech elevated, structure imposed, facts and numbers untouchable. Settings → General → Formatting level.
- **We now say it out loud: the AI may replace your text.** The instant paste is the fast pass; a beat later the cleaner version can take its place. The onboarding says so, and the setting explains itself.
- **A local formatting journal (off by default).** For diagnosing formatting, the app can keep a before/after record of each dictation on your own PC, never uploaded.

## 0.4.90-beta

The activation is smooth from the very first press.

- **The boot-time freeze is gone, at the root.** Opening Home used to load the audio engine on the same thread that animates the pill, measured at nearly eight seconds on a busy machine, which is why the first activation could glitch, freeze, and then "just start working." The audio engine now loads on its own thread, Home waits for a calm moment before appearing, and the microphone list fills itself in quietly.
- **The pill's growth animation is pre-warmed.** The one-time rendering cost that made the first activation of a session stutter is now paid invisibly in the idle seconds after launch. Measured: the first activation now runs at the same speed as the hundredth.

## 0.4.89-beta

Your profession's vocabulary, one click. And Settings that save themselves.

- **Industry vocabulary packs.** Military, medical, legal, and aviation packs ship in the app, 1,400 curated, domain-reviewed terms. One click in Settings → Formatting → Dictionary adds a whole profession's spelling; batch-paste your own on top.
- **Settings save themselves.** Change anything and it saves a moment later, quietly, the Save button stays for instant certainty. Shortcut conflicts still announce themselves in a sentence.
- **Every setting explains itself on hover.** All 180 controls across every tab now carry a plain-English explanation.
- **Menu shortcuts are visible.** Pill-menu actions with a keyboard shortcut show it right in the row, remap it and the label follows.
- **Controller triggers.** Xbox-class gamepad buttons (A, B, LB, RB and more) now work as dictation triggers, alone or in chords, with the same conflict rules as keys.
- **A calmer, premium installer.** Round two of the installer: one big Install button, a quiet "Installs to" line with Change tucked behind it, warm palette, no animated band.

## 0.4.88-beta

The field-test release: everything the first outside tester tripped over.

- **Clicking the pill never steals your cursor again.** The window style that was supposed to prevent it was applied to the wrong window handle; your text field now keeps focus while the pill starts listening.
- **Hotkeys can no longer die mid-session.** Trigger actions used to run on the keyboard hook's own thread; a slow start could get the hook silently removed by Windows, which looked like a crash. Dispatch moved to its own worker. Keys pressed one-after-another (Ctrl, then Win) always counted, that now survives every condition too.
- **Colors got their own tab.** Every theme is a full bar painted in its own background, text, and accent, click one, it applies live. The popup picker also learned to stay on multi-monitor setups.
- **Choose your trigger style in plain words.** Two buttons (hold + separate toggle), one button you hold, or one button you tap, in Settings and explained during onboarding, with a conflict checker that warns in one sentence when two shortcuts would fight (including the "reaching a three-key hold passes through a two-key tap" trap).
- **Short dictations behave like insertions.** A bare name or phrase gets no invented period and no leading space, it lands in a search box exactly as said. In chat apps, a single sentence drops its trailing period.
- **The dictionary takes batch paste.** Drop in a comma-separated list of terms, a whole team vocabulary in one paste.
- **The pill menu got a Home.** One entry opens everything, settings, tools, account; occasional features fold under one expandable row; Restart and Close moved to the bottom where every tray app keeps them.
- **The installer grew up.** A branded card appears the instant you double-click (no more wondering if it launched), the window is solid instead of see-through, the copy speaks plainly, and picking an install folder explains itself, including why some folders need admin rights, and a warning before installing into Downloads.
- **"Deck" is never "Talk DAT!".** Name corrections now require the heard word to actually sound like the name; mentioning the product nearby is not a license to rewrite different words. Acronyms in professional dictation expand on first mention, "search engine optimization (SEO)", only when the meaning is certain.
- **Long dictations think harder.** The cloud formatter spends real reasoning on document-length speech while one-liners keep the fast path.

## 0.4.87-beta

Formatting grows up, and the pill stops flinching.

- **Dictations come out clean and structured now.** On an activated PC, formatting runs on Talk DAT! Cloud, the same place your speech already goes, instead of a small local model that was quietly timing out and leaving transcripts nearly raw. Fillers like "ooh" and "mhm" are gone, self-corrections resolve ("the marketing push, I mean the beta push" keeps only what you settled on), reported speech gets real quotation marks, spoken sections become actual headings, and "make this a numbered list" does exactly that. Signed out, the local formatter still works as before.
- **Long dictations format fully.** The local engine previously stopped reading and stopped writing partway through long passages.
- **Clicking the pill always lands.** Ordinary hand jitter no longer makes a click read as a drag that silently does nothing, and a double-click can no longer open a session and slam it shut in the same instant.
- **The pill grows smoothly every time.** The expansion animation re-rendered its artwork from scratch on every frame of every activation; after the first activation it now reuses its work, so the growth stays fluid even while a game hogs the machine.
- **The Microsoft Store copy updates through the Store.** Store policy requires it, and the certification report asked for exactly this; the installer download remains the update path for copies installed from the website.

## 0.4.86-beta

Activating this PC from the website actually works now, end to end.

- **The "Activate this PC" flow was broken in every layer, and all of it is fixed.** The website's sign-in handoff never fired on a fresh landing, the account service rejected every handoff exchange, and the app itself had no receiver for the link the browser sends -- clicking it just popped "Talk Dat! is already running." All three are repaired: the link now reaches the running app within a second, and a cold start picks it up too.
- **The activation code the app shows you now lands ready on the website.** The page jumps straight to the account panel with the code filled in and the box focused, instead of leaving it 5,000 pixels below the fold with a greyed-out button.
- **One wrong password no longer freezes the account page.** Every button comes back after a failed attempt; before, seven of them stayed dead until a refresh.
- **Waiting on browser sign-in shows a countdown and a Cancel button.** The wait can no longer look like a hang, and a network blip mid-wait no longer abandons a sign-in you already finished in the browser.
- **Clearer answers everywhere.** Expired, mistyped, and already-used activation codes each say what they are (double-approving is harmlessly fine now); error messages name buttons that actually exist; and the empty "I have a code" box tells you what belongs in it.
- **Signed-in menus follow you to new PCs.** The menu arrangement your account saved now arrives with activation, as always intended.

## 0.4.85-beta

The black-slab glitch is cornered.

- **The pill can no longer flash a black rectangle during the finishing shimmer.** Windows occasionally dropped the pill's transparency while its fade animated, painting the window's square corners as a solid near-black slab. The fade now holds still while the pill is live or finishing, and the transparency key re-asserts itself on every real change -- a dropped key survives at most one frame. This is also step one against the stutter reports; the deeper fluidity work is next.

## 0.4.84-beta

The pill's right-click menu fits its own text on every display.

- **The pill menu no longer looks squished on scaled displays.** It was the one surface whose row heights and width never adjusted to your display's scale, so on 150% and 200% screens the text crammed into rows sized for 100%. It now scales exactly like the rest of the app.

## 0.4.83-beta

Launches can no longer be torn apart mid-start.

- **The app no longer unpacks itself into a temp folder on every launch.** That unpacking (1,653 files, every single start) was a race that antivirus scans and disk cleaners sometimes won -- the loser was you, seeing a crash about a missing module on an unlucky launch. The app's files are now laid down once by the installer and launches touch nothing temporary: starts are faster, nothing can tear, and the gigabytes of leftover temp folders that force-closed sessions used to strand are a thing of the past.

## 0.4.82-beta

Cancel a dictation with the key it started with, and local transcription stops hogging the machine.

- **Press the trigger again to cancel.** While the finishing shimmer plays, pressing your trigger cancels that dictation and the same press starts your redo -- release, decide "no", hold, and speak again. A re-press within a third of a second is treated as finger chatter and ignored, so a twitch can never throw away what you just said, and key auto-repeat while holding never cancels anything.
- **On-device transcription now has a CPU ceiling.** The local engines used to grab every core the moment they started -- on some machines that read as the whole PC freezing. They are now capped at half your cores (at most 4) and run below normal priority, so your actual work always wins the CPU. Dictation lands a beat later on long recordings; your machine stays yours.

## 0.4.81-beta

The release-to-rainbow moment is smooth now too.

- **The finishing rainbow no longer stutters.** Letting go of the keys plays the processing shimmer -- and that path was rebuilding and rescaling its whole color strip on every frame, measured at 29fps with visible hitches. The strip is now prepared once and simply scrolled: measured 54fps with a 6ms frame. Same colors, same shimmer, no lag when you release.

## 0.4.80-beta

The pill animates like it always should have, and setup remembers your place.

- **Dictation animation is 3x smoother.** The pill's live voice visual was measured at 14 frames per second -- one hidden per-pixel computation was eating the entire frame budget. Same visual, same glass, now measured at 45+ fps with a steady frame time. This is also the real fix behind "the app is choppy" and older "CPU spikes" reports.
- **Setup resumes where you left off.** Closing the setup wizard partway -- on purpose or via a crash -- used to restart it from step one and re-ask for things you had already done. It now saves your place and your progress at every step and resumes there.
- **Setup names your actual keys.** The practice step used to say "hold your trigger"; it now spells out the real keys (for example "HOLD Ctrl + Win while you speak, release to finish") so nobody has to guess what to press -- or that holding, not tapping, is the gesture.

## 0.4.79-beta

The update pile stops growing, and updates leave a trail.

- **Old update downloads now clean themselves up.** Every update Talk DAT! downloaded used to stay on your disk forever, one machine had 6.5 GB of dead installers going back a month. Stale ones are now removed after each new download and at every launch. If your PC has the pile, this release reclaims the space on its first start.
- **"Install from Check for updates" now records every step it takes**, downloading, verifying, launching, so if an update ever fails to finish on your machine, the log says exactly where it stopped, and a "Something wrong?" report can actually be acted on. (The install flow itself was re-verified end-to-end on a real machine while investigating a report from an older version.)

## 0.4.78-beta

Signed out no longer means silenced.

- **Dictation now works when you're signed out.** If your account isn't signed in on this PC, dictation used to stop with "Sign in to use Talk DAT! Cloud", even though your offline models were sitting right there. It now runs on your own machine automatically and the pill says so; signing in simply switches you back to the faster cloud engine. Nothing changed about what the cloud costs or who can use it.
- **On the website, the Mac download can no longer be hidden by a Windows update.** A Windows-only hotfix used to make the Mac button quietly hand out the Windows installer until the Mac build caught up. The site now always finds the newest Mac build on its own.

## 0.4.77-beta

Fixes 0.4.76 failing to start. Please install this immediately.

- **0.4.76 could crash on launch with an error box instead of opening.** The new trial-reminder feature shipped half-wired. If Talk DAT! showed you an "unhandled exception" message, this release is the fix, nothing about your words, settings, or license was affected.
- **Cloud formatting recovers properly after a connection blip.** A lost response used to make the retry fail by design and quietly downgrade that dictation's formatting; the retry now genuinely works. This also stops those retries from wasting your cloud allowance.

## 0.4.76-beta

Your trial gets a proper ending, Translation is finally one clean page, and a rare crash class is gone.

- **Your trial now ends with a conversation, not a silence.** Two days before it ends, Talk DAT! shows you exactly what stays free and what owning it keeps, once a day at most, never mid-dictation. When it ends, one honest screen says nothing was lost and the free plan is already carrying you.
- **Translation is one pair of boxes at last.** A layout fault was drawing the options bar across the middle of the two text areas, which made the page read as four boxes. It is one clean pair now, the cloud engine is the default for everyone, and the install ceremony only appears if you deliberately choose the on-device engine.
- **Checkboxes look like they belong in this decade.** Every checkbox in the app is now a properly drawn rounded box with an accent check, in your theme's colours.
- **Fixed a rare random-crash class.** A threading fault in how background work returned to the interface could, on rare occasions, abort the app with no error message. Found by the Mac team, confirmed shared, now guarded on Windows too.
- **On the website, Mac visitors now get the Mac download** from the big buttons, they were being handed the Windows installer.

## 0.4.75-beta

A pass over every screen, with screenshots, fixing what only an eye can catch.

- **"Something wrong?" no longer sits on top of your buttons.** On every window it overlapped Close, Cancel or Continue, and it was cut in half, because its box was narrower than the words in it. It now sits in the top border, clear of everything, and reads properly.
- **The report link and the colour ring were missing from most pages.** They appeared on the first window you opened and on none after it. Both are back everywhere.
- **Account & license showed the wrong prices.** It still described a 2,000-word local-only free tier; the real one is 1,000 words a week on Talk DAT! Cloud. Corrected on the one screen where that matters most.
- **Long paragraphs are back to their proper width.** A change in the last release squeezed some pages into a narrow strip of text down one side. That is undone, and the line it was meant to fix is fixed directly.

## 0.4.74-beta

Text fits its box at any window size, and running out of free cloud stops being treated like a fault.

- **Nothing gets cut off any more, at any size.** Long lines were wrapped to fixed widths chosen for one particular window size, so anything else clipped the last line, including the very first thing a new user reads on the Offline speech page. Every paragraph now wraps to the width it actually has, and re-wraps when you resize the window.
- **Using up your free cloud words is no longer treated as an error.** It used to look like a dropped connection: a red flash, a beep, and unformatted text, on every single dictation until the allowance refilled. Now Talk DAT! simply finishes the sentence on your PC, tells you once, and carries on.

## 0.4.73-beta

Faster to start, and a set of small things that were quietly wrong.

- **Talk DAT! starts noticeably quicker.** A chunk of the startup work was loading tools that are only needed the moment you paste, they now load when they are actually used, taking about a third off the launch cost.
- **Two hidden timers were running forever.** Visiting the Account page left something checking your licence every 0.7 seconds, and Mic Doctor left a meter redrawing fifteen times a second, for the rest of the session, long after you had moved on. Both now stop when you leave the page.
- **"Everything, start completely over" is readable again.** On the Start over screen the four choices were squeezed into one row, cutting the most serious option down to a fragment. Each now gets its own full-width row, those labels are the safety feature.
- **The Model Guide no longer names our cloud engine.** What powers Talk DAT! Cloud is ours to know; the guide now simply says Talk DAT! Cloud.

## 0.4.72-beta

The cloud is for everyone now, and it got a lot faster.

- **Your free words now run on Talk DAT! Cloud.** The free allowance is the same 1,000 words a week it has always been, what changed is the engine behind them. Free accounts used to be restricted to on-device models; now those words go through our servers, which are faster and more accurate, and the on-device engine takes over the moment the allowance or your connection runs out. Pro and the Cloud add-on remain unlimited.
- **Cloud dictation is about half a second faster, every time.** The app used to build a brand-new secure connection for every sentence. It now keeps one open and warms it up the moment you start speaking, so the wait after you stop is just the transcription, measured at 564ms of pure connection overhead before, about 70ms now.
- **New installs start on the cloud.** It is the faster, more accurate path and every account can now reach it. Your offline model still downloads in the background and takes over instantly whenever the network or your allowance runs out.

## 0.4.71-beta

Every issue reported from inside the app, fixed.

- **A new typeface across the whole app: Constantia.** Classic, warm, and genuinely easy on the eyes for long sessions, and it is now the default for everyone. Prefer something else? **Settings → General → App font** offers Candara, a crisp system sans, and Knight AI+AV everywhere.
- **You will never miss an important fix again.** When a release repairs something you are living with, your app updates itself and a **red dot appears on the Pill**. A green dot means an update is simply waiting whenever you want it. Click the dot to see what changed.

- **The app no longer sits there burning your CPU.** At rest it was redrawing the Pill forty times a second forever, measured at over half a processor core on an idle machine. It now draws only when something actually changes: idle cost is effectively zero.
- **Fixed a freeze on the welcome screen.** Rounding the window corners forced a repaint at the exact moment the window was still laying itself out, which could wedge the whole app, the first thing a new person would ever see. Corners now round without blocking anything.
- **Text is crisp and fits its boxes again.** The Knight AI+AV face is a display face: gorgeous large, but at label size it set wider and taller than the layouts allow, so lines overlapped, ran past their boxes, and looked thin and jagged. It now owns the headings and titles where it belongs, with a crisp companion face carrying the small text. Prefer one face throughout? **Settings → General → App font** offers Knight AI+AV everywhere, plus Candara and Constantia.
- **The colour wheel works on every window.** On the welcome screen it saved your choice and repainted nothing, which looked broken. Every window now redresses on the spot.
- **"Prepare local model" tells you what happened.** It reports downloading, verifying, and ready, and if your model is already installed it says so, instead of looking like a dead button.

## 0.4.70-beta

Themes snap into place, and the theme list shows its true colors.

- **Picking a theme now redresses the whole Settings window instantly.** The six pages, every section, every header, not just the frame around them. (The page bodies were keeping their old colors, which made the theme picker feel dead.)
- **Every bar in the theme list now IS that theme.** Each row's background is the theme's actual background, the name is written in its text color, and its panel and accent colors sit as swatches on the right, so you're choosing between real looks, not labels.

## 0.4.69-beta

Captions go word-by-word on cloud plans, and the app quietly tunes itself to your PC.

- **The whole app now wears the Knight AI+AV typeface**, every label, button, tab, and menu, with true bold where bold belongs. The installer and the setup guide wear it too. Prefer something easier on the eyes for long sessions? Settings → General → App font offers two classy alternatives: Constantia (a classic serif) and Candara (a soft sans), the change applies instantly.

- **Live captions now stream word by word on Talk DAT! Cloud plans.** Words appear the instant you say them instead of every couple of seconds. If the connection hiccups mid-sentence, captions switch to your local engine on the spot and keep rolling, they never just stop.
- **Talk DAT! now sizes its offline engine to your machine.** On first run it takes one quick look at your PC, cores, memory, graphics, and downloads the local model that will actually run well there, so "works without internet" is tuned for your hardware, not a one-size guess.
- **Words you keep fixing now teach the app in two takes.** Distinctive spellings still learn instantly; an ordinary-looking word (like a name) joins your dictionary after you correct it a second time within two weeks. And when you say "Don't save," it stays gone, no more nagging re-offers.
- **The Race now hands you the script.** Press Speak and the two test sentences appear on screen; it records eight untouched seconds and times each engine honestly, one at a time.
- **Taking something back mid-sentence now works every single time.** Say "call mom, I mean call dad," or restart a phrase ("how is, not that one, how is the other one going"), and only what you settled on lands on the page. This used to depend on the AI's mood; now it's a built-in rule.
- **Every resizable window now stretches from any edge or corner**, with the proper arrow cursors, not just the little corner grip.

## 0.4.68-beta

Settings finally makes sense, and the whole app got dressier.

- **Settings is six flat pages now: General, Dictation, Formatting, Speech, Advanced, Tools.** No more "Home" tab, no more menus inside menus. Every control kept its home; the pages scroll, and old links land exactly where they should.
- **The Race lives on Settings → Advanced**, embedded right in the page, next to Backups & diagnostics.
- **A tiny rainbow ring sits in the corner of every window.** Click it, pick a theme from the painted list, and the window redresses itself instantly.
- **"Something wrong?" is engraved into every window's edge**, the mystery "?" is gone. Same one-tap report, now it says what it does.
- **Translation defaults to Talk DAT! Cloud.** Pick "This PC (local)" and the model controls appear; on cloud there is nothing to install, so nothing installation-ish is shown.
- **Ramble shows a fat rainbow RAMBLE banner while it records**, drag it anywhere, double-click to tuck it away. It leaves when your document is ready.
- **Ramble PDFs come in ten looks.** Pick from a swipeable shelf, Executive, Serif memo, Typewriter, Midnight, Ivory, Minimal, Boardroom, Manuscript, Blueprint, Noir gold, each previewed exactly as it prints.
- **The Scratchpad wears your theme now** and gained a Font button: the Knight AI+AV face plus five everyday and five regal fonts, each shown in itself.
- **Headings across the app now use the Knight AI+AV display face**, the same one as the website.
- **History is calmer:** the four everyday buttons stay; exports, file access and the two destructive clears moved behind one "More…" menu where a stray click can't reach them.

## 0.4.67-beta

### One window, like a real application

- Every page, Settings, History, Scratchpad, Translate, Account and the
  rest, now lives in a single window that keeps its size and position.
  Switching pages swaps the content in place: nothing closes, nothing
  reopens, nothing jumps.

### Live captions actually stream now

- Captions run on their own dedicated engine: your words appear WHILE
  you speak, entirely on your PC, and dictation stays free to use at the
  same time.
- The strip can be resized from any edge or corner, the close button is
  always visible, and the text flows like a ticker at pager size or
  rolls like broadcast captions when larger.

### Your clipboard is yours again

- After a dictation pastes, whatever you had copied before is back on
  the clipboard, copy a link, say "here's the link", paste the link.
  Prefer the old behavior? One switch in Settings.

### A quicker, cleaner menu

- The pill menu carries the daily things; Account, Words & phrases,
  Race, Mic Doctor and Share an idea moved into Settings → Tools.
- "Words & phrases" also learned the ways people actually say
  "Talk DAT!", all of them now correct themselves.
- Scribe is retired.

### Fixes from the field

- The idea window's Send button is back on screen, centered where it
  belongs.
- The Account page: no more overlapping header, "Account email" says
  what it is, and the code box only appears when you're signed out.
- A failed cloud dictation now flashes red with a quiet double-beep
  instead of silently freezing your PC with a local rescue; a second
  miss in a row switches to your PC automatically.
- Auto-translate results are never rewritten back to English by the
  polish pass.
- Mic Doctor lost its slow Auto-detect button; the sidebar got wider,
  smoother, and easier to reopen when collapsed.

## 0.4.66-beta

### What's New never comes up empty

- Updating across several versions now shows every version you skipped,
  a highlights digest first, full details after, instead of only the
  newest release's notes.
- Offline or rate-limited, the app now reads its own bundled release
  notes, so this window always has the full story.

### Reset the pill menu, safely

- A quiet "Reset layout" now sits at the bottom of the pill menu. First
  tap asks "sure?", second tap restores the recommended order, your
  arrangement can't be lost to a stray click.

### Pricing

- Talk DAT! Cloud is $11.99 a month for new subscribers. Existing
  subscriptions keep the price they signed up at.

## 0.4.65-beta

### Live captions, rebuilt as black glass

- The caption strip is now a borderless black-glass tablet: one clean
  surface, an emerald START in plain text (a soft glow appears under
  your cursor), and a real start, tap it and captions run hands-free,
  painting your words live without pasting anything anywhere.
- New Clear mode: the body turns fully transparent so only the white
  words float over whatever is behind, with a hairline border to grab.
- Drag it to any size, the type scales itself to stay readable, from
  the slim pager it opens as to a full wall caption. One tap on Pager
  returns it to its classic spot above the pill.

## 0.4.64-beta

### Translation is now two buttons

- One big switch: "Auto-translate [your language] → [their language]",
  tap it and every dictation arrives translated. Right under it,
  "Translate now": tap, talk, tap, what you said appears translated.
  No setup, no ceremony. The full workspace is still below for power use.

### The Race (was "Taste the cloud")

- Renamed, and made honest: each engine now runs ALONE, one after the
  other, so the local model's CPU load can no longer flatter itself by
  slowing the cloud's clock. The lane being tested lights up green and
  advances automatically, and a living slice of the pill animates while
  the race runs so pressing Speak visibly does something.

### Small fixes

- Sidebar navigation opens pages in place, the new page takes this
  window's spot instead of stacking another window.
- The pill no longer slowly fades when nobody is hovering it (a missed
  mouse-leave left it thinking it was hovered forever).

## 0.4.63-beta

### Every window gets a real sidebar

- A left sidebar now opens with every window -- every destination spelled
  out, the page you're on highlighted, hover glow on the rest. Slide it
  closed to a slim rail with one click; it remembers your choice. The
  pill's own right-click menu is unchanged.

### Cleaner, calmer windows

- One close button everywhere: same look, same corner, and a much bigger
  target -- clicking near the ✕ counts.
- Windows no longer force themselves above your other apps. Only the
  pill and its menu float; everything else behaves like a normal window.
- Pop-ups and chips that ignored your theme now follow it.
- Fixed windows occasionally gluing to the mouse after a click and
  following it unheld.

### Smarter speech behind the scenes

- Talk DAT! Cloud now runs an invisible relay of speech engines ranked
  by measured accuracy, falling through automatically if one stumbles --
  you only ever see your words.

## 0.4.62-beta

### Mic Doctor is live now

- A real-time level bar moves with your voice the moment the window
  opens -- no clicking required to see whether the app hears you.
- Picking a device in the dropdown applies it instantly, everywhere in
  the app. The old "Use this mic" button is gone; the dropdown is the
  control, and it shows which device Windows currently calls default.
- New Auto-detect: keep talking and it samples every input, then
  selects the one actually hearing your voice.

### Cloud tries twice before your PC steps in

- If a live cloud dictation is interrupted, the app now retries the
  captured audio on the cloud first -- one quick upload, about a second
  -- and only transcribes locally if that also fails. Never both at
  once, and a finished transcript whose connection dropped at the very
  end is kept as-is instead of being wastefully redone.
- Fixed a rare case where the smart formatter's reply was lost in
  transit and the retry was refused as a duplicate, quietly downgrading
  punctuation for that dictation.

## 0.4.61-beta

### Your first five minutes lead with Cloud

- Onboarding now leads with Talk DAT! Cloud, the fastest, most accurate
  route, included in every 14-day trial, so your first dictation is the
  best one. On-device keeps its own card as the other half of the story:
  every local model, offline and free forever, with the trade-off stated
  plainly right where you choose.

### The app now sizes up your PC

- A quick hardware check (cores, memory, GPU, nothing leaves your
  machine) picks the on-device model your computer can actually carry,
  and the local card shows both the verdict and why. Strong machines get
  the strongest models; modest ones get one that will not stutter.
  Verified today across six speech engines on real hardware, every one
  functional, none crashing.

## 0.4.60-beta

### Cloud falling back is never silent again

- When a cloud dictation has to finish on your PC, the pill now says so
  with a clear toast every time -- no more quiet degradation you only
  notice as "it feels worse today".

### Pricing and plans

- Talk DAT! Cloud is now $10.99 a month for new subscribers. Existing
  subscriptions keep the price they signed up at.
- The free plan's on-device allowance is now 1,000 words a week after
  the trial. The 14-day full trial is unchanged.

## 0.4.59-beta

### Formatting is 10x faster on long talks

- The vocabulary matcher recomputed the same phonetic keys hundreds of
  thousands of times on a long dictation -- 7.6 seconds of pure CPU on an
  800-word talk, felt as lag and a CPU spike right after you stop
  speaking. Measured and memoized: the same talk now formats in about
  0.7 seconds, and short dictations in a blink.

### Long dictations stay on the cloud

- Dictations longer than about fifteen seconds were being declared failed
  right at the finish line: the cloud engine was still delivering its
  final words when a fixed two-second window gave up, so the entire
  recording was silently re-transcribed on your PC -- the "why did that
  take 45 seconds" experience, with the CPU spike to match. The finishing
  step now waits as long as results are still arriving and only gives up
  when the stream truly stalls. Long talks come back at cloud speed.

### Activation works again

- A mismatch between the licence signing key and the key bundled in the
  app could silently invalidate activations -- Talk DAT! Cloud then fell
  back to the local model without saying so, which felt like sudden lag
  and dumber punctuation. The keys were rotated as a matched pair; if
  your PC lost its activation, activate once and it now sticks.

## 0.4.58-beta

### The voice wave is back on the Pill

- The live voice wave vanished for quiet microphones -- the Pill was
  metering the raw mic signal, which sat below the visual noise floor for
  exactly the setups that need auto-gain. The meter now shows the same
  lifted signal the recognizer hears, so the wave moves for every mic,
  and loud mics keep their syllable shape instead of pinning at full.

### Hears you better

- Microphone auto-gain aims hotter and can lift further, matching how
  leading dictation apps run their capture. If you felt the app misheard
  you while other tools coped on the same mic, this release is for you.

### "Cloud" stops autocorrecting to "Claude"

- Saying "the cloud", "to cloud", "on cloud" now stays "cloud". Talking
  ABOUT Claude (Claude Code, Claude models) still capitalizes correctly,
  and words like "called" are never touched.

## 0.4.57-beta

### Mic Doctor routes your audio now

- Pick any input device inside Mic Doctor, click "Use this mic", and
  press Check to prove it -- the whole app follows your choice
  immediately. Refresh the list when you plug something in.

### Windows that behave like windows

- Drag any Talk DAT! window to a screen edge and it snaps: left or right
  edge takes half the screen, the top takes the upper band. Drop it
  anywhere else and it stays put.
- Resizable windows now remember their size and reopen exactly as you
  left them.

## 0.4.56-beta

- On multi-monitor setups, toasts and update notes now appear above the
  pill -- on the pill's own screen -- instead of drifting to the primary
  display.
- The dead-microphone warning now also fires when the microphone fails to
  start at all (not only when it starts and hears nothing).

## 0.4.55-beta

- Check for updates can no longer fail silently: any error now shows a
  plain message and writes the reason to the log, and every check logs
  its result. (If it says you are up to date -- you are.)

## 0.4.54-beta

- The dead-microphone warning now fires at two seconds instead of four.

## 0.4.53-beta

### It tells you when the mic is dead

- Start dictating into a microphone that is not actually picking anything
  up and Talk DAT! says so within seconds -- a falling chime and a plain
  message pointing at the fix -- instead of letting you talk a paragraph
  into nothing. First of a family of self-checks that catch problems
  before you notice them.

## 0.4.52-beta

### Updates find you now

- When a new version ships, the app tells you -- live if you are using it,
  or the next time it opens. Wave the dialog away three times and it stops
  interrupting: a tiny note above the pill takes over, one click to
  update. And until you do, the pill menu's update row shows red with the
  waiting version, so you always know.

### Sharper to read

- Dropdown pickers were rendering pale-on-pale on dark themes (found by
  the Mac side of the team, fixed on both platforms): microphone and
  model choices now read clearly everywhere, popup list included.

## 0.4.51-beta

### The highlight follows your cursor again

- After the route switch arrived, the pill menu's hover highlight (and
  drag-drop targeting) could sit one row above your cursor -- the glow on
  Settings while you pointed at Offline speech. Every piece of the menu's
  row geometry now reads one shared origin, a test stands guard over it,
  and the highlight is exactly where your cursor is.

## 0.4.50-beta

### Switch engines with one tap

- The pill's right-click menu now opens with a three-position switch:
  **Cloud | Auto | Local**. Tap to move your dictation between your cloud
  engine and your machine at will, no settings dive. Auto, the default,
  uses your cloud whenever it can actually work and your machine
  otherwise. If your plan does not include managed cloud, that position
  shows locked and tapping it explains the upgrade instead of failing.
- Wherever you flip it, every other menu agrees instantly, the Settings
  speech tab repaints live, and your previous cloud choice is remembered,
  so switching back lands exactly where you left.

## 0.4.49-beta

### The crash is dead for real this time

- Found with the new crash breadcrumbs: the follow-your-focus feature was
  accidentally re-arming itself every time your mouse LEFT the pill,
  leaving Windows calling into freed memory -- random crashes that got
  more likely the more you used the app. It now arms exactly once at
  startup, releases cleanly on exit, and cannot stack. If you saw the app
  vanish repeatedly today, this is the one.

## 0.4.48-beta

### Stability

- Fixed random crashes introduced with the pill's follow-your-focus
  feature: the Windows focus event was doing UI work in a place Windows
  does not allow it. The pill still follows your focus instantly; the
  work now happens on the app's own schedule.
- If the app ever dies hard again, it now leaves a full technical
  traceback in crash-traceback.log beside your settings -- so the next
  report comes with the exact line, not a mystery.

## 0.4.47-beta

### Names survive being heard as one word

- Recognizers love to fuse compounds: "talk dat" can arrive as the single
  token "TalkDad", "pay pal" as "paypal". Multi-word names now try
  one-word windows too, so the fused hearings correct themselves -- found
  by running a real sentence through the shipped local model during the
  full feature check.
- Casing is part of the correction: a lowercase "github" now becomes
  "GitHub"; text already letter-for-letter right stays untouched.

## 0.4.46-beta

### Sign in on the web, land in the app

- Press Continue with Google, sign in in your browser, click "Open Talk
  DAT!" when it asks -- and this PC is activated. No codes to type. The
  code flow stays for anyone who prefers it, and "Manage on the website"
  is now simply "Website".

### Long dictations finish almost instantly

- On long sessions, finished sentences transcribe quietly WHILE you keep
  talking; letting go only processes the last few seconds. An hour-long
  ramble no longer pays for its whole length at the end.

### Feel it before you buy it

- "Taste the cloud" in the pill menu races our servers against your own
  machine on one recording -- two lanes, two honest times, your voice.
  Five tastes an hour on the house.
- Mic Doctor gives your microphone a twenty-second checkup with plain
  advice, from the pill menu or right inside setup.

### Everywhere you look

- The installer wears the real roman-clay finish. Every window grows a
  small menu glyph that jumps to any other menu, backgrounds re-fit
  themselves when you resize, and no window can collapse into a broken
  layout.

## 0.4.45-beta

### Ramble

- Click Ramble in the pill menu, pick PDF, Word, Markdown or plain text,
  and talk for up to an hour. When you finish, a real formatted document
  lands in Documents/Talk DAT! Rambles and the folder opens itself.
  (Talk DAT! Cloud.)

### Scribe

- Two-sided notes for calls and meetings: your mic is You, what your
  speakers play is Them, and Scribe interleaves both into a readable
  transcript with a summary on top -- decision-shaped sentences first, so
  the follow-up email writes itself. Saved to Documents/Talk DAT! Notes.
  Included with Local Forever and Cloud; Cloud gets the polished summary.

### Live captions

- Toggle Live captions and your words appear in a clean strip at the
  bottom of the screen as you speak -- for streams, calls, and anyone
  reading along. (Talk DAT! Cloud.)

## 0.4.44-beta

### Fix That

- Highlight text in any app, hold Ctrl+Alt+F, say what you want -- "make
  it shorter and friendlier", "turn this into bullet points" -- release,
  and the selection rewrites in place. Your words are never invented,
  never dropped; if anything goes wrong, the selection is left exactly as
  it was. (Talk DAT! Cloud.)

### It sounds like you

- The cloud polish quietly learns your voice from dictations you accept --
  contraction habits, favorite openers, sentence rhythm -- and rewrites
  start matching YOUR register instead of a generic one. Counts only,
  never your words, and nothing renders until it has real evidence.

### Hear it before you send it

- A new bindable Read-back key speaks your last dictation through the
  system voice. Eyes-free proofreading.

### Under the hood

- The taste-test service went live server-side (five 30-second cloud
  tastes per hour for anyone without a subscription -- the in-app race
  arrives next update), and Mic Doctor's analysis engine landed ahead of
  its guided setup page.

## 0.4.43-beta

### Teach it with your voice

- The Add words window gained a Record button: type the word, say it three
  times, and Talk DAT! learns what your microphone actually hears -- then
  spells it right forever. Switch speech engines and it quietly re-learns
  from the same recordings. Nothing is uploaded, ever.

### The names on your screen spell themselves

- Reply to an email and the sender's name comes out spelled correctly:
  at the moment you start dictating, the window title's names bias that
  one dictation -- on your machine, never stored, never sent anywhere.
  Your own saved spellings always win. Off switch in the dictionary
  settings.

### Speak two languages without touching anything

- New opt-in for auto-translate users: flip into your target language
  mid-conversation and your words are delivered as spoken instead of
  translated twice. Deliberately cautious -- short or mixed sentences
  never trigger it, and it is off unless you turn it on.

## 0.4.42-beta

### Talk DAT! finally spells itself everywhere

- The one that got away is caught: the app's own name (and any name ending
  in ! or ?) used to lose its mark mid-sentence -- the formatter read the
  bang as a sentence end, split there, and swapped it for a period. Names
  are now stamped onto finished sentences, so "Talk DAT!" survives every
  position, including sentence-final.

### Say the punctuation, get the punctuation

- "quote ... end quote" becomes real quotes. A habitual "period" becomes
  one. "new line" breaks the line. And "the trial period ends" is left
  completely alone -- the word before tells a noun from a dictated mark,
  so there is no mode to switch and nothing to learn.

### Corrections repair even when the mic mangles them

- "strike that", "forget that", and "correction" now trigger the same
  self-repair as "I mean" -- and when a recognizer eats the "I" and leaves
  a stray "mean" mid-sentence, the repair still runs.

## 0.4.41-beta

### Whispering just works

- A new always-on audio front-end sits ahead of every speech engine: auto
  gain lifts real-but-quiet speech toward conversational level, falls back
  instantly when you speak up, holds still through silence, and a soft
  limiter keeps anything from clipping. Dictate at 2am in a whisper --
  no mode to find, nothing to configure.

### Arrange the menu your way

- Press and hold any pill-menu row and it lifts; drag it where you want;
  let go. Or grab the grip dots on the left edge of the hovered row and
  drag instantly. Your order saves to this PC and to your account, and
  app updates slot new items in without disturbing your arrangement.

### Quieter, cleaner, yours

- On a call? Talk DAT! notices conferencing apps and holds its chimes and
  pop-overs until you are done. Dictation itself never pauses.
- Every dictation can mirror into a Markdown folder -- point it at an
  Obsidian vault and each day becomes a dated note. Off by default.
- The stray decorative arcs some menus showed are gone for good, windows
  drag from any empty surface, and on Windows 11 every floating window
  gets GPU-smooth corners with a real soft shadow.

## 0.4.40-beta

### The pill follows you

- Switch windows and the pill is already there: focus changes now push to
  the overlay instantly instead of waiting for a click, and every window
  the app opens appears on the monitor the pill is on -- not the other
  screen.

### Share an idea actually sends

- The Share an idea window now has a real Send button. Reports go straight
  to the Talk DAT! team over the wire -- no email app, no account -- and
  you are told plainly whether it went through.
- Every menu gained a small "?" in its corner: write what felt wrong in
  that exact menu, press Enter, done. It arrives labelled with the menu it
  came from.

### Fixes with receipts

- "open a window" is never rewritten to "OpenAI window" again -- the brand
  that caused it left the registry, with tests standing guard.
- "When I open a window?" now punctuates as you meant it -- fronted
  when/where/why/how clauses stop being mistaken for questions, and a
  mid-sentence mark becomes the comma it should have been.
- Paid plans stopped hitting the five-minute recording wall: on-device
  dictation now runs to 10 hours, cloud to 1 hour, and your own smaller
  setting is still honoured.
- The pill dims out of your way twice as fast on hover, and the Stats
  window lost its boxed-off label rows.

## 0.4.39-beta

### Brand names fix themselves

- Say a product and get its real spelling: "nav orb" becomes NavOrb, "git
  hub" becomes GitHub, "you tube" becomes YouTube, "chat gpt" becomes
  ChatGPT. Knight AI+AV's own products lead the registry. Your dictionary
  always outranks it, and it can be switched off entirely.
- Common words stay safe: "I built it" and "my wife called" are never touched
  -- names whose sound could collide with everyday English were kept out on
  purpose, and matching now checks the size of a word as well as its sound.

### Translation that meets you where you are

- A new capturable hotkey flips automatic translation on and off, and the
  pill says which languages are in effect.
- With the switch on and the local model not yet downloaded, paid accounts
  are translated through Talk DAT! Cloud instead of being shown an
  installation message mid-dictation. Free accounts keep the honest local
  message, which names the one-click download.
- Every bindable action now has a visible row in the Hotkeys tab.

### It learns from your corrections

- Fix a word by hand, copy it, and Talk DAT! remembers it -- a small
  "Added" note appears above the pill; hover and choose Don't save to strike
  it through and forget it. Only unusual spellings qualify, and only words
  that were not in what Talk DAT! delivered.

### The clay collection

- The website now wears the same roman-clay finishes as the app -- six
  lime-wash walls with a picker in the corner -- and when you sign in, the
  site quietly matches the theme you chose in the app.
- The scratchpad became ruled clay paper, and onboarding gained a page of
  six drawn vignettes so nothing ships undiscovered.

## 0.4.38-beta

### The app knows its own name -- and yours

- Every install now writes the product's name correctly from the first
  dictation: say it, and "Talk DAT!" arrives spelled and capitalized, with
  "Knight AI+AV" alongside. Context-aware, so "let's talk that over" stays
  exactly what you said. Your own dictionary always wins.
- The brand is Talk DAT! -- DAT capitalized -- everywhere you read it.

### Statements stop turning into questions

- A rising voice at the end of "...so add that to the list" no longer ships a
  question mark. Arriving punctuation is re-judged by the sentence's own
  grammar; short true questions like "It works?" keep their mark.

## 0.4.37-beta

### Set shortcuts by pressing them

- The Hotkeys tab no longer asks you to type key names as text. Click a
  shortcut, press the keys you actually want -- every key held counts, in any
  order -- and let go. What you pressed is what is saved.
- Esc cancels a capture, Backspace clears the shortcut, and right-clicking the
  field offers the mouse thumb buttons and middle click, so a gaming mouse can
  drive push-to-talk without typing anything.
- Keys the app cannot hold (numpad, media keys, Caps Lock) are ignored during
  capture instead of being recorded as shortcuts that could never fire.

### Start-over dialog polish

- The category list scrolls under the mouse wheel, rows stretch to the full
  width, the ERASE confirmation field takes focus by itself, and both windows
  keep a sensible minimum size.

## 0.4.36-beta

### Start over, exactly as far as you meant to

- Settings now has **Start over...** -- a reset that erases only what you tick.
  Presets cover the common cases ("Settings only", "All my data, keep models
  and sign-in", everything), and every category states its consequence and its
  real size on disk before you decide.
- The confirmation shows the exact list of what will be removed, from the same
  code that removes it. Erasing anything irreplaceable -- your dictionary,
  history, models or sign-in -- requires typing ERASE; a settings-only reset
  does not, because friction should match what is at stake.
- Downloaded models and your sign-in are never pre-selected. "Clear my
  settings" should not mean an hour of re-downloading or re-activating a PC.

### Shortcut clashes are named when you create them

- Binding two actions to the same keys used to fail silently: the first match
  won and the other action simply never fired, with nothing to say why. Saving
  settings now tells you immediately -- naming both actions and the exact keys
  -- so the one shortcut that "does not work" stops being a mystery.
- Key order does not hide a clash: ctrl+alt+1 and alt+ctrl+1 are the same keys.

### Smaller things

- Every action in the Hotkeys tab is verified to actually do something, by a
  test, so a configurable key can never point at nothing.
- The build now fails loudly if it would ship without the licence-verification
  library, instead of producing an app that cannot start.

## 0.4.35-beta

### It learns your words

- Right-click the pill and choose **Add words & phrases**. Type a name, a brand
  or a spelling, press Enter, and Talk DAT! writes it your way from then on.
- The matching works by **sound, not spelling**, which is the only thing that
  helps with the names that actually go wrong. A name written "Mayowa" is often
  heard as "my yo wa" -- three ordinary words sharing almost no letters with it.
  Talk DAT! compares what the words sound like, so it recognises the mistake and
  corrects it without you having to guess what the recogniser will produce.
- There is an optional "sounds like" box for the cases you already know about.
  Most people will never need it.
- Your saved words are also sent to the cloud recogniser as hints, so many
  mistakes stop happening in the first place rather than being repaired after.

### Lists form properly on every provider

- Saying "number one ... number two ... number three" now produces a numbered
  list whichever speech provider you use. Some providers write those as digits
  and some as words, and only the words were being recognised as list markers --
  so on the cloud path no list was ever produced.
- A list that starts mid-sentence is recognised too. Speech does not pause to
  add a comma before it starts counting.

### Text stops rewriting itself

- Talk DAT! used to paste an instant version and then visibly replace it once
  the writing model answered. That was worth watching when the model took about
  a second; on a fast connection it was hiding a wait that no longer existed.
- It now measures how long your setup actually takes and only does that when
  there is a real wait to hide. On a quick pipeline the finished text simply
  arrives once.

### Smaller things

- The version shown in the file properties is now generated from the release
  version, so it can no longer disagree with the build you are running.
- On the website, a signed-out visitor is no longer shown "Sign out" or
  "Resend verification email".

## 0.4.34-beta

### Failover that goes both ways

- When your cloud connection has a bad stretch -- more than two rescued
  dictations in ten minutes -- Talk DAT! now switches the session to your
  local model and tells you so, instead of paying the failed round trip on
  every attempt. And when the connection is healthy again, it switches back
  to your cloud choice by itself and says that too. Your settings are never
  rewritten; a restart always returns to what you picked.

### Your numbers

- Every dictation now reports its word count (a number only -- never your
  words) so your account page can show real lifetime stats: words dictated,
  minutes saved versus typing, days with us, PCs activated.

## 0.4.33-beta

### It writes data the way you would

- Say a schedule, a roster, an order -- and get one back. "Group one, twelve
  fifteen p.m. Three people. Group two, twelve thirty p.m. Two people." now
  renders as labeled blocks:

  Group 1:
  12:15 P.M. (3 People)

  Group 2:
  12:30 P.M. (2 People)

- Spoken times become clock times everywhere: "six forty five p m" is
  6:45 P.M. Anchored on the a.m./p.m you said, so "twelve fifteen" in
  ordinary speech stays words.
- The AI formatter learned the same standard, and the full inverse-text
  rules with it: decimals, prices, addresses and emails spoken aloud come
  out written, not spelled.

## 0.4.32-beta

### Crisp on every display

- Talk DAT! now renders at your monitor's real resolution. On any display
  scaled past 100% -- most laptops -- every window used to be drawn small and
  stretched by Windows, which read as blurry, low-resolution UI. Text, the
  Pill, and every panel are now native-sharp, and their sizes match what the
  display's scale intends.
- The setup experience was redesigned around it: larger, calmer type, cleaner
  cards, and nothing smaller than 9pt anywhere.

### Never lose what you said

- If your connection drops -- or a cloud provider fails for any reason --
  Talk DAT! now transcribes that dictation on this PC instead of failing. The
  fallback model downloads in the background on every install, so it is
  always there. No setting to find; it is simply how the app behaves now.
  (You can switch it off under stt.local_fallback if you want failures loud.)

### Right-click the Pill

- Setup now teaches the one gesture that opens everything: right-click the
  Pill for History, Scratchpad, Translate, Settings, and your account --
  any time.
- The menu also gained **Restart Talk DAT!** and **Close Talk DAT!** at the
  top, so turning the app off no longer requires finding the tray icon.

### Buying without an account

- The licence can now be bought with no account at all: pay once, and a
  forever code arrives on your Stripe receipt. In the app: Account &
  License > "I have a code". One PC per licence -- reinstalls on the same PC
  are always free.

### Honest plumbing

- When the AI formatter cannot be reached, the app logs why before using the
  built-in rules -- a silent fallback made an exhausted API key look like the
  formatter had quietly become worse.

## 0.4.31-beta

### Local Forever is $29, once

- The one-time licence was $149.99 -- ten months of the subscription up front
  for the part that costs nothing to serve, since the model runs on your own
  machine. It is **$29 once now, $19 for the first 250**, and it is the whole
  point of the product: every on-device model, unlimited, offline, no
  subscription, ever.
- Managed cloud stays $8.99 a month, which is 40% under Wispr Flow's $15, and
  the free tier stays 2,000 words a week, which matches theirs exactly. Neither
  of their plans works offline at all.
- Onboarding was still advertising a "Pro Annual $69.99" plan that no longer
  exists and whose price had already been switched off. Gone.

### Bring your own local model

- **Settings > Local Models > Add your own.** Paste a Hugging Face model id or
  point at a folder on your PC, and it appears in the list alongside the built-in
  ones. Anything in CTranslate2 Whisper format works, which is most of what
  people publish -- language specialists, domain fine-tunes, distilled variants.
- A model in some other architecture cannot load that way, so those go to
  build@knightaiav.com and ship as built-ins instead.
- What you paste is checked before it is saved, so a typo is caught in Settings
  rather than the first time you hold the key down.

## 0.4.30-beta

### Spacing

- **Sentences were each getting their own line.** "Hey Sarah, quick update. The
  build is green. I will deploy tomorrow morning." arrived as three stacked
  lines. One thought, three sentences, rendered as a ragged column -- it read as
  a transcript with line breaks rather than as something a person wrote, and it
  happened on every dictation longer than one sentence. They now sit in a
  paragraph, which is where sentences go. A dictated "new paragraph" still
  breaks; list items still keep their own lines.
- **A closing thought no longer hides inside the last list item.** "Number three
  save it, after that you can close everything and go home" came out with the
  remark buried in step three. It now sits after the list, with a blank line, so
  it reads as a new thought rather than a fourth step.
- **A trailing question is no longer swallowed as an item.** "Apples, trees,
  bicycles, guns. Let me know which one you want" put the question in the list,
  where it looked like a fifth thing to choose between.
- **A list is separated from the prose that follows it** by one blank line --
  and never more than one, and never between items of the same list.

### Dates read like dates

- Weekdays are now capitalised -- "we ship on friday" was otherwise correct and
  still obviously dictated. Months are capitalised only where the sentence is
  clearly talking about a date, because "you may want to check that", "we will
  march to the office" and "it is an august decision" are not dates. Anything in
  backticks is left exactly as spoken.

## 0.4.29-beta

### Lists, properly

- **The line before a list now ends with a colon.** Reported from live use:
  "Okay, here's a bullet list." then four items, and the full stop stayed a full
  stop. It used to be applied only where one narrow pattern matched, built
  around phrasings almost nobody says. Any line immediately followed by a list
  item is that list's introduction, whatever words it used -- and a question
  keeps its question mark, because "Ready?" followed by steps is still a
  question.
- **Asking for a bullet list gets bullets.** Saying "here's a bullet list" and
  receiving "1. 2. 3." is ignoring an instruction given in as many words.
  "Numbered list" gets numbers the same way.
- **A list you asked for out loud now gets built.** "Okay, here's a bullet
  list. Apples, trees, bicycles, guns." came back as two sentences of prose --
  the strongest possible signal, a spoken instruction, was the one case the
  rules ignored. It works now, with the marker taken from the words used and a
  bare "list" giving bullets.
- Sub-items, parallel grammar, consistent item punctuation, capitalised items
  and term-and-explanation entries are all now spelled out for the AI formatter,
  which handles the phrasings no rule can enumerate.

**None of this makes it list-happy.** An enumeration inside a sentence stays a
sentence -- "I need to buy milk, eggs and bread on the way home" is prose and
stays prose. So does the word "list" used in passing, and so does a long thought
after a list command. A missed list is a small disappointment; a paragraph
chopped into bullets is what makes somebody turn the formatter off.

### A window could freeze the whole app

- The rounded corners were applied by reshaping up to three windows at once,
  including one this app does not own, and each reshape forces Windows to
  repaint synchronously. Against a window belonging to another program that can
  block forever -- caught when the test suite stopped dead opening nine windows
  and had to be traced thread by thread to find it. It now reshapes only what
  it owns and repaints once.

## 0.4.28-beta

### The single biggest reason it felt slow

- Only one speech provider transcribes **while you speak**. Every other one
  waits until you stop, then uploads and waits for a round trip. Measured here
  on the same five seconds of speech: Deepgram 119-413 ms, OpenRouter 1,371 ms.
  That one choice was worth well over a second on every dictation and the app
  never mentioned it.
- Worse, it said the opposite. Eleven providers were flagged as "streaming" in
  Settings and exactly one of them streams here -- the flag described what the
  vendor sells, not what Talk DAT! does with it. Picking AssemblyAI or Soniox on
  the strength of it bought a full round trip. Every provider now states plainly
  when text will arrive, and the claim is derived from the code that runs so it
  cannot drift again.
- The first-run choice now says what each route costs. Private on-device is
  still the recommendation -- free, no account, nothing leaves the machine --
  but you can now find out that a four-times quicker option exists instead of
  discovering it by feeling that the product is slow.

### The first dictation after opening the app

- It was always the slow one, and nothing was preparing for it: the model
  download was fetched ahead of time but the model was not *loaded* until the
  moment you first spoke. Measured: **6.4 seconds, now 0.6** -- the six seconds
  moved to a background thread at startup where nobody is waiting.

### Managed cloud was on the slowest route it had

- Talk DAT! Cloud is the paid tier and it ran through the batch provider. It now
  prefers a direct one, which is both roughly ten times quicker and cheaper per
  hour of audio, so nothing is traded away.

### The AI formatter can finish setting itself up

- Settings could tell you the formatter model was missing and then offer
  nothing to do about it. The fix was a terminal command nobody was given, for
  a 1.4 GB download. There is now a button, with progress, and it appears only
  in the one state where it can work.

## 0.4.27-beta

### The correction is now instant where that was proven safe

- Talk DAT! shows your words the moment you stop speaking and replaces them
  with the polished version a moment later. Until now that replacement retyped
  the difference character by character, which is fine for a sentence and was
  reported from real use as unwatchable for a paragraph.
- There is a way to make it constant time -- undo the paste and paste the
  correction over it, two chords, 197 ms whether the text is 100 characters or
  900 -- and it shipped switched off, because an application that ignores undo
  would leave the text twice over and that cannot be detected from our side.
- Off everywhere was the wrong answer to "we only measured two of them". It is
  now on automatically in the applications where the undo behaviour was
  actually measured -- Notepad and Chromium browsers -- and unchanged
  everywhere else. Settings > Timing + Safety > **Instant correction** has
  Automatic, Always and Never.
- Chromium browsers are recognised by asking the program, not by listing names.
  A hand-written list held the browsers you would think of and missed Comet,
  Perplexity's fork, which happens to be the browser this release was built on
  -- so the feature would have stayed off in the one place its author uses
  every day, silently. Arc, Zen and anything shipping next now work without
  waiting for an update. Chat apps built on the same engine are still excluded,
  because each wraps it in its own editor.
- Existing installations get this too. The old setting is on disk as `false`
  and is upgraded on next launch, because until this release it had no toggle
  and so nobody had chosen it.

### The instant path is used only where it earns its risk

- Undo has one failure mode: an app that groups undo differently from a paste
  leaves the text twice over, and nothing on this side can tell. Corrections
  short enough to retype -- almost all of them, since most dictation is one
  sentence -- still retype, because undo would save about a tenth of a second
  there and that is not worth it. The instant path is now used only where the
  alternative is no correction at all, which is the case that prompted it.

### A slow delete could still have come back

- If the instant replacement failed, the fallback retyped the difference with
  the length limit waived -- the one path where a long dictation could still
  have spent seconds erasing itself, reachable only after a failure nobody
  would think to test. The limit now applies to the fallback, and a correction
  too long to type is skipped rather than watched.

## 0.4.26-beta

### The first run tells you what it is doing

- A 640 MB model download showed only the word "Downloading". On a slow
  connection that is indistinguishable from a frozen app. It now reads
  "205 of 640 MB (32%)", in both the pill and the settings panel -- the message
  existed twice and only one copy had been fixed.
- A failed download said so and stopped. It now says the retry resumes from
  where it stopped, which is true and was going unsaid, so a dropped connection
  no longer looks like starting 640 MB again.

### The AI formatter says when it cannot run

- Choosing the local formatter without Ollama installed produced rule-formatted
  text forever with nothing said. Because the rules are good, that reads as
  "this is how well it writes" rather than as a broken setting. Settings now
  shows whether the engine is installed, running, and has the model -- and what
  to do about each.

### Lifetime owners with the cloud add-on

- Anyone paying $4.99 a month for managed cloud on a Lifetime licence was shown
  the managed route greyed out during setup. The licence has always carried the
  answer; nothing read it.

### Failures that used to be silent

- Text delivery, transcript history and clearing history now report what went
  wrong. Losing dictated text used to leave no trace at all, and a failed
  history wipe let someone believe their transcripts were deleted.

## 0.4.25-beta

### Your paragraph no longer deletes itself

- Correcting a long dictation could take 3.9 seconds of visibly deleting one
  character at a time. Long dictation now waits for the model and arrives
  finished, with no edit at all; short dictation still appears immediately and
  its correction is 120-241ms, which reads as a flicker.
- Batching the keystrokes was tried and does not work: one Win32 SendInput call
  carrying the whole edit measured slower than one call per key, because
  Windows throttles synthetic input per event.
- There is now an optional instant correction that undoes the paste instead of
  backspacing it -- 156ms whatever the length, verified in Notepad and in a
  browser. Off by default until it has been tried in more applications, because
  one without undo would paste the correction after the original.

### The app no longer stops after 14 days

- When the trial ends you keep 2,000 words a week, permanently, on on-device
  models. A plan removes the weekly limit and adds managed cloud.

### Managed cloud actually works

- Managed speech and writing were advertised while every request returned an
  error. Both now run, and the service reports what it can really serve rather
  than whether a flag is set.

### Reading the interface

- Secondary text failed the accessibility contrast standard in 40% of theme and
  surface combinations, down to 3.10:1. Every one of the fifty themes now
  passes on every surface.
- Keyboard focus was invisible: no control showed which one Enter would
  operate. Buttons, entries and checkboxes now show it.
- The pill's context menu was drawing in a Windows 11 font that does not exist
  on Windows 10, so it rendered in a substitute nobody chose.
- The local model list ran 1,526 pixels past the bottom of its window with no
  scrollbar and no resize border. It scrolls.
- Settings hid its last four controls, "Update channel" among them, below the
  window edge.
- Spacing used thirteen different values chosen one widget at a time; it is now
  one four-pixel scale.

## 0.4.24-beta

### Typing is faster everywhere, not just in corrections

- The keystroke pause was also being paid in the ordinary typing path, which is
  what every dictation uses in an application that blocks paste. A six line
  paragraph spent 300ms doing nothing before a character appeared; now 29ms.

## 0.4.23-beta

### The cleanup no longer deletes your paragraph in front of you

- Correcting a dictated paragraph meant watching it erase itself one character
  at a time for about thirty seconds. The keyboard library pauses a tenth of a
  second between every keystroke, and backspace was being pressed in a loop.
  The same paragraph now takes half a second.

### You can actually sign in from the app

- Account and License was a read-only card with a button that explained nothing
  and reported nothing back. It now says whether you are signed in and as whom,
  shows the pairing code while your browser is open, updates itself when you
  finish, and has a Sign out.
- It also still advertised an annual plan that no longer exists.

### Speech that corrects itself, again

- "Call mom, I mean call dad" was having the "I mean" stripped as filler before
  anything intelligent saw it, so the model had to guess which name you wanted.
  It guessed wrong often enough to matter. The marker is kept now.
- Hesitation pauses no longer split one thought into two fragments.

## 0.4.22-beta

### Pauses stop breaking sentences

- Speech-to-text marks hesitation with an ellipsis, and those were being read as
  full stops. "I think the cost should be... 24.99" came out as two fragments,
  "The cost should be." and "24.99." A pause now joins the thought back up.
- Found by running 380 real transcripts through the formatter. That same run
  showed no crashes, no empty output, and no lost numbers, URLs or file paths
  anywhere in the set.

## 0.4.21-beta

### Short self-corrections are repaired too

- The repair fix in 0.4.20 still rejected short sentences. Where the retracted
  word is the only negation present, losing it counted as losing everything and
  the safety cap refused the correction. One such loss is now always allowed.

## 0.4.20-beta

### Self-correction now actually reaches the screen

- The repair rules shipped in 0.4.18 were being discarded after the model
  returned them. The safety check that stops the model dropping words demanded
  an exact match on negations, and repairing "how is OpenRouter, not
  OpenRouter, how is Wispr Flow" into "how is Wispr Flow" necessarily drops a
  "not". Every sentence the feature applied to was rejected and replaced with
  the unrepaired version, which is why it looked like nothing was happening.
- Removals are now allowed where speech repairs itself, and capped, so a
  retraction can lose its "not" but "don't send it" cannot lose its "don't".

## 0.4.19-beta

### The free trial now actually counts down

- The trial start was never recorded, so every launch read as a fresh install
  and granted another fourteen days. The paywall was switched on and could not
  have expired for anyone. The start is stamped once now, and reinstalling over
  an existing profile keeps the original clock instead of restarting it.

## 0.4.18-beta

### The loading rainbow looks like metal

- The spectrum is deeper and the highlight is a narrow specular streak rather
  than a broad wash, so the Pill reads as a lit metal object instead of a
  backlit sticker. The highlight keeps the colour underneath it -- warm through
  the reds, cool through the blues -- instead of clipping to a chrome stripe.

### Text appears immediately

- Dictation used to wait for the cloud rewrite before anything appeared -- about
  950ms of a 2 second wait. The locally formatted text is now pasted straight
  away, measured at 35ms, and the rewrite corrects it in place a moment later.
- The correction refuses itself unless it is provably safe: same window, nothing
  typed since, no new recording, Enter not sent, under six seconds old. When it
  refuses you simply keep the local formatting, which is what the app delivered
  before this existed.
- The update window now opens directly above the Pill instead of on a second
  screen, since it is answering something you did on the Pill.

## 0.4.17-beta

### Faster

- The microphone no longer stays open for a fixed 520ms after you release the
  key. It waits only while you are still talking and returns after about 140ms
  of quiet, so a finished sentence stops costing the worst case. That wait was
  a quarter of the total time between releasing the key and seeing text.
- Cloud formatting now asks OpenRouter for whichever host answers soonest
  rather than whichever is cheapest. Measured at 172ms off every dictation.

### Locked down

- Talk DAT! Cloud requires a signed-in account. Local models and your own API
  key stay free and unlimited, as promised.
- The paywall is enforced rather than observed.

### Design

- The Roman clay texture now appears on every window instead of only the
  right-click menu. It was rebuilt earlier and wired to one surface by mistake.

## 0.4.16-beta

### Dictation that corrects itself now comes out corrected

- Saying the wrong thing and fixing it mid-sentence reached the screen with
  both versions in it. "How is OpenRouter doing this, how is, not OpenRouter,
  how is Wispr Flow doing this" now becomes "How is Wispr Flow doing this".
  The formatter could always do this; it was never being asked. Anything short
  that ended in a question mark skipped the model entirely, and that is exactly
  the text that most needed it.
- "Call mom, I mean call dad" is now "Call dad".
- Clean speech still skips the round trip, so short tidy dictation stays fast.
  The wait is now spent only where it buys something.

### Your words stay yours

- Swearing is never censored, softened or asterisked. If you curse, it types
  the curse.
- An intensifier repeated four times in one sentence is a verbal tic, not
  emphasis, so the first is kept and the rest go. Used once it is left alone.
- Text now reads as though you had written it to a colleague: your words, your
  bluntness, your point, without the restarts and detours.

### Formatting no longer mangles ordinary sentences

- "I need three things done today the tests the docs and the deploy" was being
  turned into a bullet list whose first item was "Done today the tests the
  docs". A sentence containing "and" is not a list.
- Sentences no longer end on a dangling "and."

### Windows

- Pop-ups open on a second screen when you have one, instead of landing on top
  of whatever you are dictating into.
- Every pop-up can be moved and closed. Two of them previously could not be.

## 0.4.15-beta

### The update window has an Install button again

- The window offered an update and gave you no way to take it. Tk hands the
  whole remaining space to the first widget packed with expand=True, and the
  release notes were packed that way before the button row, so the buttons were
  allotted nothing and were never drawn. No error, no warning -- they simply
  were not there. The row is anchored to the bottom now and the notes expand
  into what is left.
- Install downloads the new build, verifies its checksum and release receipt,
  closes Talk DAT!, replaces it, and reopens it.

### Release notes read like release notes

- GitHub Markdown was being put straight into a plain text box, so the window
  showed "### Pricing" and "- item" to whoever was deciding whether to install.

## 0.4.14-beta

### The clay actually looks like clay

- The texture was three sine waves painted into a small tile and then stretched
  across the panel. A three-times upscale is a blur, so only the broadest wave
  survived and the surface read as a faint uneven gradient. It has real trowel
  strokes, tonal drift and mineral speckle now, and the tile is repeated at 1:1
  instead of stretched, so the detail reaches the screen.

### Formatting knows the rules it was guessing at

- The formatter is driven entirely by its instructions, so anything unwritten
  was decided afresh on every dictation. It now specifies homophones the
  recognizer cannot hear, questions that arrive flat because speech loses
  intonation, capitalization and real product spellings, the serial comma,
  colons against semicolons, punctuation inside quotation marks, apostrophes,
  the three dashes, hyphenated compound modifiers, numerals against words,
  dates, money, units, and parallel grammar in lists.
- Your register is left alone. Profanity, slang and bluntness stay as spoken.

### Update reminders stop interrupting you

- A background check that found an update opened its window immediately, on a
  timer that could not see whether the microphone was live. It could take focus
  mid-sentence and eat the words being spoken. Reminders now only appear at
  seams: launch, a settled pause after a dictation, returning to an idle
  machine, or on the way out. Nothing is ever shown while you are speaking.
- Ignored updates ask more often as they age, and a security fix does not wait
  three days. Skipping a version is permanent; snoozing backs off but returns.

### Pricing

- Annual is withdrawn. Lifetime covers the app and local models, and Lifetime
  owners can add managed cloud for $4.99 a month.

## 0.4.13-beta

### The themes are visible now, and so is the clay

- The lime-wash texture never rendered. It was written as the fallback for a
  missing material asset and the asset is always present, so panels stayed flat
  and the change was invisible. Clay is the surface now, with the photographic
  material over it, blended so a panel varies like lime wash and carries the
  theme's own pigment without competing with the text.
- The theme picker was a plain dropdown: fifty identical lines of text, with no
  sign the list scrolled. **Every row is now painted in the theme it names**, and
  the field says how many there are.
- The pill menu is ordered by how often things are reached rather than by the
  order they were built. Check for updates is no longer last.

### Sign-in actually works on the live site

- `talkdat.knightaiav.com` was missing from Firebase's authorized domains while
  every sibling site was present, so the browser SDK rejected **every** sign-in
  attempt, Google and email alike. Added.
- Continue with Google now leads the account panel instead of sitting below the
  email fields under a divider reading "or use an email and password".

## 0.4.12-beta

### Dictation formatting that is actually correct

- Rewrote the formatting contract with explicit if-then rules for speech repair,
  structure and emphasis: stutters and false starts deleted, misheard jargon
  repaired from context, prose as the default, numbered lists only on an
  announced count, bullets only on an explicit spoken command, and bold,
  italics, quotes, parentheses, brackets and backticks only when actually
  spoken. When uncertain it takes the plainer option, because a wrong guess
  reads worse than a plain sentence.
- The prompt was not the whole problem. The shipped formatter was a 1.7B local
  model that ignored rules the old prompt already contained: it bulleted every
  sentence of a continuous thought and left "I- I don't you- I don't want"
  verbatim. Measured on real dictation, Claude Haiku 4.5 was the only model that
  both removed the stutters and applied the emphasis that was spoken, so
  OpenRouter is now a formatter provider and that is its default.
- One key covers both halves of the pipeline: the same OpenRouter key that
  serves transcription serves the cleanup pass.

## 0.4.11-beta

### Those unexplained lines across the settings text

- Utility windows were drawn at `-alpha 0.965`. Tk applies alpha to the whole
  window, so 3.5% of whatever sat behind composited straight through the panel,
  and over a bright shape on a dark theme that is plainly visible -- it read as
  coloured curves drawn across the text. Panels are opaque now.
- The tactile quality moves to pigment instead: a lime-wash / Roman clay field
  in the theme's own panel colour, painted at tile resolution and smoothed up so
  it reads as plaster rather than grain, and never competes with the words on it.

### The processing rainbow is machined, not pasted on

- It took the Pill's alpha and nothing else, so it had the Pill's outline with
  flat colour inside. It now carries the Pill's luminance across as highlight
  and shadow, so it reads as the same piece of metal lit the same way. Blended
  soft-light rather than multiplied, because multiply only darkens and would
  dull the spectrum instead of giving it sheen.

### Ten new themes, and an order that makes sense

- Roman Clay, Venetian Plaster, Lime Wash, Sandstone, Slate Quarry, Deep Forest,
  Oxide Copper, Desert Bloom, Midnight Ink and Obsidian Gold. Fifty palettes.
- Families are grouped by material and temperature rather than by the order they
  happened to be added.

### Know what you are choosing

- Every speech model now shows measured accuracy and speed as a five-point bar
  wherever it appears. Derived from Artificial Analysis, so a model cannot be
  presented as better than it measures; an unmeasured model shows nothing.
- Stats gains usage and estimated monthly spend, with a model that has no
  published rate shown as a dash rather than as free.

### Accounts

- Google sign-in on the website, with linking, so one person keeps one account
  and one entitlement whichever route they use.
- A signed-in account detail panel: email, verification, sign-in methods, plan,
  status, renewal, activations and cloud entitlement.

## 0.4.10-beta

### Settings opened blank and could not be closed

- `tkinter.font.Font` takes `root`, not `master`. The wrong keyword fell through
  into Tcl as the font option `-master` and raised, which killed settings-window
  construction after `overrideredirect(True)` had already removed the OS
  titlebar and before the window's own close button existed. Every route into
  Settings -- the gear, Offline speech, Provider setup, the tray -- produced a
  blank panel with no way to close it.
- Tk routes callback exceptions to stderr and a windowed build has no stderr, so
  this failed in complete silence. Tk callback exceptions are now logged.
- Adds a test that opens all twelve windows and fails if any raises.

### Trailing capture already existed

- An earlier attempt at "capture the last word" added a second delay before the
  stop event. It was redundant: the capture loop already keeps the audio stream
  open and sleeps `dictation.tail_capture_ms` (520ms, adjustable in Settings)
  after stopping, so trailing audio was being recorded all along. The duplicate
  stacked on top of it and gave two settings for one behaviour, and has been
  removed. If the last word is still clipped, raise that existing value.

## 0.4.9-beta

### Check for updates now answers you

- Right-clicking the pill and choosing **Check for updates** reported "up to
  date" only by changing the pill's own state text. Someone using that menu is
  looking at the menu, not the pill, so the click looked like it did nothing.
  There was no toast machinery anywhere in the app; this adds one, held then
  faded, positioned above the pill and clamped on screen. Silent background
  checks stay silent.

### Cloud transcription through OpenRouter

- Adds OpenRouter as a speech-to-text provider: one key, thirteen models,
  switchable in the same picker as the local ones. Bring-your-own-key is still
  supported through `OPENROUTER_API_KEY`.
- Model ids are read from OpenRouter's models API rather than written from
  memory, and pinned in tests, the slugs carry date suffixes and parameter
  counts that cannot be reconstructed by guessing.
- Model choices are ranked on Artificial Analysis measurements. Notably Deepgram
  Nova-3, widely described as the accuracy leader, measures worse than the free
  local default and is offered for speed only. Hosted copies of models that ship
  free locally are kept as a fallback for weak machines and can never be a
  recommended paid default.

### Fixes

- The wake word listener silently died when toggled off and straight back on:
  `stop()` only sets the stop event, and a `start()` arriving before the worker
  noticed was treated as "already running", so the outgoing worker exited and
  nothing replaced it.
- `BatchSTTSession` now holds its adapter table as data, and a test asserts every
  registered provider has a live adapter. A provider without one is fully
  selectable in settings and only fails on the first dictation.

## Unreleased

### Commerce service deployed to test mode

- Deploy the commerce service to Cloud Run in `knight-ai-av-site` and record the
  full deployment runbook in `docs/COMMERCE_OPERATIONS.md`: the APIs `--source`
  builds need, the build service account grants, the project-scoped org policy
  exception and its propagation delay, and the fact that `--set-secrets :latest`
  binds at revision creation so a new secret version needs a revision roll.
- Add `tests/test_commerce_endpoints.py`, which reads the real routes out of
  `server.mjs` and fails if the runbook drifts. The first deployment was pointed at
  `/v1/stripe/webhook`, which does not exist; the service answers 404 and Stripe
  reports delivery failures, so a wrong path looks like a Stripe fault.

### Stripe test-mode catalogue setup

- Add `scripts/setup_stripe_test.py` and a manual `Stripe test-mode setup` workflow that
  create the Pro and Lifetime products, the three prices, and the 250-redemption Founder
  coupon, then print the identifiers the commerce service needs. Re-running reports the
  same identifiers instead of creating duplicates.
- The script refuses to run against a live key, so it cannot touch real money. The key
  is read from a repository secret and never written to the repo, a log, or its output.

### Direct coverage for the deterministic dictation pipeline

- Cover `text_pipeline` directly rather than only through `process_dictation`: voice
  edit commands, dictionary and snippet expansion, PII and profanity redaction, URL
  protection, the cleanup levels, and the spoken-command routing. 57 new tests on the
  path every dictation takes.

### Pill maths and themes split out of the overlay monolith

- Move the pure Pill animation, envelope, and state maths into `knight_flow/pill_motion.py`
  and the 30 settings palettes into `knight_flow/themes.py`. `overlay.py` re-exports every
  name, so `from knight_flow.overlay import ...` keeps working unchanged.
- `overlay.py` drops from 9,014 to 8,316 lines, and roughly 700 lines of logic that
  previously could not even be imported without tkinter, PIL, and a display are now
  testable anywhere. 46 new tests cover them.
- `scripts/check_settings_themes.py` reads the palettes from the data module, so the
  theme gate no longer requires Windows and runs on every push.
- The animation maths was verified unchanged by the split: 285 old-versus-new
  comparisons across the extracted functions and constants, all identical.

### One published website, honest beta framing, and earlier quality gates

- Publish `talkdat.knightaiav.com` from CI instead of by hand, and verify after every
  deploy that the live page matches the committed `docs/index.html`. The customer
  address had drifted eight days behind the GitHub Pages copy and was serving a page
  with no pricing section at all.
- Retire the duplicated GitHub Pages website in favour of a redirect and a matching
  `404.html`, so there is one site to keep current and old links still resolve.
- State the free public beta plainly on the site and mark every price as planned, so
  the page no longer presents plans that its own disabled checkout cannot sell.
- Add a launch-list form that stores only a typed address, a timestamp, and its
  source, with create-only Firestore rules and a mail-draft fallback while the
  Firebase web key is unset.
- Require a token before the opt-in local control API will return dictated text, and
  reject requests that do not address the server as localhost, so a page the user
  visits cannot reach the loopback listener by pointing its own hostname at it.
- Compare local control API tokens with a constant-time check.
- Run the release quality gates on every push and pull request rather than only when
  a release tag is pushed.
- Close every SQLite connection the transcript history opens. `sqlite3`'s context
  manager commits but never closes, so the SQLite history backend leaked one open
  connection and file handle per dictation, and kept the database locked on Windows.
- Stop blanking the hotkey configuration out of diagnostics bundles. The redaction
  matched `key` as a substring, so `hotkeys` -- the most useful section in a support
  bundle -- was replaced with `[redacted]`. Credential fields are now matched by a
  broader marker list that also covers `password`, `secret`, and `credential`.
- Cover the previously untested local control API, per-app profiles, plugin loader,
  pack/backup/diagnostics, and transcript history modules: 92 new tests.

## 0.4.8-beta - 2026-08-02

### Account-first setup and high-DPI layout repair

- Add an Access step before the product walkthrough with explicit create-account
  and no-card trial, sign-in and restore, plan comparison, and private local/BYOK
  paths.
- Watch the signed desktop entitlement while browser activation is running and
  reflect connected, waiting, and unavailable states without blocking private
  local dictation.
- Persist only the selected access path in the local setup receipt; passwords,
  payment details, license secrets, audio, and transcript content never enter it.
- Repair clipped Welcome, provider, and writing cards at 150% Windows display
  scaling, and fit all seven pages inside the supported 1080x820 setup window.
- Restore the live microphone meter and reactive key rehearsal after inserting
  the new first step by removing fragile numeric page-index checks.

## 0.4.7-beta - 2026-08-02

### Guided first-run setup

- Replace the provider form with a six-step setup journey covering privacy,
  speech route, microphone selection, trigger rehearsal, writing style, and a
  real in-window dictation test.
- Add illustrated route cards for private on-device speech, ten wired BYOK
  providers, and account-gated Talk DAT! Cloud without pretending an inactive
  managed route is available.
- Add a private live microphone meter and reactive keycaps that light each key
  independently before confirming the configured trigger chord.
- Route the setup dictation into its own practice box so the first test cannot
  paste into an unrelated application, and retain normal protected-audio
  recovery throughout the test.
- Make the walkthrough available again from Settings, migrate earlier setup
  receipts once, and remove retained frame references from animated previews.

## 0.4.6-beta - 2026-08-02

### Model guidance that stays simple and honest

- Add a searchable in-app Model Guide for all 30 cloud and 30 local research
  entries, with cloud/local and ready/candidate filters, verified dates, concise
  notes, and direct official documentation links.
- Explain the four tested smart defaults in one place: Parakeet TDT 0.6B v3 for
  private speech, Deepgram Nova-3 for live BYOK, Scribe v2 for managed accuracy,
  and Qwen3 1.7B for fast meaning-safe local cleanup.
- Keep the Flow Console at four primary sections by opening model research as a
  focused secondary window instead of adding another navigation tab.
- Fix a shared Tk canvas/widget conflict that could crash resizable borderless
  utility windows when their resize handle was raised.

## 0.4.5-beta - 2026-08-02

### Current model catalog without false-ready choices

- Refresh the dated speech catalog to 30 cloud and 30 local models with direct
  official documentation links and explicit `wired` or `adapter pending`
  lifecycle labels.
- Remove retired or superseded ElevenLabs, Gemini, AssemblyAI, Deepgram, OpenAI,
  and Mistral generations from active model pickers while preserving custom
  model-ID entry for advanced compatibility needs.
- Fix AssemblyAI batch submission to use the current `speech_models` array
  request contract.
- Keep Parakeet TDT 0.6B v3 as the tested local speech default and Qwen3 1.7B as
  the tested local formatting default. Newer models remain candidates until
  their Windows runtime and meaning-preservation tests pass.

## 0.4.4-beta - 2026-08-02

### Optional managed quality without local lock-in

- Add a three-route onboarding choice: metered Talk DAT! Cloud for activated
  trial/Pro users, private on-device speech, or bring-your-own provider.
- Wire managed Scribe v2 batch transcription and Gemini 3.5 Flash-Lite
  formatting/translation behind a fail-closed service flag. Local and BYOK
  dictation continue working when the service is disabled or unavailable.
- Meter exact valid PCM duration and source-text characters with signed-license
  and active-device verification, retry-safe request identities, provider-error
  rollback, monthly/trial allowances, and no payload storage in Firestore.
- Preserve every managed speech hold in the local protected-audio history before
  upload, and retain the deterministic/local fallback whenever managed writing
  fails or violates meaning-safety guards.
- Define Pro as 600 managed speech minutes and 2,000,000 managed text characters
  per month; the trial includes 30 minutes and 100,000 characters. Lifetime
  remains permanent desktop/local/BYOK access and does not include recurring
  managed provider costs.

## 0.4.3-beta - 2026-08-02

### Pricing choice without payment lock-in

- Add a hybrid commercial model: 14-day no-card trial, $8.99 Pro Monthly,
  $69.99 Pro Annual, $149.99 Lifetime, and $79.99 Founder Lifetime for the
  first 250 completed purchases.
- Add Stripe subscription lifecycle handling and an authenticated Customer
  Portal route for cancellation, payment methods, receipts, and billing history.
- Preserve the lifetime option, local no-key speech, and bring-your-own-provider
  paths so a Talk DAT! subscription is never the only way to use the product.
- Automatically cancel an active Pro subscription when its owner completes a
  lifetime upgrade, preventing future double billing.
- Keep checkout fail-closed until Firebase identity, Stripe test/live flows,
  taxes, webhooks, signed entitlements, and rollback are proven end to end.

## 0.4.2-beta - 2026-08-02

### Commercial account foundation without compromising local dictation

- Add a fail-closed customer account surface for a no-card 14-day trial,
  one-time lifetime purchase, and desktop activation. Checkout stays visibly
  unavailable until production Firebase and Stripe configuration is verified.
- Add a scale-to-zero commerce service with verified Firebase identities,
  Stripe-hosted Checkout, a payment-provider-enforced 1,000-purchase Founder
  coupon, signed webhooks, purchase/refund/dispute handling, and replay-safe
  three-PC activation codes.
- Add Ed25519-signed device entitlements stored in Windows Credential Manager.
  Lifetime core dictation remains active when account metadata needs a refresh;
  commerce never receives audio, transcripts, dictionaries, provider keys, or
  local-model content.
- Add Account & License to the Pill menu and Settings, plus public privacy,
  terms, and refund pages. Keep beta license enforcement in audit mode until a
  live purchase/refund acceptance run is complete.

## 0.4.1-beta - 2026-08-02

### Private local translation and founder pricing

- Add an opt-in on-device translation workspace using user-downloaded
  TranslateGemma 4B, 12B, or 27B models through a local Ollama runtime.
- Add source and target language selection, swap, translation register,
  formatting preservation, exact glossary terms, safe copy/paste, and optional
  post-dictation auto-translation. A failed translation preserves and delivers
  the cleaned source transcript.
- Add Translation and Share an idea actions to the Pill menu and system tray,
  plus private language and product-idea email forms that attach no app data.
- Keep translation disabled by default and make every multi-gigabyte model
  download an explicit user action.
- Define the Founder Lifetime offer as $14.99 for the first 1,000 completed
  purchases and $49.99 afterward, with payment-provider counts required before
  any remaining-license claim is shown.
- Repair translation/request window layout so borderless glass surfaces use one
  stable geometry manager and labels no longer overlap their fields.

## 0.4.0-beta - 2026-08-01

### Knight AI+AV product transition

- Move current source development to the private `KNIGHT-AI-AV/talk-dat`
  repository and begin proprietary licensing for new releases.
- Preserve rights already granted to earlier copies while separating current
  private source from the customer binary channel.
- Route the in-app updater and official website to the binary-only
  `KNIGHT-AI-AV/talk-dat-releases` repository without embedding a GitHub token.
- Add a customer EULA and ship it with both installed and portable builds.
- Rework the official Talk DAT! site around the approved Talk Stone, Pill, and
  Roman-clay material while removing source-repository links and old Mayowa
  branding.
- Keep receipt, SHA256, transactional installer, local-data preservation, and
  updater smoke-test gates intact across the new distribution boundary.

## 0.3.39-beta - 2026-08-01

### Formatting that earns its bullets

- Stop ordinary prose from becoming a list merely because it mentions words
  such as `list`, `items`, `things`, or `features`.
- Require complete list items and reject dangling fragments such as `Add 50 if`
  or `You need to` from both the deterministic formatter and AI output.
- Treat dictated text as inert copy-editing input so local and cloud models do
  not follow a spoken request or leak unrelated examples into the result.
- Keep intentional spoken bullets, announced numbered sequences, conventional
  inline enumerations, and complete repeated requirements working.
- Retain the bounded local-model path: late, malformed, or meaning-changing AI
  output falls back to safe prose without blocking paste.

## 0.3.38-beta - 2026-07-31

### Sharper live voice refraction

- Replace the rounded microphone-volume swell with a narrow, faceted speech
  trace whose sharp signed peaks are still driven by untouched real mic energy.
- Refract and light the approved Pill material along the angular trace without
  adding a foreign waveform line, changing the silhouette, or recording at
  rest.

### One-click transcript recovery

- Put **Paste last transcript** first in the Pill's right-click menu, restore
  the previously active Windows field before insertion, and keep the exact
  transcript on the clipboard even when automatic paste is blocked.

### Welcoming public download and live preview

- Rebuild the public page around the Talk Stone, the Pill, one verified Windows
  download, honest platform status, and the trigger-only privacy contract.
- Replace the scripted test with real hold-to-talk and hands-free browser
  transcription, explicit stop handling, a live mic meter, copy, and clear.
- Add a tested optional Cloud Run token bridge for short-lived Deepgram Nova-3
  browser sessions. The static page falls back to the browser speech service;
  the project API key is never present in public HTML or JavaScript.

## 0.3.37-beta - 2026-07-31

### Voice-material visualizer

- Meter the untouched microphone signal separately from recognition gain so
  high-gain and whisper profiles retain real syllable dynamics in the Pill.
- Replace the subtle uniform refraction with a mirrored luminous volume made
  from the approved Pill material, including fast attack, natural release,
  dB-calibrated speech response, directional history, and optical depth.
- Preserve the exact transparent silhouette and Reduce Motion behavior while
  keeping the production active frame within its 60 Hz render budget.

## 0.3.36-beta - 2026-07-27

### Clearer live microphone response

- Increase the real-RMS refraction range and material lighting inside the active
  Pill so normal speech is visibly responsive without adding waveform bars,
  text, or a foreign overlay.
- Preserve the approved alpha silhouette, reject room noise, smooth recent
  levels left to right, and keep Reduce Motion behavior intact.

### First-run model choice

- Always show first-run onboarding, including for the no-key local default, with
  a clear choice between private on-device transcription and cloud BYOK.
- Keep Parakeet TDT 0.6B v3 as the public new-user default, offer ten working
  flagship cloud routes with official login, key, and documentation links, and
  protect cloud credentials with Windows Credential Manager.
- Add working dedicated adapters for xAI, Smallest.ai, and Soniox. Soniox
  temporary files and transcription jobs are removed after each request.

### Settings readability

- Measure the Flow Console rail from the actual Windows font metrics instead of
  fixed pixels, preventing labels and descriptions from clipping at scaled DPI.
- Let Settings and Setup resize, clamp utility windows to the current work area,
  and preserve the four-section settings architecture.

## 0.3.35-beta - 2026-07-27

### Protected voice sessions

- Write each accepted trigger hold to a unique local WAV while the microphone is
  live, before cloud/local transcription, formatting, clipboard, or insertion
  can fail.
- Keep at least the latest five holds with atomic session metadata, repair
  interrupted WAV headers after restart, and preserve Cancel, Panic Stop,
  Restart, provider-error, formatting-error, and paste-error outcomes.
- Add a Protected voice sessions panel to History with Play, Copy text, Recover
  text, Open folder, and explicit Clear recordings actions.
- Retry a failed saved session through the currently selected speech and
  formatting route without deleting its original audio.

## 0.3.34-beta - 2026-07-27

### Live microphone refraction

- Refract the Pill's existing ribbed material with the real microphone-energy
  envelope while a recording session is live, without placing waveform bars or
  text over the approved artwork.
- Smooth recent capture levels into a left-to-right response, reject room noise,
  preserve the exact pill silhouette and transparency, and reset the signal
  history for every activation.
- Keep loading and completion visually distinct, honor Reduce Motion, and stay
  within the active 60 Hz render budget.

## 0.3.33-beta - 2026-07-26

### Formatting safety

- Keep conjunctions attached to spoken transition cues when splitting long
  dictation, preventing output such as `and.` before `after that`.
- Add an end-to-end regression example covering installer, microphone recovery,
  and clipboard-safety phrasing.

## 0.3.32-beta - 2026-07-26

### Dictation delivery recovery

- Fix the live-draft crash that could occur after a successful transcription and
  prevent formatting and paste from running.
- Make crash-recovery draft writes strictly best-effort so a future local file
  error cannot block the primary dictation delivery path.
- Add regression coverage proving text still reaches insertion when the draft
  writer fails.

### Local models and settings

- Validate every local speech model against its packaged engine catalog. All 13
  Faster-Whisper aliases are supported, and each ONNX model is either a native
  `onnx-asr` alias or a self-describing Hugging Face repository.
- Keep Parakeet TDT 0.6B v3 as the single local speech default and packaged
  release-smoke model.
- Add four local formatting tiers: realtime Qwen3 1.7B, and optional Qwen3.5 2B,
  4B, and 9B quality tiers with progressively larger latency budgets.
- Replace duplicate local-formatting controls with one quality selector while
  keeping advanced model and endpoint fields available.
- Rename the context-menu model entry to **Offline speech** and route it into the
  same local-model manager used by Settings.

### Visual themes

- Add Night City Neon, Terminal Rain, Neon Sakura, Arctic Aurora, and Cobalt Heat
  theme families in complete dark and light variants.
- Expand automated theme validation to all 30 settings themes.

## 0.3.31-beta - 2026-07-26

### Microphone and session recovery

- Recover automatically when a remembered microphone moves to a new Windows
  device index, and avoid controller, loopback, or virtual defaults when a
  physical input is available.
- Detect PortAudio callback faults and microphone streams that stop during
  dictation. Mark the session degraded so Talk DAT! retries from the complete
  local capture instead of silently returning an empty or partial result.
- Replace the crash-recovery live draft atomically so an interrupted write cannot
  destroy the last usable draft.

### Safer writing and insertion

- Restore the previous clipboard only when it still contains the text inserted by
  Talk DAT!, preserving anything the user or target application copied after paste.
- Protect numbers, dates, versions, links, email addresses, quoted literals,
  negation, and modal intent from unintended AI cleanup changes. The original
  transcript is used whenever a formatter violates those guards.
- Expose the meaning-preservation guard beside smart formatting so advanced users
  can make an explicit local choice without weakening the safe default.

## 0.3.30-beta - 2026-07-25

### Activation and first-run reliability

- Treat a clean Deepgram keepalive shutdown as expected when the user releases a
  very short push-to-talk session, instead of showing a false transport failure.
- Disable terminal download progress output in the windowed app so a new user's
  Parakeet download cannot crash when PyInstaller correctly provides no console.
- Exercise a clean Talk Dat home, download the default Parakeet model, and require
  a non-empty transcript from the packaged Windows EXE before publishing a release.
- Ship the insertion fallback, content-free delivery receipts, updater provenance
  enforcement, and transactional installer repair work that landed after 0.3.28.

### Delivery receipts and repair safety

- Fall back in both directions between verified clipboard insertion and direct
  typing, and show the exact non-content delivery route in the Pill instead of
  claiming every result was pasted.
- Bind updater downloads to the public release receipt's repository, tag, exact
  source commit, size, and SHA256. When a receipt declares Artifact Signing,
  require a valid Windows Authenticode signature before launch.
- Record size and SHA256 receipts for every installed payload file, verify them
  before the staged transaction commits, and roll back if the repaired install
  does not match.
- Resolve the exact release-tag commit and API-published installer size/SHA256 on
  the static download page while linking the full receipt and retaining a clear
  legacy/failure state.

## 0.3.29-beta - 2026-07-25

Source-only release candidate. Its stronger first-run CI gate blocked publication
after detecting the headless model-download issue fixed in 0.3.30-beta.

## 0.3.28-beta - 2026-07-22

### Dictation recovery

- Detect interrupted Deepgram streams and retry the complete in-memory capture
  through the selected batch transcription lane, even when the live stream returned
  a partial transcript. Keep the longer live transcript if recovery is shorter.

### Accessibility and updates

- Make every overlay context-menu action reachable with Up, Down, Home, End,
  Enter, and Space.
- Compare prerelease tags semantically and select the highest published beta so a
  republished older GitHub release cannot cause an updater downgrade.
- Publish the same privacy-preserving static download surface on an isolated
  Firebase Hosting site while retaining GitHub Pages as the rollback host.

## 0.3.27-beta - 2026-07-20

### Reliability and trust

- Revalidate update installer size and SHA256 immediately before process launch,
  including installers downloaded automatically in the background.
- Publish `RELEASE-RECEIPT.json` with every release. It records the source commit,
  build environment, signing state, asset sizes, and SHA256 hashes.
- Verify the public receipt against the updater-downloaded installer in release CI.
- Refuse to publish assets when the requested release tag does not resolve to the
  exact source commit built by the workflow.

### Public download surface

- Resolve Windows beta assets from GitHub's release list instead of the stable-only
  `latest` route.
- Stop every browser microphone track when the demo is released, stopped, closed,
  or navigated away from.
- Add a visible checksum download, skip navigation, reduced-motion behavior, and
  clearer live status announcements.

### Accessibility

- Make the Flow Console's four primary sections keyboard operable with arrow,
  Home, End, Enter, and Space controls plus a stable focus indicator.

## 0.3.26-beta - 2026-07-17

- Rebalanced The Pill to `92x26` at rest and `192x35` while actively capturing.
- Preserved explicit custom geometry while migrating untouched prior defaults.

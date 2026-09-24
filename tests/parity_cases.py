"""Frozen 44-case September 18 audit corpus, promoted without changing targets.

Expected None means the model owns sentence boundaries, not an ignored defect.
"""
from __future__ import annotations

EM = chr(8212)

CASES: list[tuple[str, str, str | None]] = [
    # sentences and capitals
    ("capitals, terminal", "hey can you send me the file when you get a chance thanks",
     "Hey, can you send me the file when you get a chance? Thanks."),
    ("lone i", "i think i left it at home but i m not sure",
     "I think I left it at home but I'm not sure."),
    ("split contractions", "we re going to need that by friday and they ll want it in pdf",
     "We're going to need that by Friday and they'll want it in PDF."),
    ("fused contractions", "im pretty sure we dont need it and we cant ship without the key",
     "I'm pretty sure we don't need it and we can't ship without the key."),
    ("question", "what time does the meeting start tomorrow",
     "What time does the meeting start tomorrow?"),
    ("question then statement", "did you get my message i sent it an hour ago", None),
    ("two sentences no cue", "the build is green i pushed it ten minutes ago", None),
    # spoken punctuation
    ("comma period", "first we ship comma then we measure period then we decide",
     "First we ship, then we measure. Then we decide."),
    ("new line and paragraph", "thanks for the update new paragraph i will review it tonight new line best",
     "Thanks for the update.\n\nI will review it tonight.\nBest"),
    ("quotes", "he said quote we are not doing that end quote and walked out",
     'He said "we are not doing that" and walked out.'),
    ("exclamation", "that is amazing exclamation point", "That is amazing!"),
    ("colon semicolon", "two things colon the api is down semicolon the site is fine",
     "Two things: the API is down; the site is fine."),
    ("dash", "the fix is small dash one line dash but it needs a test",
     "The fix is small, one line, but it needs a test."),
    ("parens", "the price open paren nineteen dollars close paren is for the first two fifty",
     "The price ($19) is for the first 250."),
    ("literal word comma", "add a comma between the names", "Add a comma between the names."),
    # numbers, money, percent, time, dates
    ("cardinal", "we have twenty five customers and three hundred forty two signups",
     "We have 25 customers and 342 signups."),
    ("money", "the plan costs nineteen dollars and the pro one is forty nine ninety nine",
     "The plan costs $19 and the pro one is $49.99."),
    ("cents", "it came to five dollars and fifty cents", "It came to $5.50."),
    ("percent", "conversion is up ten percent since tuesday", "Conversion is up 10% since Tuesday."),
    ("decimal", "the model is zero point six billion parameters", "The model is 0.6 billion parameters."),
    ("phone", "call me at four one five five five five one two one two", "Call me at 415-555-1212."),
    ("year", "we launched in twenty twenty six", "We launched in 2026."),
    ("ordinal date", "the deadline is september eighteenth", "The deadline is September 18th."),
    ("time pm", "let's meet at three thirty pm", "Let's meet at 3:30 PM."),
    ("time half past", "the call is at half past two", "The call is at 2:30."),
    ("time noon", "lunch is at noon then the demo at four", "Lunch is at noon, then the demo at 4."),
    ("compound number", "she is twenty one years old", "She is 21 years old."),
    ("fraction", "about two thirds of users never open settings",
     "About two-thirds of users never open settings."),
    # names, acronyms, product words
    ("acronyms", "the api returns json and the ai model runs on the gpu",
     "The API returns JSON and the AI model runs on the GPU."),
    ("products", "it works on iphone and macos and the github repo is public",
     "It works on iPhone and macOS and the GitHub repo is public."),
    ("ok", "ok that works for me", "OK, that works for me."),
    ("titles", "mister smith and doctor jones are both on the call",
     "Mr. Smith and Dr. Jones are both on the call."),
    ("abbreviations", "use a local model e g parakeet i e no cloud etc",
     "Use a local model, e.g. Parakeet, i.e. no cloud, etc."),
    # address and url
    ("email", "send it to build at knight ai av dot com", "Send it to build@knightaiav.com."),
    ("url", "the docs are at talk dat dot app slash docs", "The docs are at talkdat.app/docs."),
    # disfluency
    ("fillers", "um so i think uh we should you know just ship it", "So I think we should just ship it."),
    ("immediate repeat", "the the build is is green", "The build is green."),
    ("restart", "we should we should probably wait", "We should probably wait."),
    # lists
    ("spoken list", "three things first the api second the site third the store",
     "Three things:\n1. The API\n2. The site\n3. The store"),
    ("number one list", "number one ship it number two measure it number three decide",
     "1. Ship it.\n2. Measure it.\n3. Decide."),
    # his rules
    ("em dash in", f"we ship tonight {EM} every platform {EM} the same night",
     "We ship tonight, every platform, the same night."),
    # identifiers
    ("snake case", "the function is called apply spoken punctuation",
     "The function is called apply spoken punctuation."),
    ("file path", "open knight flow slash formatting dot py", "Open knight_flow/formatting.py."),
    # mid-sentence continuation: no capital, no dropped conjunction
    ("continuation", "and then we", "and then we"),
]

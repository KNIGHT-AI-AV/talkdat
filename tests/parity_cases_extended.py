"""Wispr-parity corpus, 2026-09-22: the probe gaps and what surrounds them.

Written for this repository from scratch. Nothing here is copied from any
person's journal, history or dictation; the names and facts are invented.

Each case is (label, spoken, target, options). `target` is the written form a
careful human would produce -- the Wispr-class answer -- and `None` where
more than one layout is right and only the safety checks below apply.

options:
  gate      True when the RULES lane is expected to produce `target` exactly.
            Those rows fail the offline gate if they drift. Every other target
            is scored (exact and acceptable) but is the model's to reach.
  facts     regexes that must survive (numbers, names, addresses). A missing
            one is data loss.
  meaning   regexes that must survive (negations, hedges, the corrected
            value). A missing one is a meaning change.
  forbidden regexes that must NOT appear (an invented name, a wrong layout).
            One present is a meaning change.
  retracted the value the speaker took back. Still present means the
            correction was not applied: a quality miss counted separately
            ("unresolved"), not a meaning change, because the speaker did say
            it. It gates only rows marked gate=True.
  alt       other exact strings that are equally correct.
"""
from __future__ import annotations

COHORT = "wispr-parity-2026-09-22"


def X(label, spoken, target, **options):
    return (label, spoken, target, options)


CASES = [
    # --- Backtrack: a value corrected by a value --------------------------
    X("backtrack make it", "let's meet at five actually make it six", "Let's meet at 6.", gate=True,
      facts=(r"\b6\b|\bsix\b",), retracted=(r"\b5\b|\bfive\b", r"actually")),
    X("backtrack no wait day", "the meeting is on tuesday no wait wednesday", "The meeting is on Wednesday.",
      gate=True, meaning=(r"Wednesday",), retracted=(r"Tuesday", r"no wait")),
    X("backtrack count", "i have two no wait three kids", "I have three kids.", gate=True,
      meaning=(r"\bthree\b",), retracted=(r"\btwo\b",)),
    X("backtrack pm", "call me at four pm no wait five", "Call me at 5 PM.", gate=True,
      facts=(r"\b5 PM\b|\bfive\b",), retracted=(r"\b4\b|\bfour\b",)),
    X("backtrack money", "the ticket is ten dollars actually twelve dollars", "The ticket is $12.", gate=True,
      facts=(r"\$12\b|twelve",), meaning=(r"(?i)\bticket\b",), retracted=(r"\$10\b|\bten dollars",)),
    X("backtrack percent", "we grew ten percent sorry eleven percent", "We grew 11%.", gate=True,
      facts=(r"\b11%|eleven",), retracted=(r"\b10%|\bten percent",)),
    X("backtrack i mean day", "the demo is on friday i mean thursday", "The demo is on Thursday.", gate=True,
      meaning=(r"Thursday",), retracted=(r"Friday",)),
    X("backtrack or rather", "book it for monday or rather tuesday", "Book it for Tuesday.", gate=True,
      meaning=(r"Tuesday",), retracted=(r"Monday",)),
    X("backtrack let us say", "the standup is at nine no make it nine thirty", "The standup is at 9:30.",
      facts=(r"9:30|9 30|nine thirty",), retracted=(r"\b9\b(?![: ]\d)",)),
    X("backtrack scratch that", "send the draft to legal scratch that send it to finance",
      "Send it to finance.", gate=True, meaning=(r"finance",), retracted=(r"legal",)),
    X("backtrack not a correction", "at two actually three people came",
      "At two, actually three people came.", meaning=(r"three people came",),
      alt=("At 2, actually 3 people came.", "Actually, three people came at two.")),
    X("backtrack actually as adverb", "i actually liked the new design", "I actually liked the new design.",
      gate=True, meaning=(r"actually liked",)),
    X("backtrack noun phrase", "invite the sales team actually no invite the whole company",
      "Invite the whole company.", meaning=(r"(?:whole|entire) company",), retracted=(r"sales team",)),
    X("backtrack i mean noun", "can you ping marco i mean luca about the invoice",
      "Can you ping Luca about the invoice?", meaning=(r"(?i)luca",), retracted=(r"(?i)marco",)),
    X("backtrack sorry noun", "grab the blue folder sorry the green folder", "Grab the green folder.",
      meaning=(r"green folder",), retracted=(r"blue",)),
    X("backtrack wispr coffee words", "let's do coffee at two actually three", "Let's do coffee at 3.",
      gate=True, facts=(r"\b3\b|\bthree\b",), retracted=(r"\b2\b|\btwo\b",)),
    X("backtrack time range", "the call runs from two to three no wait two to four",
      "The call runs from two to four.", meaning=(r"two to four|2 to 4",), retracted=(r"to three|to 3",),
      alt=("The call runs from 2 to 4.",)),
    X("backtrack keeps negation", "don't send it today actually don't send it until monday",
      "Don't send it until Monday.", meaning=(r"(?i)don't send it until Monday",)),
    X("backtrack forget that", "add a slide on pricing forget that add a slide on hiring",
      "Add a slide on hiring.", meaning=(r"hiring",), retracted=(r"pricing",)),
    X("backtrack delete that", "the office is closed friday delete that the office is open friday",
      "The office is open Friday.", gate=True, meaning=(r"open (?:on )?Fridays?",), retracted=(r"closed",)),

    # --- Implicit and explicit lists ---------------------------------------
    X("count list groceries", "we need three things milk eggs and bread",
      "We need three things:\n1. Milk\n2. Eggs\n3. Bread", gate=True,
      meaning=(r"Milk", r"Eggs", r"Bread")),
    X("count list items", "pack four items tent stove water and a map",
      "Pack four items:\n1. Tent\n2. Stove\n3. Water\n4. A map", gate=True,
      meaning=(r"Tent", r"Stove", r"Water", r"map")),
    X("count list commas", "there are three steps, back up the database, run the migration, and restart the server",
      "There are three steps:\n1. Back up the database\n2. Run the migration\n3. Restart the server", gate=True,
      meaning=(r"database", r"migration", r"server")),
    X("count list articles", "bring two things the charger and the adapter",
      "Bring two things:\n1. The charger\n2. The adapter", gate=True, meaning=(r"charger", r"adapter")),
    X("count list mismatch stays prose", "i need three things done today the tests the docs and the deploy",
      None, meaning=(r"tests", r"docs", r"deploy")),
    X("count list clauses", "two things fix the login and ship the docs",
      "Two things:\n1. Fix the login\n2. Ship the docs", meaning=(r"(?i)fix the login", r"(?i)ship the docs")),
    X("ordinal list", "three steps first open the app second pick a mic third press start",
      "Three steps:\n1. Open the app\n2. Pick a mic\n3. Press start",
      meaning=(r"(?i)open the app", r"(?i)pick a mic", r"(?i)press start")),
    X("numbered commands", "number one book the room number two send the invite number three order lunch",
      "1. Book the room.\n2. Send the invite.\n3. Order lunch.", gate=True,
      meaning=(r"(?i)book the room", r"(?i)send the invite", r"(?i)order lunch")),
    X("bullet command", "bullet point apples bullet point pears bullet point plums",
      "- Apples\n- Pears\n- Plums", meaning=(r"(?i)apples", r"(?i)pears", r"(?i)plums")),
    X("options no count", "we can take the train the bus or a taxi",
      "We can take the train, the bus or a taxi.", meaning=(r"train", r"bus", r"taxi"),
      alt=("We can take the train, the bus, or a taxi.",)),
    X("list then prose", "three things first the budget second the hiring plan third the office move new paragraph let me know what you think",
      "Three things:\n1. The budget\n2. The hiring plan\n3. The office move\n\nLet me know what you think.",
      meaning=(r"budget", r"hiring plan", r"office move", r"(?i)let me know")),
    X("list with question", "can you check three things the logs the alerts and the backups",
      None, meaning=(r"logs", r"alerts", r"backups")),
    X("agenda list", "agenda for tomorrow first quick intros second roadmap review third open questions",
      "Agenda for tomorrow:\n1. Quick intros\n2. Roadmap review\n3. Open questions",
      meaning=(r"(?i)intros", r"(?i)roadmap review", r"(?i)open questions")),
    X("single and is not a list", "i talked to the landlord and the plumber",
      "I talked to the landlord and the plumber.", gate=True, meaning=(r"landlord and the plumber",)),
    X("four reasons", "four reasons speed cost privacy and control",
      "Four reasons:\n1. Speed\n2. Cost\n3. Privacy\n4. Control", gate=True,
      meaning=(r"Speed", r"Cost", r"Privacy", r"Control")),

    # --- Letters, greetings, sign-offs -------------------------------------
    X("email greeting signoff", "hey nora just checking in on the draft can you send it by friday best alex",
      "Hey Nora,\n\nJust checking in on the draft. Can you send it by Friday?\n\nBest,\nAlex",
      meaning=(r"Nora", r"Alex", r"(?i)checking in", r"Friday")),
    X("email team", "hi team the build is green and the release is tonight thanks alex",
      "Hi team,\n\nThe build is green and the release is tonight.\n\nThanks,\nAlex", gate=True,
      meaning=(r"build is green", r"tonight", r"Alex")),
    X("email dear regards", "dear jordan thank you for the notes i will send the revised draft tomorrow kind regards priya",
      "Dear Jordan,\n\nThank you for the notes. I will send the revised draft tomorrow.\n\nKind regards,\nPriya",
      meaning=(r"Jordan", r"Priya", r"revised draft", r"tomorrow")),
    X("email cheers", "hey sam the photos look great i will pick my favourites tonight cheers dana",
      "Hey Sam,\n\nThe photos look great. I will pick my favourites tonight.\n\nCheers,\nDana",
      meaning=(r"Sam", r"Dana", r"favou?rites")),
    X("greeting without signoff", "hey marta can you resend the invoice when you get a chance",
      "Hey Marta, can you resend the invoice when you get a chance?",
      meaning=(r"(?i)marta", r"invoice"), alt=("Hey Marta,\n\nCan you resend the invoice when you get a chance?",)),
    X("greeting quick question", "hey quick question can you send the file", "Hey, quick question: can you send the file?",
      meaning=(r"(?i)send the file",), forbidden=(r"Quick,",),
      alt=("Hey, quick question. Can you send the file?",)),
    X("thanks at end not a letter", "can you send the file when you get a chance thanks",
      "Can you send the file when you get a chance? Thanks.", gate=True, meaning=(r"send the file",)),
    X("signoff name only", "the report is attached let me know if anything is missing thanks omar",
      "The report is attached. Let me know if anything is missing.\n\nThanks,\nOmar",
      meaning=(r"report is attached", r"(?i)omar"), alt=("The report is attached. Let me know if anything is missing. Thanks, Omar.",)),
    X("email with list", "hi lena three things for monday the slides the budget and the venue thanks ravi",
      "Hi Lena,\n\nThree things for Monday:\n1. The slides\n2. The budget\n3. The venue\n\nThanks,\nRavi",
      meaning=(r"Lena", r"Ravi", r"slides", r"budget", r"venue")),
    X("email new paragraph", "hi chris thanks for the call new paragraph i will draft the proposal this week best maya",
      "Hi Chris,\n\nThanks for the call.\n\nI will draft the proposal this week.\n\nBest,\nMaya",
      meaning=(r"Chris", r"Maya", r"proposal", r"this week")),
    X("slack greeting", "morning all the deploy is done", "Morning all, the deploy is done.",
      meaning=(r"deploy(?:ment)? is (?:done|complete)",), alt=("Morning all,\n\nThe deploy is done.", "Morning, all. The deploy is done.")),
    X("email good morning", "good morning ellis the contract is signed and filed regards tom",
      "Good morning Ellis,\n\nThe contract is signed and filed.\n\nRegards,\nTom", gate=True,
      meaning=(r"Ellis", r"Tom", r"signed and filed")),

    # --- Names and proper nouns ----------------------------------------------
    X("names pair", "i talked to sam and sarah about it", "I talked to Sam and Sarah about it.",
      meaning=(r"(?i)sam and sarah",)),
    X("name direct address", "thanks mike that works for me", "Thanks, Mike, that works for me.",
      meaning=(r"(?i)mike", r"works for me"), alt=("Thanks, Mike. That works for me.",)),
    X("name possessive", "put it on jenna's calendar", "Put it on Jenna's calendar.", meaning=(r"(?i)jenna's",)),
    X("city", "we fly to lisbon on thursday", "We fly to Lisbon on Thursday.", meaning=(r"(?i)lisbon", r"Thursday")),
    X("product names", "export it from figma and upload it to github", "Export it from Figma and upload it to GitHub.",
      meaning=(r"(?i)figma", r"(?i)github")),
    X("name after with", "i'm meeting with carlos tomorrow", "I'm meeting with Carlos tomorrow.", meaning=(r"(?i)carlos",)),
    X("names no invention", "tell the team the api is down", "Tell the team the API is down.", gate=True,
      meaning=(r"API is down",), forbidden=(r"Deepgram", r"OpenAI")),
    X("month name", "the launch moved to october", "The launch moved to October.", gate=True, meaning=(r"October",)),
    X("weekday name", "see you on saturday", "See you on Saturday", gate=True, meaning=(r"Saturday",),
      alt=("See you on Saturday.",)),
    X("company name", "we signed with acme last week", "We signed with Acme last week.", meaning=(r"(?i)acme",)),

    # --- Numbers, money, quarters, phones ---------------------------------------
    X("quarter", "our q three revenue was one point two million dollars", "Our Q3 revenue was $1.2 million.", gate=True,
      facts=(r"Q3|q three", r"1\.2 million|one point two million")),
    X("quarter four", "we grew twenty percent in q four", "We grew 20% in Q4.", gate=True,
      facts=(r"20%|twenty percent", r"Q4|q four")),
    X("scaled money whole", "they raised two million dollars", "They raised $2 million.", gate=True,
      facts=(r"\$2 million|two million|2,?000,?000",)),
    X("scaled money billion", "the budget is one point five billion dollars", "The budget is $1.5 billion.", gate=True,
      facts=(r"1\.5 billion|one point five billion",)),
    X("scaled money thousand", "rent is two point five thousand dollars", "Rent is $2.5 thousand.",
      facts=(r"2\.5|2,500|two point five",), alt=("Rent is $2,500.",)),
    X("phone seven", "call me at five five five one two three four", "Call me at 555-1234.", gate=True,
      facts=(r"555-?1234|five five five one two three four",)),
    X("phone my number", "my number is five five five nine eight seven six", "My number is 555-9876.", gate=True,
      facts=(r"555-?9876|five five five nine eight seven six",)),
    X("phone ten", "text me at two one two five five five zero one nine eight", "Text me at 212-555-0198.", gate=True,
      facts=(r"212-?555-?0198|two one two five five five zero one nine eight",)),
    X("code not phone", "the code is five five five one two three four", "The code is 5551234.", gate=True,
      facts=(r"5551234|five five five one two three four",)),
    X("percent 2", "margins are up fifteen percent", "Margins are up 15%.", gate=True, facts=(r"15%|fifteen percent",)),
    X("money cents", "lunch was twelve dollars and forty cents", "Lunch was $12.40.", gate=True,
      facts=(r"\$12\.40|twelve dollars and forty cents",)),
    X("year 2", "the company started in twenty nineteen", "The company started in 2019.", gate=True,
      facts=(r"2019|twenty nineteen",)),
    X("date ordinal", "the review is on march third", "The review is on March 3rd.", gate=True,
      facts=(r"March 3rd|march third",)),
    X("time pm 2", "the call is at two thirty pm", "The call is at 2:30 PM.", gate=True, facts=(r"2:30 PM|two thirty",)),
    X("version", "we shipped version two point four today", "We shipped version 2.4 today.", gate=True,
      facts=(r"2\.4|two point four",)),
    X("count words stay", "i have two cats and three dogs", "I have two cats and three dogs.", gate=True,
      meaning=(r"two cats", r"three dogs")),
    X("large cardinal", "we had one thousand two hundred visitors", "We had 1,200 visitors.", gate=True,
      facts=(r"1,?200|one thousand two hundred",)),
    X("age", "my son is twelve years old", "My son is 12 years old.", gate=True, facts=(r"\b12\b|twelve",)),
    X("decimal 2", "the score was nine point five", "The score was 9.5.", gate=True, facts=(r"9\.5|nine point five",)),
    X("fraction 2", "about three quarters of the team agreed", "About three-quarters of the team agreed.", gate=True,
      facts=(r"three[ -]quarters|3/4",)),
    X("money hundreds", "the invoice is four hundred fifty dollars", "The invoice is $450.", gate=True,
      facts=(r"\$450|four hundred fifty",)),
    X("room number", "meet in room four", "Meet in room 4.", facts=(r"\b4\b|four",), alt=("Meet in room four.",)),
    X("two numbers", "we sold forty two units and returned three", "We sold 42 units and returned three.", gate=True,
      facts=(r"42|forty two", r"three|3")),

    # --- File names, addresses, links -------------------------------------------
    X("file name json", "open config dot json and change the port", "Open config.json and change the port.", gate=True,
      facts=(r"config\.json|config dot json",)),
    X("file name readme", "read the readme dot md first", "Read the readme.md first.", gate=True, facts=(r"readme\.md|readme dot md",),
      alt=("Read the README.md first.",)),
    X("file name py", "the bug is in main dot py", "The bug is in main.py.", gate=True, facts=(r"main\.py|main dot py",)),
    X("file underscore", "edit user underscore settings dot yaml", "Edit user_settings.yaml.", gate=True,
      facts=(r"user_settings\.yaml|user underscore settings dot yaml",)),
    X("email address", "send it to hello at example dot com", "Send it to hello@example.com.", gate=True,
      facts=(r"hello@example\.com",)),
    X("website", "the docs are at example dot org slash help", "The docs are at example.org/help.", gate=True,
      facts=(r"example\.org/help",)),
    X("dot in prose", "put a dot at the end of the line", "Put a dot at the end of the line.", gate=True,
      meaning=(r"a dot at the end",)),
    X("package json", "add it to package dot json", "Add it to package.json.", gate=True, facts=(r"package\.json|package dot json",)),

    # --- Spoken punctuation and layout ------------------------------------------
    X("new paragraph", "thanks for the update new paragraph i will review it tonight",
      "Thanks for the update.\n\nI will review it tonight.", gate=True, meaning=(r"review it tonight",)),
    X("new line", "milk new line eggs new line bread", "Milk\nEggs\nBread",
      meaning=(r"Milk", r"Eggs", r"Bread")),
    X("question mark spoken", "are you free tomorrow question mark", "Are you free tomorrow?", gate=True),
    X("exclamation spoken", "we did it exclamation point", "We did it!", gate=True),
    X("colon spoken", "one rule colon never ship on friday", "One rule: never ship on Friday.", gate=True,
      meaning=(r"never ship",)),
    X("quote spoken", "she said quote not today end quote", 'She said "not today."',
      meaning=(r"not today",), alt=('She said "not today".', 'She said, "Not today."')),
    X("two paragraphs", "the draft is ready new paragraph the budget still needs a review",
      "The draft is ready.\n\nThe budget still needs a review.", gate=True, meaning=(r"needs a review",)),
    X("comma spoken", "first the design comma then the build", "First the design, then the build.", gate=True),

    # --- Sentence boundaries and questions (the model's job) --------------------
    X("two statements", "the build passed i will deploy after lunch", "The build passed. I will deploy after lunch.",
      meaning=(r"build passed", r"deploy after lunch")),
    X("question then statement 2", "did you see the email i sent it this morning",
      "Did you see the email? I sent it this morning.", meaning=(r"see the email", r"this morning")),
    X("statement then question", "the room is booked do you want me to order lunch",
      "The room is booked. Do you want me to order lunch?", meaning=(r"room is booked", r"order lunch")),
    X("three sentences", "the site is live the numbers look good we should celebrate",
      "The site is live. The numbers look good. We should celebrate.", meaning=(r"site is live", r"celebrate")),
    X("wh question", "where did you put the keys", "Where did you put the keys?", gate=True),
    X("yes no question", "is the demo still on for today", "Is the demo still on for today?", gate=True),
    X("tag question", "you're coming tonight right", "You're coming tonight, right?"),
    X("embedded question stays statement", "i wonder what time it starts", "I wonder what time it starts.", gate=True),
    X("cleft stays statement", "what we need is more time", "What we need is more time.", gate=True),
    X("run on because", "we should wait because the vendor has not confirmed and the price might change",
      "We should wait because the vendor has not confirmed and the price might change.", gate=True,
      meaning=(r"has not confirmed", r"might change")),
    X("so start", "so the plan is simple we test then we ship", "So the plan is simple: we test, then we ship.",
      meaning=(r"we test", r"we ship"), alt=("So the plan is simple. We test, then we ship.",)),
    X("long ramble", "i looked at the numbers last night and honestly they are better than i expected the churn is down "
      "the new signups are up and the support queue is shorter than it has been all year so i think we can stop worrying "
      "about the forecast for now", None,
      meaning=(r"churn is down", r"signups are up", r"support queue", r"forecast")),

    # --- Fillers and stammers ------------------------------------------------
    X("fillers 2", "um i think uh we should move the meeting", "I think we should move the meeting.", gate=True,
      meaning=(r"should (?:move|reschedule) the meeting",)),
    X("you know filler", "it was you know a long day", "It was a long day.", gate=True, meaning=(r"long day",)),
    X("stammer", "we we need to fix the the login", "We need to fix the login.", gate=True, meaning=(r"fix the login",)),
    X("restart 2", "can you can you send it again", "Can you send it again?", gate=True),
    X("like as verb stays", "i like the new logo", "I like the new logo.", gate=True, meaning=(r"like the new logo",)),
    X("kind of meaning", "the kind of work we do is careful", None, meaning=(r"kind of work",)),
    X("filler and question", "uh what time is the thing", "What time is the thing?", gate=True),
    X("sort of hedge", "it sort of works on my machine", None, meaning=(r"works on my machine",)),

    # --- Negations, hedges and certainty must survive --------------------------
    X("negation not", "we should not ship it until friday", "We should not ship it until Friday.", gate=True,
      meaning=(r"(?i)not ship|shouldn't ship",)),
    X("negation never", "never merge without a review", "Never merge without a review.", gate=True,
      meaning=(r"(?i)never merge", r"without a review")),
    X("negation contraction", "i don't think it's ready", "I don't think it's ready.", gate=True,
      meaning=(r"(?i)don't think|do not think",)),
    X("hedge maybe", "maybe we can move it to next week", "Maybe we can move it to next week.", gate=True,
      meaning=(r"(?i)maybe",)),
    X("hedge probably", "it will probably rain tomorrow", "It will probably rain tomorrow.", gate=True,
      meaning=(r"probably",)),
    X("hedge not sure", "i'm not sure the client agreed", "I'm not sure the client agreed.", gate=True,
      meaning=(r"not sure",)),
    X("must", "you must sign before friday", "You must sign before Friday.", gate=True, meaning=(r"must sign",)),
    X("cannot", "we cannot accept late submissions", "We cannot accept late submissions.", gate=True,
      meaning=(r"(?i)cannot|can't",)),
    X("double negative", "it's not that we don't want to", "It's not that we don't want to.", gate=True,
      meaning=(r"not that", r"(?:don't|do not) want")),
    X("without", "ship it without the analytics", "Ship it without the analytics.", gate=True, meaning=(r"without",)),
    X("hedge might", "the vendor might raise prices in june", "The vendor might raise prices in June.", gate=True,
      meaning=(r"might raise",)),
    X("hedge roughly", "it takes roughly two hours", "It takes roughly two hours.", gate=True,
      meaning=(r"roughly",), facts=(r"two hours|2 hours",)),

    # --- Trivial and bare fragments ---------------------------------------------
    X("trivial ok", "ok", "OK", gate=True),
    X("trivial sounds good", "sounds good", "Sounds good", gate=True, alt=("Sounds good.",)),
    X("trivial fragment", "quarterly report", "quarterly report", alt=("Quarterly report",)),
    X("trivial yes", "yes", "Yes", gate=True, alt=("Yes.",)),
    X("trivial thanks", "thank you", "Thank you", alt=("Thank you.",)),
    X("trivial search", "cheap flights to rome", "cheap flights to rome", alt=("Cheap flights to Rome", "cheap flights to Rome")),
    X("trivial sentence", "the tests pass", "The tests pass", alt=("The tests pass.",)),

    # --- Acronyms and casing -----------------------------------------------------
    X("acronyms 2", "the pdf and the csv are in the shared drive", "The PDF and the CSV are in the shared drive.",
      meaning=(r"PDF", r"CSV")),
    X("ok sentence", "ok let's go", "OK, let's go", gate=True, alt=("OK, let's go.",)),
    X("titles 2", "doctor patel will see you now", "Dr. Patel will see you now.", gate=True, meaning=(r"Dr\. Patel",)),
    X("iphone", "it crashes on my iphone", "It crashes on my iPhone.", meaning=(r"iPhone",)),

    # --- Contractions ---------------------------------------------------------
    X("split contractions 2", "we re almost done and it s looking good", "We're almost done and it's looking good.",
      gate=True),
    X("fused contraction", "i cant make it and she doesnt know", "I can't make it and she doesn't know.", gate=True,
      meaning=(r"can't|cannot", r"doesn't|does not")),

    # --- Chill vs Executive material (long, casual) -----------------------------
    X("casual update", "so basically the new onboarding is kind of working but honestly the second screen is way too "
      "long and people are dropping off there so i think we should cut it in half", None,
      meaning=(r"onboarding", r"second screen", r"(?i)drop(?:ping)?[- ]?off", r"half|halve")),
    X("casual request", "hey can you like take a look at the pricing page when you get a sec it still says the old "
      "number and i dont want anyone to get confused", None,
      meaning=(r"pricing page", r"old number|outdated", r"(?i)don't want|do not want")),
    X("casual decision", "ok so we talked about it and we are going with the second vendor because they are cheaper "
      "and they can start next week", None, meaning=(r"second vendor", r"cheaper", r"next week")),
    X("casual complaint", "the printer is broken again and nobody has called the repair guy so i guess i will do it",
      None, meaning=(r"printer", r"broken", r"repair")),
    X("casual plan", "tomorrow i'm gonna finish the slides then i'll send them to jess and then we can rehearse on "
      "thursday", None, meaning=(r"slides", r"(?i)jess", r"Thursday")),
    X("casual feedback", "i really like the direction of the logo but the colour feels a bit too dark maybe try a "
      "lighter blue", None, meaning=(r"logo", r"(?i)too dark", r"(?i)maybe", r"lighter blue")),
    X("casual status", "just a heads up the server migration is taking longer than we thought it should be done by "
      "tonight though", None, meaning=(r"migration", r"longer", r"tonight")),
    X("casual thanks", "thanks so much for jumping on that so quickly you really saved us today", None,
      meaning=(r"(?i)thank", r"saved us")),

    # --- Mixed ---------------------------------------------------------------------
    X("mixed letter numbers", "hi dev team the q two report is at reports dot example dot com and revenue was three "
      "point four million dollars thanks lee", None,
      facts=(r"Q2|q two", r"reports\.example\.com", r"3\.4 million|three point four million"),
      meaning=(r"(?i)lee",)),
    X("mixed backtrack list", "we need three things chairs tables and lamps actually make that four things chairs "
      "tables lamps and rugs", None, meaning=(r"(?i)rugs",)),
    X("mixed question number", "can you call me at five five five two two two one", "Can you call me at 555-2221?",
      gate=True, facts=(r"555-?2221|five five five two two two one",)),
    X("mixed file and time", "update notes dot txt before three pm", "Update notes.txt before 3 PM.", gate=True,
      facts=(r"notes\.txt|notes dot txt", r"3 PM")),
    X("mixed percent quarter", "q one churn fell by two percent", "Q1 churn fell by 2%.", gate=True,
      facts=(r"Q1|q one", r"2%|two percent")),
    X("backtrack noon", "the meeting is at noon actually one pm", "The meeting is at 1 PM.",
      facts=(r"1 PM|one pm",), retracted=(r"noon",)),
    X("reminder am", "set a reminder for eight am", "Set a reminder for 8 AM.", gate=True, facts=(r"8 AM|eight am",)),
    X("units quarter", "we sold three hundred units in q two", "We sold 300 units in Q2.", gate=True,
      facts=(r"300|three hundred", r"Q2|q two")),
    X("email me", "email me at jo at example dot io", "Email me at jo@example.io.", gate=True,
      facts=(r"jo@example\.io",)),
    X("short letter", "hi priya the invoice is paid thanks sam", "Hi Priya,\n\nThe invoice is paid.\n\nThanks,\nSam",
      gate=True, meaning=(r"invoice is paid", r"Priya", r"Sam")),
    X("negation want", "i don't want to cancel the trip", "I don't want to cancel the trip.", gate=True,
      meaning=(r"(?i)don't want|do not want",)),
    X("hedge should", "maybe we should wait until tuesday", "Maybe we should wait until Tuesday.", gate=True,
      meaning=(r"(?i)maybe", r"should")),
    X("two options no and", "two options wait or ship", "Two options:\n1. Wait\n2. Ship",
      meaning=(r"(?i)wait", r"(?i)ship"), alt=("Two options: wait or ship.",)),
    X("file toml", "edit the settings dot toml file", "Edit the settings.toml file.", gate=True,
      facts=(r"settings\.toml|settings dot toml",)),
    X("price range", "the price went from ten dollars to twelve dollars", "The price went from $10 to $12.",
      gate=True, facts=(r"\$10|ten dollars", r"\$12|twelve dollars")),
]


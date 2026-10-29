"""The router of the narration layer (design section 24.8): what a question is, and no word of it.

`route(question)` is a pure function that returns the `Understanding` of `render.py`; the page
prints that and never the question. Four steps, all linear in the length of the question:

1. Normalise: NFKC of the case-folded NFKC text, then each of U+0020, tab, line feed, carriage
   return and the categories Zs, Zl and Zp is one space and a run of spaces is one.
2. Unreadable (a decision of form): empty, over 500 characters, no letter, a character of
   category C or M or one of the invisible letters (so no invisible character can split a word),
   or a word that mixes Latin letters with Cyrillic, Greek, Armenian, Coptic or Cherokee ones.
   The reason is one of `render.UNREADABLE_REASONS`.
3. Match. The words of the question are the runs of letters and digits (an apostrophe joins its
   neighbours, `re-run` is one word), with `^` before the first, `$` after the last, `,` for a
   clause boundary and `#` for a rule ID (`RES-004`, `res 004`, `ZZZ-123`). A pattern is a short
   sequence of steps: `(2, "call* declare*", "it this test")` is call or declare, or a word that
   begins so, then it, this or test, with at most two words between. A word ending in `*` is a
   prefix; an integer sets the number of words that may lie between a step and the one before it,
   for the steps that follow (0 when none is given); a step that begins with `!` is any word but
   those listed. A pattern is matched by dynamic programming over the positions of the words, one
   pass for each step, so the time is linear in the question and nothing backtracks. The tables
   are data. The words of a command are matched only after the start of a clause (`START`), so
   that "Skip the warnings." is steering and "Can we skip the warnings?" is not; a category that
   is about a finding counts only where the question names no rule, or not that one (`causal`,
   `effect_numbers`, `UNLESS_NAMED`): the numbers behind a finding are its explanation. Where a
   clause only says what must hold first ("fix it before we ship"), what the review did ("did you
   check whether it ran long enough") or why a rule says so ("why does RES-003 say it ran too
   short"), the words of `SOFT` in the rest of it are not matched (`QUIET`, `hush`); injection is
   never hushed.
4. Decide. A refusal category beats an intent, and the categories matched are listed in the order
   of `render.CATEGORIES` (the order of precedence); then the intents (`checked`, `next_steps`,
   an explanation of a rule named, `summary`); then the default route. A question that matches a
   category and an intent is a refusal that keeps the intent, so that the refusal can say that an
   answerable part was not answered; a refusal keeps an explanation only when a word of
   `INTENT_PATTERNS["explain_finding"]` (why, explain, mean, matter) is in the question, since a
   rule named in a refused question is not yet a question about it.

A target is a rule ID in the question or a phrase of `PHRASES`. An ID of the nine results rules
is printed canonically (`res 004` is RES-004). A string shaped like an ID that is not one of the
nine (RES-005, DES-001, ZZZ-123) is a target that `Understanding` cannot keep, so the explanation
of it is an `explain_finding` with no target and no `as_summary`. Two different targets give no
single target: the explanation is answered as a summary (`as_summary`). A question that asks to
explain the findings and names no rule is a `summary` (the taxonomy labels it so).

Three things go beyond the normalisation of 24.8, to close gaps that its own purpose (no
character can split a trigger word) leaves. (1) The Hangul fillers and the braille blank are
letters or symbols that show nothing, and category C or M does not hold them: they are unreadable
too. (2) A look-alike of a Latin letter in Armenian, Coptic or Cherokee makes a mixed word as
Cyrillic and Greek do, and an apostrophe that `read` removes does not end a word for that test.
(3) A letter that NFKC composed from a letter and a mark (the i with an acute accent of `ship`)
is matched as the letter, since the words are read from the text with its diacritics folded; the
readability rules stay those of 24.8. A refusal word spelt with look-alike letters of one script
(an all-Cyrillic word, a dotless i) is read as another word and missed (24.13).
"""

from __future__ import annotations

import unicodedata

from referee.narration.render import CATEGORIES, RULE_IDS, Understanding

MAX_CHARS = 500
RULE_FAMILIES = ("res", "des")  # a rule ID may be written with a space only for these
LOOKALIKES = frozenset({"CYRILLIC", "GREEK", "ARMENIAN", "COPTIC", "CHEROKEE"})
# Letters that show nothing and are in no category C or M: the Hangul choseong and jungseong
# fillers and the braille blank. NFKC maps the fillers U+3164 and U+FFA0 to U+1160.
INVISIBLE = "ᅟᅠ⠀"

Pattern = tuple[int | str, ...]

# --- The tables ------------------------------------------------------------------------------

# fmt: off
# Words that several patterns share (a prefix ends in `*`).
MODALS = "should shall can could may might will would do does need"
LAUNCH = "launch* releas* deploy*"
READY = "ok okay ready safe good begin start proceed cleared worth"
OBJECTS = (
    "variant* arm* change* feature* page* treatment* design* version* option* offer* layout* flow* "
    "control* one b"
)
VERDICTS = "pass passes passed passing clear valid approved green"
SUBJECTS = "verdict review report experiment result everything"
FINDINGS = "finding* block* warning*"
TARGETS = (
    FINDINGS + " verdict # srm flag* alert* issue* problem* caveat* severity breach* violation* "
    "failure* drift* guardrail* skew* config* negative* critical* criticism* downside* bad "
    "expos* imbalanc*"
)
STEERED = (
    TARGETS + " check* rule* validat* verif* instruction* guideline* prompt* constraint* "
    "restriction* polic* "
    "programming directive* safeguard* default* setting* everything previous above earlier"
)
QUALITY = (
    "fine valid ok okay safe trust* reliab* rely sound acceptable clean solid robust credible "
    "accurate normal reasonable sensible appropriate wise healthy legit* kosher correct right "
    "proper"
)
REAL = (
    "real genuine* significant significantly chance nois* random* fluke* luck* "
    "exist* believable plausible artifact* artefact* legit* accident* coincidence* coincidental "
    "signal* wobble* fluctuat* authentic* conclusive* proven bona demonstrat* illusion* mirage"
)
CHANGE = (
    "effect lift uplift difference gap change increase decrease rise drop decline gain higher "
    "lower jump* spike* bump* surge* boost* growth swing* gains effects lifts improvement*"
)
MOVES = CHANGE + " revenue purchases spend* conversion sales sessions retention buy*"
EFFECT_WORDS = MOVES + " bought up down metric more less better worse beat beats won ahead"
CAUSES = (
    "banner button discount* sale promo* campaign* holiday* price pricing design layout email "
    "newsletter marketing ad ads bug release"
)
GROUP = "control treatment arm arms variant group"
AVERAGES = "average* median"
AMOUNTS = "player* data time day* week* month* sample traffic users long run observation* events"
PEOPLE = "player* user* customer* account* buyer* gamer* member* people"
ANALYSES = (
    "median mean average* revenue conversion retention metric* test* model* method* window* "
    "period* approach* estimator*"
)
# Where a question or a clause starts, so that a verb after it is a command: "Skip the warnings."
CLAUSE = "^ , or and but so what which how"
SUBJECT = "review referee report you anyone anybody someone it they we"
CHECKING = (
    "check* test* verif* examin* inspect* assess* evaluat* look* cover* consider*"
)
START = "^ , and then also but plus so please just now kindly"
START_YOU = START + " you"

HIDE = (
    "hid* skip* omit* suppress* leav* left exclude* delete* remov* drop* cut strip* eras* conceal* "
    "censor* mask* discard* ignor* disregard* withhold* overlook* disabl* strik* clear purge* "
    "sanitiz* neglect* dismiss* bury* sweep* sugarcoat* whitewash* spin cook* falsif* rig gloss* "
    "embellish* exaggerat* downplay* minimi* shrug* brush*"
)
SPINNABLE = (
    STEERED + " result* number* figure* data stat* conclusion* outcome* summary review report "
    "experiment answer output"
)
SAY = (
    "mention* show* report* list* include* print* say tell flag* raise* reveal* display* output* "
    "give*"
)
ALTER = (
    "downgrad* demot* soften* reclassif* relabel* recategor* lower* reduc* turn turns turned "
    "chang* convert* mak* set sets mark marks marked label* classif* rewrit* replac* swap* "
    "substitut*"
)
TREAT = (
    ALTER + " treat* regard regards regarded consider* count counts counted report* call* rate "
    "rates rated record records recorded log logs logged present presents presented describe* "
    "portray* depict* frame frames framed characteriz*"
)
SEVERITIES = (
    "info informational note minor low nonblocking advisory warning fine ok okay no zero none "
    "nothing non resolved fixed closed " + VERDICTS
)
LATER = (
    "shorter briefer clearer easier concise* succinct* accessible approachable longer detailed "
    "lengthier fuller"
)
BEHIND = MOVES + " up down more less better worse numbers results"

# The refusal categories, in the order of precedence (`render.CATEGORIES`).
TRIGGERS: dict[str, tuple[Pattern, ...]] = {
    "injection": (
        # set the rules aside
        (3, "forget* override* bypass* circumvent* reset* flush* wipe*", STEERED),
        (3, "forget* ignor* disregard*", "told said instructed taught programmed trained"),
        (0, "forget* ignor*", "you your", "are role"),
        (3, "stop* cease* quit*", "follow* obey* observ*"),
        (3, "stop* cease* quit* skip* disabl*", "apply* enforc* running", 3, STEERED),
        (0, "no", "longer", 2,
         "bound constrained restricted limited required obliged follow* obey* reviewer referee"),
        (0, "you youre", "are", 1, "my", "assistant servant"),
        (0, "you", "agree", "with", "everything anything all"),
        (START_YOU, 1, "updat* chang* modif* adjust*", 1, "your", "behavio* rules instructions "
         "guidelines"),
        (0, "from", "the", "next", 1, "message answer reply turn time", "on onward"),
        (0, "asked told instructed ordered requested wants want need needs require requires", 2,
         "us me you him her them", "to", 1, HIDE, 4, STEERED),
        (0, "whatever", "it", "takes"),
        (3, "set put lay push cast brush", "aside"),
        (0, "stop quit", "being"),
        (0, "let", "this it that them", "through slide pass go"),
        (2, "rule* constraint* restriction* limit* guideline* polic*", "dont doesnt arent wont",
         "apply"),
        (0, "instead", "of", 3, "rule* instruction* guideline* polic*"),
        (0, "your", "own", "judgement judgment"),
        (START_YOU, 1, "ignor* disregard* forget* bypass* override*", 1, "them it all"),
        # take another role, or a mode
        (1, "act behave", "as like to you"),
        (0, "from", "now here then", "on onward onwards"),
        (0, "from", "this", "point", 1, "on onward forward"),
        (0, "you youre", "now"),
        (0, "you", "are", "now"),
        (0, "imagin*", "youre"),
        (0, "your", "job task role mission purpose goal", 1, "now"),
        (1, "your", "new", 0, "role task job purpose mission"),
        (3, "take assume adopt", "role character identity"),
        (0, "play", 1, "the a", "role character", "of as"),
        (0, "cherry", "pick*"),
        (0, "rubber", "stamp*"),
        (0, "your", "only sole one", "goal job task purpose mission aim"),
        (0, "system developer admin",
         "message note instruction notice prompt update command override*"),
        (START_YOU, 1, HIDE, 6, SPINNABLE),
        (0, "play", "a", "game"),
        (1, "developer debug admin maintenance god sudo test", "mode"),
        (3, "switch* enter enabl* activat*", "mode"),
        ("persona* jailbreak* unrestricted uncensored unfiltered roleplay*",),
        (2, "pretend*", "you youre to"),
        (3, "pretend*", TARGETS + " " + SUBJECTS),
        # claim an authority, or give new orders
        (1, "authoriz* authoris* telling ordering instructing commanding directing demanding",
         "you"),
        (2, "im i ive", "authoriz* authoris* entitled"),
        (3, "have has got using with",
         "admin* root sudo override* clearance privilege* credentials"),
        (0, "my", "permission"),
        (2, "new updated revised additional latest",
         "instruction* rule* directive* order* command*"),
        (0, "higher", "priority", 3, "instruction* rule* command*"),
        (1, "you", "must always only never", 2,
         SAY + " answer respond reply call treat mark label state write"),
        (0, "regardless", "of", 3, "what the report rules checks findings result* data"),
        (0, "no", "matter", "what"),
        (0, "whatever", 3, "data report rules results review checks"),
        # invent, hide or alter a finding or the verdict: commands
        (6, "invent* fabricat* falsif* fak* forg*",
         FINDINGS + " verdict number* figure* result* data estimate*"),
        (3, "add insert append", FINDINGS),
        (START, 1, "add insert append inject include", 3,
         "line lines sentence* note* statement* claim* remark* comment*", 4,
         "saying stating claiming that"),
        (0, "make", "up", 3, FINDINGS + " verdict result* number* figure* value* estimate* data"),
        (1, "hid* conceal* omit* suppress*", "fact* truth detail* information"),
        (3, "lie lies lying", "about", 3, TARGETS),
        (0, "if", "you", 3, "dont didnt wouldnt not never", 1, SAY, 4, STEERED),
        (START_YOU, 1, HIDE, 6, "from", 2,
         "your the this my output answer reply response summary report writeup page review"),
        (START, 1, "do", "away", "with", 3, STEERED),
        (START, 1, "get", "rid", "of", 3, STEERED),
        (START, 1, "take pull", 4, STEERED, 3, "out off away"),
        (START, 1, "switch* turn* shut*", 1, "off down", 4, STEERED),
        (START, 1, "tone", 1, "down", 4, TARGETS),
        (START, 1, "dont never avoid* stop* refrain*", 1, SAY, 4, STEERED),
        ("can could would will", "you", 1, "not dont", 1, SAY, 4, STEERED),
        (START, 1, "do", "not", 1, "apply* use* enforc* run* check* consider*", 4, STEERED),
        (START, 1, "do", "not", 1, SAY, 4, STEERED),
        (START, 1, "dont never", 1, "let", 6, STEERED),
        (0, "without", "mentioning showing listing including printing reporting flagging", 4,
         STEERED),
        (4, "show print give display output report summar*", "without", 2, TARGETS),
        (4, "show give display report summar*", "with", 1, "no zero", 2, TARGETS),
        (0, "no", "finding* warning* blocker*", 1, "in on from", 2,
         "output answer page report summary response"),
        (0, "make", "it", "so", "that", 8, TARGETS),
        (3, "only", "positive good favorable favourable optimistic",
         "finding* result* news point* thing* part* bit bits side aspect*"),
        (0, "keep stay", "quiet silent"),
        (4, "overrid* overwrit* overturn* revers* alter alters altered altering tamper* "
            "manipulat* adjust* tweak* edit* modif* doctor* massag* revis* amend*", TARGETS),
        (4, "flip*", "verdict finding* result* #"),
        (START_YOU, 1, "soften* play", 6, TARGETS),
        (START_YOU, 1, HIDE, 3, "part parts section* line* bit bits sentence* paragraph* note*", 8,
         STEERED),
        (START_YOU, 1, "mak* get have let", 4, TARGETS + " it them", 2, "not never", 1,
         "show appear display print"),
        (START_YOU, 1, "mak* get", 4, TARGETS, 2, "disappear vanish go"),
        (START_YOU, 1, "say tell state claim declare conclude report write print respond answer",
         3, "that", 5, SUBJECTS + " everything all it #", 3, VERDICTS),
        (0, "imagin* suppose", "you youre", 3, "have had are were no without"),
        (0, "no without", 1, "rules guidelines restrictions instructions constraints limits "
         "filters safeguards"),
        (START, 1, "replac* swap* substitut* overwrit* cancel* void* nullif*", 4,
         "finding* verdict warning* block* # list result*"),
        # tell Referee what to say, or how to treat a finding
        (START_YOU, 1, TREAT, 8, "to as into", 4,
         SEVERITIES + " success* positive good great healthy valid clean"),
        (START_YOU, 1, ALTER, 4, "verdict conclusion* outcome*"),
        (START_YOU, 1, "mak* set turn mark* label*", 3, SUBJECTS, 2,
         VERDICTS + " resolved fixed closed"),
        (START_YOU, 1, "mark* label* set", 1, "it this that", 2,
         VERDICTS + " resolved fixed closed"),
        (0, "sound sounds", "like", 3, "succeeded passed won worked success valid clear approved"),
        (4, "mak* needs need", "come comes", 1, "out", 2, "clean clear fine good valid green"),
        (2, "verdict result* review report", "to", 1, "say read be show", 1, VERDICTS),
        (START_YOU, 1, "print* output write respond reply answer say", 2, VERDICTS),
        (START_YOU, 2, "report* state declar* claim conclude", 3, "everything all", 2, VERDICTS),
        (START, 1, "say state claim output print write declar* report* conclude", 1,
         "no zero none nothing", 2, TARGETS),
        (START, 1, "say tell state claim output print write declar* report* conclude", 4,
         "that there", 6, "no zero none nothing", 4, TARGETS),
        (0, "asked requested insisted demanded want wants need needs", 2, "that us me you", 8,
         SUBJECTS + " output answer summary report", 3,
         "show shows say says state states read reads be is has have contain contains", 2,
         "no zero none nothing clear valid passed"),
        (0, "treat* regard* consider* count* classif* rate* record* log* report* mark* label* "
            "call*", 4, TARGETS, 1, "as", 2,
         "info informational note minor low nonblocking advisory resolved fixed closed fine ok "
         "okay trivial negligible irrelevant"),
        (START_YOU, 1, ALTER, 3, "#"),
        (3, "reply* respond* answer* say output print", "with", 1,
         "no zero nothing all approved clear valid"),
        (0, "in", "which", 6, TARGETS, 5, VERDICTS + " fine ok never"),
        (0, "as", "if though", 6, TARGETS),
        (0, "as", "if though", 8, "nothing none"),
        (0, "as", "if though", 1, "it they that this", 1,
         "never didnt hadnt hasnt wasnt isnt doesnt"),
        (4, "mak* needs need", "look* appear* seem* sound*", 2,
         "tidy clean good better positive favourable favorable nicer green passed approved perfect "
         "balanced fine valid successful great strong healthy"),
    ),
    "ship_decision": (
        ("ship ships shipped",),
        ("adopt*",),
        ("rollback",),
        ("revert*",),
        (2, "roll*", "back"),
        (4, MODALS, "roll rolls rolling", 4, "out"),
        (START, 1, "roll rolls rolling", 4, "out"),
        (3, READY, "roll rolls rolling", 4, "out"),
        (0, "go", "with"),
        (0, "go", "ahead", "with"),
        (0, "the", "go", "ahead"),
        ("productioniz* productionis*",),
        (3, "publish* push*",
         OBJECTS + " it this them everyone all audience customers production live"),
        (4, MODALS, "back", 1, OBJECTS),
        (1, "go", "no", "go"),
        (0, "green", "light"),
        ("greenlight* greenlit",),
        (4, MODALS, "go goes", 0, "out"),
        (4, MODALS, "go goes", 3, "100 everyone all production live"),
        (0, "a", "go"),
        (0, "good ready set cleared clear", "to", "go"),
        (2, "go put make push take", "live production prod"),
        (2, "send promote graduat* move migrat*", "to", 0, "production prod"),
        (0, "pull", "the", "trigger"),
        (2, "promote promotes promoted promoting", "to", 1, "hundred percent* global*"),
        (3, "advisable wise sensible prudent justified justify* appropriate reasonable",
         LAUNCH + " rollout roll rolling promote promoted promoting replac* switch* enabl* expan* "
         "ramp*"),
        (3, "ramp* sunset* merge* enabl* expan* flip* promote promoted promoting",
         OBJECTS + " it this them branch* everyone everybody all players production live default"),
        (4, "put", "in", 0, "front", 3, "players everyone customers all every each"),
        (1, "switch* turn* flip*", "on", 5,
         "everyone everybody all players customers markets production live default"),
        (3, "be become", "default permanent baseline standard"),
        (0, "a", "yes no"),
        (0, "sign", "off", 2, LAUNCH + " shipping rollout"),
        (3, "make", OBJECTS + " it this", 2, "default standard"),
        ("winner*",),
        (5, "which what", OBJECTS, 3,
         "won win wins winn* best better choos* pick* select* keep* prefer* favo* use " + LAUNCH),
        (0, "better best right correct", "choice option pick call"),
        (4, "comfortable happy fine ok okay", "with", 3, LAUNCH + " shipping rollout"),
        (0, "commit committing", "to", 3, OBJECTS),
        (0, "not", "to", LAUNCH + " rollout"),
        (2, "flip* toggle*", "flag* switch*", 6,
         "everyone everybody all 100 traffic players users production live"),
        (2, "shipping", "it", "or", "not"),
        (4, "did does is are", OBJECTS, 2, "win wins won winn*"),
        (3, "should shall can could may might will would do", LAUNCH),
        (3, LAUNCH, "recommendation*"),
        (2, "should shall can could may might do", "proceed*", 0, ", $ to and or"),
        (2, "should shall can could may might do", "proceed*", 0, "with", 2,
         OBJECTS + " it this rollout " + LAUNCH),
        (2, MODALS, "mov*", 1, "forward ahead"),
        (3, "recommend* advis* suggest*", LAUNCH + " proceed* shipping"),
        (0, LAUNCH, "or", "not"),
        (3, "whether", LAUNCH),
        (4, "yes no", LAUNCH),
        (3, LAUNCH, "yes no"),
        (0, "we", LAUNCH),
        (0, "a b c", "or", "a b c"),
        (0, "who", "wins won win"),
        (0, "replac* swap* supersed*", "a c"),
        (1, LAUNCH, "tomorrow tonight"),
        (3, READY, LAUNCH + " shipping"),
        (1, "moment time", "to", 0, LAUNCH),
        (5, "keep* scrap* drop* abandon* ditch* retire* discard* pick* choos* select* prefer* axe* "
            "shelve* nix*", OBJECTS),
        (4, "replac* swap* substitut* supersed*",
         OBJECTS + " old new current existing original one"),
        (1, "stay stick switch", "with to on", 2, OBJECTS + " old original current existing new"),
        (3, "justify* warrant*",
         LAUNCH + " shipping rollout switch* promote promoted promoting replac*"),
        (3, "make making", OBJECTS, 2, "permanent permanently"),
        (5, "approv* decision*", OBJECTS + " " + LAUNCH + " shipping rollout"),
        (2, "should shall can could may might will would do", "decid*", 4,
         OBJECTS + " " + LAUNCH + " shipping rollout"),
        (2, "would could can will do should", "approv*"),
    ),
    "stopping": (
        (2, "call* declare*",
         "it this test experiment run early finished done complete over now"),
        (3, "enough", AMOUNTS + " read conclude interpret end stop finish"),
        (0, AMOUNTS + " arm arms group variant", "enough"),
        (0, "big large bigger larger ample", "enough"),
        ("sufficient* adequate*",),
        (1, "too", "early soon"),
        ("premature*",),
        (1, "stop stops stopping halt halts halting",
         "it this test experiment run trial study now today here collecting enrolling"),
        (3, "stop stops stopping halt halts halting", "early"),
        (1, "we i you it they", "stop stopping halt halting", 0, ", $"),
        (0, "to", "stop stopping halt halting", 0, ", $"),
        (0, "in", "a", "position", "to"),
        (0, "still", "running"),
        (0, "done", "yet"),
        (0, "^ , or and but", "has have had did do does", 4, "reach* hit meet met achiev*", 4,
         "sample target size goal"),
        ("extend* prolong*",),
        (3, "keep kept keeping run running continue go collecting", "longer", 0, "!than"),
        (3, MODALS + " have has must worth", "wait waiting"),
        (2, "keep kept keeping", "running collecting going"),
        (0, "can could may might should", "we i", "read interpret", 3,
         "it this results result numbers data outcome test experiment"),
        (0, "at on", "day week", 1, "of"),
        ("peek*",),
        (3, "need* collect* gather* get run running continue",
         "another more additional", 1, "week* day* month* player* data time traffic sample* user*"),
        (0, "how", "many", "more"),
        (0, "how", "much", "more additional extra", 1,
         "week* day* month* player* data time traffic sample* user*"),
        (0, "hold", "off"),
        (3, "draw drawing", "conclusion* inference*"),
        (1, "test experiment trial study", "is was has", 1,
         "over finished complete completed ended done"),
        (2, "cut", "short"),
        ("plug",),
        ("earliest",),
        (2, "continu*", "running collecting"),
        (2, "end ends ending ended finish* finaliz* wrap close terminat* kill* abort* cancel* "
         "pause* shut*",
         "test experiment trial run study here now today up it this early down"),
        (0, "we", "done finished conclude finaliz* finalis*"),
        (1, "continu*", "test experiment run trial study"),
        (3, "allowed permitted safe ok okay fine appropriate",
         "look read see view check* analys* analyz* interpret conclu*"),
        (0, "when", "can could may might should do", 1, "i we", 2,
         "look read see check analys* analyz* interpret conclu* stop end finish call"),
        (3, "let lets letting", "finish* run running end complete continue"),
        (3, "read look interpret analys* analyz*", "yet already"),
        (1, "conclu*", "now today yet already early"),
        (6, "reach* hit achiev* collect* gather* finish* complet*", "yet already"),
        (0, "^ , or and but", "may can could might should do shall", 8, "before until", 4,
         "end ending finish* planned scheduled completion deadline registered target"),
        (1, "stop stopping halt halting", "at after on by before until"),
        (3, "is are was has have", "test experiment trial study", 1,
         "finished complete completed over ended concluded"),
        (0, "its full", "course"),
        ("stabili* converg* plateau*",),
        (0, "mature matured", "enough"),
        (0, "to", "completion"),
        (0, "early", "look read glance"),
        (2, "far", "along enough"),
        (0, "at", "this", "point stage"),
        (0, "at", "what", "point stage day"),
        (1, "reach reached reaching hit", "point stage"),
        (0, "how", "many", 1, "days weeks", 3, "do we still need must", 2,
         "more before until left"),
        (0, "how", "long", 3, "until before must need"),
    ),
    "reassurance": (
        (8, "confirm* reassur* assur*",
         QUALITY + " properly correctly wrong problem* issue* worry worried concern* nothing "
         "quality enough small tiny minor inconsequential"),
        ("surely",),
        (0, ",", "right correct agreed yes yeah no ok okay true fair", 1, "$"),
        (0, "non", "issue"),
        (0, "as", 1, "noise irrelevant unimportant minor fluke"),
        (0, "doesnt isnt arent wasnt werent", "it they that this", 1, "$"),
        (0, "cant couldnt shouldnt wont wouldnt dont", "i we you", 1, "$"),
        (0, "i", "assume presume guess suppose hope", 0, ", $"),
        (0, "rest", "easy easier assured"),
        (0, "lose", "sleep"),
        (0, "above", "board"),
        (0, "bill", "of", "health"),
        (0, "within", "tolerance range limits bounds"),
        (0, "no", "red", "flag flags"),
        (0, "isnt arent", "a", "concern problem issue worry"),
        (0, "really actually truly", 1, "a an that such", "problem issue concern worry deal"),
        (0, "that so really", "serious bad important critical worrying severe"),
        (0, "serious bad important critical worrying severe big major", "or", 1,
         "just only merely", "noise minor nothing fluke"),
        (4, "it this that they data results numbers experiment test setup",
         "looks look seems seem appears appear", 3, QUALITY + " good great healthy"),
        (0, "be", "sure certain confident", 3, "numbers results data figures experiment setup", 3,
         QUALITY + " correct right"),
        (0, "fair", "to", "say"),
        (0, "you", "agree* concur*", 1, "$"),
        (0, "is are am", "i he she we they it that this", "right correct wrong"),
        (0, "i", "take", "it"),
        (0, "^ , or and but so", "is are was were can could", 8, QUALITY, 0, "!or"),
        ("^", "so then okay basically", 5, "is are was were", 5, QUALITY, 0, "!or"),
        (0, "^ , or and but so", "does do", 2, "look* seem*", 3, QUALITY, 0, "!or"),
        (0, "wont isnt doesnt arent wasnt dont cant couldnt", 6, ",", 0,
         "will is does are was do can could", "it they that this he she there", 1, "$"),
        (0, "i im we id",
         "say assume* presum* guess suppos* think believe hope gather understand", 8,
         QUALITY + " minor small tiny"),
        (0, "you youd", "agree* think say consider* believe* deem*", 8, QUALITY),
        (1, "would could can do will", "you", 1, "trust* rely vouch*"),
        (0, "sign", "off", 6, "data results numbers test experiment quality"),
        (2, "nothing",
         "worry wrong broken concern* alarming sleep fret* stress* fix change repair"),
        (0, "too", "small tiny minor little", 3, "matter ignore worry"),
        (0, "no", "impact effect bearing influence", "on", 1,
         "validity results conclusion* data verdict quality"),
        (0, ",", "should shall do does can could is are was", "we i you it they", 1, "$"),
        (2, "worth", "worrying worry bother sleep"),
        (4, "should shouldnt shall do dont does doesnt need must",
         "worry worried concerned alarmed bothered panic worrying"),
        (2, "stop* quit* cease*", "worrying worry"),
        (0, "to", "worry worrying worried fret*"),
        (0, "missing", "anything something"),
        (0, "am", "i", "being"),
        (3, "enough small tiny minor safe fine ok okay", "ignor* disregard* dismiss* overlook*"),
        (3, "small tiny minor low little", "enough", 3, "matter"),
        (2, "it they that this", "doesnt dont wont", "matter"),
        (0, "feel", "confident comfortable reassured safe good okay"),
        (3, "can could may might should shall",
         "ignor* disregard* dismiss* overlook* brush* shrug* skip*"),
        ("ignorable negligible harmless benign immaterial",),
        (0, "false", "alarm* positive* alert* flag* warning* signal*"),
        (0, "big", "deal"),
        (0, "^ , so then", "no", "problem* issue* concern* worry"),
        (0, "in", "the", "clear"),
        (2, QUALITY + " right alright allowed worth", "to", 1,
         "trust* rely use ignor* disregard* dismiss* overlook* skip* proceed"),
        ("^ ,", 3, QUALITY, 0, ", $"),
        (0, "in", "order", 0, ", $"),
        (1, "to would could", "doubt"),
        (0, "pass", "muster"),
        (0, "good fine close okay ok safe clean sound solid", "enough"),
        (2, "all", "good fine clear ok okay"),
        (4, "say tell promise", "fine ok okay good safe valid clean sound"),
        (0, "doesnt dont", "change affect* alter alters invalidate* undermine*", 3,
         "anything result* conclusion* verdict validity"),
    ),
    "effect_reality": (
        (0, "^ , or and but so", "is are was were does do did can could will would", 8,
         REAL + " variation distinguishable detectable"),
        (8, "whether if", REAL),
        (3, "effect lift uplift difference gain impact improvement increase", REAL),
        (0, "is are was were", "there", 3, "effect* difference lift uplift impact", 2, ", $"),
        (0, "is are was were", "there", 3, "effect* difference lift uplift impact", 1, "between"),
        (1, "had has have", "an any no a", "effect impact difference"),
        ("statistically",),
        ("insignific*",),
        (0, "statistical*", "signific* differ* distinguish* meaning* speaking"),
        (3, "effect lift uplift difference gain impact improvement result", "significance"),
        (3, "really actually truly genuinely", "make makes made", 2, "difference impact"),
        (0, "genuinely truly really actually", "better superior worse improved effective"),
        (2, "evidence data results", "show* suggest* indicat* support* prove*", 1, "that", 3,
         "better beat* outperform* improv* higher increas*"),
        (0, "work works", "or", "not"),
        (1, "true truly genuinely really",
         "effect* improvement* difference* lift* uplift* impact* gain* mov* increas* help* chang* "
         "affect* outperform* beat*"),
        (3, "show* suggest* indicat* reveal* support*", "any a an", 2,
         "effect* difference* lift* uplift impact improvement"),
        (3, "evidence sign signs proof indication* hint",
         "effect* difference* lift* uplift impact worked work chang* affect* mov* improv* "
         "increas*"),
        (2, "different distinguishable", "from", "zero null nothing"),
        ("nonzero",),
        (0, "null", "hypothesis"),
        (4, "did does do", OBJECTS + " it they", 3,
         "anything nothing work works worked help* mov* chang* affect* influenc* improv* increas*",
         1, ", $"),
        (0, "actually really truly genuinely", "differ*"),
        (3, OBJECTS + " it they", "did does do", 1, "anything nothing work works worked"),
        (0, "how", "sure confident certain", 8,
         "effect* difference* lift* uplift impact improvement gain* result* page does works"),
        (0, "move", "the", "needle"),
        ("^ , or and but just so", 1, REAL + " meaningful", 4, "or , $"),
        (1, "any", REAL + " measurable meaningful"),
        (0, "non", "zero"),
        (6, "say claim conclude prove confirm* show back* support* demonstrat* suggest* indicat*",
         "works worked work helps helped improves improved increases increased"),
        (4, "is are was does do did", OBJECTS, 2, "better superior outperform* worse"),
        (3, "effect* difference* lift* uplift impact", "actually", 1, "there present"),
        (2, "believe* trust*", "effect* lift* uplift difference* improvement* gain* impact*"),
    ),
    "effect_numbers": (
        (0, "how", "big* larg* strong* high*"),
        (0, "how", "much", 3, "did does was were has have is are", 4, EFFECT_WORDS),
        (0, "how", "much", 2, "more less higher lower better worse"),
        (0, "by", "how", "much"),
        (0, "what", "percent*"),
        (4, AVERAGES, GROUP),
        (0, "the", "mean", "of for in"),
        (0, GROUP + " metric", "mean"),
        (4, GROUP, AVERAGES),
        (0, "effect", "size*"),
        (3, "size", "lift* uplift* effect* difference* gain* improvement* change*"),
        (1, "absolute relative percent*", "terms points difference lift uplift effect change"),
        (0, "how", "many", 1, "dollar dollars euro euros point* percent* cent cents"),
        (3, "what which", "number* figure* value* score*", 4, GROUP),
        (3, "what which", "number* figure* value* score*", 3,
         "lift* uplift* effect* difference* delta* gain* improvement*"),
        (0, "how", "many", 1, "extra additional more", "purchases sales conversions orders"),
        (0, "what", "is was are were", 4,
         "revenue conversion retention spend* arpu sessions rate*", 4, GROUP),
        (START_YOU, 1, "give show tell report print state provide quote read list send quantify", 4,
         "lift* uplift* effect* difference* delta* gain* improvement* number* figure* revenue "
         "conversion retention spend* arpu sessions mean average* median"),
        (START_YOU, 1, "show tell give", 5, "statistics result*", 4, GROUP + " metric* kpi*"),
        (0, "i we id wed", "need want like", 4,
         "lift* uplift* effect* difference* delta* gain* improvement* number* figure*"),
        (0, "percent* pct", "change increase gain lift improvement decrease growth"),
        (0, "arpu revenue conversion retention spend*", "difference diff delta lift gain gap"),
        (1, "results effect", "table"),
        (3, "variant treatment arm control", "lift uplift"),
        ("magnitude",),
        (0, "what", "is was are were", 3, "lift* uplift* delta*"),
        (3, "whats", "lift* uplift* delta* effect*"),
        (0, "what", "is was are were", 3,
         "observed measured overall total net actual headline primary final", 1,
         "effect* difference* gain* improvement* impact change*"),
        (2, "put", "number figure value", 1, "on"),
        (4, "number* figure* stats", "for on of", 2, GROUP + " b c metric* kpi*"),
        ("^ ,", "lift uplift estimate effect", 0, ", $"),
    ),
    "causal": (
        (8, "caus*", EFFECT_WORDS),
        (8, EFFECT_WORDS, "caus*"),
        (4, "drove driv*", EFFECT_WORDS),
        ("novelty seasonality",),
        ("curiosity honeymoon hype primacy shiny confound*",),
        (0, "down", "to"),
        (0, "account*", "for", 4, "it that this outperform* beat* " + MOVES),
        ("inflat* distort*",),
        (4, "explain*", MOVES),
        (2, "produce produced produces producing", MOVES),
        (3, "made make*", MOVES),
        (3, "behind", BEHIND),
        (3, "from because due", CAUSES),
        (0, "owing thanks", "to"),
        (0, "anything something", "to", "do", "with"),
        (1, "what", "moved moves", 2, "metric numbers needle lift revenue"),
        (0, "is was", "it", "the a", 1, CAUSES),
        (6, EFFECT_WORDS, "come comes came", 1, "from"),
        (1, "just only simply merely purely", "react* excited hyped"),
        (1, "outside external exogenous", "influence* factor* event*"),
        (3, "could might may maybe perhaps possibly",
         "campaign* promo* sale pricing outage* bug competitor* weather news holiday*"),
        (6, "attribut* responsible", EFFECT_WORDS),
        (6, EFFECT_WORDS, "attribut* responsible"),
    ),
    "forecast": (
        ("expect expecting expects",),
        ("forecast* predict* projected projecting projection* extrapolat* anticipat*",),
        (START_YOU, 1, "project", 4, EFFECT_WORDS),
        ("future rollout* eventually",),
        (0, "long", "run term"),
        (0, "full at to", "scale"),
        (0, "scale scaling scaled", "up out"),
        (2, "when once after as if", "scale scaling scaled"),
        (4, "will",
         CHANGE + " impact result revenue conversion growth metric"),
        (0, "what", "happens happen", 3, "when after once next later"),
        ("holiday* season seasons annual* yearly monthly quarterly",),
        (1, "in next every per each over within for coming following another",
         "month* year* quarter*"),
        (2, "beyond", "month* year* quarter* week*"),
        (0, "past", "the", "first"),
        (0, "no", "longer", 1, "new novel"),
        (0, "wears wear worn", "off"),
        (4, "will would", "look be", 3, "after once when later"),
        (0, "times", "the", "traffic players users volume sample"),
        (0, "in during by", "january february march april june july august september october "
         "november december summer winter spring autumn christmas"),
        (2, "in for during", "second first", "half"),
        (0, "from", "now"),
        (2, "year* month* quarter* week*", "ahead later out down hence"),
        (0, "live", "for", "everyone everybody all"),
        (0, "as", "time", "passes goes"),
        (1, "weeks days months years time", "go goes pass passes", 1, "by"),
        (0, "will would", "it this that", 1, "hold stay grow"),
        (0, "likely", "to", 1, "be grow last hold continue change increase decrease drop rise"),
        (2, "will would", "last remain continue"),
        (0, "steady", "state"),
        ("maturity",),
        ("shrink* disappear* vanish*",),
        (0, "going", "forward"),
        (0, "going", "to", 1, "last hold stay continue wear grow"),
        (1, "next coming upcoming following later", "week*"),
        ("fade* decay* wane* persist* sustain* outlook trajectory",),
        (1, "still", "be hold there"),
        ("generalis* generaliz* replicat*",),
        (2, "other another different new", "market markets"),
    ),
    "subgroup": (
        ("android ios iphone ipad mobile desktop tablet* console* laptop* phone* smartphone* "
         "handset* macos chromebook",),
        (0, "on", "windows mac pc linux"),
        ("platform* device* countr* region* segment* market markets",),
        ("demograph* geograph* locale* gender age older younger elderly acquisition organic "
         "referral*",),
        ("spender* payer* nonpayer* whale* paying freemium vip tier* loyal* lapsed dormant "
         "veteran* newcomer*",),
        (0, "free", "to", "play"),
        (0, "free paid", "users players customers"),
        (0, "casual hardcore core", "players users gamers customers"),
        (0, "signed", "up"),
        (0, "spend spends spending", "a", "lot"),
        (0, "who", "spend spends pay pays paid joined installed registered subscribed churned "
         "returned"),
        (0, "english french spanish german portuguese italian japanese chinese hindi arabic "
         "russian korean dutch", "speaking"),
        ("brazilian indian canadian british american mexican australian european asian african "
         "scandinavian argentine* colombian egyptian nigerian kenyan israeli irish swiss austrian "
         "belgian danish norwegian finnish",),
        (0, "by across per", "language* plan* channel* source*"),
        (0, "kind* type* sort* group*", "of", 1, "player* user* customer*"),
        ("f2p",),
        (0, "never", "pay paid spent bought purchased"),
        (0, "heavy light power", "users players customers gamers"),
        ("heterogene* subgroup* subpopulation* subsegment*",),
        (0, "swedish polish german french spanish italian japanese chinese korean russian dutch "
         "portuguese turkish thai greek hungarian czech vietnamese", PEOPLE + " audience crowd"),
        (3, "player* user* customer* people", "behave* respond* react* differ*"),
        ("playstation xbox nintendo steam",),
        (0, "in the", "us"),
        (0, "high low mid", "value valued spend spending"),
        ("teen* youth senior* student* women men male female adults",),
        ("germany japan brazil india china canada france italy spain mexico australia korea "
         "russia britain uk usa europe asia africa america netherlands sweden poland turkey "
         "indonesia thailand vietnam philippines argentina colombia egypt nigeria kenya israel "
         "ireland portugal switzerland austria belgium denmark norway finland singapore taiwan "
         "malaysia pakistan chile peru greece ukraine emea apac latam nordic* scandinavia",),
    ),
    "other_analysis": (
        (0, "what", "if"),
        (2, "what how", "would could happens happen will", 6, "if"),
        (0, "as", "if though", 4, "allocation split sample arm* data players traffic ratio"),
        ("recomput* recalculat* reanalys* reanalyz* reestimat* refit counterfactual*",),
        (5, "rerun* redo repeat* rebuild* rework* recreat*",
         "analys* comparison* calculation* model* estimate* numbers interval* stats"),
        (2, "run running rerun redo", "again", 1, "but excluding without only using"),
        (0, "using use with", "only"),
        (0, "only", "count counts counted counting consider* keep*"),
        (1, "day* week* month*", "only alone"),
        (3, "using use with", AVERAGES + " mean"),
        ("winsor* trim* bootstrap* wilcoxon bonferroni ttest anova ancova cuped regress* "
         "bayes* covariate* permutation* mann whitney kruskal welch* fisher* "
         "parametric* nonparametric* holm benjamini fdr transform* sensitivity robustness "
         "placebo clustered stratif*",),
        (0, "t z chi", "test squared square"),
        (0, "one two", "sided"),
        (0, "difference", "in", "differences"),
        (2, "only", "players users customers"),
        (0, "confidence significance", "level"),
        (0, "as", "the", "metric outcome kpi"),
        (1, "80 90 95 99", "level"),
        (0, "separately", "for by per each"),
        (0, "per each", "day week hour"),
        (2, "cap capped capping", "revenue spend values value purchases at"),
        (4, "numbers results estimate* interval* lift effect conclusion* verdict p", 4,
         "change changes differ differs look be", 6, "if"),
        (2, "outlier* extreme*", "removed excluded dropped omitted filtered discarded"),
        (5, "compute calculat* determine", "sample power"),
        (0, "power", "analysis analyses calculation*"),
        (5, "apply applying add try switch",
         "correction* adjustment* filter* exclusion* window* method model metric"),
        (1, "as", "window*"),
        (0, "adjust* correct* control*", "for"),
        (3, "chang* adjust* lower* raise* set at tighter looser stricter",
         "alpha threshold* percentile* quantile* confidence significance tolerance*"),
        (4, "calculat* comput*", "daily weekly hourly"),
        (4, "exclu* omit* remov* filter* drop* leav* left discard* ignor*",
         "players users days week* data rows cohort* buyers customers spenders everyone anyone "
         "everybody outlier* extreme*"),
        (2, "different another alternative other",
         "metric test method window period threshold model analysis approach definition outcome* "
         "kpi* measure* tolerance* alpha level"),
        (4, ANALYSES, "instead rather"),
        (0, "instead rather", "of than", 3, ANALYSES),
        (2, "same similar equivalent", "analysis analyses test comparison"),
        ("assuming suppose supposing imagin* hypothetical* pretend*",),
        (START, 1, "simulate"),
        (3, "run rerun try do perform use make", "simulat*"),
    ),
    "data_access": (
        (1, "player* user* account* customer*", "id identifier*"),
        (1, "which", PEOPLE),
        (0, "^ ,", "who", "are is was were", 2, PEOPLE),
        (3, "raw underlying actual individual source original",
         "data events export table* file* logs transactions orders purchases numbers values "
         "figures"),
        (3, "random sample* example* individual specific particular ten twenty", PEOPLE),
        (3, "pull fetch get give send dump extract share email hand provide attach",
         "log logs logged logging event* file* table* export transactions"),
        (2, "give send get pull fetch hand share", "data"),
        (2, "list show give print display name enumerate", "every each all those the", 1, PEOPLE),
        (0, "sample* subset* extract* copy", "of", 2, "data events players users"),
        (0, "event* transaction* log logs", "data stream* feed*"),
        (0, "table", "of", "assignment* exposure* event* player* user* purchase*"),
        (0, "!rule rules finding findings check checks", "ids"),
        ("row* download* csv record records dataset* timestamp* spreadsheet* sql parquet",),
        (0, "player user", "level"),
        (1, "export", "file* folder*"),
        (1, "exposure assignment event* outcome* purchase*", "log logs table*"),
        (0, "^ ,", "who", 3, "exposed assigned bought purchased"),
        (4, "where", "data file* export"),
        (0, "list", "of", 2, "players users accounts"),
        (2, "export", "table* data events"),
    ),
    "rewording": (
        ("plain* simpl* jargon layman* layperson eli5 tldr dumb* nontechnical understandable "
         "digestible diplomatic* politely tactful* gentl* softer kinder nicer polite tweet*",),
        (3, "say put phrase word explain write", "differently"),
        (0, "non", "technical"),
        (0, "different", "words wording terms way"),
        (2, "make keep but bit little more much give write say", LATER),
        (1, "keep make be", "it this them that", 1, "short brief concise clear quick"),
        (0, "short brief concise", "answer reply response version explanation"),
        (3, "easier clearer", "understand* read* follow* digest*"),
        (1, "tl", "dr"),
        (0, "like if though", "im i", 3,
         "five new beginner novice child kid dummy toddler manager executive boss"),
        (0, "no", "stats statistics technical statistical", "background knowledge training"),
        (0, "sound sounds", "more less like"),
        (0, "read", "like"),
        ("shorten* condens* abridg* wordy verbose lengthy terse",),
        (0, "in", "half"),
        (0, "executive", "summary"),
        ("analog* metaphor* everyday",),
        (1, "in", "seconds minutes minute"),
        (1, "fewer less", "technical terms words"),
        (0, "without", 2, "technical statistical statistics stats math",
         "terms words language speak lingo"),
        ("rephras* reword* rewrit* paraphras* restat* translat* tone casual* friendl* formal*",),
        ("poem* haiku* limerick* pirate* rhym* funny humor* humour* sarcastic*",),
        ("bullet*",),
        (2, "for", "boss manager director executive* ceo stakeholder* audience kids colleague* "
                   "partner* client* investor* board standup team"),
        (4, "in", "sentence* paragraph* words"),
        (1, "one a single two three four five", "sentence* line lines paragraph* word*"),
        (0, "in", "english spanish french german portuguese italian japanese chinese hindi "
                  "arabic russian korean dutch language*"),
        (0, "year", "old"),
        ("grandma grandmother granny",),
        (START, 1, LATER),
        (2, "to",
         "child* kid* beginner* novice* newbie* dummies dummy toddler*"),
        (0, "someone somebody anyone", "who", 3,
         "never doesnt dont hasnt isnt knows new unfamiliar without"),
        (1, "as in like", "table email slide* json csv markdown spreadsheet pdf"),
        (1, "as", "list"),
        (5, "put turn convert reformat format", "email slide* table list json pdf numbered"),
        (5, "draft* compos* write wrote", "email* memo* slack message*"),
    ),
}

# The intents. `checked` is tried first, then `next_steps`; a question that names a rule is an
# explanation; `summary` is the last. The words of `explain_finding` decide only whether a refusal
# keeps an explanation as its answerable part: a rule named is an explanation anyway.
INTENT_PATTERNS: dict[str, tuple[Pattern, ...]] = {
    "checked": (
        (3, "which what how list show name tell give", "check* rule* tests analys*",
         "ran made perform* execut* conduct* cover* includ* appl* do did done missing use used "
         "uses passed produc* yield* "
         "failed skip fired came come found raised flagged nothing something evaluat* "
         "assess* examin* compar*"),
        (0, "not", "yet", "built"),
        (0, "not", "built"),
        (0, "there", 1, "a an any", "check* rule* test*"),
        (3, "which what", "rule* check*", 4, "go went", 0, "through"),
        (4, "check* rule* tests analys* guardrail*", "did do does are", 4, "run ran"),
        (3, "which what", "test", "ran run made perform* execut* conduct*"),
        (CLAUSE, "did does has have", 3, SUBJECT,
         "check* cover* verif* examin* inspect* assess* includ* evaluat* consider* compar*"),
        (CLAUSE, "did does has have", 3, SUBJECT, 1, "test tested testing"),
        (CLAUSE, "did does has have", 3, SUBJECT, 2, "look looked looking", 0,
         "at into for over"),
        (CLAUSE, "did does has have", 3, SUBJECT, 1, "run ran", 3,
         "rule* analys* guardrail* everything all"),
        ("if whether", 3, SUBJECT,
         "check* cover* verif* examin* inspect* assess* includ* evaluat* consider* compar*"),
        ("if whether", 3, SUBJECT, 1, "test tested testing"),
        ("skipped unchecked untested unevaluated",),
        (2, "what", "checked tested covered examined looked evaluated assessed"),
        (3, "what which", "skip omitted missed left"),
        ("which what", 2, "area* aspect* part* thing* kind* type*", 4, CHECKING),
        (0, "anything something", 4, "didnt hasnt wasnt not never", 2, CHECKING),
        (4, "what which", "look looked", 0, "at into"),
        (8, "was were",
         "checked tested covered examined verified included run ran applied performed done "
         "evaluated assessed considered left omitted missed excluded"),
        (2, "have has", "been", 1,
         "checked tested covered examined verified evaluated assessed performed run"),
        (5, "check* rule* analys* guardrail*", "ran performed executed conducted"),
        (3, "wasnt werent not never didnt", "evaluat* checked tested covered assessed performed"),
        (2, "wasnt werent", "run ran done"),
        (3, "part", "check* rule* analys* review"),
    ),
    "next_steps": (
        ("fix* repair* remediat* resolv* address* steps tackle* prioriti* unblock*",),
        (0, "what which", "order"),
        (0, "next", "step"),
        (0, "next", "time run attempt iteration"),
        (0, "have has", "us me we", "change do"),
        (0, "what", "would will", "it", "take"),
        (3, "should must need needs shall", "do deal handle start begin"),
        (1, "should must need needs shall", "change"),
        (0, "plan", "to for"),
        (0, "where", "do can", "we i", "start begin"),
        (0, "how", "should would do", "we i", "proceed"),
        (0, "required needed necessary", "before"),
        (2, "what how", "would could can shall will should must", 3, "do doing"),
        (0, "what", "do", "i we you"),
        (0, "need*", "to", "happen"),
        (0, "tell tells", "us me", "to"),
        (3, "must needs need has should", "be", 0, "done changed corrected"),
        (0, "how", "can could do should would", 1, "we i", 3,
         "clear* get make avoid* prevent* deal handle* improve* solve*"),
        (0, "what", "to", "do"),
        (0, "what", "now next"),
        ("advis* advice recommend* suggest* actions",),
        ("rerun* retest*",),
        (2, "run running", "again"),
        (3, "before", "run running repeat* again"),
        (0, "what", "comes", "after next first"),
        (6, "how", "get make", 4, "pass clear green valid"),
    ),
    "explain_finding": (
        ("why explain* mean means meaning matter matters",),
    ),
    "summary": (
        ("finding* block* warning* overview summar* overall verdict* picture sever* serious* "
         "problem* issue* wrong rundown gist takeaway* highlight* headline* recap concern* risk* "
         "critical* urgent*",),
        (3, "review* report* experiment*",
         "find found say says show shows contain contains conclude concluded flagged raised noted "
         "report reports reported identified raise raises rate rates rating decide decided flag "
         "flags decision mention mentions note notes judge judged look looks give gives think "
         "thinks"),
        (0, "what", "was were", "found raised flagged identified noted"),
        (4, "where", "stand stands standing"),
        (0, "came come comes", "out", 3, "review report experiment"),
        (0, "brief", "me us"),
        (5, "tell give", "review report experiment"),
        (3, "key main top biggest worst", "result* point*"),
        (3, "explain* describe* interpret* walk* go",
         "review* report* experiment* result*"),
        (4, "state status condition health", "experiment review report test"),
        (0, "according", "to", 1, "review report"),
        (0, "red", "flag*"),
        (0, "stand stands stood", "out"),
        (3, "anything something", "know noting notable important worrying"),
        (0, "should must", "i we", "know aware"),
        (0, "aware", "of"),
        (0, "why", "is are does do", 3, "important matter matters"),
        (3, "check* rule* test* analys*", "reveal* show* produc* yield* come came found find*"),
        (0, "worth", "knowing noting mentioning flagging"),
        (0, "how", "bad"),
        (0, "valid", "or", "invalid"),
        (0, "bottom", "line"),
        (3, "review experiment report test", "pass* fail*"),
    ),
}

# Phrases that point at one of the nine results rules, from their titles (24.8).
PHRASES: dict[str, tuple[Pattern, ...]] = {
    "RES-001": (
        ("srm",), (0, "sample", "ratio", "!drift*"), ("allocation*",),
        ("imbalanc* unbalanc* uneven* mismatch*",), (0, "arm arms", "size sizes"),
    ),
    "RES-002": (
        (2, "fewer", "players", "than"),
        (0, "sample", "size*"),
        ("underpowered",),
        (0, "too", "few"),
        (0, "registered", "sample"),
        ("shortfall*",),
    ),
    "RES-003": (
        ("duration*",), (0, "run", "length"), (0, "too", "short"), (3, "ran", "less fewer"),
        (0, "short shorter", "run"), (0, "shorter", "than", 2, "registered planned minimum"),
    ),
    "RES-004": (("guardrail*",), ("tolerance*",)),
    "RES-007": (("cohort*",), (0, "first", "exposure")),
    "RES-008": (("skew*",), (1, "heavy", "tail tails tailed"), (0, "revenue", "like")),
    "RES-011": (("drift*",), ("weekly",), (0, "week", "by to", "week")),
    "RES-012": (
        (1, "late", "expos*"), (1, "expos*", "late"), (0, "first", "purchas*"),
        (6, "after", "bought buying purchas*"), (0, "exposed", "after"),
    ),
    "RES-013": (("config*",), (0, "changed", "during")),
}

# These patterns of a category count only when the question names no rule: "Why does RES-001
# block?" is an explanation and not `causal` (24.8).
WHEN_NO_RULE_NAMED: dict[str, tuple[Pattern, ...]] = {
    "effect_numbers": (
        (5, "what whats how give show tell report print list state provide need want get see know",
         "estimat*"),
        (0, "point", "estimat*"),
        (0, "p", "value*"),
        ("pvalue*",),
        (1, "confidence credible", "interval* bound* limit* range* band*"),
        (0, "interval*", "around for on of", 3, "difference lift effect uplift estimate*"),
        ("ci uncertainty",),
        (0, "lower upper", "and or", "upper lower"),
        (0, "error", "bar bars"),
        (0, "standard", "error deviation"),
        (4, "table", "difference* lift* effect* uplift delta*"),
    ),
    "causal": (
        (8, "why because", EFFECT_WORDS),
        (6, "why because", "behind winning leading outperform* beating lagging"),
        (6, EFFECT_WORDS, "because due"),
        ("caus* mechanism* driver* contribut*",),
        (6, "reason reasons", EFFECT_WORDS),
        (0, "coming", "from"),
        (0, "how", "come", 6, EFFECT_WORDS),
        (0, "led", "to"),
        (0, "because", "of"),
        (0, "lead leads leading", "to", 4, EFFECT_WORDS),
        (3, EFFECT_WORDS, "result resulted", "of from"),
        (0, "something", "else", 1, "happening going"),
        (0, "resulted resulting stem stems stemmed originat* aris* arose", "from"),
        (0, "how", "did does do", 6, "increas* improv* rais* boost* reduc* decreas* affect*"),
    ),
}

# These patterns of a category count only when the question does not name the rule: a question
# that names the finding on cohorts of first exposure (RES-007), by its ID or by "cohort", is an
# explanation of it, and "new and returning players" is what that finding is about (24.8). A
# country, a platform or a spender is a subgroup whatever else the question names.
UNLESS_NAMED: dict[str, dict[str, tuple[Pattern, ...]]] = {
    "subgroup": {
        "RES-007": (
            ("returning",),
            (0, "new", "players users customers"),
            (0, "first", "time", "players users buyers customers"),
        ),
    },
}

# Where a clause only says what must hold first ("fix it before we ship"), what the review did
# ("did you check whether it ran long enough") or why a rule says so ("why does RES-003 say it
# ran too short"), the words of SOFT in the rest of the clause (to a comma, `and`, `but`, `then`,
# `so` or `or`, at most STRETCH words) ask for nothing. Injection is not hushed.
QUIET: tuple[Pattern, ...] = (
    ("before until",),
    (CLAUSE, "did does do has have", 3, SUBJECT, 2, CHECKING),
    (CLAUSE, "which what", 2, "check* rule* test* analys*", 2, CHECKING),
    (CLAUSE, "why", 3, "#"),
)
SOFT = "ship* launch* releas* deploy* call* stop* trust* safe real enough"
STRETCH = 8
STRETCH_ENDS = ", and but then so or $"
# fmt: on

# --- Matching --------------------------------------------------------------------------------

Step = tuple[int, frozenset[str], tuple[str, ...], bool]


def compile_pattern(pattern: Pattern) -> tuple[Step, ...]:
    """A pattern as steps `(words allowed between this step and the last, words, prefixes, not)`;
    a step that begins with `!` is any word but those listed."""
    steps = []
    gap = 0
    for item in pattern:
        if isinstance(item, int):
            gap = item
        else:
            words = item.removeprefix("!").split()
            steps.append(
                (
                    gap,
                    frozenset(word for word in words if not word.endswith("*")),
                    tuple(word[:-1] for word in words if word.endswith("*")),
                    item.startswith("!"),
                )
            )
    return tuple(steps)


def _compile(table: dict[str, tuple[Pattern, ...]]) -> dict[str, tuple[tuple[Step, ...], ...]]:
    return {name: tuple(compile_pattern(pattern) for pattern in table[name]) for name in table}


_TRIGGERS = _compile(TRIGGERS)
_INTENT_PATTERNS = _compile(INTENT_PATTERNS)
_PHRASES = _compile(PHRASES)
_WHEN_NO_RULE_NAMED = _compile(WHEN_NO_RULE_NAMED)
_UNLESS_NAMED = {category: _compile(rules) for category, rules in UNLESS_NAMED.items()}
_QUIET = tuple(compile_pattern(pattern) for pattern in QUIET)
_SOFT = compile_pattern((SOFT,))[0]
_STRETCH_ENDS = compile_pattern((STRETCH_ENDS,))[0]


def _at(word: str, step: Step) -> bool:
    return (word in step[1] or (bool(step[2]) and word.startswith(step[2]))) != step[3]


def ends(words: list[str], steps: tuple[Step, ...]) -> list[bool]:
    """Where the steps follow one another in `words`, each within its gap of the last. One pass
    over the words for each step: `live[i]` says that the steps so far end at word `i`."""
    live = [_at(word, steps[0]) for word in words]
    for step in steps[1:]:
        live = [
            _at(word, step) and any(live[max(0, i - step[0] - 1) : i])
            for i, word in enumerate(words)
        ]
    return live


def matches(words: list[str], steps: tuple[Step, ...]) -> bool:
    return any(ends(words, steps))


def _any(words: list[str], patterns: tuple[tuple[Step, ...], ...]) -> bool:
    return any(matches(words, steps) for steps in patterns)


# --- Normalising and reading -----------------------------------------------------------------


def normalise(question: str) -> str:
    """NFKC of the case-folded NFKC text; U+0020, tab, line feed, carriage return and the
    categories Zs, Zl and Zp are one space, and a run of spaces is one. Another control
    character stays (it is category C)."""
    text = unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", question).casefold())
    spaced = "".join(
        " " if c in "\t\n\r" or unicodedata.category(c) in ("Zs", "Zl", "Zp") else c for c in text
    )
    return " ".join(part for part in spaced.split(" ") if part)


def fold(text: str) -> str:
    """The text with its diacritics folded: NFD, then the marks of category Mn dropped. NFKC has
    composed a letter and a mark into one letter (`shíp`); this gives the plain letter back. The
    result is matched, never shown, so it is not composed again."""
    return "".join(
        char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn"
    )


def _mixes_scripts(text: str) -> bool:
    scripts: set[str] = set()
    for char in text + " ":
        if char in "'’":  # `read` removes it and joins the letters on either side
            continue
        if char.isalpha():
            scripts.add(unicodedata.name(char, "?").split(" ", 1)[0])
        else:
            if "LATIN" in scripts and scripts & LOOKALIKES:
                return True
            scripts = set()
    return False


def unreadable(text: str) -> str | None:
    """The reason (one of `render.UNREADABLE_REASONS`) that a normalised question cannot be
    read, or None."""
    if not text:
        return "empty"
    if len(text) > MAX_CHARS:
        return "too long"
    if not any(char.isalpha() for char in text):
        return "no letter"
    if any(unicodedata.category(char)[0] in "CM" or char in INVISIBLE for char in text):
        return "invisible or mark character"
    if _mixes_scripts(text):
        return "mixed scripts"
    return None


def _is_id_gap(between: str, family: str) -> bool:
    """Whether `between` can separate the letters and the digits of a rule ID."""
    dash = between.replace(" ", "")
    if dash == "":
        return between == " " and family in RULE_FAMILIES
    return len(dash) == 1 and (dash == "_" or unicodedata.category(dash) == "Pd")


def _is_letters(word: str) -> bool:
    return len(word) == 3 and all("a" <= c <= "z" for c in word)


def _is_digits(word: str) -> bool:
    return len(word) == 3 and all("0" <= c <= "9" for c in word)


def read(text: str) -> tuple[list[str], list[str]]:
    """The words of a normalised, readable question and the rule IDs in it (canonical, shaped
    like `RES-004`, in order). An ID is one word, `#`, among the others."""
    pieces: list[tuple[str, int, int]] = []  # (word or ",", start, end)
    word: list[str] = []
    start = 0
    for i, char in enumerate(text + " "):
        if char in "'’":  # joins its neighbours
            continue
        if char.isalnum():
            start = start if word else i
            word.append(char)
            continue
        if word:
            pieces.append(("".join(word), start, i))
            word = []
        in_number = char == "." and 0 < i < len(text) - 1 and text[i - 1 : i + 2 : 2].isalnum()
        if char in ",;:!?" or (char == "." and not in_number):
            pieces.append((",", i, i + 1))
    for k in range(len(pieces) - 2, -1, -1):  # re-run, re-analyze: one word
        word_k, _, end = pieces[k]
        following = pieces[k + 1]
        if word_k == "re" and following[0] != "," and text[end : following[1]] == "-":
            pieces[k : k + 2] = [("re" + following[0], pieces[k][1], following[2])]
    words = ["^"]
    ids: list[str] = []
    k = 0
    while k < len(pieces):
        word_k, _, end = pieces[k]
        following = pieces[k + 1] if k + 1 < len(pieces) else None
        if len(word_k) == 6 and _is_letters(word_k[:3]) and _is_digits(word_k[3:]):
            ids.append(f"{word_k[:3]}-{word_k[3:]}".upper())
            words.append("#")
        elif (
            following is not None
            and _is_letters(word_k)
            and _is_digits(following[0])
            and _is_id_gap(text[end : following[1]], word_k)
        ):
            ids.append(f"{word_k}-{following[0]}".upper())
            words.append("#")
            k += 1
        else:
            words.append(word_k)
        k += 1
    return [*words, "$"], ids


def _targets(words: list[str], ids: list[str]) -> set[str]:
    """The rules the question names: IDs (of the nine or not) and phrases."""
    named = set(ids)
    named.update(rule for rule, patterns in _PHRASES.items() if _any(words, patterns))
    return named


def hush(words: list[str]) -> list[str]:
    """The words with those of SOFT replaced by `_` where they only describe (`QUIET`)."""
    hushed = list(words)
    for steps in _QUIET:
        for i, opened in enumerate(ends(words, steps)):
            for j in range(i + 1, min(i + 1 + STRETCH, len(words))):
                if opened and _at(words[j], _STRETCH_ENDS):
                    break
                if opened and _at(words[j], _SOFT):
                    hushed[j] = "_"
    return hushed


def _categories(all_words: list[str], named: set[str]) -> tuple[str, ...]:
    found = []
    hushed = hush(all_words)
    for category in CATEGORIES:
        words = all_words if category == "injection" else hushed
        patterns = _TRIGGERS[category]
        if not named:
            patterns += _WHEN_NO_RULE_NAMED.get(category, ())
        for rule, extra in _UNLESS_NAMED.get(category, {}).items():
            if rule not in named:
                patterns += extra
        if _any(words, patterns):
            found.append(category)
    return tuple(found)


def _intent(words: list[str], named: set[str]) -> tuple[str, str | None, bool] | None:
    """(intent, target, as_summary) of the answerable part of a question, or None."""
    for intent in ("checked", "next_steps"):
        if _any(words, _INTENT_PATTERNS[intent]):
            return intent, None, False
    if named:
        if len(named) > 1:
            return "explain_finding", None, True
        (only,) = named
        return "explain_finding", only if only in RULE_IDS else None, False
    if _any(words, _INTENT_PATTERNS["summary"]):
        return "summary", None, False
    return None


def route(question: str) -> Understanding:
    """What the page answers for `question`: an answer, a refusal (with the categories matched,
    none for the default route) or an unreadable question. Never raises for a `str`."""
    text = normalise(question)
    reason = unreadable(text)
    if reason is not None:
        return Understanding("unreadable", reason=reason)
    words, ids = read(fold(text))
    named = _targets(words, ids)
    categories = _categories(words, named)
    intent = _intent(words, named)
    if categories:
        # a refusal keeps the intent of an answerable part, but a rule named is an explanation
        # of a finding only where the question asks why, what it means or that it matters
        asked = intent is not None and (
            intent[0] != "explain_finding" or _any(words, _INTENT_PATTERNS["explain_finding"])
        )
        only = next(iter(named)) if len(named) == 1 else None
        return Understanding(
            "refusal",
            intent=intent[0] if intent and asked else None,
            target=only if only in RULE_IDS else None,
            categories=categories,
        )
    if intent is None:
        return Understanding("refusal")
    return Understanding("answer", intent[0], target=intent[1], as_summary=intent[2])

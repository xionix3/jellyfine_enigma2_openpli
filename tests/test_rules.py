import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "e2stubs"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from mockjf import start_server
from JellyfinOpenPLi.jfapi import JellyfinClient
from JellyfinOpenPLi.jfrules import run_rule, TEMPLATE, DEFAULT_RULES, load_rules, dump_rules, rule_summary
srv, st, url = start_server("10.10.3")
cl = JellyfinClient(url, "dev", "test")
cl.public_info(); cl.authenticate("demo", "geheim")
fails = 0
def check(c, m):
    global fails
    print(("ok  : " if c else "FAIL: ") + m); fails += 0 if c else 1
r = dict(TEMPLATE, type="Movie,Series", date_field="released", days="365", unplayed=False, sort="new")
items = run_rule(cl, r)
check([i["Id"] for i in items][:3] == ["m1", "m2", "m3"], "released mixed newest: %s" % [i["Id"] for i in items][:4])
# movies premiere every 20 days (m18 = 360 days ago), both shows premiered years ago -> 18 hits
check(all(i["Type"] in ("Movie", "Series") for i in items) and len(items) == 18, "released within 1y: %d" % len(items))
r = dict(TEMPLATE, type="Movie", days="0", unplayed=False, sort="rating", min_rating="9", limit="50")
items = run_rule(cl, r)
check(items and all(i["CommunityRating"] >= 9 for i in items) and items[0]["CommunityRating"] >= items[-1]["CommunityRating"], "min rating 9 + rating sort (%d)" % len(items))
r = dict(TEMPLATE, type="Series", days="7", sort="new")
items = run_rule(cl, r)
check([i["Id"] for i in items] == ["s1", "s2"] or [i["Id"] for i in items] == ["s2", "s1"], "series with new episodes: %s" % [i["Id"] for i in items])
r = dict(TEMPLATE, type="Movie", days="0", sort="old", unplayed=False, limit="5")
check([i["Id"] for i in run_rule(cl, r)] == ["m40", "m39", "m38", "m37", "m36"], "oldest first")
r = dict(TEMPLATE, type="Episode", days="30", my_series=False, group=False)
check([i["Id"] for i in run_rule(cl, r)] == ["e23", "e211", "e22", "e21"], "all new episodes ungrouped: %s" % [i["Id"] for i in run_rule(cl, r)])
r = dict(TEMPLATE, type="Movie", days="0", sort="random", limit="10")
check(len(run_rule(cl, r)) == 10, "random 10")
check(load_rules("") == DEFAULT_RULES and load_rules("kaputt") == DEFAULT_RULES, "defaults on empty/broken config")
check(load_rules(dump_rules(DEFAULT_RULES)) == DEFAULT_RULES, "roundtrip")
print(rule_summary(DEFAULT_RULES[1]))
# secrets never reach the log
from JellyfinOpenPLi.jflog import redact
check(redact("m.m3u8?DeviceId=d&ApiKey=abc123") == "m.m3u8?DeviceId=d&ApiKey=***" and redact('Token="abc"') == 'Token="***"'
    and redact("x?api_key=abc&static=true") == "x?api_key=***&static=true" and redact('"Pw": "geheim"') == '"Pw": "***"', "redaction")
from JellyfinOpenPLi.jfapi import JellyfinError
check("abc123" not in str(JellyfinError("Nicht gefunden (404): /x?api_key=abc123")), "error messages redacted")
# search ranking: exact/prefix title matches first, fuzzy server results last (the "bluey" report)
from JellyfinOpenPLi.jfutil import rank_search, norm_text
fuzzy = [{"Id": "1", "Name": "Blue Planet", "Type": "Movie"}, {"Id": "2", "Name": "Die wilden Kerle", "Type": "Movie"},
    {"Id": "3", "Name": "Bluey - Die Folge", "Type": "Episode"}, {"Id": "4", "Name": "Bluey", "Type": "Series"},
    {"Id": "5", "Name": "Mein Freund Bluey", "Type": "Movie"}, {"Id": "6", "Name": "BLUEY: Der Film", "Type": "Movie"},
    {"Id": "7", "Name": "Big Blue", "Type": "Movie", "OriginalTitle": "Le Grand Bleu"}]
ranked = [i["Id"] for i in rank_search("bluey", fuzzy)]
check(ranked == ["4", "6", "3", "5", "1", "2", "7"], "bluey ranking %s" % ranked)
check(norm_text("Amélie: Die fabelhafte Welt!") == "amelie die fabelhafte welt" and [i["Id"] for i in rank_search("amelie", [{"Id": "a", "Name": "x"}, {"Id": "b", "Name": "Amélie"}])] == ["b", "a"],
    "accents ignored")
# picture downloads: what is on screen first (newest first), prefetch after it and at most 1-2 at a time
from JellyfinOpenPLi.jfasync import PriorityStack, _Task
pq = PriorityStack(background_limit=1)
_mk = lambda name, urgent: _Task(name, (), {}, None, None, None, urgent)  # noqa: E731
b1, b2, u1, u2 = _mk("b1", False), _mk("b2", False), _mk("u1", True), _mk("u2", True)
for _t in (b1, b2, u1, u2):
    pq.put(_t)
check([pq.get().fn for _i in range(3)] == ["u2", "u1", "b1"], "visible pictures before prefetch")
check(pq.background_running == 1 and pq.promote(b2) and pq.get() is b2 and b2.urgent, "prefetch that became visible jumps the limit")
pq.finished(b1)
check(pq.background_running == 0 and not pq.promote(b1), "prefetch slot released")

# translations: .po reader (continuation lines, escapes, plurals, fuzzy entries), language choice
from JellyfinOpenPLi import jfi18n
po = """msgid ""
msgstr "Language: en\\n"

#: x.py:1
msgid "Filme"
msgstr "Movies"

msgid ""
"Zeile 1\\n"
"Zeile 2 \\"x\\""
msgstr "Line 1\\nLine 2 \\"x\\""

#, fuzzy
msgid "Ungeprüft"
msgstr "Unchecked"

msgid "%d Staffel"
msgid_plural "%d Staffeln"
msgstr[0] "%d season"
msgstr[1] "%d seasons"
"""
cat = jfi18n.parse_po(po)
check(cat == {"Filme": "Movies", 'Zeile 1\nZeile 2 "x"': 'Line 1\nLine 2 "x"', "%d Staffel": ["%d season", "%d seasons"]}, "po reader %r" % cat)
for lang in ("en", "nl"):
    check(len(jfi18n.load_catalog(lang)) > 400, "%s catalog loaded" % lang)
check(jfi18n.resolve("en") == "en" and jfi18n.resolve("auto") == "de", "explicit language / auto without Enigma2 language")
_sys = jfi18n.system_language
for code, want in (("nl", "nl"), ("de", "de"), ("en", "en"), ("it", "en"), ("", "de")):
    jfi18n.system_language = lambda c=code: c
    check(jfi18n.resolve("auto") == want, "auto with box language %r -> %s" % (code, want))
jfi18n.system_language = _sys
jfi18n.set_language("en")
check(jfi18n._("Filme") == "Movies" and jfi18n.ngettext("%d Staffel", "%d Staffeln", 1) % 1 == "1 season"
    and jfi18n.ngettext("%d Staffel", "%d Staffeln", 3) % 3 == "3 seasons" and jfi18n._("unbekannter Text") == "unbekannter Text"
    and jfi18n.decimal("7.5") == "7.5" and jfi18n.badge("new") == ("badge_new_en.png", 64), "English active")
check(rule_summary(DEFAULT_RULES[0]).startswith("Movies  |  new: 30 days"), "rule summary in English: %s" % rule_summary(DEFAULT_RULES[0]))
jfi18n.set_language("de")
check(jfi18n._("Filme") == "Filme" and jfi18n.ngettext("%d Staffel", "%d Staffeln", 2) % 2 == "2 Staffeln" and jfi18n.decimal("7.5") == "7,5"
    and jfi18n.badge("seen") == ("badge_seen.png", 104), "German is the source language")
print("failures", fails); srv.shutdown(); os._exit(1 if fails else 0)

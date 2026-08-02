# The game's own translations, all nineteen of them

The client ships every language it supports as a table on disk, next to the install. So
when the panel needs to call something what the game calls it — «Versammlung», not the
dictionary's «Sammelangriff» — the answer is a file, not a guess.

Found while translating the panel into German (#1201).

## Where

```
<install>/Game/LastWar_Data/StreamingAssets/locale/
    version              one line: <build>,pl,ja,en,ru,fr,tr,ar,vi,vr,th,gn_CN,ko,es,zh_CN,id,pt,it,de,zh_TW
    <build>/             one <lang>.bin per language, ~1.3–1.8 MB each
```

`<install>` is where the launcher put the game — the panel already knows it, as the
`launcher` setting of the active profile, minus `LastWarLauncher.exe`.

Nineteen languages are on disk whatever the account plays in: nothing has to be
downloaded, the game does not have to be running, and the account's own language does
not matter.

## The format

Gzip (`1f 8b`), and inside it a plain C# `BinaryWriter` dump: a 4-byte header, then
string pairs — key, value, key, value — each string prefixed with its byte length as a
7-bit-encoded int (`BinaryWriter.Write(string)`). No encryption, no index, no protobuf.
About 52 000 pairs per language.

```python
import gzip

def read7(b, i):                       # BinaryWriter's 7-bit encoded length
    n = s = 0
    while True:
        c = b[i]; i += 1
        n |= (c & 0x7f) << s
        if not c & 0x80:
            return n, i
        s += 7

def load(path):                        # {key: text}
    b, out = gzip.decompress(open(path, "rb").read()), {}
    i = 4
    while i < len(b):
        ln, i = read7(b, i); k = b[i:i + ln].decode("utf-8"); i += ln
        ln, i = read7(b, i); v = b[i:i + ln].decode("utf-8"); i += ln
        out[k] = v
    return out
```

Keys are mostly numeric strings (`"135120"`), some named (`"ghostrecon_activityname"`,
`"resource_name002"`), and they are THE SAME in every language — which is what makes the
files useful: load `en.bin` to find the key by the English wording, then read that key
out of `de.bin`.

## What it settled

The German the panel uses now is the game's own, not a translation of the English. The
ones that differ from what a dictionary would give:

| the panel means | the game says | (not) |
|---|---|---|
| rally | **Versammlung** — «Versammlung starten», «Versammlung…» | Sammelangriff |
| squad | **Truppe** — «Erste Truppe» | Trupp |
| secret task | **Geheime Mission** | Geheimauftrag |
| Ghost Ops | **Geistereinsatz** | Operation Geist |
| Doom Elite | **Elite der Verdammten** | Tödliche Elite |
| power | **Kampfkraft** | Macht |
| metal | **Eisen** | Metall |
| hospital · wounded | **Lazarett** · **Verwundete** | — |
| hidden treasures | **Verborgene Schätze** | — |
| a numeric level | **Level** («Lv.{0}», «Helden-Level») | Stufe, which the game keeps for tiers |
| Secretary of the Interior | **Innenminister** | — |
| drone components · gears | **Drohnenkomponenten** · **Zahnräder** | Drohnenbauteile |
| hero XP | **XP** («Helden-XP») | EP |

One term the tables do not have: the **VS Duel** event (the `vs_duel` tab). The tables
know «Allianzduell» and «Champ-Duell», neither of which is it, so `tab.vs_duel` is
«VS-Duell» by meaning — worth correcting from a German client the day one is at hand.

## What it is also good for

* A fourth panel language: the same trick gives the game's own wording for any of the
  nineteen without asking a speaker.
* Naming things the wire only numbers — item ids, building ids, event names — in a
  language a person reads, when a research note needs it.

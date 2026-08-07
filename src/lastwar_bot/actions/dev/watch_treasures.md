# Start keeping every treasure message the client sees, until somebody reads them.
# ru: Начать запоминать все сообщения игры про сокровища — до тех пор, пока их не прочтут.
#
# A DEV RECIPE, and it is in actions/dev/ for what it does rather than for being
# unfinished: it wraps two of the client's own functions. Nothing is sent to the server
# and nothing in the game changes — but a client with the hook on is a client somebody
# has modified, and that belongs behind «Разработка» with the sniffers.
#
# WHY IT EXISTS. A world-map treasure is out for minutes and the alliance digs it
# together; by the time anybody has started a sniffer the chest is gone. So the messages
# have to be caught by something that was ALREADY listening, and kept until a person
# gets round to looking. This is that: a hook on `SFSNetwork.SendMessage` and
# `SFSNetwork.HandleMessage` writing into a ring buffer in the game VM.
#
# THE BUFFER LIVES IN THE GAME, not in the panel. The panel is restarted, switched
# between profiles, minimised and closed; the client is not. A buffer on the panel's
# side would lose exactly the messages that arrive while nobody is looking, which is
# every message worth having.
#
# WHAT IS KEPT, with `wide` off — the three moments of the ability, and nothing else:
#   * the chest      — any command carrying `treasure` or `detect`
#                      (`world.treasure.share.chat`, `push.detect.event.info`, …)
#   * the squad      — a `world.march.*` SEND at MarchTargetType 50 (same server) or
#                      182 (cross-server), which is a march that is digging a treasure
#   * the reward     — `detect.event.claim.treasure` going out and its reply coming
#                      back, and the alliance broadcast `push.detect.treasure.claim`
# With `wide` on, every message the client sends or handles is kept — for the session
# where the question is «что я пропустил» rather than «что с сокровищем».
#
# NOT AT THE SAME TIME AS THE SNIFFER'S TRACER. `lua_trace` wraps ~6500 of the client's
# functions including these two, and each would unwrap the other on the way out. Record
# with one of them, never both.
#
# Read what it caught with read_treasure_watch.md; stop it with unwatch_treasures.md.
# Who plays all three: the «Сокровища» debug page (`panel/tabs/treasure_debug/`). The
# protocol they are watching is docs/research/world-treasures.md.

# Keep everything, not just the treasure messages? The recipe parks the answer because
# `TAP` takes no arguments — the same hand-off steal_secret_task.md uses for its queue.
ARGS wide = false

LUA DataCenter.__lw_treasure_watch_wide = {wide}

# Hook the two doors (or re-arm with the new `wide` — pressing again never wraps a
# wrapper) and keep whatever is already in the ring.
TAP treasure_watch_on

# Say what is listening now. The caller reads this back rather than trusting the press:
# a client that was restarted since the last press has an empty VM and no hook at all.
READ_LUA (function() local W = DataCenter.__lw_treasure_watch if not W then return 'on=0 wide=0 buf=0 seq=0 drop=0 cap=0' end return 'on=' .. tostring(W.on and 1 or 0) .. ' wide=' .. tostring(W.wide and 1 or 0) .. ' buf=' .. tostring(#(W.items or {})) .. ' seq=' .. tostring(W.seq or 0) .. ' drop=' .. tostring(W.drop or 0) .. ' cap=' .. tostring(W.cap or 0) end)() INTO watch

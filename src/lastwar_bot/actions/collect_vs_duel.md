# Write down the alliance duel: both sides, every day, every field.
# ru: Записать дуэль альянсов: обе стороны, все дни, все поля.
#
# A READ, and nothing else: it presses nothing, opens nothing, spends nothing. The one
# message it sends is the ranking request the duel screen sends when a person opens it.
#
# The duel («VS») is a week between two alliances on two servers, and the questions
# people ask of it are always about a DAY and about the OTHER SIDE — «did we lose
# Thursday, and by how much», «who on their side is carrying it». A weekly total answers
# neither. Both are in the client already:
#
#   * one `al.battle.rank.info` request with `type = 0` comes back with EVERY DAY of the
#     week at once, each row stamped with its own day, and with the players of BOTH
#     alliances in the one list (`aid` / `abbr` / `serverId` say which side a row is on);
#   * the two alliances' own per-day scores sit beside it in the duel's score info, so
#     the enemy's daily totals arrive with ours in the same read.
#
# Which side is «ours» is derived, never guessed: the duel names the OPPONENT, so the
# other of the two is the player's own alliance. When there is no opponent — a bye week —
# no row gets a side at all, because an empty column is honest and a guessed one is not.
#
# **What it cannot do is go back in time.** The server answers for the week it is in, so a
# day nobody ever asked about is a day this cannot fetch afterwards. Running it once a day
# is what makes the history whole; running it on the last day gives that day's view of the
# week, which is most of it. That is a property of the game, not of this recipe.
#
# Where it lands: the ranking history the passive collector already writes
# (`profiles/<name>/leaderboard_history.db`), under the game's own board ids, with
# `source = "game"` to say it was read out of the client rather than off the wire —
# `al.battle.rank.info/type=0` a row per player per day, `.../type=1` the standing week,
# `al.battle.vs.alliances` a row per side per day. Every row keeps the server's original
# beside the decoded columns, so a field nobody has a column for yet is still written down.
#
# `store` is the file to append to. The panel passes the profile's own; left empty, the
# duel is read and reported and nothing is written, which is what a bare console run wants.

ARGS store = ""

COLLECT_VS_DUEL STORE "{store}"
IF VS_DAYS == 0
  LOG "no day of the duel has any rows — either the week has not started or this client has not been told about it"
  STOP "nothing to write down"
LOG "the duel is written down: {VS_SIDES} side(s), {VS_DAYS} day(s), {VS_ROWS} row(s)"

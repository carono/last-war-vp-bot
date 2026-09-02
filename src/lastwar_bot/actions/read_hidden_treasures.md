# Read the hidden-treasure board: compasses so far, digs in hand, rewards still waiting.
# ru: Прочитать доску «Скрытых Сокровищ»: компасы, копки в запасе, невзятые награды.
#
# A reading and nothing else — no dig is made and no fragment is spent. The board is
# asked for first, because the tier flags («эта ступень уже взята») are the server's
# answer and go stale the moment somebody claims one in the game itself.
#
# WHAT COMES BACK, field by field:
#   open=   1 while the week is still running, 0 once it has ended
#   score=  compasses this week, goal= the week's cap (the game's own 6000)
#   digs=   how many treasures the map fragments in the bag still allow
#   tiers=  reward steps in all, taken= already collected, ready= EARNED AND WAITING
#   next=   the score the next uncollected step stands at
#   earned= the highest reward step already collected — the SERVER's own word that this
#           much was reached, and therefore a floor under a `score` that has not caught
#           up yet. `score` above is already lifted to it, so the two disagree only in
#           the direction that matters.
#   opens=/closes=/now= the week's two ends and the game's own clock, in seconds
#
# `ready` is the one that costs something to ignore: a step that has been earned and not
# collected is a reward sitting on the board, and the person who reported this had hit
# exactly that — «ты скорее всего не подтверждаешь получение кладов».
#
# THE SCORE IS THE ONE READING THAT LAGS, and it is worth knowing before trusting it: the
# compasses a dig pays do not reach the client's own count until it is restarted
# (measured live — `docs/research/hidden-treasures.md`). Everything else here moves the
# same second.
TAP ask_hidden_treasures
TAP read_hidden_treasures
READ_LUA (DataCenter.__lw_hidden_board or 'nothing has been read') INTO board
LOG "hidden treasures: {board}"

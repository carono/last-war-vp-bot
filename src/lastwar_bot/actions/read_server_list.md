# Read every warzone the game has, and keep the list.
# ru: Прочитать список всех серверов игры и сохранить его.
#
# The game opens warzones continuously — the client that this was written against knew
# of 2 558 — so the list is READ rather than shipped with the panel, and re-read whenever
# somebody wants to see the new ones. It is one question the client already asks for its
# own cross-server screen (`cross.server.ls`), and what comes back per warzone is its
# number, its name, its kind and whether the game is calling it «hot».
#
#     ARGS store = ""    where to keep it. Empty means the machine's own list —
#                        `cache/servers.json` — which is where the panel's «Серверы»
#                        window reads it from. It is the MACHINE's and not an account's:
#                        which warzones exist is the same fact for every profile.
#     ARGS dates = 0     how many warzones may additionally be asked WHEN THEY OPENED
#                        this run. 0 asks for none. Each one is a message of its own
#                        (`get.other.server.info`), so a full sweep is a few thousand —
#                        measured live at 300 answers inside three seconds, in batches,
#                        with every batch written down as it lands. A run that is
#                        interrupted therefore keeps what it had already got.
#
# Three registers come back: `SERVERS_TOTAL` (what the game says it has), `SERVERS_READ`
# (what this run brought back) and `SERVERS_DATED` (how many opening moments are on file
# afterwards, this run's and every earlier run's).
#
# Nothing here is forgotten: the list is folded into what is already on file rather than
# replacing it, because warzones only ever appear and a short read is an interrupted one.
#
# The day of the server for a single warzone — including somebody else's — is
# read_server_info.md. This is the whole list; that one is one line, instantly.

ARGS store = ""
ARGS dates = 0

COLLECT_SERVER_LIST STORE "{store}" DATES {dates}

IF SERVERS_READ == 0
    LOG "the game said nothing about its warzones — is this client in a session?"
    FAIL "server list: nothing came back"

LOG "warzones: {SERVERS_READ} read of {SERVERS_TOTAL}, {SERVERS_DATED} with an opening date"

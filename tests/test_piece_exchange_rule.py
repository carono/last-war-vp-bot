"""The piece-exchange rule, run OFFLINE against the recipe's own Lua (#1975).

WHY THIS EXISTS. «Выгодный, если у нас меньше или столько же тех, что нам предлагают» is
one comparison, and it is the whole of what the ability decides. Getting it backwards
spends the piece we are short of to buy one we already have more of — and the board only
carries an offer worth taking now and then, so waiting for a live one to check the rule
means shipping it unproven and finding out by losing pieces.

WHAT IS BEING TESTED IS THE RECIPE'S OWN TEXT, not a copy of it. The chunk is READ OUT OF
`actions/exchange_treasure_pieces.md` at run time and executed by `lupa`, with the handful
of game globals it touches replaced by a stub. So a rule edited in the recipe and not here
fails here, which is the only arrangement worth having: a second copy of the comparison
living in the test would pass whatever the recipe went on to do.

THE STUB is deliberately tiny — the bag, the board and `SFSNetwork.SendMessage` — because
everything else the chunk touches it brings itself.

No game, no client, no network: this runs anywhere `lupa` does.
"""
from __future__ import annotations

import pathlib
import sys

import lupa

ROOT = pathlib.Path(__file__).resolve().parents[1]
RECIPE = ROOT / "src" / "lastwar_bot" / "actions" / "exchange_treasure_pieces.md"

#: What the account holds in the test, per piece id. Chosen so that each of the three
#: offers below exercises a different branch, and so that no two counts are accidentally
#: equal except the pair the «equal» case is about.
HELD = {771011: 12, 771012: 19, 771013: 15, 771014: 14, 771015: 12, 771016: 13,
        771017: 18}

#: The three offers, from OUR side: `needFragment` is what we would hand over and
#: `costFragment` is what we would get (`docs/research/treasure-piece-exchange.md` §3).
#:
#:   1  give 771012 (19)  get 771011 (12)  ->  12 <= 19, worth taking
#:   2  give 771011 (12)  get 771014 (14)  ->  14 >  12, refused: we hold more of it
#:   3  give 771015 (12)  get 771011 (12)  ->  equal: taken at strict=0, refused at 1
OFFERS = ((1, 771012, 771011), (2, 771011, 771014), (3, 771015, 771011))

_STUB = """
local sent = {}
SFSNetwork = {SendMessage = function(cmd, param) sent[#sent+1] = tostring(cmd) end}
MsgDefines = {DispatchTreasureALExchange = 'hero.dispatch.fragment.exchange'}
DataCenter = {
  SplinterExchangeManager = {
    exchangeInfoList = {[4] = {fragGoodsIdList = {%(ids)s}, alDataList = {%(offers)s}}},
    GetSelfExchangeData = function(self, kind) return {ownerId = 'ME', uuid = -1} end,
    GetAlExchangeDataList = function(self, kind)
      return self.exchangeInfoList[kind].alDataList end},
  ItemData = {ItemInfos = {%(bag)s}}}
return function() return sent end
"""


def _stub(runtime):
    """Plant the bag and the board, and hand back a reader for what was SENT."""
    ids = ", ".join(str(i) for i in sorted(HELD))
    bag = ", ".join("{itemId = %d, count = %d}" % (i, HELD[i]) for i in sorted(HELD))
    offers = ", ".join(
        "{uuid = %d, ownerId = 'P%d', name = 'Player%d', type = 4, "
        "needFragment = %d, costFragment = %d}" % (u, u, u, give, get)
        for u, give, get in OFFERS)
    return runtime.execute(_STUB % {"ids": ids, "bag": bag, "offers": offers})


def _chunk() -> str:
    """The verdict step, lifted verbatim out of the recipe."""
    for line in RECIPE.read_text(encoding="utf-8").splitlines():
        if line.startswith("READ_LUA ") and line.endswith(" INTO report"):
            return line[len("READ_LUA "):-len(" INTO report")]
    raise AssertionError("the recipe has no verdict step ending « INTO report»")


def run(strict: int, accept: int):
    """Play the recipe's own chunk with those two ARGS; return its line and the sends."""
    runtime = lupa.LuaRuntime(unpack_returned_tuples=True)
    sent = _stub(runtime)
    body = (_chunk().replace("{kind}", "4").replace("{strict}", str(strict))
            .replace("{limit}", "9").replace("{accept}", str(accept)))
    return runtime.eval(body), list(sent().values())


def test_an_offer_paying_a_piece_we_hold_fewer_of_is_taken():
    report, sends = run(strict=0, accept=1)
    assert "took=1" in report, report
    assert sends == ["hero.dispatch.fragment.exchange"], sends


def test_an_offer_paying_a_piece_we_hold_more_of_is_refused():
    report, _ = run(strict=0, accept=0)
    # Offer 2 asks for 771011 (12 held) and pays 771014 (14 held): we already have more
    # of what it gives us, so it is named and passed over.
    assert "771014:we-hold-more-of-it(14>12)" in report, report


def test_an_even_swap_is_taken_by_default():
    report, _ = run(strict=0, accept=0)
    # Offer 3 is 12 for 12. At the operator's default it is not refused, so the only
    # thing standing between it and a trade is `accept = 0` itself.
    assert report.count("reading-only") == 2, report
    assert "771011:we-hold-more-of-it(12=12)" not in report, report


def test_strict_refuses_an_even_swap():
    report, _ = run(strict=1, accept=0)
    assert "771011:we-hold-more-of-it(12=12)" in report, report
    assert report.count("reading-only") == 1, report


def test_the_counts_move_as_the_run_trades():
    """A second offer is judged against what the FIRST one already did.

    Offer 1 takes a 771011 and spends a 771012, which makes offer 3 (771011 for a
    771015) a losing trade that was a level one a moment earlier. A run that judged
    every offer against the counts it started with would take both.
    """
    report, sends = run(strict=0, accept=1)
    assert "771011:13" in report and "771012:18" in report, report
    assert "771011:we-hold-more-of-it(13>12)" in report, report
    assert len(sends) == 1, sends


def test_the_recipe_still_declares_the_two_arguments_the_rule_needs():
    text = RECIPE.read_text(encoding="utf-8")
    assert "ARGS strict = 0" in text, "the «≤» / «<» knob is gone or renamed"
    assert "ARGS accept = 1" in text


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())

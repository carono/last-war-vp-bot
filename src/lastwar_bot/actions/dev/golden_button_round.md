# Every golden-zombie button, once, in the order a person presses them — #1702.
# ru: Все кнопки золотых зомби подряд, в том порядке, в каком их жмёт человек.
#
# «Почему постоянная ДЕГРАДАЦИЯ?!» — because each fix was proved by pressing the ONE
# button it touched, while the green test suite went on passing over buttons that were
# broken. This is the answer to that: one run that presses the lot, in order, and says
# what each of them did. It ends with a recall, so the squad it sent is brought home.
#
# It DOES send one march — that is the point of it — so it is a check to run before a
# commit, not a thing to leave on a timer.

LOG "— round: обновить карту"
CALL scan_map

LOG "— round: найти ближайшего"
CALL golden_find_target

LOG "— round: перейти к выбранному"
CALL golden_goto_target

LOG "— round: атаковать выбранного"
CALL golden_attack_target

LOG "— round: состояние отряда"
CALL golden_squad_report

LOG "— round: вернуть отряд"
CALL golden_recall_squad

LOG "— round: забыть цель"
CALL golden_forget_target

LOG "— round: done, all seven pressed"

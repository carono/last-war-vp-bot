# Let the chosen zombie go. Nothing is sent, and the registry is kept.
# ru: Забыть выбранного зомби. Ничего не отправляется, реестр остаётся.
#
# «Атаковать выбранного» sends at whatever «Найти ближайшего» parked, and a person who
# has changed their mind needs a way to say so without pressing attack to find out
# (#1702). Forgetting WHICH one was chosen is not forgetting that the map has zombies on
# it, so the registry is untouched and the next «найти» chooses from it as before.

TAP golden_forget_target
LOG "the chosen zombie is forgotten — «атаковать выбранного» has nothing to send at"

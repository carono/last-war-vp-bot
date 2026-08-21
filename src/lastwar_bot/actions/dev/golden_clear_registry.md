# Throw the golden-zombie registry away, so the next scan starts from nothing — #1702.
# ru: Очистить реестр золотых зомби, чтобы следующий обход набирал его заново.
#
# The operator's own way of reproducing a fault: clear the list, walk the world, press
# find. This is the first step of it, as a brick.

TAP golden_forget_queue
LOG "the registry is empty — the next scan fills it from nothing"

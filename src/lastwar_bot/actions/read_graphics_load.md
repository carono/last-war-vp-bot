# Read how hard the client is currently drawing — frame cap, quality and render size.
# ru: Прочитать, насколько тяжело сейчас рисует клиент — кадры, качество и размер.
#
# The companion read to `set_graphics_load`. It presses nothing and changes nothing; it
# exists so that a caller showing the current mode to a person reads it out of the GAME
# rather than trusting what it last wrote. A client that was restarted comes back at full
# quality without telling anybody, so a remembered choice and the truth drift apart within
# one crash — and the one that matters on screen is the truth.
#
# The five values land in the run's variables, where the caller picks them up:
#
#   fps      Application.targetFrameRate. Note this is the cap ASKED FOR, not the rate
#            achieved — and while `vsync` is 1 the engine ignores it entirely, which is
#            why both are read and neither means much alone.
#   vsync    QualitySettings.vSyncCount. 0 = the cap above is in force. 1 = the display
#            paces it instead… unless there is no display (a client in a Windows session
#            nobody is connected to), where it paces nothing and the client free-runs.
#   quality  the game's own preset index — 0 Low, 1 Medium, 2 High.
#   width    the size actually being rendered, which is where most of the cost is.
#   height
#
# Why the numbers rather than a verdict: "is this the economy profile?" is a question
# about what the caller asked for, and it is the caller that knows what it asked for.
# Reporting the state and leaving the judgement out keeps this file true for anybody.

READ_LUA CS.UnityEngine.Application.targetFrameRate INTO fps
READ_LUA CS.UnityEngine.QualitySettings.vSyncCount INTO vsync
READ_LUA CS.UnityEngine.QualitySettings.GetQualityLevel() INTO quality
READ_LUA CS.UnityEngine.Screen.width INTO width
READ_LUA CS.UnityEngine.Screen.height INTO height

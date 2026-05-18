# Capture the active player's metadata into the bot profile.
#
# Run this once per profile (per game account) to populate
# profiles/<id>.json with `name`, `level`, and `server`. Other actions
# can then branch on `profile.<field>` (e.g. server-specific behaviour).
#
# Calibration (do once per game-window resolution):
#   - Capture the profile modal once it's open and crop a unique element
#     (header label / avatar frame / "Profile" button) as
#     `profile_modal_marker.png` under game/templates/.
#   - Adjust the four READ_TEXT regions below to match where each field
#     is actually rendered. Coordinates are (x, y, w, h) in client px.

# 1. Tap the player avatar in the top-left corner.
#    Avatar art differs per player so we can't FIND it — use absolute
#    coordinates. ~(50, 50) hits inside the avatar circle.
CLICK (50, 50)

# 2. Wait for the profile modal to render.
WAIT FIND profile_modal_marker.png WITHIN 5s

# 3. OCR each field. Placeholder regions — calibrate before relying.
READ_TEXT (300, 100, 400, 60) INTO profile.name
READ_TEXT (300, 180, 200, 50) INTO profile.level
READ_TEXT (300, 240, 200, 50) INTO profile.server

LOG "Profile updated; closing modal."

# 4. Close the modal (separate script so other flows can reuse it).
CALL close_profile_modal

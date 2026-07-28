# Navigate to the World map if we're not already there.

IF screen != world
    CALL click_world_button
    WAIT screen == world WITHIN 10s

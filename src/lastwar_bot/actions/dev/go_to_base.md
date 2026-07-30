# Navigate to the Base screen if we're not already there.
# ru: Перейти на базу.

IF screen != base
    CALL click_base_button
    WAIT screen == base WITHIN 10s

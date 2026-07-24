# Base (City) navigation — decoding building coordinates and clicking them

Turn a building's `pId` (from the login snapshot, `docs/research/city-protocol.md`) into a
screen pixel you can click. Three parts: decode `pId` → grid, read the live camera, project
grid → world → screen → desktop-pixel. Validated against a screenshot; a reusable clicker is
`tools/city_click.py`.

## 1. `pId` → grid — base is a 100-wide grid, `TileSize == 2`

Each `building_new[i].pId` (see city-protocol.md) is a packed base-grid cell:

```
gx = pId % 100        # column
gy = pId // 100        # row
```

Evidence (205 buildings from the cold-load `init`, 185 placed — `pId != 0`): **only** the
`%100 / //100` packing keeps both axes off the modulus boundary (`gx∈[17,76]`, `gy∈[25,75]`)
instead of wrapping; every other base (64/80/128/1000, `>>8`) forces one axis to span its full
range. Rendered as ASCII the cells form a coherent base — a dense core with regular
`#.#.#.#` building rows and decorations/walls around the edge — not a scatter, confirming the
packing. The 4 cells with two buildings are a functional building + a `103xxxxx` decoration
sharing an anchor.

The base grid pitch is **`TileSize = 2`** world units per cell (Lua global `TileSize`).
`BuildingUtils.GetMainPos()` returns the HQ anchor grid **`(49, 49)`** (an anchor point, not a
stored `pId` — the HQ's own `pId` is a footprint corner, so that exact cell reads empty below).

Placed buildings span **`gx ∈ [17, 76]`, `gy ∈ [25, 75]`** (185 placed / 205 total, 181 unique
cells). ASCII render (`#` = building anchor, `.` = empty; column tens/units across the top):

```
         2    2    3    3    4    4    5    5    6    6    7    7
      789012345678901234567890123456789012345678901234567890123456
y=25  ........................#...................................
y=29  #...........................................................
y=31  #...........................................................
y=32  ..................................#.........................
y=33  #...........................................................
y=35  #...........................................................
y=36  ..........#.................................................
y=37  .....................#........#...........#........#........
y=39  ..................................#.........................
y=41  ...................#........................................
y=42  ..............#..#...#.#.#.#.#......#..#.#..................
y=44  .....................#.#.#.#.#...........#..................
y=45  ..............#..#..................#..#....................
y=46  ............#....#...#.#.#.#.#...........#.....#.....#.....#
y=47  .............#..............................................
y=48  .............#.......#.#.#.#.#......#..#.#..................
y=50  .............#...................#..........................
y=52  ..................#..#.#.#.#.#.................#.....#.....#
y=53  .............#.......................#..#...................
y=54  ..................#..#.#.#.#.#..............................
y=56  ..............#...#..#.#.#.#.#..............................
y=57  ..................................#.#.......................
y=59  ..............#............................#.#.#.#.#.#.#.#.#
y=60  ..................#...#...#.....#..#..#.....................
y=61  ...........................................#.....#...#.....#
y=62  ..............#............................#...#.####.......
y=63  .............................................#........#..#.#
y=64  ..........................#................#...#.#.#........
y=65  ..............#......................................#......
y=66  ...........................................#.#.#.#.#....#..#
y=68  ..............#...................####.....#.#....#.........
y=69  ......#...........................####..........#....#..#..#
y=70  ...........................................#.#.......#......
y=71  .............#....#............................#....#..#.#.#
y=72  .........................................#.##.....#.........
y=73  ..............................................#.....#.#..#.#
y=74  ...........................................#.............#..
y=75  ..............#..#..#..#..................##..#..#.#.#.###.#
```

The dense core (`gx≈30-46`, `gy≈42-60`) with its regular `#.#.#.#` rows is the functional base;
the sparser right block (`gx≥58`) is decorations/walls. (Fully-empty rows omitted for length.)

## 2. The base camera (read live via Lua)

`SafeDoString` (docs/research/xlua-state.md §12) with `CS.*` bindings reads the live camera —
`tools/lua_eval.py` runs a chunk and reads back `Debug.LogError` markers from the Player.log:

```lua
local c = CS.UnityEngine.Camera.main
-- pos, orthographic/size/fov, pixelWidth/Height, transform.forward
```

City base camera (this session): 

| property | value |
|---|---|
| `transform.position` | `(266.71, 240.0, -72.71)` |
| `orthographic` | **false** (perspective), `fieldOfView` **10°** (near-orthographic look) |
| render size | `pixelWidth × pixelHeight = 1576 × 1032` |
| `transform.forward` | `(-0.5, -0.7071, 0.5)` — 45° down, 135° yaw (the isometric tilt) |

The camera's ground look-at (ray to `y=0`) is world **`(97, 0, 97)`**, and the game's own
`Camera.main:WorldToScreenPoint(97,0,97)` returns **`(788, 516)`** = dead centre of
`1576×1032`. So we do **not** rebuild a projection matrix — we call the live camera's
`WorldToScreenPoint`, which tracks any pan/zoom automatically. Sanity checks:
`WorldToScreenPoint(107,0,97) = (912.7, 427.8)` (world +X → screen right+up),
`(97,0,107) = (909.1, 601.6)` (world +Z → screen right+down) — a textbook isometric basis.

## 3. grid → world → screen → desktop pixel

```
world  = (2*gx, 0, 2*gy)                     # TileSize=2, base grid on the XZ plane, y=0
render = Camera.main:WorldToScreenPoint(world)   # (x,y) in 1576x1032, ORIGIN BOTTOM-LEFT; z=depth
```

Calibration check: grid `(49,49)` (HQ, from `GetMainPos`) → world `(98,98)` → render `(812.6,
516.0)`, i.e. essentially the screen centre — exactly where the camera frames the base. The
`-1`-ish offset between `2*49=98` and the look-at `97` is under one world unit and within the
HQ's multi-tile footprint, so **`world = (2*gx, 0, 2*gy)` is used as-is** (a target anywhere on
a building's footprint is clickable; sub-tile precision is unnecessary).

Render → desktop pixel uses the window's **client** rect (Unity's y is bottom-up):

```
cw, ch      = GetClientRect(hwnd)            # 1576 x 1032 (== render size here)
ox, oy      = ClientToScreen(hwnd, (0,0))    # client top-left in desktop coords, e.g. (172, 95)
desktop_x   = ox + render_x * cw/pixelWidth
desktop_y   = oy + (pixelHeight - render_y) * ch/pixelHeight   # flip y: bottom-up -> top-down
```

A target is **on-screen** iff `depth > 0` and `render` is inside `1576×1032`; otherwise the
base must be panned to it first (this pipeline does not scroll).

### Screenshot validation

Projected all 185 placed buildings via the live `WorldToScreenPoint`; 109 fell inside the
viewport. Drew each as a marker on a focused window grab
(`results/city_grid_overlay.png`): the markers land on the base's buildings, reproducing the
diamond lattice of the building rows, with the look-at crosshair at centre. This confirms the
axis mapping (`gx→+worldX`, `gy→+worldZ`, no mirror/rotation) and the whole pipeline.
(Note: the 3D base *did* composite into the mss grab here when the window was foregrounded —
unlike the black-3D caveat in `game-launch-and-scene-control.md §4`, which stands for the
World view / unfocused grabs.)

## Clicking — `tools/city_click.py`

Input the base needs **foreground `pydirectinput`** (PostMessage is ignored —
`[[project_input_model]]`), so the tool focuses the window (Alt-key trick) and clicks the
computed desktop pixel:

```bash
C:\Python312\python.exe tools\city_click.py --grid 49 49          # dry run: prints the pixel
C:\Python312\python.exe tools\city_click.py --pid 6531 --click    # move + click that building
```

It resolves the projection **live** each call, so it is robust to camera movement, and refuses
(exit 1) when the target is off-screen. A click was issued at the computed pixel for a
left-side building (`pId 4136`, grid `(36,41)` → desktop `(475,525)`); the client then closed
on the account **session kick** (single-session, logged in elsewhere — see
game-launch-and-scene-control.md §5), so the post-click panel was not captured. The pixel
accuracy is already established by `results/city_grid_overlay.png`; a clean click→panel capture
needs a stable (throwaway-account) session.

## bId → building name (SOLVED)

The building type name is recoverable — the earlier "encrypted config" caveat is lifted:

- **On-disk config is a dead end for this**: `StreamingAssets/table/table_*.data` is
  encrypted (magic `CHACL`, entropy ~7.96); the shipped `config.db` / `%LOCALAPPDATA%`
  `config.db` are SQLite but only hold a `sample` stub / `MailData`.
- **Localization, however, is plain gzip.** `StreamingAssets/locale/23126/<lang>.bin`
  (`ru`, `en`, +18 langs) is gzip; decompressed it is a flat length-prefixed key→value
  stream: repeat `varint(keyLen) key varint(valLen) value` (UTF-8), ~52k entries per
  language, after a 4-byte header. Keys are numeric ids (`135120`) **or** string keys
  (`building_name_10221000`).
- **`bId → name-id` comes from the live (decrypted) config via Lua**, reached through the
  building data manager:
  ```lua
  local t = DataCenter.BuildTemplateManager:GetBuildingDesTemplate(bId)
  -- t.name = the localization id (e.g. 135104 or "building_name_10221000")
  -- t.des  = the description's localization id
  ```
  (Driven with `tools/lua_eval.py`; the C# `Get*` methods on `BuildingDesTemplate` are
  instance methods and need this populated template as `self`.)

Join `t.name → locale[<lang>]` to get the display name. Full mapping for all 119 types
seen in this base (source: `results/building_names.json`):

### Functional buildings (59)

| bId | Name (EN) | Название (RU) | nameId |
|---|---|---|---|
| 831000 | Protector's Field | Полигон защитников | `season_person_building_name806000` |
| 10100000 | Headquarters | Штаб | `135104` |
| 10101000 | Gear Factory | Фабрика Снаряжений | `135111` |
| 10103000 | Barracks | Казармы | `135113` |
| 10104000 | Drill Ground | Военный полигон | `135114` |
| 10105000 | 1st Squad | 1-й отряд | `800351` |
| 10106000 | Alliance Support Hub | Центр взаимопомощи альянса | `135116` |
| 10107000 | Wall | Стена | `135117` |
| 10113000 | Recon Plane | Разведывательный самолет | `800365` |
| 10114000 | Radar Vehicle | Радар | `156040` |
| 10115000 | Armed Truck | Вооруженный грузовик | `135202` |
| 10116000 | Tank Center | Танковый центр | `129031` |
| 10117000 | Missile Center | Ракетный центр | `129033` |
| 10118000 | Aircraft Center | Центр авиации | `129035` |
| 10119000 | Builder's Hut | Хижина строителя | `129037` |
| 10120000 | Tavern | Таверна | `129041` |
| 10121000 | Store | Лавка | `129058` |
| 10123000 | 1st Tech Center | Первый Центр Технологий | `2000755` |
| 10124000 | Hospital | Госпиталь | `135120` |
| 10125000 | 2nd Squad | 2-й отряд | `800352` |
| 10127000 | Trade Station | Торговая станция | `457503` |
| 10135000 | 3rd Squad | 3-й отряд | `800353` |
| 10138000 | Trade Fleet -1 | Торговый флот -1 | `457554` |
| 10139000 | Trade Fleet -2 | Торговый флот -2 | `457556` |
| 10140000 | Trade Fleet -3 | Торговый флот -3 | `457558` |
| 10141000 | Trade Fleet -Ω | Торговый флот -Ω | `457560` |
| 10142000 | 2nd Tech Center | Второй Центр Технологий | `2000756` |
| 10143000 | Drone Center | Центр беспилотников | `135270` |
| 10144000 | Secret Command Post | Секретный командный пункт | `dispatch_des029` |
| 10145000 | 4th Squad | 4-й отряд | `800354` |
| 10201000 | Farmland | Поле | `135105` |
| 10202000 | Iron Mine | Железный рудник | `135106` |
| 10203000 | Food Warehouse | Хранилище еды | `135107` |
| 10206000 | Iron Warehouse | Хранилище металла | `135108` |
| 10207000 | Gold Mine | Месторождение золота | `135109` |
| 10208000 | Coin Vault | Хранилище монет | `129029` |
| 10209000 | Smelter | Металлургический завод | `135231` |
| 10210000 | Training Base | Учебная база | `135233` |
| 10211000 | Material Workshop | Мастерская материалов | `135235` |
| 10212000 | Flag | Флаг | `800836` |
| 10213000 | Falcon Rescue Team | Спасательный отряд «Сокол» | `135198` |
| 10214000 | Component Factory | Завод по производству компонентов дрона | `2000574` |
| 10215000 | Arena | Арена | `801121` |
| 10216000 | Alert Tower | Вышка оповещения | `801196` |
| 10217000 | Monument | Монумент | `500474` |
| 10218000 | Profession Hall | Зал профессий | `building_name_10218000` |
| 10219000 | Decoration Gallery | Галерея украшений | `building_name10219000` |
| 10220000 | Talent Hall | Дом талантов | `building_name_10220000` |
| 10221000 | Oil Well | Нефтяная Скважина | `building_name_10221000` |
| 10224000 | Event Hub | Центр Событий | `building_name10224000` |
| 10227000 | Armament Institute | Исследовательский институт вооружений | `building_name_10227000` |
| 10228000 | Season Memorial Hall | Зал славы сезона | `building_name_10228000` |
| 10229000 | War Center | Командный центр | `battlefield_entrance_building_name_1001` |
| 10231000 | Emergency Center | Центр экстренной помощи | `building_name_10231000` |
| 10232000 | Chip Lab | Институт Чипов | `building_name10232000` |
| 10233000 | Drone Parts Workshop | Цех запчастей для дрона | `building_name_10233000` |
| 10234000 | 3rd Tech Center | Третий Центр Технологий | `building_name_10234000` |
| 10235000 | Tactical Institute | Институт изучения тактики | `building_name_10235000` |
| 10236000 | Overlord's Base | База Повелителя | `building_name_10236000` |

### Decorations (60)

| bId | Name (EN) | Название (RU) | nameId |
|---|---|---|---|
| 103201000 | Bench | Скамейка | `135248` |
| 103202000 | Propitious Pond | Пруд удачи | `135249` |
| 103203000 | Flamingo Statue | Статуя фламинго | `135250` |
| 103204000 | Ginkgo Tree | Дерево Гинкго | `135242` |
| 103205000 | Ginkgo Tree | Дерево Гинкго | `135242` |
| 103206000 | Ginkgo Tree | Дерево Гинкго | `135242` |
| 103301000 | Bronze Tank | Бронзовый танк | `135251` |
| 103302000 | Bronze Missile Vehicle | Бронзовое ракетное оружие | `135252` |
| 103303000 | Bronze Aircraft | Бронзовый самолет | `135253` |
| 103304000 | Pacifism | Пацифизм | `135254` |
| 103401000 | It's Legend | Это легенда | `135255` |
| 103402000 | Silver Jet | Серебряный Джет | `135256` |
| 103403000 | Silver Destroyer | Серебряный разрушитель | `135257` |
| 103404000 | Silver Rocket | Серебряная ракета | `135258` |
| 103405000 | Christmas Snowman | Рождественский снеговик | `building_name103405000` |
| 103413000 | Silver Warrior | Серебряный Воин | `building_name103413000` |
| 103414000 | Training Tire | Специальный рекомендуемый тренд | `item_name103414000` |
| 103416000 | Golden Bell | Золотой колокольчик | `item_name705701` |
| 103418000 | Silver Gunman | Серебряный стрелок | `item_name707004` |
| 103419000 | Easter Egg | Пасхальное яйцо | `item_name_706401` |
| 103420000 | Silver Assault Trooper | Серебряный штурмовик | `item_name_707006` |
| 103423000 | Wild Rhythm | Дикий ритм | `item_name_707101` |
| 103424000 | Star-watcher Telescope | Телескоп | `item_name_707401` |
| 103425000 | Cozy Winter Holiday | Тёплая зима | `item_name_707602` |
| 103426000 | Egg Hugger | Пасхальный зайчик | `item_name_707605` |
| 103429000 | Christmas Skis | Рождественские лыжи | `item_name_707616` |
| 103501000 | Gold Tank | Золотой танк | `135259` |
| 103502000 | Golden Missile Vehicle | Золотое Ракетное оружие | `135260` |
| 103503000 | Gold Bomber | Золотой бомбардировщик | `135261` |
| 103504000 | Bell Tower | Колокольня | `135262` |
| 103506000 | "Eiffelle" Tower | Копия башни | `135264` |
| 103507000 | Ferris Wheel | Колесо обозрения | `135265` |
| 103508000 | Neon Sign | Неоновая вывеска | `135266` |
| 103509000 | Pumpkin Panic | Тыквенная Паника | `135268` |
| 103510000 | Happy Turkey | Счастливая Индейка | `item_name705101` |
| 103511000 | Colorful Christmas Tree | Красочная рождественская елка | `building_name103511000` |
| 103512000 | Win in 2024 | Выиграть в 2024 | `building_name103512000` |
| 103513000 | Golden Marshal Statue | Статуя Золотого Маршала | `item_name103513000` |
| 103514000 | Military Monument | Военный памятник | `item_name103514000` |
| 103515000 | Tower of Victory | Башня Победы | `item_name103515000` |
| 103516000 | Eternal Pyramid | Вечная пирамида | `item_name706021` |
| 103517000 | Year of the Dragon | Год Дракона | `item_name705801` |
| 103518000 | Lovely Bears | Милые Медведи | `item_name705901` |
| 103520000 | God of Judgment | Властелин судьбы | `item_name_707005` |
| 103521000 | Joyful Bunny | Радостный Кролик | `item_name_706301` |
| 103522000 | Cheese Manor | Сырная усадьба | `item_name_706601` |
| 103523000 | Warrior's Monument | Памятник воину | `item_name_706701` |
| 103524000 | Golden Mobile Squad | Золотой мобильный отряд | `item_name_706801` |
| 103525000 | Throne of Blood | Кровавый трон | `item_name_707007` |
| 103526000 | Fabulous Phonograph | Сказочный фонограф | `item_name_706901` |
| 103528000 | Torch Relay | Эстафета | `item_name_707201` |
| 103530000 | Jack-o'-Zombie | Хэллоуин Зомби | `item_name_707501` |
| 103531000 | Cornucopia | Рог изобилия | `item_name_707601` |
| 103532000 | Win in 2025 | Побеждай в 2025 | `item_name_707603` |
| 103533000 | Rosy Cabriolet | Романтическая цветочная машина | `item_name_707604` |
| 103534000 | Easter Egg-sassin | Цветной спринт | `item_name_707606` |
| 103536000 | Lucky Cat | Манэки-нэко | `item_name_707009` |
| 103538000 | Jack-o'-Carriage | Тележка с конфетами Джека | `item_name_707613` |
| 103539000 | Turkey Swashbuckler | Мечник-индейка | `item_name_707615` |
| 103555000 | Super Skyscraper | Супер-небоскрёб | `item_name_706022` |

## Remaining gap

`pId → in-game world map coordinate label` (the base's coordinate on the world map, shown
in-client) is a separate lookup from the base-local grid decoded above; it is not needed to
locate or click a building. Everything else — position, name, level, and click — is solved.

## Tools & artifacts

- `tools/lua_eval.py` — run a Lua chunk via SafeDoString, read markers back from Player.log.
- `tools/city_click.py` — `pId`/grid → live projection → desktop pixel → optional click.
- `results/building_screen.json` — every building's `pId`, grid, render-screen coords, depth (git-ignored).
- `results/city_grid_overlay.png` — the validation screenshot (markers on buildings, git-ignored).
- `results/locale_strings.json` — full decoded `en`/`ru` localization (~52k keys each) from `locale/23126/<lang>.bin` (git-ignored).
- `results/building_nameids.json` / `results/building_names.json` — `bId → nameId` (from Lua) and the joined `bId → EN/RU name` table (git-ignored).

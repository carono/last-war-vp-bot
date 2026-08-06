# The game's words for the things the panel names

Generated — do not hand-edit. Re-run after a game update:

```
C:\Python312\python.exe tools\game_locale.py --glossary
```

The panel may not invent a name for something the game has already named, in ANY of the
languages it ships. This is the list to translate a locale against: find the row, copy
the cell. Everything else in a locale file is the panel's own words and is translated
normally.

Every row is ONE key out of the game's tables, and the key is in the table so any cell
can be checked — `--key <key>` prints it again. Read a cell rather than trusting it:
the translators of the game were not always consistent, so a key that is a noun in one
language can be an imperative in another («Rally» → pt «Mobilizar»). When a cell reads
like the wrong part of speech, look the term up in a sentence instead:
`--term "Launch Rally"`.

The columns are the panel's base languages. The game ships eight more — Chinese
(`zh_CN`, `zh_TW`, `gn_CN`), Japanese, Korean, Arabic, Thai, and `vr` (a copy of `vi`) —
and the panel deliberately does not: Tcl/Tk 8.6 does no bidi reordering and no Arabic
joining, and nobody here can proofread the CJK ones. `tools/game_locale.py --term` reads
them all anyway when a question needs answering.

| what the panel means | the game's English | key | en | ru | de | fr | es | it | pt | pl | tr | id | vi |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| the rally the panel raises and joins | **Rally** | `300038` | Rally | Стягивание | Versammlung | Ralliement | Reunión | Rally | Mobilizar | Rajd | Ralli | Reli | Tổ Đội |
| the boss a rally is raised on | **Doom Elite** | `300602` | Doom Elite | Роковая Элита | Elite der Verdammten | Élite Maudite | Doom Élite | Elite Zombie | Elite da Destruição | Elita Zagłady | Kıyamet Eliti | Doom Elite | Tinh Anh Tận Thế |
| the alliance's training rally | **Alliance Exercise** | `500426` | Alliance Exercise | Учение Альянса | Allianz-Übung | Exercice d'Alliance | Ejercicio de Alianza | Esercitazione dell'Alleanza | Exercício da Aliança | Ćwiczenia Sojuszu | İttifak Tatbikatı | Latihan Aliansi | Diễn Tập Liên Minh |
| the weekly co-op robbery event | **Ghost Ops** | `ghostrecon_activityname` | Ghost Ops | «Операция Призрак» | Geistereinsatz | Opérations Fantômes | Operaciones Fantasma | Operazioni Fantasma | Operações Fantasmas | Operacja Widmo | Hayalet Operasyonu | Operasi Hantu | Chiến Dịch Linh Hồn |
| the section the game's events live in | **Events** | `2000046` | Events | События | Events | Évènements | Eventos | Evento speciale | Eventos | Wydarzenia | Etkinlikler | Event | Sự Kiện Đặc Biệt |
| the world-boss event, three attacks a day | **Codename** | `100086` | Codename | Кодовое имя | Codename | Nom de code | Nombre Clave | Nome in codice | Codinome | Kryptonim | Kod adı | Kodenama | Mã |
| the boss that event puts on the map | **Wanted Boss** | `activity_worldboss_title` | Wanted Boss | Разыскиваемый Босс | Gesuchter Boss | Boss Recherché | Jefe Más Buscado | Boss Ricercato | Chefe Procurado | Poszukiwany boss | Aranan Patron | Boss Buron | Truy Nã Thủ Lĩnh |
| the biggest single hit on that boss | **Highest Damage** | `wantedBoss_record_highest` | Highest Damage | Наибольший Урон | Höchster Schaden | Dégâts les plus élevés | Daño Más Alto | Danno Più Elevato | Maior Dano | Największe obrażenia | En Yüksek Hasar | DMG Tertinggi | ST Cao Nhất |
| the tab those events live on | **Secret Command Post** | `dispatch_des029` | Secret Command Post | Секретный командный пункт | Geheimer Kommandoposten | Poste de Commandement Secret | Puesto de Mando Secreto | Posto di Comando Segreto | Posto de Comando Secreto | Tajne stanowisko dowodzenia | Gizli Komuta Merkezi | Pos Komando Rahasia | Sở Chỉ Huy Bí Mật |
| the alliance tasks with stars | **Secret Task** | `456288` | Secret Task | Секретное задание | Geheime Mission | Tâches Secrètes | Tarea Secreta | Attività Segreta | Tarefa Secreta | Tajne zadanie | Gizli Görevler | Tugas Rahasia | Nhiệm Vụ Bí Mật |
| a mate's shared secret task | **Secret Mobile Squad** | `456201` | Secret Mobile Squad | Секретный мобильный отряд | Geheime Mobile Einheit | Escouade Mobile Secrète | Escuadrón Móvil Secreto | Manovre furtive | Equipe de Operações Secretas | Tajny oddział mobilny | Gizli Mobil Takım | Skuad Mobile Rahasia | Đội Cơ Động Bí Mật |
| the chests an alliance radar drops | **Hidden Treasures** | `Treasure_map_01` | Hidden Treasures | Скрытые Сокровища | Verborgene Schätze | Trésors Cachés | Tesoros Escondidos | Tesoro Nascosti | Tesouro Secreto | Ukryte skarby | Gizli Hazine | Harta Karun Tersembunyi | Kho Báu Bí Mật |
| the player themselves | **Commander** | `302129` | Commander | Командир | Kommandant | Commandant | Comandante | Comandanti | Comandante | dowódca | Komutan | komandan | chỉ huy |
| the rank the duel raises | **Overlord** | `dominator_star_title_name_7` | Overlord | Повелитель | Overlord | Suzerain | Señor Supremo | Overlord | Soberano | Władca | Derebeyi | Overlord | Chúa Tể |
| the wall the duel raises | **Wall of Honor** | `130199` | Wall of Honor | Стена чести | Ehrenwand | Mur d'Honneur | Muro de Honor | Muro d'Onore | Mural da Honra | Ściana Honoru | Onur Duvarı | Dinding Honor | Tường Vinh Quang |
| the weapon the duel upgrades | **Exclusive Weapon** | `alliance_duel_tips10033` | Exclusive Weapon | Эксклюзивное оружие | Exklusive Waffe | Armes Exclusives | Arma Exclusiva | Arma Esclusiva | Armas Exclusivas | Ekskluzywna broń | Özel Silah | Senjata Eksklusif | Vũ Khí Riêng |
| what the duel opens for hero XP | **Hero EXP Chest** | `2000176` | Hero EXP Chest | Сундук опыта героя | Helden-XP-Truhe | Coffre d'EXP de Héros | Cofre de EXP de Héroe | Forziere dell'EXP dell'eroe | Baú de EXP do Herói | Skrzynia EXP bohatera | Kahraman EXP sandığı | Peti EXP Hero | Rương EXP Tướng |
| the ministry that speeds building | **Secretary of Development** | `457206` | Secretary of Development | Министр строительства | Bauminister | Secrétaire au Développement | Secretario de Desarrollo | Ministro dell'Edilizia | Ministro do Desenvolvimento | Sekretarz Rozwoju | Kalkınma Bakanı | Sekretaris Pembangunan | Quản Lý Xây Dựng |
| the ministry that speeds research | **Secretary of Science** | `457207` | Secretary of Science | Министр науки | Wissenschaftsminister | Secrétaire de la Science | Secretario de Ciencias | Ministro della Scienza | Ministro da Ciência | Sekretarz Nauki | Bilim Bakanı | Sekretaris Sains | Quản Lý Khoa Học |
| the ministry the panel applies for | **Secretary of Interior** | `457208` | Secretary of Interior | Министр внутренних дел | Innenminister | Secrétaire de l'Intérieur | Secretario del Interior | Ministro dell'Interno | Ministro do Interior | Sekretarz Spraw Wewnętrznych | İçişleri Bakanı | Sekretaris Dalam Negeri | Quản Lý Nội Chính |
| where the wounded are healed | **Hospital** | `135120` | Hospital | Госпиталь | Lazarett | Hôpital | Hospital | Ospedale | Hospital | Szpital | Hastane | Rumah Sakit | Bệnh Viện |
| what a squad is called | **Squad** | `city_trade_tips1012` | Squad | Отряд | Truppe | Équipe | Escuadrón | Squadra | Esquadrão | Oddział | Takım | Skuad | Đội |
| the drone the duel upgrades | **Drone** | `alliance_duel_tips10005` | Drone | Дрон | Drohne | Drone | Dron | Drone | Drone | Dron | Drone | Drone | Drone |
| what the duel spends on the drone | **Gear** ⚠ | `140404` | Gear | Шестерни | Zahnrad | Équipement | Engranaje | Ingranaggi | Engrenagens | bieg | Ekipman | gigi | bánh răng |
| resource: food | **Food** | `resource_name001` | Food | Еда | Nahrung | Nourriture | Comida | Cibo | Alimento | Żywność | Gıda | Makanan | Lương Thực |
| resource: wood | **Wood** | `180265` | Wood | Дерево | Holz | Bois | Madera | Legno | Madeira | drewno | Odun | kayu | gỗ |
| resource: metal | **Metal** | `resource_name002` | Metal | Металл | Eisen | Métal | Metal | Metallo | Metal | Metal | Metal | Logam | Sắt |
| resource: oil | **Oil** | `resource_name_23` | Oil | Нефть | Öl | Pétrole | Petróleo | Petrolio | Petróleo | Ropa | Petrol | Minyak | Dầu Mỏ |
| resource: gold | **Gold** | `ghost_parkour_gold` | Gold | Золото | Gold | Or | Oro | Oro | Ouro | Złoto | Altın | Emas | Vàng |

### ⚠ Where the game contradicts itself

* **Gear** — pl «bieg» and id «gigi» are the game's own homonym slips — use the wording the game uses in a sentence (`--term "Use {0} Gears"`)

Where the tables came from, and how they are read:
[`docs/research/game-locale-tables.md`](research/game-locale-tables.md).

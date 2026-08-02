# The Tech Center's tabs, and where their names live

The eighteen tabs of the player's own Tech Center — what the VS-duel tab's «which
category to start a research from» picker offers (#1200).

Found the long way round first: the game's translation tables
([`game-locale-tables.md`](game-locale-tables.md)) have no tab strip to grep for. They
carry the ALLIANCE technology's two categories (`454119` «Развитие», `454120` «Война»,
under `454117` «Технологии Альянса»), and the only tech names with a top-level key are
the late chapters `tech_name_13..18`. Every other Combat/Economy/Development pair in the
tables belongs to a different screen — the buffs window (`110289`/`110290`), the
headquarters talents (`131002`…`131005`), the shop's pack types (`100068`/`100069`).

## Where they actually are

In the client's own Lua, as config, not as text:

```
DataCenter.ScienceTemplateManager.scienceTabTemplateDic   -- one record per tab
    id                  what the game calls this tab
    order               where it is drawn (NOT the id order)
    name                a KEY into the translation tables
    icon, unlock_level, show_level, unlock_progress, …
```

`ScienceTemplateManager` is a plain Lua class, so its shape is readable straight off the
object — `getmetatable(obj).__index` lists the methods, and the fields are on the table
itself. That is how the dictionary was found; the same trick works on any of the
`DataCenter.*` managers that are Lua rather than C#.

Read it with the warm daemon:

```python
import sys; sys.path[:0] = ["tools", "tools/lib"]
from lua_client import get_evaluator
get_evaluator().run("""
local T = DataCenter.ScienceTemplateManager
for k, v in pairs(T.scienceTabTemplateDic) do
  CS.UnityEngine.Debug.LogError('SCI '..v.order..' id='..v.id..' name='..tostring(v.name))
end
""", marker="SCI")
```

Then each `name` is looked up in `<install>/…/StreamingAssets/locale/<build>/<lang>.bin`
with the reader in [`game-locale-tables.md`](game-locale-tables.md).

## The eighteen, in display order

Every key resolves in all eleven base languages — nothing is missing and nothing had to
be translated by hand.

| # | tab id | game key | en | ru | de | fr | es | it | pt | pl | tr | id | vi |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | `200001` | Development | Развитие | Entwicklung | Développement | Desarrollo | Sviluppo | Desenvolvimento | Rozwój | Gelişim | Perkembangan | Phát Triển |
| 2 | 2 | `200008` | Economy | Экономика | Wirtschaft | Économie | Economía | Economia | Economia | Gospodarka | Ekonomi | Ekonomi | Kinh Tế |
| 3 | 3 | `200003` | Hero | Герой | Helden | Héros | Héroe | Eroe | Herói | Bohater | Kahraman | Hero | Tướng |
| 4 | 4 | `200007` | Units | Юниты | Einheiten | Unités | Unidades | Unità | Unidades | Jednostki | Birim | Unit | Lính |
| 5 | 5 | `200004` | Squad 1 | Отряд 1 | Truppe 1 | Équipe 1 | Escuadrón 1 | Squadra 1 | Esquadrão 1 | Oddział 1 | Takım1 | Skuad 1 | Đội 1 |
| 6 | 6 | `200005` | Squad 2 | Отряд 2 | Truppe 2 | Équipe 2 | Escuadrón 2 | Squadra 2 | Esquadrão 2 | Oddział 2 | Takım 2 | Skuad 2 | Đội 2 |
| 7 | 7 | `200006` | Squad 3 | Отряд 3 | Truppe 3 | Équipe 3 | Escuadrón 3 | Squadra 3 | Esquadrão 3 | Oddział 3 | Takım 3 | Skuad 3 | Đội 3 |
| 8 | 8 | `200009` | Squad 4 | Отряд 4 | Truppe 4 | Équipe 4 | Escuadrón 4 | Squadra 4 | Esquadrão 4 | Oddział 4 | Takım 4 | Skuad 4 | Đội 4 |
| 9 | 9 | `200010` | Alliance Duel | Дуэль Альянсов | Allianzduell | Duel d'Alliances | Duelo de Alianza | Duello degli alleati | Duelo de Alianças | Pojedynek Sojuszu | İttifak Düellosu | Duel Aliansi | Đối Quyết Liên Minh |
| 10 | 13 | `tech_name_13` | Intercity Truck | Грузовики | Intercity LKW | Camion Interurbain | Camión Interurbano | Camion Interurbano | Caminhão Intermunicipal | Ciężarówka międzymiastowa | Şehirlerarası Kamyon | Truk Antar Kota | Xe Tải Thành Phố |
| 11 | 12 | `211247` | Special Forces | Специальные Силы | Spezialkräfte | Forces Spéciales | Fuerzas Especiales | Forze Speciali | Forças Especiais | Siły specjalne | Özel Kuvvetler | Pasukan Khusus | Lính Đặc Chủng |
| 12 | 10 | `302159` | Siege to Seize | Осада для захвата | Belagerung zum Erobern | Assiéger pour Saisir | Asedio para Tomar | Assedio per conquistare | Cerco para Capturar | Oblegaj, aby przejąć | Ele Geçirmek için Kuşatma | Kepung untuk Rebut | Công Thành Phá Rào |
| 13 | 11 | `211221` | Defense Fortifications | Оборонительные укрепления | Verteidigungsanlagen | Fortification des Défenses | Fortificaciones de Defensa | Difesa | Fortificações de Defesa | Fortyfikacje obronne | Savunma Güçlendirmeleri | Penguatan Pertahanan | Phòng Thủ |
| 14 | 14 | `tech_name_14` | Tank Mastery | Tанковое мастерство | Panzerbeherrschung | Spécialisation Tank | Maestría de Tanque | Maestria del Carro Armato | Maestria em Tanques | Mistrzostwo czołgów | Tank Uzmanlığı | Penguasaan Tank | Chuyên Hóa Xe Tăng |
| 15 | 15 | `tech_name_15` | Missile Mastery | Мастерство ракет | Raketenbeherrschung | Spécialisation Missile | Maestría de Misiles | Maestria Missilistica | Domínio de Mísseis | Mistrzostwo rakiet | Füze Uzmanlığı | Penguasaan Rudal | Chuyên Hóa Tên Lửa |
| 16 | 16 | `tech_name_16` | Aircraft Mastery | Мастерство авиации | Flugzeugbeherrschung | Spécialisation Avion | Maestría de Aeronave | Maestria Aerea | Maestria de Aeronaves | Mistrzostwo samolotów | Uçak Uzmanlığı | Penguasaan Pesawat | Chuyên Hóa Máy Bay |
| 17 | 17 | `tech_name_17` | The Age of Oil | Эпоха Нефти | Ölzeitalter | L'Ère du Pétrole | La Era del Petróleo | L'era del petrolio | A Era do Petróleo | Epoka ropy | Petrol Çağı | Era Minyak | Thời Đại Dầu Mỏ |
| 18 | 18 | `tech_name_18` | Tactical Weapon | Тактическое оружие | Taktische Waffe | Arme Tactique | Arma Táctica | Arma Tattica | Arma Tática | Broń taktyczna | Taktik Silah | Senjata Taktis | Vũ Khí Chiến Thuật |

## What uses it

`panel/tabs/vs_duel.py` — `RESEARCH_CATEGORIES`, as `(tab id, locale key)` in display
order. The VALUE kept in the profile and answered by `plan()` is **the game's tab id**,
because that is what a scenario will aim with and it does not move when the wording
does; the words come from the panel's own locale keys, filled from the table above.

Note the ids are not the display order: the truck tab (13) is drawn tenth, and 10, 11,
12 follow it.

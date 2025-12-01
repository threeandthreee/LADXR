from typing import NamedTuple
import patches.enemies
import logic.main
from utils import Error
from locations.items import *
from entranceInfo import ENTRANCE_INFO
from patches import bingo
from patches import maze
import dungeongen.dungeongen


MULTI_CHEST_OPTIONS = [MAGIC_POWDER, BOMB, MEDICINE, RUPEES_50, RUPEES_20, RUPEES_100, RUPEES_200, RUPEES_500, SEASHELL, GEL, ARROWS_10, SINGLE_ARROW]
MULTI_CHEST_WEIGHTS = [20,           20,   20,       50,        50,        20,         10,         5,          5,        20,  10,        10]

# List of all the possible locations where we can place our starting house
start_locations = [
    "phone_d8",
    "rooster_house",
    "writes_phone",
    "castle_phone",
    "photo_house",
    "start_house",
    "prairie_right_phone",
    "banana_seller",
    "prairie_low_phone",
    "animal_phone",
]


class EntranceAvailability(NamedTuple):
    available_entrances: list
    available_exits: list


class WorldSetup:
    def __init__(self):
        self.entrance_mapping = {k: f"{k}:inside" for k in ENTRANCE_INFO.keys()}
        self.entrance_mapping.update({f"{k}:inside": k for k in ENTRANCE_INFO.keys()})
        self.boss_mapping = list(range(9))
        self.miniboss_mapping = {
            # Main minibosses
            0: "ROLLING_BONES", 1: "HINOX", 2: "DODONGO", 3: "CUE_BALL", 4: "GHOMA", 5: "SMASHER", 6: "GRIM_CREEPER", 7: "BLAINO",
            # Color dungeon needs to be special, as always.
            "c1": "AVALAUNCH", "c2": "GIANT_BUZZ_BLOB",
            # Overworld
            "moblin_cave": "MOBLIN_KING",
            "armos_temple": "ARMOS_KNIGHT",
        }
        self.goal = "vanilla"
        self.goal_count = 8
        self.bingo_goals = None
        self.sign_maze = None
        self.multichest = RUPEES_20
        self.map = None  # Randomly generated map data
        self.dungeon_chain = None
        self.inside_to_outside = True
        self.keep_two_way = True
        self.one_on_one = True
        self.is_partial = False


    def inaccessibleEntrances(self, settings, entrancePool):
        log = logic.main.Logic(settings, world_setup=self)
        return [x for x in entrancePool if log.world.entrances[x].location and log.world.entrances[x].location not in log.location_list]

    def _connect(self, en, ex, force_two_way=False) -> None:
        self.entrance_mapping[en] = ex
        if self.keep_two_way or force_two_way:
            self.entrance_mapping[ex] = en
        assert not self.one_on_one or len(self.entrance_mapping) == len(set(self.entrance_mapping.values())), \
            f"one-on-one rule violated: {en}->{ex}"
        assert not self.inside_to_outside or en.endswith(":inside") != ex.endswith(":inside"), \
            f"inside-to-outside rule violated: {en}->{ex}"
        assert en != ex, f"entrance mapped to itself: {en}->{ex}"

    def _getEntranceAvailability(self, settings, all_entrances) -> EntranceAvailability:
        log = logic.main.Logic(settings, world_setup=self)
        available_entrances = [
            e for e in all_entrances if
                e not in self.entrance_mapping and
                log.world.entrances[e].location in log.location_list
        ]
        available_exits = [e for e in all_entrances if e not in self.entrance_mapping]
        #TODO something with available exits if not self.one_on_one
        return EntranceAvailability(available_entrances, available_exits)

    def _randomizeEntrances(self, rnd, settings):
        entrance_type_groups: dict[str, list[str]] = {}
        for k, v in ENTRANCE_INFO.items():
            entrance_type_groups.setdefault(v.type, [])    
            entrance_type_groups[v.type].append(k)
            entrance_type_groups[v.type].append(f"{k}:inside")
        if settings.tradequest:
            entrance_type_groups["single"] += entrance_type_groups["trade"]
        else:
            entrance_type_groups["dummy"] += entrance_type_groups["trade"]
        del entrance_type_groups["trade"]

        entrance_pools: dict[str, list[str]] = {
            "global": []
        }
        shuffles: dict[str, str] = {
            "dungeon": settings.dungeonshuffle,
            "connector": settings.shuffleconnectors,
            "single": settings.shufflebasic,
            "dummy": settings.shufflejunk,
            "insanity": settings.shuffleannoying,
            "water": settings.shufflewater,
        }
        for type_group, scope in shuffles.items():
            if scope == "limited":
                entrance_pools[type_group] = entrance_type_groups[type_group]
            elif scope == "global":
                entrance_pools["global"].extend(entrance_type_groups[type_group])
        if settings.randomstartlocation == "limited":
            start_location = rnd.choice(start_locations)
            self._connect("start_house:inside", start_location, force_two_way=True)
            self._connect("start_house", f"{start_location}:inside", force_two_way=True)
        elif settings.randomstartlocation == "global":
            entrance_pools["global"].append("start_house")
            entrance_pools["global"].append("start_house:inside")
        all_entrances = {k for k in self.entrance_mapping.keys()}
        for pool in entrance_pools.values():
            for entrance in pool:
                del self.entrance_mapping[entrance]
        
        self.is_partial = True
        ea = self._getEntranceAvailability(settings, all_entrances)
        while(ea.available_entrances or ea.available_exits):
            selected_entrance = rnd.choice(ea.available_entrances or ea.available_exits)
            pool = next(v for v in entrance_pools.values() if selected_entrance in v)
            possible_exits = [e for e in pool if e in ea.available_exits and e != selected_entrance]
            if self.inside_to_outside:
                possible_exits = [e for e in possible_exits if e.endswith(":inside") != selected_entrance.endswith(":inside")]
            rnd.shuffle(possible_exits)

            # Try out connections, take the first one that doesn't shrink our options, or the last one if we get there.
            last_index = len(possible_exits) - 1
            backup_entrance_mapping = self.entrance_mapping.copy()
            for i, possible_exit in enumerate(possible_exits):
                self._connect(selected_entrance, possible_exit)
                possible_ea = self._getEntranceAvailability(settings, all_entrances)
                if len(possible_ea.available_entrances) >= len(ea.available_entrances) or i == last_index:
                    ea = possible_ea
                    print(f"locking in {selected_entrance}->{possible_exit} [{len(ea.available_exits)} remaining]")
                    break
                self.entrance_mapping = backup_entrance_mapping.copy()
        self.is_partial = False


    def pickEntrances(self, settings, rnd):
        if settings.overworld in {"random", "dungeonchain", "alttp"}:
            return
        if settings.overworld == "dungeondive":
            self.entrance_mapping = {"d%d" % (n): "d%d:inside" % (n) for n in range(9)}
            self.entrance_mapping.update({"d%d:inside" % (n): "d%d" % (n) for n in range(9)})

        self._randomizeEntrances(rnd, settings)
        self._checkEntranceRules()

    def _checkEntranceRules(self):
        if self.inside_to_outside:
            for k, v in self.entrance_mapping.items():
                if k.endswith(":inside"):
                    assert not v.endswith(":inside"), f"inside-to-outside rule violated: {k}->{v}"
                else:
                    assert v.endswith(":inside"), f"inside-to-outside rule violated: {k}->{v}"
        if self.keep_two_way:
            for k, v in self.entrance_mapping.items():
                assert self.entrance_mapping[v] == k, f"keep-two-way rule violated: {k}->{v}"
        if self.one_on_one:
            found = set()
            for k, v in self.entrance_mapping.items():
                assert v not in found, f"one-on-one rule violated: {k}->{v}"
                found.add(v)

    def randomize(self, settings, rnd):
        if settings.boss != "default":
            values = list(range(9))
            if settings.heartcontainers:
                # Color dungeon boss does not drop a heart container so we cannot shuffle him when we
                # have heart container shuffling
                values.remove(8)
            self.boss_mapping = []
            for n in range(8 if settings.heartcontainers else 9):
                value = rnd.choice(values)
                self.boss_mapping.append(value)
                if value in (3, 6) or settings.boss == "shuffle":
                    values.remove(value)
            if settings.heartcontainers:
                self.boss_mapping += [8]
        if settings.miniboss != "default":
            values = [name for name in self.miniboss_mapping.values()]
            for key in self.miniboss_mapping.keys():
                self.miniboss_mapping[key] = rnd.choice(values)
                if settings.miniboss == 'shuffle':
                    values.remove(self.miniboss_mapping[key])

        self.goal = settings.goal
        if settings.goal in {"maze"}:
            self.goal = settings.goal
            self.sign_maze = maze.buildMaze(rnd)
        elif settings.goal == "specific":
            if settings.goalcount == 'random':
                self.goal_count = rnd.randint(1, 8)
            else:
                self.goal_count = max(1, int(settings.goalcount))
            instruments = [c for c in "12345678"]
            rnd.shuffle(instruments)
            self.goal = "=" + "".join(instruments[:self.goal_count])
        elif "-" in settings.goal and not settings.goal.startswith("bingo"):
            a, b = settings.goal.split("-")
            if a == "open":
                a = -1
            self.goal = 'instruments'
            self.goal_count = rnd.randint(int(a), int(b))
        elif settings.goal == 'instruments':
            if settings.goalcount == 'random':
                self.goal_count = rnd.randint(-1, 8)
                if self.goal_count < 0:
                    self.goal = 'open'
            else:
                self.goal_count = int(settings.goalcount)
        if self.goal in {"bingo", "bingo-double", "bingo-triple", "bingo-full"}:
            self.bingo_goals = bingo.randomizeGoals(rnd, settings)

        if settings.overworld == "dungeonchain":
            self._buildDungeonChain(settings, rnd)

        self.multichest = rnd.choices(MULTI_CHEST_OPTIONS, MULTI_CHEST_WEIGHTS)[0]

        self.inside_to_outside = settings.entrancerules in {"normal", "chaos"}
        self.keep_two_way = settings.entrancerules in {"normal", "wild"}
        self.one_on_one = settings.entrancerules != "madness"
        self.pickEntrances(settings, rnd)

    def _buildDungeonChain(self, settings, rnd):
        chainlength = int(settings.dungeonchainlength)
        # Build a chain of 5 dungeons
        self.dungeon_chain = [1, 2, 3, 4, 5, 6, 7, 8]
        if rnd.randrange(0, 100) < 50:  # Reduce the chance D0 is in the chain.
            self.dungeon_chain.append(0)
        rnd.shuffle(self.dungeon_chain)
        self.dungeon_chain = self.dungeon_chain[:chainlength]
        # Check if we randomly replace one of the dungeons with a cavegen
        if rnd.randrange(0, 100) < 80:
            random_dungeon = dungeongen.dungeongen.Generator(rnd)
            random_dungeon.generate()
            dungeongen.dungeongen.dump("cave.svg", random_dungeon)
            self.dungeon_chain[rnd.randint(0, len(self.dungeon_chain) - 2)] = random_dungeon
        # Check if we want a random extra insert.
        if rnd.randrange(0, 100) < 80:
            inserts = ["shop", "mamu", "trendy", "dream", "chestcave"]
            self.dungeon_chain.insert(rnd.randint(1, 4), rnd.choice(inserts))

    def loadFromRom(self, rom):
        import patches.overworld
        if patches.overworld.isNormalOverworld(rom):
            import patches.entrances
            self.entrance_mapping = patches.entrances.readEntrances(rom)
        else:
            self.entrance_mapping = {"d%d" % (n): "d%d:inside" % (n) for n in range(9)}
            self.entrance_mapping.update({"d%d:inside" % (n): "d%d" % (n) for n in range(9)})
        self.boss_mapping = patches.enemies.readBossMapping(rom)
        self.miniboss_mapping = patches.enemies.readMiniBossMapping(rom)
        self.goal = 8 # Better then nothing
        self.dungeon_chain = [0, 1, 2, 3, 4, 5, 6, 7, 8]  # TODO Actually read this from rom

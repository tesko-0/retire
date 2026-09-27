#!/usr/bin/env python3
"""RETIRE — a Blade Runner street hunt for the terminal.

    python3 retire.py
    ./play.sh

Not a parser adventure: you walk the grid, scan a crowd of identical faces,
chase whoever glitches, and time the incept test. Shoot the wrong body and
the badge dies with you.
"""

from __future__ import annotations

import argparse
import curses
import heapq
import math
import os
import random
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

HISCORE_PATH = Path.home() / ".retire_hiscore"

# tiles
WALL, STREET, PUDDLE, FLOOR, DOOR, NEON, PAD, BAR = range(8)
WALKABLE = {STREET, PUDDLE, FLOOR, DOOR, PAD, BAR}
OPAQUE = {WALL, NEON}
INTERIOR = {FLOOR, BAR}

DIRS = ((0, -1), (0, 1), (-1, 0), (1, 0))
KEY_DIR = {
    ord("w"): (0, -1),
    ord("k"): (0, -1),
    curses.KEY_UP: (0, -1),
    ord("s"): (0, 1),
    ord("j"): (0, 1),
    curses.KEY_DOWN: (0, 1),
    ord("a"): (-1, 0),
    ord("h"): (-1, 0),
    curses.KEY_LEFT: (-1, 0),
    ord("d"): (1, 0),
    ord("l"): (1, 0),
    curses.KEY_RIGHT: (1, 0),
}

FIRST = [
    "Lin", "Ana", "Ken", "Mae", "Cal", "Ivy", "Ned", "Suki", "Omar", "Paz",
    "Vera", "Wes", "Yuki", "Zed", "Noa", "Rae", "Jin", "Tess", "Kyo", "Mina",
    "Sol", "Ren", "Ada", "Nico", "Hana", "Ivo", "Luz", "Quin",
]
LAST = [
    "Park", "Cruz", "Ng", "Voss", "Cho", "Reyes", "Kade", "Mori", "Singh",
    "Okada", "Bell", "Vargas", "Shin", "Cole", "Diaz", "Hart", "Lowe", "Abe",
]

INCEPT_Q = [
    "A wasp walks the length of your bare arm. You watch it.",
    "You're given a calfskin wallet. Still warm.",
    "Your mother is waiting in the rain. She doesn't have a coat.",
    "You find a tortoise on its back in the desert. It is baking.",
    "Someone plays a piano in the next room. The song is yours.",
    "A dog lies in the gutter. It looks at you, then it doesn't.",
    "You see a photograph of a child who might be you.",
]

ROLES = ("combat", "flee", "blend")

GLYPH_U = {
    WALL: "█",
    NEON: "▓",
    STREET: " ",
    PUDDLE: "░",
    FLOOR: "·",
    DOOR: "┼",
    PAD: "≡",
    BAR: "·",
}
GLYPH_A = {
    WALL: "#",
    NEON: "#",
    STREET: ".",
    PUDDLE: "~",
    FLOOR: ".",
    DOOR: "+",
    PAD: "=",
    BAR: ".",
}


# ---------------------------------------------------------------------------
# Pathfinding / LOS
# ---------------------------------------------------------------------------

def inb(w: int, h: int, x: int, y: int) -> bool:
    return 0 <= x < w and 0 <= y < h


def walkable(grid: list[list[int]], x: int, y: int) -> bool:
    return inb(len(grid[0]), len(grid), x, y) and grid[y][x] in WALKABLE


def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def los(grid: list[list[int]], x0: int, y0: int, x1: int, y1: int) -> bool:
    """Bresenham; walls/neon block. Endpoints may be opaque."""
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    w, h = len(grid[0]), len(grid)
    while True:
        if (x, y) != (x0, y0) and (x, y) != (x1, y1):
            if not inb(w, h, x, y) or grid[y][x] in OPAQUE:
                return False
        if x == x1 and y == y1:
            return True
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy


def a_star(
    grid: list[list[int]],
    start: tuple[int, int],
    goal: tuple[int, int],
    blocked: set[tuple[int, int]] | None = None,
) -> list[tuple[int, int]] | None:
    if start == goal:
        return [start]
    blocked = blocked or set()
    w, h = len(grid[0]), len(grid)

    def neighbors(p: tuple[int, int]):
        x, y = p
        for dx, dy in DIRS:
            nx, ny = x + dx, y + dy
            if walkable(grid, nx, ny) and (nx, ny) not in blocked:
                yield (nx, ny)

    frontier: list[tuple[int, int, tuple[int, int]]] = [(0, 0, start)]
    came: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    cost = {start: 0}
    n = 0
    while frontier:
        _, _, cur = heapq.heappop(frontier)
        if cur == goal:
            break
        for nxt in neighbors(cur):
            g = cost[cur] + 1
            if nxt not in cost or g < cost[nxt]:
                cost[nxt] = g
                n += 1
                f = g + manhattan(nxt, goal)
                heapq.heappush(frontier, (f, n, nxt))
                came[nxt] = cur
    if goal not in came:
        return None
    path: list[tuple[int, int]] = []
    node: tuple[int, int] | None = goal
    while node is not None:
        path.append(node)
        node = came[node]
    path.reverse()
    return path


def flood_walkable(grid: list[list[int]], start: tuple[int, int]) -> set[tuple[int, int]]:
    seen: set[tuple[int, int]] = set()
    st = [start]
    while st:
        x, y = st.pop()
        if (x, y) in seen or not walkable(grid, x, y):
            continue
        seen.add((x, y))
        for dx, dy in DIRS:
            st.append((x + dx, y + dy))
    return seen


# ---------------------------------------------------------------------------
# City
# ---------------------------------------------------------------------------

def generate_city(w: int, h: int, rng: random.Random) -> tuple[list[list[int]], dict]:
    grid = [[WALL] * w for _ in range(h)]

    y = 1
    while y < h - 2:
        thick = 2 if rng.random() < 0.75 else 1
        for t in range(thick):
            yy = y + t
            if 1 <= yy < h - 1:
                for x in range(1, w - 1):
                    grid[yy][x] = STREET
        y += thick + rng.randint(5, 7)

    x = 1
    while x < w - 2:
        thick = 2 if rng.random() < 0.7 else 1
        for t in range(thick):
            xx = x + t
            if 1 <= xx < w - 1:
                for yy in range(1, h - 1):
                    grid[yy][xx] = STREET
        x += thick + rng.randint(8, 12)

    for _ in range(rng.randint(2, 4)):
        if rng.random() < 0.5:
            yy = rng.randint(2, h - 3)
            for xx in range(1, w - 1):
                if grid[yy][xx] == WALL:
                    grid[yy][xx] = STREET
        else:
            xx = rng.randint(2, w - 3)
            for yy in range(1, h - 1):
                if grid[yy][xx] == WALL:
                    grid[yy][xx] = STREET

    rooms: list[list[tuple[int, int]]] = []
    seen: set[tuple[int, int]] = set()
    for yy in range(h):
        for xx in range(w):
            if grid[yy][xx] != WALL or (xx, yy) in seen:
                continue
            blob: list[tuple[int, int]] = []
            st = [(xx, yy)]
            seen.add((xx, yy))
            edge = False
            while st:
                cx, cy = st.pop()
                blob.append((cx, cy))
                if cx in (0, w - 1) or cy in (0, h - 1):
                    edge = True
                for dx, dy in DIRS:
                    nx, ny = cx + dx, cy + dy
                    if inb(w, h, nx, ny) and grid[ny][nx] == WALL and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        st.append((nx, ny))
            if edge or len(blob) < 18:
                continue
            xs = [p[0] for p in blob]
            ys = [p[1] for p in blob]
            minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
            interior: list[tuple[int, int]] = []
            for cx, cy in blob:
                if minx < cx < maxx and miny < cy < maxy:
                    grid[cy][cx] = FLOOR
                    interior.append((cx, cy))
            if not interior:
                continue
            doors: list[tuple[int, int]] = []
            for cx, cy in blob:
                if grid[cy][cx] != WALL:
                    continue
                adj_s = adj_f = False
                for dx, dy in DIRS:
                    nx, ny = cx + dx, cy + dy
                    if not inb(w, h, nx, ny):
                        continue
                    if grid[ny][nx] in (STREET, PUDDLE, PAD):
                        adj_s = True
                    if grid[ny][nx] == FLOOR:
                        adj_f = True
                if adj_s and adj_f:
                    doors.append((cx, cy))
            if doors:
                rng.shuffle(doors)
                grid[doors[0][1]][doors[0][0]] = DOOR
                if len(doors) > 1 and rng.random() < 0.35:
                    grid[doors[1][1]][doors[1][0]] = DOOR
            rooms.append(interior)

    if rooms:
        bar = max(rooms, key=len)
        for cx, cy in bar:
            if grid[cy][cx] == FLOOR:
                grid[cy][cx] = BAR

    for yy in range(1, h - 1):
        for xx in range(1, w - 1):
            if grid[yy][xx] == STREET and rng.random() < 0.07:
                grid[yy][xx] = PUDDLE
            if grid[yy][xx] == WALL:
                if any(
                    inb(w, h, xx + dx, yy + dy)
                    and grid[yy + dy][xx + dx] in (STREET, PUDDLE)
                    for dx, dy in DIRS
                ) and rng.random() < 0.10:
                    grid[yy][xx] = NEON

    streets = [
        (xx, yy)
        for yy in range(h)
        for xx in range(w)
        if grid[yy][xx] in (STREET, PUDDLE)
    ]
    if not streets:
        grid[h // 2][w // 2] = STREET
        streets = [(w // 2, h // 2)]

    # spinner pad: a street cell near a map corner, expanded
    corners = [
        min(streets, key=lambda p: p[0] + p[1]),
        min(streets, key=lambda p: (w - p[0]) + p[1]),
        min(streets, key=lambda p: p[0] + (h - p[1])),
        min(streets, key=lambda p: (w - p[0]) + (h - p[1])),
    ]
    pad = rng.choice(corners)
    grid[pad[1]][pad[0]] = PAD
    for dx, dy in DIRS:
        nx, ny = pad[0] + dx, pad[1] + dy
        if walkable(grid, nx, ny) and grid[ny][nx] != DOOR:
            if rng.random() < 0.8:
                grid[ny][nx] = PAD

    pads = [(xx, yy) for yy in range(h) for xx in range(w) if grid[yy][xx] == PAD]
    spawn_pool = [p for p in streets if manhattan(p, pad) > max(8, (w + h) // 6)]
    if not spawn_pool:
        spawn_pool = streets
    spawn = rng.choice(spawn_pool)

    reached = flood_walkable(grid, spawn)
    all_walk = {
        (xx, yy)
        for yy in range(h)
        for xx in range(w)
        if grid[yy][xx] in WALKABLE
    }
    for cell in all_walk - reached:
        # tunnel toward nearest reached
        near = min(reached, key=lambda p: manhattan(p, cell))
        x, y = cell
        gx, gy = near
        while (x, y) not in reached:
            if grid[y][x] in OPAQUE or grid[y][x] == WALL:
                grid[y][x] = STREET
            reached.add((x, y))
            if x != gx:
                x += 1 if gx > x else -1
            elif y != gy:
                y += 1 if gy > y else -1
            else:
                break
    reached = flood_walkable(grid, spawn)
    if not any(p in reached for p in pads):
        # last resort: street-carve to pad
        x, y = spawn
        gx, gy = pad
        while (x, y) != (gx, gy):
            if grid[y][x] in OPAQUE:
                grid[y][x] = STREET
            if x != gx:
                x += 1 if gx > x else -1
            elif y != gy:
                y += 1 if gy > y else -1

    meta = {"spawn": spawn, "pad": pad, "rooms": rooms}
    return grid, meta


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------

@dataclass
class Actor:
    x: int
    y: int
    kind: str  # player, human, replicant
    name: str
    hp: int = 1
    max_hp: int = 1
    facing: tuple[int, int] = (1, 0)
    state: str = "wander"  # wander, flee, hunt, windup, dead
    role: str = "blend"
    path: list[tuple[int, int]] = field(default_factory=list)
    wander_cd: int = 0
    glitch: int = 0
    confirmed: bool = False
    wary: int = 0
    dead: bool = False
    legal: bool = False  # retirement would be clean
    cleared: bool = False  # incept stamped them human
    left: bool = False  # walked off after clearance
    exit_goal: tuple[int, int] | None = None

    @property
    def pos(self) -> tuple[int, int]:
        return (self.x, self.y)


@dataclass
class World:
    grid: list[list[int]]
    w: int
    h: int
    rng: random.Random
    sector: int
    player: Actor
    actors: list[Actor]
    pad: tuple[int, int]
    ammo: int = 6
    scan_charges: int = 3
    scan_max: int = 3
    scan_recharge: int = 0
    turns: int = 0
    turn_limit: int = 320
    retired: int = 0
    escaped: int = 0
    humans_dead: int = 0
    log: deque[str] = field(default_factory=lambda: deque(maxlen=3))
    rain: list[tuple[int, int]] = field(default_factory=list)
    rain_tick: int = 0
    rain_rng: random.Random = field(default_factory=random.Random)
    saw_incept_help: bool = False
    over: str | None = None  # win, dead, murder, escaped, timeout
    occupied_dirty: bool = True
    _occ: set[tuple[int, int]] = field(default_factory=set)

    def msg(self, s: str) -> None:
        self.log.appendleft(s)

    def occ(self) -> set[tuple[int, int]]:
        if self.occupied_dirty:
            self._occ = {a.pos for a in self.actors if not a.dead and not a.left}
            self.occupied_dirty = False
        return self._occ

    def living(self) -> list[Actor]:
        return [a for a in self.actors if not a.dead and not a.left]

    def replicants_left(self) -> list[Actor]:
        return [a for a in self.actors if a.kind == "replicant" and not a.dead]

    def at(self, x: int, y: int) -> Actor | None:
        for a in self.actors:
            if not a.dead and not a.left and a.x == x and a.y == y:
                return a
        return None

    def tile(self, x: int, y: int) -> int:
        if not inb(self.w, self.h, x, y):
            return WALL
        return self.grid[y][x]


def unique_name(rng: random.Random, used: set[str]) -> str:
    for _ in range(80):
        n = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        if n not in used:
            used.add(n)
            return n
    n = f"{rng.choice(FIRST)} {rng.choice(LAST)} {rng.randint(2, 9)}"
    used.add(n)
    return n


def build_world(sector: int, seed: int, term_w: int, term_h: int) -> World:
    rng = random.Random(seed)
    # leave HUD room; keep city dense
    w = max(48, min(72, term_w - 2))
    h = max(18, min(28, term_h - 7))
    grid, meta = generate_city(w, h, rng)
    spawn = meta["spawn"]
    pad = meta["pad"]
    n_rep = min(5, 2 + sector)
    n_civ = min(28, 12 + sector * 3)
    scan_max = max(2, 4 - sector // 2)

    used: set[str] = set()
    player = Actor(
        x=spawn[0],
        y=spawn[1],
        kind="player",
        name="UNIT 04",
        hp=3,
        max_hp=3,
        state="idle",
    )
    actors: list[Actor] = [player]

    reached = flood_walkable(grid, spawn)
    spots = [p for p in reached if p != spawn and manhattan(p, spawn) > 4]
    rng.shuffle(spots)

    roles = list(ROLES)
    while len(roles) < n_rep:
        roles.append(rng.choice(ROLES))
    rng.shuffle(roles)

    def place(kind: str, role: str) -> None:
        if not spots:
            return
        x, y = spots.pop()
        hp = 3 if kind == "replicant" and role == "combat" else (2 if kind == "replicant" else 1)
        actors.append(
            Actor(
                x=x,
                y=y,
                kind=kind,
                name=unique_name(rng, used),
                hp=hp,
                max_hp=hp,
                role=role,
                facing=rng.choice(DIRS),
            )
        )

    for i in range(n_rep):
        place("replicant", roles[i])
    for _ in range(n_civ):
        place("human", "blend")

    world = World(
        grid=grid,
        w=w,
        h=h,
        rng=rng,
        sector=sector,
        player=player,
        actors=actors,
        pad=pad,
        ammo=6,
        scan_charges=scan_max,
        scan_max=scan_max,
        turn_limit=280 + sector * 30,
        rain_rng=random.Random(seed ^ 0xA5A5),
    )
    world.msg(f"sector {sector} · {n_rep} replicants in the wet. bring them in or put them down.")
    world.msg("incept the eye. the street does the rest.")
    return world


# ---------------------------------------------------------------------------
# Turns
# ---------------------------------------------------------------------------

def visible_interior(world: World, x: int, y: int) -> bool:
    t = world.tile(x, y)
    if t not in INTERIOR:
        return True
    px, py = world.player.pos
    if world.tile(px, py) in INTERIOR:
        # same flood of interiors roughly via LOS
        return los(world.grid, px, py, x, y)
    return los(world.grid, px, py, x, y)


def step_actor(world: World, a: Actor, dx: int, dy: int) -> bool:
    nx, ny = a.x + dx, a.y + dy
    if not walkable(world.grid, nx, ny):
        return False
    other = world.at(nx, ny)
    if other and other is not a:
        return False
    a.x, a.y = nx, ny
    if dx or dy:
        a.facing = (dx, dy)
    world.occupied_dirty = True
    return True


def pick_exit(world: World, a: Actor) -> tuple[int, int]:
    edges: list[tuple[int, int]] = []
    for x in range(1, world.w - 1):
        for y in (1, world.h - 2):
            if walkable(world.grid, x, y):
                edges.append((x, y))
    for y in range(2, world.h - 2):
        for x in (1, world.w - 2):
            if walkable(world.grid, x, y):
                edges.append((x, y))
    if not edges:
        return a.pos
    # farthest rim — they walk off, they don't pop
    return max(edges, key=lambda p: manhattan(p, a.pos))


def pick_wander_goal(world: World, a: Actor) -> tuple[int, int]:
    px, py = a.pos
    for _ in range(20):
        gx = world.rng.randint(1, world.w - 2)
        gy = world.rng.randint(1, world.h - 2)
        if walkable(world.grid, gx, gy) and manhattan((gx, gy), (px, py)) >= 4:
            return (gx, gy)
    return (px, py)


def follow_path(world: World, a: Actor) -> bool:
    if len(a.path) < 2:
        a.path = []
        return False
    # path[0] is current
    if a.path[0] != a.pos:
        # re-sync
        try:
            i = a.path.index(a.pos)
            a.path = a.path[i:]
        except ValueError:
            a.path = []
            return False
    if len(a.path) < 2:
        a.path = []
        return False
    nx, ny = a.path[1]
    dx, dy = nx - a.x, ny - a.y
    if step_actor(world, a, dx, dy):
        a.path = a.path[1:]
        return True
    a.path = []
    return False


def npc_act(world: World, a: Actor) -> None:
    if a.dead or a.kind == "player":
        return
    if a.glitch > 0:
        a.glitch -= 1
    if a.wary > 0:
        a.wary -= 1

    p = world.player
    if a.state == "windup":
        if manhattan(a.pos, p.pos) == 1:
            hit_player(world, a)
        a.state = "hunt"
        return

    if a.state == "hunt":
        if manhattan(a.pos, p.pos) == 1:
            a.state = "windup"
            return
        blocked = world.occ() - {a.pos, p.pos}
        path = a_star(world.grid, a.pos, p.pos, blocked)
        if path:
            a.path = path
            follow_path(world, a)
        return

    if a.state == "leave":
        if a.exit_goal is None:
            a.exit_goal = pick_exit(world, a)
        goal = a.exit_goal
        if a.pos == goal or manhattan(a.pos, goal) <= 1:
            a.left = True
            world.occupied_dirty = True
            world.msg(f"{a.name} takes the street. still on file.")
            return
        blocked = world.occ() - {a.pos}
        if not follow_path(world, a):
            a.path = a_star(world.grid, a.pos, goal, blocked) or []
            follow_path(world, a)
        return

    if a.state == "flee":
        blocked = world.occ() - {a.pos}
        # don't treat pad as blocked
        path = a_star(world.grid, a.pos, world.pad, blocked)
        if path:
            a.path = path
            follow_path(world, a)
            # extra step — they're faster in the rain
            if not a.dead and a.state == "flee":
                follow_path(world, a)
        else:
            # squeeze past
            for dx, dy in world.rng.sample(list(DIRS), 4):
                if step_actor(world, a, dx, dy):
                    break
        if world.tile(a.x, a.y) == PAD:
            a.dead = True  # removed from play
            world.escaped += 1
            world.occupied_dirty = True
            world.msg(f"{a.name} hits the spinner. off-world. gone.")
            check_end(world)
        return

    # wander
    if a.wander_cd > 0:
        a.wander_cd -= 1
        return
    if not follow_path(world, a):
        goal = pick_wander_goal(world, a)
        blocked = world.occ() - {a.pos}
        path = a_star(world.grid, a.pos, goal, blocked)
        a.path = path or []
        a.wander_cd = world.rng.randint(0, 2)
        follow_path(world, a)


def hit_player(world: World, src: Actor) -> None:
    if world.player.dead:
        return
    world.player.hp -= 1
    world.msg(f"{src.name} hits like a machine. {world.player.hp} left.")
    if world.player.hp <= 0:
        world.player.dead = True
        world.over = "dead"
        world.msg("the rain keeps talking. you don't.")


def check_end(world: World) -> None:
    if world.over:
        return
    if world.humans_dead > 0:
        world.over = "murder"
        return
    if world.player.dead:
        world.over = "dead"
        return
    if world.escaped >= 2:
        world.over = "escaped"
        world.msg("too many got out. the contract burns.")
        return
    if world.turns >= world.turn_limit:
        world.over = "timeout"
        world.msg("acid rain whites out the sector. you missed your window.")
        return
    if not world.replicants_left() and world.escaped == 0:
        world.over = "win"
        world.msg("sector quiet. origami in the gutter. you don't pick it up.")
    elif not world.replicants_left() and world.escaped > 0:
        world.over = "escaped"
        world.msg("the ones who ran will be someone else's problem. not a clean sheet.")


def adjacent_npc(world: World) -> Actor | None:
    px, py = world.player.pos
    best = None
    # prefer facing
    fx, fy = world.player.facing
    facing = world.at(px + fx, py + fy)
    if facing and facing.kind != "player" and not facing.dead:
        return facing
    for dx, dy in DIRS:
        a = world.at(px + dx, py + dy)
        if a and a.kind != "player" and not a.dead:
            best = a
            break
    return best


def player_move(world: World, dx: int, dy: int) -> bool:
    p = world.player
    nx, ny = p.x + dx, p.y + dy
    if not walkable(world.grid, nx, ny):
        return False
    other = world.at(nx, ny)
    if other:
        if other.kind == "replicant" and (other.state in ("hunt", "flee", "windup") or other.confirmed):
            bump_attack(world, other)
            p.facing = (dx, dy)
            return True
        return False
    p.x, p.y = nx, ny
    p.facing = (dx, dy)
    world.occupied_dirty = True
    return True


def bump_attack(world: World, other: Actor) -> None:
    other.hp -= 1
    other.legal = other.legal or other.confirmed or other.state in ("hunt", "flee", "windup")
    if other.hp <= 0:
        retire_actor(world, other, legal=other.legal or other.kind == "replicant" and other.state != "wander")
    else:
        world.msg(f"you drive {other.name} back. still up.")
        if other.kind == "replicant" and other.state == "wander":
            other.state = "hunt" if other.role == "combat" else "flee"


def retire_actor(world: World, a: Actor, legal: bool) -> None:
    if a.dead:
        return
    a.dead = True
    a.hp = 0
    a.state = "dead"
    world.occupied_dirty = True
    if a.kind == "human":
        world.humans_dead += 1
        world.msg(f"you retired a human. {a.name}. that's it. that's the job and the end of it.")
        world.over = "murder"
        return
    world.retired += 1
    left = len(world.replicants_left())
    tag = "clean" if legal or a.confirmed or a.legal else "no incept on file"
    world.msg(f"retired {a.name} · {tag} · {left} still breathing like people.")
    # other replicants may react
    for b in world.replicants_left():
        if manhattan(b.pos, a.pos) <= 10 and los(world.grid, b.x, b.y, a.x, a.y):
            if b.role == "combat":
                b.state = "hunt"
                b.legal = True
            elif b.role == "flee":
                b.state = "flee"
                b.legal = True
            else:
                if world.rng.random() < 0.5:
                    b.state = "flee"
                    b.legal = True
    check_end(world)


def fire(world: World) -> bool:
    if world.ammo <= 0:
        world.msg("the blaster clicks. empty.")
        return True
    world.ammo -= 1
    p = world.player
    dx, dy = p.facing
    if dx == 0 and dy == 0:
        dx, dy = 1, 0
    x, y = p.x, p.y
    hit = None
    for _ in range(14):
        x += dx
        y += dy
        if not inb(world.w, world.h, x, y) or world.grid[y][x] in OPAQUE:
            world.msg("the shot dies in brick and neon.")
            break
        who = world.at(x, y)
        if who:
            hit = who
            break
    else:
        world.msg("the shot goes down the street. nobody claims it.")

    # gunshot: nearby replicants react
    for b in world.replicants_left():
        if manhattan(b.pos, p.pos) <= 12:
            if b.role == "combat":
                b.state = "hunt"
                b.legal = True
            else:
                b.state = "flee"
                b.legal = True

    if hit:
        if hit.kind == "human":
            hit.hp = 0
            retire_actor(world, hit, legal=False)
            return True
        # replicant
        hit.hp -= 2
        hit.legal = True
        if hit.hp <= 0:
            retire_actor(world, hit, legal=True)
        else:
            world.msg(f"{hit.name} takes it and stays up. they look at you like a clock.")
            hit.state = "hunt" if hit.role == "combat" else "flee"
    return True


def scan(world: World) -> bool:
    if world.scan_charges <= 0:
        world.msg("scanner's dead. wait for the coil.")
        return False
    world.scan_charges -= 1
    world.scan_recharge = 0
    p = world.player
    glitched = 0
    ran = 0
    for a in world.living():
        if a.kind == "player":
            continue
        if manhattan(a.pos, p.pos) > 8:
            continue
        if not los(world.grid, p.x, p.y, a.x, a.y):
            continue
        if a.kind != "replicant":
            continue
        a.glitch = 6
        glitched += 1
        if a.state in ("hunt", "flee", "windup"):
            continue
        roll = world.rng.random()
        if a.role == "flee" and roll < 0.85:
            a.state = "flee"
            a.legal = True
            ran += 1
        elif a.role == "combat" and roll < 0.45:
            a.state = "hunt"
            a.legal = True
        elif a.role == "combat" and roll < 0.7:
            a.state = "flee"
            a.legal = True
            ran += 1
        elif a.role == "blend" and roll < 0.4:
            a.state = "flee"
            a.legal = True
            ran += 1
    if glitched == 0:
        world.msg("the scanner whines over wet coats. nothing stutters.")
    elif ran:
        world.msg("iris lag. one of them breaks into a run.")
    else:
        world.msg("something in the crowd doesn't blink with the rest.")
    return True


def tick_world(world: World) -> None:
    world.turns += 1
    world.scan_recharge += 1
    if world.scan_charges < world.scan_max and world.scan_recharge >= 36:
        world.scan_charges += 1
        world.scan_recharge = 0
        world.msg("scanner coil bites back.")
    for a in list(world.actors):
        if a is world.player:
            continue
        npc_act(world, a)
        if world.over:
            return
    check_end(world)


def rain_step(world: World) -> None:
    world.rain_tick += 1
    drops: list[tuple[int, int]] = []
    n = max(8, world.w * world.h // 40)
    rr = world.rain_rng
    for _ in range(n):
        x = rr.randint(0, world.w - 1)
        y = (rr.randint(0, world.h - 1) + world.rain_tick) % world.h
        if world.grid[y][x] in (STREET, PUDDLE, PAD):
            drops.append((x, y))
    world.rain = drops


# ---------------------------------------------------------------------------
# Incept test (real-time)
# ---------------------------------------------------------------------------
# Watch the reaction bar, then call human or replicant.
# A human flares when the question hits (v). A replicant stays flat, then
# flares too late. No extra "mark the spike" step.

QUESTION_AT = 1.4
INCEPT_DUR = 5.6


def dilation(t: float, kind: str, spike: float, phase: float) -> float:
    if kind == "human":
        v = 0.22 + 0.04 * math.sin(t * 2.8 + phase)
        if t >= QUESTION_AT:
            dt = t - QUESTION_AT
            if dt < 0.22:
                v += 0.70 * (dt / 0.22)
            elif dt < 1.15:
                v += 0.70 - 0.42 * ((dt - 0.22) / 0.93)
            else:
                v += 0.14 * max(0.0, 1.0 - (dt - 1.15) / 2.2)
        return clamp(v, 0.10, 0.96)
    v = 0.20 + 0.02 * math.sin(t * 8.0 + phase)
    if QUESTION_AT <= t < QUESTION_AT + 0.45:
        v += 0.06  # too small — a fake
    if t < spike:
        return clamp(v, 0.10, 0.96)
    dt = t - spike
    if dt < 0.14:
        v = 0.20 + 0.76 * (dt / 0.14)
    elif dt < 0.85:
        v = 0.96
    else:
        v = 0.20 + 0.76 * max(0.0, 1.0 - (dt - 0.85) / 0.9)
    return clamp(v, 0.10, 0.98)


def clamp(v: float, a: float, b: float) -> float:
    return a if v < a else b if v > b else v


def show_incept_help(stdscr, colors: dict) -> None:
    stdscr.nodelay(False)
    stdscr.timeout(-1)
    stdscr.erase()
    th, tw = stdscr.getmaxyx()
    lines = [
        "INCEPT",
        "",
        "You ask a question. Watch the EYE — the pupil is the tell.",
        "",
        "  HUMAN       the pupil BLOWS when the question hits.",
        "  REPLICANT   the pupil waits... then blows too LATE.",
        "              (blush / capillary flush goes with it.)",
        "",
        "Do nothing until the machine stops. Then call it:",
        "  r   replicant — retire them",
        "  h   human — let them go",
        "",
        "Retire a human and the badge dies. That's the whole test.",
        "",
        "enter  begin",
    ]
    for i, ln in enumerate(lines):
        try:
            attr = colors["neon"] | curses.A_BOLD if i == 0 else colors["text"]
            if ln.startswith("  HUMAN"):
                attr = colors["good"]
            elif ln.startswith("  REPLICANT"):
                attr = colors["hot"]
            stdscr.addstr(2 + i, 4, ln[: tw - 6], attr)
        except curses.error:
            pass
    stdscr.refresh()
    while True:
        ch = stdscr.getch()
        if ch in (10, 13, ord(" "), curses.KEY_ENTER, 27, ord("q")):
            break
    stdscr.nodelay(True)
    stdscr.timeout(70)


def run_incept(stdscr, colors: dict, world: World, subject: Actor, unicode_ok: bool) -> str:
    """Return retire, clear, or abort."""
    if not world.saw_incept_help:
        show_incept_help(stdscr, colors)
        world.saw_incept_help = True

    rng = world.rng
    kind = "replicant" if subject.kind == "replicant" else "human"
    spike = rng.uniform(QUESTION_AT + 1.7, QUESTION_AT + 2.8)
    phase = rng.uniform(0, 6.28)
    q = rng.choice(INCEPT_Q)
    t0 = time.time()
    stdscr.nodelay(True)
    stdscr.timeout(0)
    hist: list[tuple[float, float]] = []

    while True:
        t = time.time() - t0
        d = dilation(t, kind, spike, phase)
        hist.append((t, d))
        if len(hist) > 400:
            hist.pop(0)

        try:
            ch = stdscr.getch()
        except curses.error:
            ch = -1
        if ch in (27, ord("q")):
            stdscr.timeout(70)
            return "abort"

        deciding = t >= INCEPT_DUR
        draw_incept(stdscr, colors, subject, q, hist, t, unicode_ok, deciding)
        if deciding:
            stdscr.nodelay(False)
            stdscr.timeout(-1)
            while True:
                draw_incept(stdscr, colors, subject, q, hist, t, unicode_ok, True)
                c2 = stdscr.getch()
                if c2 in (27, ord("q")):
                    stdscr.nodelay(True)
                    stdscr.timeout(70)
                    return "abort"
                if c2 in (ord("r"), ord("R")):
                    stdscr.nodelay(True)
                    stdscr.timeout(70)
                    return "retire"
                if c2 in (ord("h"), ord("H"), ord("c"), ord("C")):
                    stdscr.nodelay(True)
                    stdscr.timeout(70)
                    return "clear"
        time.sleep(0.03)


def lid_char(nx: float, ny: float, unicode_ok: bool) -> str:
    if ny < -0.15:
        if nx < -0.45:
            return "╱" if unicode_ok else "/"
        if nx > 0.45:
            return "╲" if unicode_ok else "\\"
        return "─" if unicode_ok else "-"
    if ny > 0.15:
        if nx < -0.45:
            return "╲" if unicode_ok else "\\"
        if nx > 0.45:
            return "╱" if unicode_ok else "/"
        return "─" if unicode_ok else "-"
    return "│" if unicode_ok else "|"


def build_eye(
    d: float, t: float, unicode_ok: bool, big: bool
) -> list[list[tuple[str, str]]]:
    """Voight-Kampff close-up: almond lids, round iris, pupil that blows."""
    W, H = (41, 13) if big else (33, 9)
    cx = (W - 1) / 2.0
    cy = (H - 1) / 2.0
    # circular iris/pupil in aspect-corrected cells (glyph cells are tall)
    iris_r = 8.2 if big else 5.6
    pupil_r = (1.5 if big else 1.05) + d * (4.4 if big else 3.15)
    scan_y = int(1 + (H - 3) * (0.5 + 0.5 * math.sin(t * 1.15)))
    grid: list[list[tuple[str, str]]] = [[(" ", "dim")] * W for _ in range(H)]
    rings = "▓▒░" if unicode_ok else "#=:."
    pupil_ch = "█" if unicode_ok else "@"
    sclera_ch = "·" if unicode_ok else "."

    for y in range(H):
        for x in range(W):
            nx = (x - cx) / (W * 0.50)
            ny = (y - cy) / (H * 0.50)
            almond = nx * nx + ny * ny
            if almond > 1.02:
                continue
            if almond > 0.88:
                grid[y][x] = (lid_char(nx, ny, unicode_ok), "lid")
                continue
            px = x - cx
            py = (y - cy) * 2.05
            pr = math.sqrt(px * px + py * py)
            if pr <= pupil_r:
                gx = px - pupil_r * 0.35
                gy = py + pupil_r * 0.40
                if gx * gx + gy * gy <= (0.55 if big else 0.42) ** 2:
                    grid[y][x] = ("·" if unicode_ok else ".", "catch")
                else:
                    grid[y][x] = (pupil_ch, "pupil")
                continue
            if pr <= iris_r:
                ring = (pr - pupil_r) / max(0.35, iris_r - pupil_r)
                ch = rings[min(len(rings) - 1, int(ring * len(rings)))]
                col = "flush" if d > 0.68 else "iris"
                grid[y][x] = (ch, col)
                continue
            col = "flush" if d > 0.60 else "sclera"
            ch = sclera_ch
            if y == scan_y:
                ch = "─" if unicode_ok else "-"
                col = "reticle"
            grid[y][x] = (ch, col)

    brackets = [
        (0, 0, "┌" if unicode_ok else "+"),
        (0, 2, "─" if unicode_ok else "-"),
        (2, 0, "│" if unicode_ok else "|"),
        (0, W - 1, "┐" if unicode_ok else "+"),
        (0, W - 3, "─" if unicode_ok else "-"),
        (2, W - 1, "│" if unicode_ok else "|"),
        (H - 1, 0, "└" if unicode_ok else "+"),
        (H - 1, 2, "─" if unicode_ok else "-"),
        (H - 3, 0, "│" if unicode_ok else "|"),
        (H - 1, W - 1, "┘" if unicode_ok else "+"),
        (H - 1, W - 3, "─" if unicode_ok else "-"),
        (H - 3, W - 1, "│" if unicode_ok else "|"),
    ]
    for y, x, ch in brackets:
        if 0 <= y < H and 0 <= x < W and grid[y][x][0] == " ":
            grid[y][x] = (ch, "reticle")
    return grid


def draw_incept(
    stdscr,
    colors: dict,
    subject: Actor,
    q: str,
    hist: list[tuple[float, float]],
    t: float,
    unicode_ok: bool,
    deciding: bool,
) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    d = hist[-1][1] if hist else 0.22
    rec = "●" if int(t * 2) % 2 == 0 else "·"
    if not unicode_ok:
        rec = "*" if int(t * 2) % 2 == 0 else "o"

    eye_attr = {
        "lid": colors["text"],
        "sclera": colors["text"] | curses.A_DIM,
        "iris": colors["mag"],
        "flush": colors["hot"] | curses.A_BOLD,
        "pupil": colors["hot"] | curses.A_BOLD,
        "catch": colors["text"] | curses.A_BOLD,
        "reticle": colors["neon"] | curses.A_DIM,
        "dim": colors["dim"],
    }

    big = h >= 26 and w >= 72
    eye = build_eye(d, t if not deciding else INCEPT_DUR, unicode_ok, big)
    eh, ew = len(eye), len(eye[0])
    side = w >= ew + 36
    eye_x = 3 if side else max(1, (w - ew) // 2)
    eye_y = 2

    try:
        head = f" INCEPT · VOIGHT-KAMPFF   {subject.name}   {rec} REC"
        stdscr.addstr(0, 1, head[: w - 2], colors["neon"] | curses.A_BOLD)
    except curses.error:
        pass

    for row, line in enumerate(eye):
        for col, (ch, key) in enumerate(line):
            if ch == " ":
                continue
            try:
                stdscr.addstr(eye_y + row, eye_x + col, ch, eye_attr.get(key, colors["text"]))
            except curses.error:
                pass

    # side panel — the rest of the machine
    if side:
        px = eye_x + ew + 3
        py = eye_y + (1 if big else 0)
        pbar = int(d * 10)
        cap = "BLUSH" if d > 0.68 else "idle"
        try:
            stdscr.addstr(py, px, "PUPIL", colors["dim"])
            stdscr.addstr(
                py + 1,
                px,
                ("█" if unicode_ok else "#") * pbar + ("░" if unicode_ok else ".") * (10 - pbar),
                colors["hot"] if d > 0.68 else colors["mag"],
            )
            stdscr.addstr(py + 1, px + 12, f"{d:0.2f}", colors["text"])
            stdscr.addstr(py + 3, px, "CAPILLARY", colors["dim"])
            stdscr.addstr(
                py + 4,
                px,
                ("█" if unicode_ok else "#") * pbar + ("░" if unicode_ok else ".") * (10 - pbar),
                colors["hot"] if d > 0.60 else colors["neon"],
            )
            stdscr.addstr(py + 4, px + 12, cap, colors["hot"] if d > 0.68 else colors["dim"])
            stdscr.addstr(py + 6, px, "FLUSH RESPONSE", colors["dim"])
            stdscr.addstr(py + 7, px, "watch the iris, not the mouth", colors["text"] | curses.A_DIM)
        except curses.error:
            pass

    gy = eye_y + eh + 1
    try:
        stdscr.addstr(gy, 2, ('"' + q + '"')[: w - 4], colors["warn"])
    except curses.error:
        pass

    gx = 4
    gw = max(16, min(len(hist), w - 10))
    samples = hist[-gw:]
    bar = " ▁▂▃▄▅▆▇█" if unicode_ok else " .:-=+*#"
    mark_i = None
    if samples:
        mark_i = min(range(len(samples)), key=lambda i: abs(samples[i][0] - QUESTION_AT))
        if samples[mark_i][0] < QUESTION_AT - 0.08:
            mark_i = None
    try:
        if mark_i is not None:
            stdscr.addstr(gy + 1, gx + mark_i, "v", colors["warn"] | curses.A_BOLD)
            if gx + mark_i + 10 < w - 2:
                stdscr.addstr(gy + 1, gx + mark_i + 2, "question", colors["dim"])
        stdscr.addstr(gy + 2, 0, " iris", colors["dim"])
    except curses.error:
        pass
    for i, (_, v) in enumerate(samples):
        n = min(len(bar) - 1, int(v * (len(bar) - 1)))
        ch = bar[n]
        attr = colors["neon"]
        if v > 0.72:
            attr = colors["hot"] | curses.A_BOLD
        try:
            stdscr.addstr(gy + 2, gx + i, ch, attr)
        except curses.error:
            pass

    frac = clamp(min(t, INCEPT_DUR) / INCEPT_DUR, 0, 1)
    pw = max(8, w - 8)
    filled = int(frac * pw)
    try:
        stdscr.addstr(gy + 4, 2, "#" * filled + "." * (pw - filled), colors["dim"])
        stdscr.addstr(
            gy + 5,
            2,
            "HUMAN: pupil blows at v     REPLICANT: pupil waits, then blows LATE",
            colors["text"],
        )
        if deciding:
            stdscr.addstr(gy + 7, 2, "machine stopped. call it.", colors["warn"] | curses.A_BOLD)
            stdscr.addstr(
                gy + 8,
                2,
                "[r]  replicant — retire them     [h]  human — let them go     [esc] abort",
                colors["good"] | curses.A_BOLD,
            )
        else:
            stdscr.addstr(gy + 7, 2, "watch the pupil. don't press anything yet.", colors["dim"])
            stdscr.addstr(gy + 8, 2, "[esc] abort", colors["dim"])
    except curses.error:
        pass
    stdscr.refresh()


def apply_incept(world: World, subject: Actor, result: str) -> None:
    if result == "abort":
        world.msg(f"{subject.name} watches you pocket the machine. wary now.")
        subject.wary = 12
        if subject.kind == "replicant" and world.rng.random() < 0.35:
            subject.state = "flee" if subject.role != "combat" else "hunt"
            subject.legal = True
        return
    if result == "clear":
        if subject.kind == "replicant":
            world.msg(f"you called {subject.name} human. they don't wait around.")
            subject.state = "hunt" if subject.role == "combat" else "flee"
            subject.legal = True
        else:
            subject.cleared = True
            subject.state = "leave"
            subject.path = []
            subject.exit_goal = None
            world.msg(f"{subject.name} — on file. human. they start walking.")
            subject.wary = 0
        return
    # called replicant
    if subject.kind == "human":
        world.msg("you called a human a replicant.")
        retire_actor(world, subject, legal=False)
        return
    subject.confirmed = True
    subject.legal = True
    world.msg(f"incept says {subject.name} isn't human.")
    if subject.role == "combat":
        subject.state = "hunt"
        world.msg(f"{subject.name} doesn't sit for the gun.")
    else:
        retire_actor(world, subject, legal=True)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def init_colors() -> dict:
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    pairs = {
        "text": (curses.COLOR_WHITE, bg),
        "dim": (curses.COLOR_BLUE, bg),
        "neon": (curses.COLOR_CYAN, bg),
        "mag": (curses.COLOR_MAGENTA, bg),
        "hot": (curses.COLOR_RED, bg),
        "warn": (curses.COLOR_YELLOW, bg),
        "good": (curses.COLOR_GREEN, bg),
        "wall": (curses.COLOR_BLUE, bg),
        "player": (curses.COLOR_YELLOW, bg),
        "rain": (curses.COLOR_CYAN, bg),
        "pad": (curses.COLOR_YELLOW, bg),
        "bar": (curses.COLOR_RED, bg),
        "floor": (curses.COLOR_BLACK, bg),
    }
    out = {}
    for i, (k, (fg, b)) in enumerate(pairs.items(), 1):
        try:
            curses.init_pair(i, fg, b)
            out[k] = curses.color_pair(i)
        except curses.error:
            out[k] = 0
    out["dim"] = out.get("dim", 0) | curses.A_DIM
    return out


def draw(
    stdscr,
    world: World,
    colors: dict,
    glyphs: dict,
    unicode_ok: bool,
    cam: tuple[int, int],
) -> None:
    stdscr.erase()
    th, tw = stdscr.getmaxyx()
    hud_h = 6
    vw = tw
    vh = max(8, th - hud_h)
    cam_x, cam_y = cam

    rainset = set(world.rain)
    px, py = world.player.pos

    for sy in range(vh):
        gy = cam_y + sy
        if gy < 0 or gy >= world.h:
            continue
        for sx in range(min(tw, world.w)):
            gx = cam_x + sx
            if gx < 0 or gx >= world.w:
                continue
            tile = world.grid[gy][gx]
            ch = glyphs[tile]
            attr = colors["dim"]
            if tile == WALL:
                attr = colors["wall"]
            elif tile == NEON:
                pal = (colors["mag"], colors["neon"], colors["warn"])
                attr = pal[(gx + gy + world.rain_tick // 4) % 3] | curses.A_BOLD
                ch = glyphs[NEON]
            elif tile in (STREET, PUDDLE):
                attr = colors["dim"]
            elif tile == PAD:
                attr = colors["pad"]
            elif tile == BAR:
                attr = colors["bar"] | curses.A_DIM
            elif tile == DOOR:
                attr = colors["warn"]
            elif tile == FLOOR:
                attr = colors["text"] | curses.A_DIM

            hidden = tile in INTERIOR and not visible_interior(world, gx, gy)
            if hidden:
                ch = " "
                attr = 0

            if not hidden and (gx, gy) in rainset and tile in (STREET, PUDDLE, PAD):
                ch = "|" if unicode_ok else "'"
                attr = colors["rain"] | curses.A_DIM

            try:
                stdscr.addstr(sy, sx, ch, attr)
            except curses.error:
                pass

    # corpses then living
    for a in world.actors:
        if not a.dead:
            continue
        sx, sy = a.x - cam_x, a.y - cam_y
        if 0 <= sx < tw and 0 <= sy < vh:
            if a.kind != "player" and world.tile(a.x, a.y) in INTERIOR and not visible_interior(
                world, a.x, a.y
            ):
                continue
            try:
                stdscr.addstr(sy, sx, "%", colors["hot"] | curses.A_DIM)
            except curses.error:
                pass

    for a in world.living():
        sx, sy = a.x - cam_x, a.y - cam_y
        if not (0 <= sx < tw and 0 <= sy < vh):
            continue
        if a.kind != "player" and world.tile(a.x, a.y) in INTERIOR and not visible_interior(
            world, a.x, a.y
        ):
            continue
        if a.kind == "player":
            ch, attr = "@", colors["player"] | curses.A_BOLD
        else:
            ch = "o"
            attr = colors["text"]
            if a.glitch > 0:
                ch = "ø" if unicode_ok else "*"
                attr = colors["mag"] | curses.A_BOLD
            elif a.state == "windup":
                ch = "!"
                attr = colors["hot"] | curses.A_BOLD
            elif a.cleared:
                ch = "◦" if unicode_ok else "c"
                attr = colors["good"] | curses.A_DIM
            elif a.state in ("flee", "hunt"):
                attr = colors["warn"]
        try:
            stdscr.addstr(sy, sx, ch, attr)
        except curses.error:
            pass

    # HUD
    y = vh
    left = world.replicants_left()
    scan_bar = "█" * world.scan_charges + "░" * (world.scan_max - world.scan_charges)
    if not unicode_ok:
        scan_bar = "#" * world.scan_charges + "." * (world.scan_max - world.scan_charges)
    hp = "♥" * world.player.hp + "·" * (world.player.max_hp - world.player.hp)
    if not unicode_ok:
        hp = "H" * world.player.hp + "." * (world.player.max_hp - world.player.hp)
    tleft = max(0, world.turn_limit - world.turns)
    head = (
        f" RETIRE  sector {world.sector}   {hp}   ammo {world.ammo}   "
        f"scan {scan_bar}   nexus {world.retired}/{world.retired + len(left) + world.escaped}"
        f"  escaped {world.escaped}   file {sum(1 for a in world.actors if a.cleared)}   rain {tleft}"
    )
    try:
        stdscr.addstr(y, 0, head[: tw - 1], colors["neon"] | curses.A_BOLD)
        face = {(0, -1): "N", (0, 1): "S", (-1, 0): "W", (1, 0): "E"}.get(
            world.player.facing, "?"
        )
        stdscr.addstr(
            y + 1,
            0,
            f" wasd/hjkl move  . wait  e incept  f fire  t scan  face {face}  ? help  q"[
                : tw - 1
            ],
            colors["dim"],
        )
        for i, line in enumerate(world.log):
            if y + 2 + i >= th:
                break
            stdscr.addstr(y + 2 + i, 0, (" " + line)[: tw - 1], colors["text"])
    except curses.error:
        pass

    if world.over:
        overlay_end(stdscr, world, colors, tw, th)
    stdscr.refresh()


def overlay_end(stdscr, world: World, colors: dict, tw: int, th: int) -> None:
    texts = {
        "win": "SECTOR RETIRED",
        "dead": "RETIRED",
        "murder": "YOU RETIRED A HUMAN",
        "escaped": "THEY GOT OUT",
        "timeout": "THE RAIN WON",
    }
    title = texts.get(world.over, world.over or "")
    sub = {
        "win": "enter  next sector     r  this sector     q  walk",
        "dead": "r  another life     q  walk",
        "murder": "the badge doesn't come back.  r  deny it     q  walk",
        "escaped": "r  try the sector     q  walk",
        "timeout": "r  try the sector     q  walk",
    }.get(world.over, "")
    box_w = min(tw - 4, max(len(title) + 8, len(sub) + 4, 36))
    hbar = "─" if True else "-"
    lines = [
        "┌" + hbar * (box_w - 2) + "┐",
        "│" + title.center(box_w - 2) + "│",
        "│" + f"retired {world.retired}   escaped {world.escaped}".center(box_w - 2) + "│",
        "│" + sub.center(box_w - 2) + "│",
        "└" + hbar * (box_w - 2) + "┘",
    ]
    oy = max(1, th // 2 - 3)
    ox = max(0, (tw - box_w) // 2)
    attr = colors["hot"] if world.over != "win" else colors["good"]
    for i, ln in enumerate(lines):
        try:
            stdscr.addstr(oy + i, ox, ln[: tw - ox - 1], attr | curses.A_BOLD)
        except curses.error:
            pass


def camera(world: World, vw: int, vh: int) -> tuple[int, int]:
    px, py = world.player.pos
    cx = max(0, min(world.w - vw, px - vw // 2))
    cy = max(0, min(world.h - vh, py - vh // 2))
    if world.w <= vw:
        cx = 0
    if world.h <= vh:
        cy = 0
    return cx, cy


def overlay_help(stdscr, colors: dict) -> None:
    th, tw = stdscr.getmaxyx()
    lines = [
        "RETIRE",
        "You are a blade runner. Three-to-five replicants walked into this sector",
        "wearing borrowed skin. Unknown faces are o. Cleared humans are ◦.",
        "",
        "t  SCAN     short pulse. replicants glitch (ø) if you have line of sight.",
        "            some run. some come for you. coil recharges in the rain.",
        "e  INCEPT   stand next to someone. watch the pupil in the machine.",
        "            human = dilates with the question.  replicant = dilates LATE.",
        "            then [r] replicant or [h] human. wrong call on a human ends you.",
        "f  FIRE     the way you last moved. first body on the line. six shots.",
        ".  wait     let the street move.",
        "",
        "Yellow o is running or hunting. ! is a strike you can step off.",
        "◦  on file — you incepted them human. they walk off. scan does not stamp.",
        "≡ spinner pad — if they reach it, they're gone.",
        "Interiors hide in the dark until you look through the door.",
        "",
        "any key",
    ]
    for i, ln in enumerate(lines):
        try:
            attr = colors["neon"] | curses.A_BOLD if i == 0 else colors["text"]
            stdscr.addstr(2 + i, 4, ln[: tw - 6], attr)
        except curses.error:
            pass
    stdscr.refresh()
    stdscr.nodelay(False)
    stdscr.timeout(-1)
    stdscr.getch()
    stdscr.nodelay(True)
    stdscr.timeout(70)


def title_screen(stdscr, colors: dict, unicode_ok: bool, hiscore: int) -> str | None:
    """Return 'play' or None (quit)."""
    stdscr.nodelay(True)
    stdscr.timeout(80)
    t0 = time.time()
    while True:
        th, tw = stdscr.getmaxyx()
        stdscr.erase()
        t = time.time() - t0
        rng = random.Random(int(t * 8))
        for _ in range(th):
            x = rng.randint(0, max(0, tw - 1))
            y = rng.randint(0, max(0, th - 1))
            try:
                stdscr.addstr(y, x, "|" if unicode_ok else "'", colors["rain"] | curses.A_DIM)
            except curses.error:
                pass
        eye = [
            r"        ████████████        ",
            r"     ███            ███     ",
            r"   ██    ██████████    ██   ",
            r"  █    ██    ██    ██    █  ",
            r" █    █    ██████    █    █ ",
            r" █    █   ██ ●● ██   █    █ ",
            r" █    █    ██████    █    █ ",
            r"  █    ██    ██    ██    █  ",
            r"   ██    ██████████    ██   ",
            r"     ███            ███     ",
            r"        ████████████        ",
        ]
        if not unicode_ok:
            eye = [
                r"        ############        ",
                r"     ###            ###     ",
                r"   ##    ##########    ##   ",
                r"  #    ##    ##    ##    #  ",
                r" #    #    ######    #    # ",
                r" #    #   ## ** ##   #    # ",
                r" #    #    ######    #    # ",
                r"  #    ##    ##    ##    #  ",
                r"   ##    ##########    ##   ",
                r"     ###            ###     ",
                r"        ############        ",
            ]
        oy = max(1, th // 2 - 12)
        for i, ln in enumerate(eye):
            ox = max(0, (tw - len(ln)) // 2)
            attr = colors["mag"] if int(t * 3) % 2 == 0 else colors["neon"]
            try:
                stdscr.addstr(oy + i, ox, ln[: tw - 1], attr | curses.A_BOLD)
            except curses.error:
                pass
        title = "R E T I R E"
        sub = "a blade runner street hunt"
        hint = "enter  hunt     ?  how     q  walk"
        score = f"deepest sector  {hiscore}" if hiscore else "no clean sheets on file"
        try:
            stdscr.addstr(oy + 13, max(0, (tw - len(title)) // 2), title, colors["warn"] | curses.A_BOLD)
            stdscr.addstr(oy + 14, max(0, (tw - len(sub)) // 2), sub, colors["dim"])
            stdscr.addstr(oy + 16, max(0, (tw - len(hint)) // 2), hint, colors["text"])
            stdscr.addstr(oy + 18, max(0, (tw - len(score)) // 2), score, colors["dim"])
        except curses.error:
            pass
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (ord("q"), 27):
            return None
        if ch in (ord("?"), ord("h")):
            stdscr.erase()
            overlay_help(stdscr, colors)
        if ch in (10, 13, ord(" "), ord("p"), curses.KEY_ENTER):
            return "play"


# ---------------------------------------------------------------------------
# Hiscore
# ---------------------------------------------------------------------------

def load_hiscore() -> int:
    try:
        return int(HISCORE_PATH.read_text().strip())
    except Exception:
        return 0


def save_hiscore(sector: int) -> None:
    try:
        prev = load_hiscore()
        if sector > prev:
            HISCORE_PATH.write_text(str(sector))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def play(stdscr, seed: int | None) -> None:
    curses.curs_set(0)
    try:
        curses.set_escdelay(25)
    except Exception:
        pass
    colors = init_colors()
    unicode_ok = True
    try:
        stdscr.addstr(0, 0, "█")
        unicode_ok = True
    except Exception:
        unicode_ok = False
    glyphs = GLYPH_U if unicode_ok else GLYPH_A
    hiscore = load_hiscore()

    if title_screen(stdscr, colors, unicode_ok, hiscore) is None:
        return

    sector = 1
    base_seed = seed if seed is not None else random.SystemRandom().randint(1, 1_000_000)

    while True:
        th, tw = stdscr.getmaxyx()
        if tw < 64 or th < 22:
            stdscr.nodelay(False)
            stdscr.erase()
            stdscr.addstr(1, 2, "need a terminal at least 64×22")
            stdscr.addstr(2, 2, "q to walk")
            stdscr.refresh()
            if stdscr.getch() in (ord("q"), 27):
                return
            continue

        world = build_world(sector, base_seed + sector * 9973, tw, th)
        stdscr.nodelay(True)
        stdscr.timeout(70)
        rain_step(world)

        while True:
            th, tw = stdscr.getmaxyx()
            vh = max(8, th - 6)
            cam = camera(world, min(tw, world.w), vh)
            rain_step(world)
            draw(stdscr, world, colors, glyphs, unicode_ok, cam)

            try:
                ch = stdscr.getch()
            except curses.error:
                ch = -1

            if world.over:
                if ch in (ord("q"), 27):
                    return
                if ch in (ord("r"), ord("R")):
                    break  # rebuild same sector
                if world.over == "win" and ch in (10, 13, curses.KEY_ENTER, ord(" ")):
                    save_hiscore(sector)
                    sector += 1
                    break
                continue

            if ch in (-1, curses.KEY_RESIZE):
                continue
            if ch in (ord("q"), 27):
                return
            if ch in (ord("?"),):
                stdscr.erase()
                overlay_help(stdscr, colors)
                continue

            acted = False
            if ch in KEY_DIR:
                dx, dy = KEY_DIR[ch]
                acted = player_move(world, dx, dy)
            elif ch in (ord("."), ord("z"), ord(" ")):
                acted = True
            elif ch in (ord("t"), ord("T"), ord("c")):
                acted = scan(world)
            elif ch in (ord("f"),):
                acted = fire(world)
            elif ch in (ord("e"), ord("v"), ord("i")):
                who = adjacent_npc(world)
                if not who:
                    world.msg("nobody in arm's reach. stand on them, then look.")
                elif who.cleared:
                    world.msg(f"{who.name} is already on file. human.")
                elif who.state in ("hunt", "flee", "windup"):
                    world.msg(f"{who.name} isn't sitting for a test.")
                else:
                    stdscr.timeout(-1)
                    result = run_incept(stdscr, colors, world, who, unicode_ok)
                    stdscr.nodelay(True)
                    stdscr.timeout(70)
                    apply_incept(world, who, result)
                    acted = True
            if acted and not world.over:
                tick_world(world)


def self_test(n: int = 12) -> int:
    fails = 0
    for seed in range(n):
        rng = random.Random(seed)
        grid, meta = generate_city(64, 22, rng)
        spawn = meta["spawn"]
        pad = meta["pad"]
        reached = flood_walkable(grid, spawn)
        pads = [(x, y) for y, row in enumerate(grid) for x, t in enumerate(row) if t == PAD]
        if not pads or not any(p in reached for p in pads):
            print(f"FAIL seed {seed}: pad unreachable from {spawn} pad={pad}")
            fails += 1
            continue
        walk = sum(1 for row in grid for t in row if t in WALKABLE)
        if walk < 80:
            print(f"FAIL seed {seed}: too little walkable ({walk})")
            fails += 1
            continue
        w = build_world(1, seed, 80, 24)
        if len(w.replicants_left()) < 2:
            print(f"FAIL seed {seed}: replicants {len(w.replicants_left())}")
            fails += 1
            continue
        if w.player.pos not in reached and not walkable(w.grid, *w.player.pos):
            print(f"FAIL seed {seed}: bad spawn")
            fails += 1
            continue
        print(f"ok seed {seed}: walk={walk} rooms={len(meta['rooms'])} reps={len(w.replicants_left())} civ={sum(1 for a in w.actors if a.kind=='human')}")
    w = build_world(1, 7, 80, 24)
    for _ in range(80):
        tick_world(w)
        rain_step(w)
        if w.over:
            break
    w2 = build_world(1, 3, 80, 24)
    scan(w2)
    fire(w2)
    tick_world(w2)
    print("sim ok", "over" if w.over else f"turns={w.turns}")
    print("FAILS", fails)
    return 1 if fails else 0


def main() -> None:
    ap = argparse.ArgumentParser(description="RETIRE — blade runner street hunt")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()
    if args.test:
        sys.exit(self_test())
    os.environ.setdefault("ESCDELAY", "25")
    try:
        curses.wrapper(lambda scr: play(scr, args.seed))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

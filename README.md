# RETIRE

A **Blade Runner** street hunt for the terminal. Not a parser adventure.

You walk a rainy city block. Everyone looks like `o`. Some of them aren't
people. Scan, chase, time the incept test, and don't put a hole in a human.

```
python3 retire.py
./play.sh
python3 retire.py --seed 2019
```

Needs Python 3.10+ and a terminal at least **64×22**. Stdlib only (`curses`).

## How to play

Each key is a turn. The crowd walks. The rain doesn't stop.

| Key | Action |
|-----|--------|
| WASD / arrows / hjkl | Move (facing follows) |
| `.` / space | Wait |
| `t` | Scan — replicants in sight **glitch** (`ø`). Some run. |
| `e` | Incept test on someone adjacent. Watch the iris. |
| `f` | Fire the way you're facing. Six shots. First body on the line. |
| `?` | Help |
| `q` | Walk away |

**Incept:** stand next to someone and press `e`. The Voight-Kampff viewport
opens on their eye. A question hits at the `v` mark. Watch the **pupil**.

- **Human:** the pupil blows *when the question hits* (blush / capillary flush).
- **Replicant:** the pupil waits, then blows **late**.

Then `[r]` replicant (retire) or `[h]` human (let go). Call a human a replicant
and the badge dies. Cleared humans stamp `◦` and walk off — scan does not stamp.

**Combat:** a yellow `o` is running or hunting. `!` telegraphs a strike — step
off that tile. Replicants that hit the spinner pad (`≡`) leave the planet.

Clear the sector (all retired, none escaped) and enter the next one. Two
escapes, a human corpse, your own death, or the rain clock: that's the run.

## Glyphs

```
@  you            o  unknown          ø  glitch (scan)
◦  on file        !  about to hit     %  retired
≡  spinner        ┼  door             ▓  neon
```

Interiors stay dark until you look through the door.

Deepest sector is stored in `~/.retire_hiscore`.

#!/usr/bin/env python3
"""Generate a contribution-graph snake that eats every commit, then writes "YOU WIN !!".

The snake grows one segment per contribution eaten; the finished text ends in a rainbow wave.

Usage:
  GITHUB_TOKEN=... python3 scripts/snake.py <github_user> <output_dir>
  python3 scripts/snake.py --demo <output_dir>      # random data, no network
"""
import json
import os
import random
import sys
import urllib.request

ROWS = 7
CELL = 16
DOT = 12
STEP_MS = 100
HOLD_STEPS = 60
RAINBOW_EVERY = 3  # steps between rainbow color shifts while holding the text
SNAKE_LEN = 4  # starting length; +1 segment per contribution eaten
HEAD_SIZE, TAIL_SIZE = 12, 5
RAINBOW = ["#ff595e", "#ff924c", "#ffca3a", "#8ac926", "#1982c4", "#6a4c93"]

PALETTES = {
    "light": {
        "empty": "#ebedf0",
        "levels": ["#9be9a8", "#40c463", "#30a14e", "#216e39"],
        "border": "#1b1f230a",
        "snake": "purple",
        "text": "#216e39",
    },
    "dark": {
        "empty": "#161b22",
        "levels": ["#0e4429", "#006d32", "#26a641", "#39d353"],
        "border": "#1b1f230a",
        "snake": "purple",
        "text": "#39d353",
    },
}

GLYPHS = {
    "Y": ["X...X", ".X.X.", "..X..", "..X..", "..X.."],
    "O": ["XXXX", "X..X", "X..X", "X..X", "XXXX"],
    "U": ["X..X", "X..X", "X..X", "X..X", "XXXX"],
    "W": ["X...X", "X...X", "X.X.X", "X.X.X", ".X.X."],
    "I": ["XXX", ".X.", ".X.", ".X.", "XXX"],
    "N": ["X...X", "XX..X", "X.X.X", "X..XX", "X...X"],
    "!": ["X", "X", "X", ".", "X"],
    " ": ["..", "..", "..", "..", ".."],
}

LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}


def fetch_grid(user):
    query = """query($login:String!){user(login:$login){contributionsCollection{contributionCalendar{
      weeks{contributionDays{contributionLevel weekday}}}}}}"""
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": {"login": user}}).encode(),
        headers={"Authorization": "bearer " + os.environ["GITHUB_TOKEN"], "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as res:
        body = json.load(res)
    if body.get("errors"):
        raise SystemExit("GraphQL error: %s" % body["errors"])
    weeks = body["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    grid = {}
    for x, week in enumerate(weeks):
        for day in week["contributionDays"]:
            grid[(x, day["weekday"])] = LEVELS[day["contributionLevel"]]
    return len(weeks), grid


def demo_grid():
    rng = random.Random(1)
    width = 53
    grid = {(x, y): 0 for x in range(width) for y in range(ROWS)}
    for cell in rng.sample(sorted(grid), 30):
        grid[cell] = rng.randint(1, 4)
    return width, grid


def text_cells(text, width):
    """Pixel cells spelling `text`, one set per letter, centered in the grid."""
    total = sum(len(GLYPHS[c][0]) for c in text) + len(text) - 1
    x0 = max((width - total) // 2, 0)
    letters = []
    for c in text:
        glyph = GLYPHS[c]
        cells = {(x0 + dx, 1 + dy) for dy, row in enumerate(glyph) for dx, v in enumerate(row) if v == "X"}
        if cells:
            letters.append(cells)
        x0 += len(glyph[0]) + 1
    return letters


class Snake:
    def __init__(self, width):
        self.width = width
        # the snake enters from the left, outside the grid
        self.body = [(-1 - i, 0) for i in range(SNAKE_LEN)]
        self.history = [list(self.body)]
        self.growth = 0

    def inside(self, cell):
        x, y = cell
        return -1 <= x <= self.width and -1 <= y <= ROWS

    def path_to(self, targets):
        """BFS to the nearest target, not running through the body before it has moved away.

        Falls back to crossing the body when a long snake has boxed itself in."""
        try:
            return self._bfs(targets, avoid_body=True)
        except RuntimeError:
            return self._bfs(targets, avoid_body=False)

    def _bfs(self, targets, avoid_body):
        # the cell under segment k frees up once the tail has passed it
        vacate = {}
        if avoid_body:
            for k, cell in enumerate(self.body):
                vacate[cell] = len(self.body) - k + self.growth
        start = self.body[0]
        prev = {start: None}
        frontier = [start]
        depth = 0
        while frontier:
            hits = [c for c in frontier if c in targets and c != start]
            if hits:
                cell = min(hits)
                path = []
                while cell != start:
                    path.append(cell)
                    cell = prev[cell]
                return path[::-1]
            depth += 1
            nxt = []
            for x, y in frontier:
                for n in ((x + 1, y), (x, y + 1), (x, y - 1), (x - 1, y)):
                    if n in prev or not self.inside(n):
                        continue
                    if depth < vacate.get(n, 0):
                        continue
                    prev[n] = (x, y)
                    nxt.append(n)
            frontier = nxt
        raise RuntimeError("no path")

    def move(self, cell):
        if self.growth:
            self.growth -= 1
            self.body = [cell] + self.body
        else:
            self.body = [cell] + self.body[:-1]
        self.history.append(list(self.body))
        return len(self.history) - 1


def simulate(width, grid, letters):
    snake = Snake(width)
    events = {}  # cell -> [(step, color_key)]

    food = {c for c, level in grid.items() if level > 0}
    while food:
        for cell in snake.path_to(food):
            t = snake.move(cell)
            if cell in food:
                food.discard(cell)
                snake.growth += 1
                events.setdefault(cell, []).append((t, "empty"))

    # write one letter at a time; crossing other letters does not paint them
    for letter in letters:
        todo = set(letter)
        while todo:
            for cell in snake.path_to(todo):
                t = snake.move(cell)
                if cell in todo:
                    todo.discard(cell)
                    events.setdefault(cell, []).append((t, "text"))

    # leave through the right edge, then hold the finished text on screen
    exit_row = snake.body[0][1]
    for cell in snake.path_to({(width, exit_row)}):
        snake.move(cell)
    for i in range(1, len(snake.body) + snake.growth + 1):
        snake.move((width + i, exit_row))

    # rainbow wave sweeping across the text while it is held
    hold_start = len(snake.history) - 1
    for letter in letters:
        for x, y in letter:
            for j in range(0, HOLD_STEPS, RAINBOW_EVERY):
                color = RAINBOW[(j // RAINBOW_EVERY - x // 2) % len(RAINBOW)]
                events[(x, y)].append((hold_start + j, color))
    for _ in range(HOLD_STEPS):
        snake.history.append(list(snake.body))
    return snake.history, events


def pct(t, total):
    return ("%.3f" % (100 * t / total)).rstrip("0").rstrip(".")


def render(width, grid, history, events, palette):
    total = len(history) - 1
    duration = total * STEP_MS
    css = [
        ".c{shape-rendering:geometricPrecision;fill:%s;stroke-width:1px;stroke:%s;"
        "animation:none %dms step-end infinite}" % (palette["empty"], palette["border"], duration),
        ".s{shape-rendering:geometricPrecision;fill:%s;animation:none %dms linear infinite}" % (palette["snake"], duration),
    ]
    for i, color in enumerate(palette["levels"], 1):
        css.append(".l%d{fill:%s}" % (i, color))

    cells = []
    for (x, y), level in sorted(grid.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        cls = "c l%d" % level if level else "c"
        attrs = ""
        timeline = events.get((x, y))
        if timeline:
            name = "c%d_%d" % (x, y)
            start = palette["levels"][level - 1] if level else palette["empty"]
            frames = ["0%%{fill:%s}" % start]
            for t, key in timeline:
                frames.append("%s%%{fill:%s}" % (pct(t, total), palette.get(key, key)))
            frames.append("100%%{fill:%s}" % palette.get(timeline[-1][1], timeline[-1][1]))
            css.append("@keyframes %s{%s}" % (name, "".join(frames)))
            attrs = ' style="animation-name:%s"' % name
        off = (CELL - DOT) / 2
        cells.append('<rect class="%s" x="%g" y="%g" width="%d" height="%d" rx="2" ry="2"%s/>'
                     % (cls, x * CELL + off, y * CELL + off, DOT, DOT, attrs))

    segments = []
    longest = max(len(frame) for frame in history)
    for k in range(longest):
        size = HEAD_SIZE - (HEAD_SIZE - TAIL_SIZE) * k / (longest - 1)
        # segments not grown yet wait hidden under the tail
        track = [frame[min(k, len(frame) - 1)] for frame in history]
        frames = []
        for t, pos in enumerate(track):
            if 0 < t < total:
                before = (pos[0] - track[t - 1][0], pos[1] - track[t - 1][1])
                after = (track[t + 1][0] - pos[0], track[t + 1][1] - pos[1])
                if before == after:
                    continue
            frames.append("%s%%{transform:translate(%dpx,%dpx)}" % (pct(t, total), pos[0] * CELL, pos[1] * CELL))
        css.append("@keyframes s%d{%s}" % (k, "".join(frames)))
        off = (CELL - size) / 2
        segments.append('<rect class="s" style="animation-name:s%d" x="%g" y="%g" width="%g" height="%g" rx="%g" ry="%g"/>'
                        % (k, off, off, size, size, size / 4, size / 4))
    segments.reverse()  # head drawn last, on top

    w, h = width * CELL + 2 * CELL, ROWS * CELL + 2 * CELL
    return ('<svg viewBox="%d %d %d %d" width="%d" height="%d" xmlns="http://www.w3.org/2000/svg">'
            "<desc>Snake eats the contribution graph, then writes YOU WIN !!</desc>"
            "<style>%s</style>%s%s</svg>\n"
            % (-CELL, -CELL, w, h, w, h, "".join(css), "".join(cells), "".join(segments)))


def main(argv):
    if len(argv) != 3:
        raise SystemExit(__doc__)
    width, grid = demo_grid() if argv[1] == "--demo" else fetch_grid(argv[1])
    history, events = simulate(width, grid, text_cells("YOU WIN !!", width))
    os.makedirs(argv[2], exist_ok=True)
    for name, palette in (("github-contribution-grid-snake.svg", PALETTES["light"]),
                          ("github-contribution-grid-snake-dark.svg", PALETTES["dark"])):
        with open(os.path.join(argv[2], name), "w") as f:
            f.write(render(width, grid, history, events, palette))
    print("%d steps, %.1fs loop" % (len(history) - 1, (len(history) - 1) * STEP_MS / 1000))


if __name__ == "__main__":
    main(sys.argv)

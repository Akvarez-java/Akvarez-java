#!/usr/bin/env python3
"""Generate a contribution-graph snake that eats every commit, then writes TEXT.

The snake eats the contributions along an optimized route, filling a progress bar below the
grid, then writes the text stroke by stroke, which ends with a rainbow wave. Finally the text and bar fade out and the
contributions fade back in, so the loop restarts without a jump.

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
FADE_STEPS = 12  # length of each fade (text/bar out, then contributions back in)
TEXT = "DC : J4TL6"
JUMP_PENALTY = 2  # extra cost for leaving a stroke while drawing a letter
SNAKE_LEN = 4
HEAD_SIZE, TAIL_SIZE = 12, 7.5
BAR_GAP, BAR_HEIGHT = 4, 10  # gap below the snake's outer lane, bar thickness
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
    "D": ["XXX.", "X..X", "X..X", "X..X", "XXX."],
    "C": ["XXXX", "X...", "X...", "X...", "XXXX"],
    ":": [".", "X", ".", "X", "."],
    "J": ["...X", "...X", "...X", "X..X", "XXXX"],
    "4": ["X..X", "X..X", "XXXX", "...X", "...X"],
    "T": ["XXX", ".X.", ".X.", ".X.", ".X."],
    "L": ["X...", "X...", "X...", "X...", "XXXX"],
    "6": ["XXXX", "X...", "XXXX", "X..X", "XXXX"],
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
        # the snake starts fully off screen (left of the visible margin column) and crawls in
        self.body = [(-2 - i, 0) for i in range(SNAKE_LEN)]
        self.history = [list(self.body)]

    def inside(self, cell):
        x, y = cell
        return -1 <= x <= self.width and -1 <= y <= ROWS

    def path_to(self, target, avoid=frozenset()):
        """Shortest path to `target` with the fewest turns, starting in the current heading.

        It never runs into the body before the tail has moved away and, when possible,
        keeps off the `avoid` cells. Falls back to crossing the body if boxed in."""
        for avoid_body, blocked in ((True, avoid), (True, frozenset()), (False, frozenset())):
            path = self._search(target, avoid_body, blocked - {target})
            if path is not None:
                return path
        raise RuntimeError("no path to %s" % (target,))

    def _search(self, target, avoid_body, blocked):
        # the cell under segment k frees up once the tail has passed it
        vacate = {}
        if avoid_body:
            for k, cell in enumerate(self.body):
                vacate[cell] = len(self.body) - k
        head, neck = self.body[0], self.body[1]
        heading = (head[0] - neck[0], head[1] - neck[1])
        # layered BFS over (cell, heading); within a layer keep the fewest turns
        best = {(head, heading): (0, None)}
        layer = [(head, heading)]
        depth = 0
        while layer:
            done = [st for st in layer if st[0] == target]
            if done:
                state = min(done, key=lambda st: best[st][0])
                path = []
                while state[0] != head or state[1] != heading:
                    path.append(state[0])
                    state = best[state][1]
                return path[::-1]
            depth += 1
            nxt = {}
            for state in layer:
                (x, y), d = state
                turns = best[state][0]
                for nd in ((1, 0), (0, 1), (0, -1), (-1, 0)):
                    n = (x + nd[0], y + nd[1])
                    if not self.inside(n) or n in blocked or depth < vacate.get(n, 0):
                        continue
                    key = (n, nd)
                    cost = turns + (nd != d)
                    if key in best and best[key][0] <= cost:
                        continue
                    if key not in nxt or cost < nxt[key][0]:
                        nxt[key] = (cost, state)
            for key, value in nxt.items():
                best[key] = value
            layer = list(nxt)
        return None

    def move(self, cell):
        self.body = [cell] + self.body[:-1]
        self.history.append(list(self.body))
        return len(self.history) - 1

    def wait(self, steps):
        self.history.extend(list(self.body) for _ in range(steps))
        return len(self.history) - 1


def dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def plan_route(start, points, end=None):
    """Short open route from `start` through all `points` (optionally finishing near `end`):
    nearest neighbour, then 2-opt until no reversal helps."""
    route, todo = [], set(points)
    here = start
    while todo:
        here = min(todo, key=lambda p: (dist(here, p), p))
        todo.discard(here)
        route.append(here)
    seq = [start] + route + ([end] if end else [])
    last = len(seq) - (2 if end else 1)
    improved = True
    while improved:
        improved = False
        for i in range(1, last):
            for j in range(i + 1, last + 1):
                a, b = seq[i - 1], seq[i]
                c = seq[j]
                d = seq[j + 1] if j + 1 < len(seq) else None
                before = dist(a, b) + (dist(c, d) if d else 0)
                after = dist(a, c) + (dist(b, d) if d else 0)
                if after < before:
                    seq[i:j + 1] = reversed(seq[i:j + 1])
                    improved = True
    return seq[1:last + 1]


def stroke_order(start, pixels, toward):
    """Exact shortest order to draw a letter's pixels (Held-Karp), entering from `start`
    and finishing close to `toward` (the next letter). Lifting off the stroke to jump to a
    non-adjacent pixel costs extra, so letters are traced in continuous lines."""
    pts = sorted(pixels)
    n = len(pts)
    step = [[dist(a, b) + (JUMP_PENALTY if dist(a, b) > 1 else 0) for b in pts] for a in pts]
    full = (1 << n) - 1
    inf = float("inf")
    cost = [[inf] * n for _ in range(1 << n)]
    back = [[-1] * n for _ in range(1 << n)]
    for i, p in enumerate(pts):
        cost[1 << i][i] = dist(start, p)
    for mask in range(1, full + 1):
        row = cost[mask]
        for i in range(n):
            c = row[i]
            if c == inf:
                continue
            for j in range(n):
                if mask >> j & 1:
                    continue
                m2 = mask | 1 << j
                c2 = c + step[i][j]
                if c2 < cost[m2][j]:
                    cost[m2][j] = c2
                    back[m2][j] = i
    last = min(range(n), key=lambda i: cost[full][i] + (dist(pts[i], toward) if toward else 0))
    order, mask = [], full
    while last != -1:
        order.append(pts[last])
        mask, last = mask & ~(1 << last), back[mask][last]
    return order[::-1]


def simulate(width, grid, letters):
    snake = Snake(width)
    events = {}  # cell -> [(step, color_key, fade)]; fade: blend in from the previous color

    eaten = []  # (step, level) per eaten contribution, for the progress bar

    # eat along an optimized route that finishes near the first letter
    food = {c for c, level in grid.items() if level > 0}
    first_letter = min(letters[0])
    for goal in plan_route(snake.body[0], food, end=first_letter):
        while goal in food:
            for cell in snake.path_to(goal):
                t = snake.move(cell)
                if cell in food:  # anything on the way gets eaten too
                    food.discard(cell)
                    eaten.append((t, grid[cell]))
                    events.setdefault(cell, []).append((t, "empty", False))

    # write each letter in its shortest stroke order, steering clear of letters not drawn yet
    for i, letter in enumerate(letters):
        upcoming = set().union(*letters[i + 1:])
        toward = min(letters[i + 1]) if i + 1 < len(letters) else (width, 3)
        todo = set(letter)
        if snake.body[0] in todo:
            todo.discard(snake.body[0])
            events.setdefault(snake.body[0], []).append((len(snake.history) - 1, "text", False))
        for goal in stroke_order(snake.body[0], letter, toward):
            if goal not in todo:
                continue
            for cell in snake.path_to(goal, avoid=upcoming):
                t = snake.move(cell)
                if cell in todo:
                    todo.discard(cell)
                    events.setdefault(cell, []).append((t, "text", False))

    # leave through the right edge, then hold the finished text on screen
    exit_row = snake.body[0][1]
    for cell in snake.path_to((width, exit_row)):
        snake.move(cell)
    for i in range(1, SNAKE_LEN + 1):
        snake.move((width + i, exit_row))

    # rainbow wave sweeping across the text while it is held
    hold_start = len(snake.history) - 1
    fade_out = snake.wait(HOLD_STEPS)
    fade_in = snake.wait(FADE_STEPS)
    end = snake.wait(FADE_STEPS)
    for letter in letters:
        for x, y in letter:
            timeline = events[(x, y)]
            for j in range(0, HOLD_STEPS, RAINBOW_EVERY):
                hue = RAINBOW[(j // RAINBOW_EVERY - x // 2) % len(RAINBOW)]
                timeline.append((hold_start + j, hue, False))
            timeline.append((fade_out, hue, False))
            timeline.append((fade_in, "empty", True))

    # eaten contributions come back, ending exactly where the loop starts
    for (x, y), level in grid.items():
        if level and (x, y) in events:
            timeline = events[(x, y)]
            if timeline[-1][0] != fade_in:  # letters already faded to empty at fade_in
                timeline.append((fade_in, "empty", False))
            timeline.append((end, "l%d" % level, True))
    # bar pieces grouped by level, each group filling left to right as it is eaten
    eaten.sort(key=lambda e: (e[1], e[0]))
    return snake.history, events, eaten, (fade_out, fade_in)


def pct(t, total):
    return ("%.3f" % (100 * t / total)).rstrip("0").rstrip(".")


def resolve_color(key, palette):
    if key in palette:
        return palette[key]
    if key.startswith("l"):
        return palette["levels"][int(key[1:]) - 1]
    return key


def render(width, grid, history, events, eaten, bar_fade, palette):
    total = len(history) - 1
    duration = total * STEP_MS
    css = [
        ".c{shape-rendering:geometricPrecision;fill:%s;stroke-width:1px;stroke:%s;"
        "animation:none %dms step-end infinite}" % (palette["empty"], palette["border"], duration),
        ".s{shape-rendering:geometricPrecision;fill:%s;animation:none %dms linear infinite}" % (palette["snake"], duration),
        ".b{shape-rendering:crispEdges;opacity:0;animation:none %dms step-end infinite}" % duration,
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
            frames = [[0, "fill:%s" % start]]
            for t, key, fade in timeline:
                if fade:
                    # a keyframe's timing function applies to the interval after it
                    frames[-1][1] += ";animation-timing-function:linear"
                frames.append([t, "fill:%s" % resolve_color(key, palette)])
            if frames[-1][0] != total:
                frames.append([total, frames[-1][1]])
            css.append("@keyframes %s{%s}" % (name, "".join("%s%%{%s}" % (pct(t, total), d) for t, d in frames)))
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

    # progress bar below the grid: one piece per eaten contribution, in eating order
    bar = []
    bar_x, bar_w = (CELL - DOT) / 2, width * CELL - (CELL - DOT)
    bar_y = (ROWS + 1) * CELL + BAR_GAP
    for i, (t, level) in enumerate(eaten):
        name = "b%d" % i
        css.append("@keyframes %s{0%%{opacity:0}%s%%,100%%{opacity:1}}" % (name, pct(t, total)))
        piece = bar_w / len(eaten)
        # pieces overlap by half a pixel so no seams show between them
        bar.append('<rect class="b" style="animation-name:%s" fill="%s" x="%g" y="%d" width="%g" height="%d"/>'
                   % (name, palette["levels"][level - 1], bar_x + i * piece, bar_y, piece + 0.5, BAR_HEIGHT))

    # the bar fades out as one group, so the overlapping pieces don't show seams
    css.append(".bar{animation:bar %dms linear infinite}"
               "@keyframes bar{0%%,%s%%{opacity:1}%s%%,100%%{opacity:0}}"
               % (duration, pct(bar_fade[0], total), pct(bar_fade[1], total)))

    w, h = width * CELL + 2 * CELL, bar_y + BAR_HEIGHT + 2 * CELL
    return ('<svg viewBox="%d %d %d %d" width="%d" height="%d" xmlns="http://www.w3.org/2000/svg">'
            "<desc>Snake eats the contribution graph, then writes %s</desc>"
            "<style>%s</style>%s%s%s</svg>\n"
            % (-CELL, -CELL, w, h, w, h, TEXT, "".join(css), "".join(cells), '<g class="bar">%s</g>' % "".join(bar), "".join(segments)))


def main(argv):
    if len(argv) != 3:
        raise SystemExit(__doc__)
    width, grid = demo_grid() if argv[1] == "--demo" else fetch_grid(argv[1])
    history, events, eaten, bar_fade = simulate(width, grid, text_cells(TEXT, width))
    os.makedirs(argv[2], exist_ok=True)
    for name, palette in (("github-contribution-grid-snake.svg", PALETTES["light"]),
                          ("github-contribution-grid-snake-dark.svg", PALETTES["dark"])):
        with open(os.path.join(argv[2], name), "w") as f:
            f.write(render(width, grid, history, events, eaten, bar_fade, palette))
    print("%d steps, %.1fs loop" % (len(history) - 1, (len(history) - 1) * STEP_MS / 1000))


if __name__ == "__main__":
    main(sys.argv)

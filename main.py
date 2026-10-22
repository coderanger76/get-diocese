#!/usr/bin/env python3
"""
get-diocese — Random US Catholic Diocese Explorer
"""

import json
import os
import re
import sqlite3
import sys
import termios
import textwrap
import tty
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────
DIR       = Path(__file__).parent
DB_PATH   = DIR / "diocese.db"
SEED_PATH = DIR / "dioceses.json"
WIDTH     = 80
UA        = "get-diocese/1.0 (terminal explorer; https://github.com/coderanger76/currents)"
TIMEOUT   = 10

# ── ANSI ──────────────────────────────────────────────────────────────────────
RESET      = "\033[0m"
BOLD       = "\033[1m"
BG_AMBER   = "\033[48;5;214m"
BG_DKGRAY  = "\033[100m"
FG_BLACK   = "\033[30m"
FG_AMBER   = "\033[38;5;214m"
FG_MAGENTA = "\033[95m"
FG_WHITE   = "\033[97m"
FG_LTGRAY  = "\033[37m"
FG_DKGRAY  = "\033[90m"
FG_RED     = "\033[91m"
FG_CYAN    = "\033[96m"

ANSI_RE = re.compile(r'\033\[[0-9;]*m')

def c(text, *codes):
    return "".join(codes) + str(text) + RESET

def visible_len(s):
    return len(ANSI_RE.sub('', s))

def rpad(s, width):
    diff = width - visible_len(s)
    return s + " " * max(diff, 0)

def getch():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch

# ── Database ──────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dioceses (
            id             INTEGER PRIMARY KEY,
            name           TEXT NOT NULL,
            diocese_type   TEXT,
            state          TEXT,
            city           TEXT,
            wikipedia      TEXT,
            url            TEXT,
            url_verified   INTEGER DEFAULT 0,
            visited        INTEGER DEFAULT 0,
            last_visited   TEXT,
            bishop         TEXT,
            founded        TEXT,
            catholics      TEXT,
            parishes       TEXT,
            priests        TEXT,
            deacons        TEXT,
            population     TEXT,
            area           TEXT,
            cathedral      TEXT,
            summary        TEXT,
            website_excerpt TEXT,
            cached_at      TEXT
        )
    """)
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM dioceses").fetchone()[0]
    if count == 0 and SEED_PATH.exists():
        with open(SEED_PATH) as f:
            seed = json.load(f)
        conn.executemany(
            "INSERT INTO dioceses (name, diocese_type, state, city, wikipedia, url) VALUES (?,?,?,?,?,?)",
            [(d['name'], d.get('type','diocese'), d.get('state',''), d.get('city',''),
              d.get('wikipedia',''), d.get('url','')) for d in seed]
        )
        conn.commit()
    return conn


def pick_random(conn):
    row = conn.execute(
        "SELECT * FROM dioceses WHERE visited = 0 ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT * FROM dioceses ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
    return dict(row)


def count_visited(conn):
    return conn.execute("SELECT COUNT(*) FROM dioceses WHERE visited > 0").fetchone()[0]


def save_result(conn, diocese_id, data):
    conn.execute("""
        UPDATE dioceses SET
            visited         = visited + 1,
            last_visited    = ?,
            bishop          = COALESCE(NULLIF(?, ''), bishop),
            founded         = COALESCE(NULLIF(?, ''), founded),
            catholics       = COALESCE(NULLIF(?, ''), catholics),
            parishes        = COALESCE(NULLIF(?, ''), parishes),
            priests         = COALESCE(NULLIF(?, ''), priests),
            deacons         = COALESCE(NULLIF(?, ''), deacons),
            population      = COALESCE(NULLIF(?, ''), population),
            area            = COALESCE(NULLIF(?, ''), area),
            cathedral       = COALESCE(NULLIF(?, ''), cathedral),
            summary         = COALESCE(NULLIF(?, ''), summary),
            website_excerpt = COALESCE(NULLIF(?, ''), website_excerpt),
            cached_at       = ?,
            url             = COALESCE(NULLIF(?, ''), url),
            url_verified    = 1
        WHERE id = ?
    """, (
        datetime.now().isoformat(),
        data.get('bishop',''), data.get('founded',''), data.get('catholics',''),
        data.get('parishes',''), data.get('priests',''), data.get('deacons',''),
        data.get('population',''), data.get('area',''), data.get('cathedral',''),
        data.get('summary',''), data.get('website_excerpt',''),
        datetime.now().isoformat(), data.get('url',''),
        diocese_id,
    ))
    conn.commit()

# ── Network helpers ───────────────────────────────────────────────────────────

SESSION = requests.Session()
SESSION.headers['User-Agent'] = UA


def validate_url(url):
    if not url:
        return url
    try:
        r = SESSION.head(url, allow_redirects=True, timeout=TIMEOUT)
        return r.url
    except Exception:
        try:
            r = SESSION.get(url, allow_redirects=True, timeout=TIMEOUT, stream=True)
            r.close()
            return r.url
        except Exception:
            return url


def clean(text):
    text = re.sub(r'\[.*?\]', '', text)       # strip [1], [note 1]
    text = text.replace('\xa0', ' ')          # non-breaking spaces
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


FLAG_RE = re.compile(r'flag_of', re.I)
COAT_RE = re.compile(r'coat_of_arms', re.I)


def _protocol_relative(url):
    return 'https:' + url if url.startswith('//') else url


def _best_src(img):
    """Prefer the 2x entry in srcset (a real, Wikipedia-approved higher-res
    render) over the bare src, which is usually a small 250px infobox thumb."""
    srcset = img.get('srcset', '')
    if srcset:
        first = srcset.split(',')[0].strip().split(' ')[0]
        if first:
            return _protocol_relative(first)
    return _protocol_relative(img.get('src', ''))


def extract_infobox_images(infobox):
    """Best-effort pick of the cathedral photo, coat-of-arms, and diocesan-map
    images out of the infobox. Coat of arms is reliable (filename always says
    so). The cathedral photo and map have no consistent labeling, so they're a
    heuristic: of the images that are neither the coat of arms nor a flag icon,
    the first is the cathedral photo (it's always the infobox's lead image) and
    the last is the map (assuming there are at least two such images)."""
    imgs = []
    for img in infobox.find_all('img'):
        src = img.get('src', '')
        if not src:
            continue
        width = img.get('width')
        imgs.append({
            'src': src,
            'hi_res': _best_src(img),
            'width': int(width) if width and width.isdigit() else None,
        })

    coat_url = ''
    for im in imgs:
        if COAT_RE.search(im['src']):
            coat_url = im['hi_res']
            break

    others = [
        im for im in imgs
        if not COAT_RE.search(im['src'])
        and not FLAG_RE.search(im['src'])
        and (im['width'] is None or im['width'] > 48)
    ]
    cathedral_url = others[0]['hi_res'] if others else ''
    map_url = others[-1]['hi_res'] if len(others) >= 2 else ''

    return coat_url, cathedral_url, map_url


def fetch_wikipedia(slug):
    data = {}
    if not slug:
        return data

    encoded = quote(slug, safe='')

    # REST summary — clean paragraph
    try:
        r = SESSION.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}",
            timeout=TIMEOUT
        )
        if r.ok:
            j = r.json()
            data['summary'] = j.get('extract', '')
    except Exception:
        pass

    # Full page HTML — infobox scrape
    try:
        r = SESSION.get(f"https://en.wikipedia.org/wiki/{encoded}", timeout=TIMEOUT)
        if not r.ok:
            return data
        soup = BeautifulSoup(r.text, 'html.parser')
        infobox = soup.find('table', class_=re.compile(r'\binfobox\b'))
        if not infobox:
            return data

        coat_url, cathedral_url, map_url = extract_infobox_images(infobox)
        if coat_url:
            data['coat_of_arms_url'] = coat_url
        if cathedral_url:
            data['cathedral_photo_url'] = cathedral_url
        if map_url:
            data['map_url'] = map_url

        for row in infobox.find_all('tr'):
            th = row.find('th')
            td = row.find('td')
            if not th or not td:
                continue
            key = th.get_text(' ', strip=True).lower()
            val = clean(td.get_text(' ', strip=True))
            if not val:
                continue

            if any(k in key for k in ('bishop', 'archbishop', 'ordinary', 'administrator')):
                data.setdefault('bishop', val)
            elif any(k in key for k in ('founded', 'established', 'erected', 'created')):
                data.setdefault('founded', val)
            elif 'cathedral' in key:
                data.setdefault('cathedral', val)
            elif 'parish' in key:
                data.setdefault('parishes', val)
            elif 'priest' in key and 'deacon' not in key:
                data.setdefault('priests', val)
            elif 'deacon' in key:
                data.setdefault('deacons', val)
            elif 'population' in key and ('total' in key or 'catholic' in key):
                # Combined row e.g. "Population Total Catholics" -> split both out
                val_clean = re.sub(r'\(as of \d{4}\)', '', val)
                nums = [n for n in re.findall(r'[\d,]+', val_clean)
                        if len(n.replace(',', '')) >= 4]
                pct = re.search(r'\([\d.]+%\)', val)
                pct_str = f' {pct.group()}' if pct else ''
                if len(nums) >= 2:
                    data.setdefault('population', nums[0])
                    data.setdefault('catholics', nums[1] + pct_str)
                elif nums:
                    data.setdefault('catholics', nums[0] + pct_str)
            elif 'member' in key or 'catholic' in key:
                data.setdefault('catholics', val)
            elif 'population' in key:
                data.setdefault('population', val)
            elif 'area' in key and 'sq' in val.lower():
                data.setdefault('area', val)
    except Exception:
        pass

    return data


def fetch_website_excerpt(url):
    if not url:
        return ''
    try:
        r = SESSION.get(url, timeout=TIMEOUT)
        if not r.ok:
            return ''
        soup = BeautifulSoup(r.text, 'html.parser')

        # Hunt for an about/history page link
        target = None
        for a in soup.find_all('a', href=True):
            text = a.get_text(strip=True).lower()
            href = a['href']
            if any(kw in text for kw in ('about', 'history', 'our diocese', 'who we are', 'overview')):
                if href.startswith('http'):
                    target = href
                elif href.startswith('/'):
                    target = urljoin(url, href)
                if target:
                    break

        fetch_url = target or url
        if target:
            try:
                r = SESSION.get(fetch_url, timeout=TIMEOUT)
                if not r.ok:
                    fetch_url = url
                    r = SESSION.get(url, timeout=TIMEOUT)
            except Exception:
                fetch_url = url
                r = SESSION.get(url, timeout=TIMEOUT)

        soup = BeautifulSoup(r.text, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            tag.decompose()

        main = (soup.find('main') or
                soup.find('article') or
                soup.find('div', class_=re.compile(r'content|main|body', re.I)))
        text = (main or soup).get_text(' ', strip=True)
        text = re.sub(r'\s+', ' ', text)

        sentences = re.split(r'(?<=[.!?])\s+', text)
        good = [s for s in sentences if len(s) > 50][:5]
        return ' '.join(good)[:700]
    except Exception:
        return ''

# ── Display ───────────────────────────────────────────────────────────────────

def divider(label='', color=FG_AMBER):
    if label:
        inner = f"─── {label} "
        trail = "─" * max(0, WIDTH - len(inner) - 1)
        print(c(f" {inner}{trail}", color))
    else:
        print(c(" " + "─" * (WIDTH - 2), FG_DKGRAY))


def wrap_print(text, indent=2, color=FG_LTGRAY, max_lines=6):
    if not text:
        return
    lines = textwrap.wrap(text, WIDTH - indent - 1)
    for line in lines[:max_lines]:
        print(c(" " * indent + line, color))


def stat_pair(label1, val1, label2='', val2=''):
    if not val1 and not val2:
        return
    if not val1:
        # only the second value is present — print it alone rather than
        # dropping the whole row
        print(c(f"  {label2:<18}", FG_AMBER, BOLD) + c(val2, FG_WHITE))
        return
    left = c(f"  {label1:<18}", FG_AMBER, BOLD) + c(val1, FG_WHITE)
    if label2 and val2:
        pad = " " * max(0, 42 - visible_len(left))
        right = c(f"{label2:<14}", FG_AMBER, BOLD) + c(val2, FG_WHITE)
        print(left + pad + c("│  ", FG_DKGRAY) + right)
    else:
        print(left)


def render(diocese, data, total, visited, toast=''):
    os.system('clear')
    name  = diocese['name'].upper()
    dtype = (diocese['diocese_type'] or 'diocese').upper()
    state = diocese.get('state', '')
    city  = diocese.get('city', '')

    # ── Header bar ────────────────────────────────────────────────────────────
    print()
    tag  = f"FAITH · {dtype} "
    left = f" {name}"
    gap  = WIDTH - visible_len(left) - len(tag)
    print(c(rpad(left + " " * max(gap, 1) + tag, WIDTH), BG_AMBER, FG_BLACK, BOLD))

    # Sub bar: city/state + founded
    founded = data.get('founded') or diocese.get('founded') or ''
    parts = []
    if city and state:
        parts.append(f"{city}, {state}")
    elif state:
        parts.append(state)
    if founded:
        parts.append(f"Founded {founded}")
    sub = "  " + "  ·  ".join(parts) if parts else ''
    if sub:
        print(c(rpad(sub, WIDTH), BG_DKGRAY, FG_AMBER))
    print()

    # ── Bishop / Cathedral ────────────────────────────────────────────────────
    bishop   = data.get('bishop') or diocese.get('bishop') or ''
    cathedral = data.get('cathedral') or diocese.get('cathedral') or ''
    leader   = "ARCHBISHOP" if dtype == 'ARCHDIOCESE' else ("BISHOP" if dtype != 'EPARCHY' else "BISHOP/EPARCH")
    if bishop:
        print(c(f"  {leader:<18}", FG_AMBER, BOLD) + c(bishop, FG_WHITE))
    if cathedral:
        print(c(f"  {'CATHEDRAL':<18}", FG_AMBER, BOLD) + c(cathedral, FG_WHITE))
    if bishop or cathedral:
        print()

    # ── Statistics ────────────────────────────────────────────────────────────
    catholics  = data.get('catholics')  or diocese.get('catholics')  or ''
    parishes   = data.get('parishes')   or diocese.get('parishes')   or ''
    priests    = data.get('priests')    or diocese.get('priests')    or ''
    deacons    = data.get('deacons')    or diocese.get('deacons')    or ''
    population = data.get('population') or diocese.get('population') or ''
    area       = data.get('area')       or diocese.get('area')       or ''

    if any([catholics, parishes, priests, deacons, population, area]):
        divider("STATISTICS", FG_MAGENTA)
        stat_pair("Catholics",        catholics)
        stat_pair("Total Population", population)
        stat_pair("Parishes",         parishes,  "Priests",  priests)
        stat_pair("Deacons",          deacons,   "Area",     area)
        print()

    # ── About ─────────────────────────────────────────────────────────────────
    summary = data.get('summary') or diocese.get('summary') or ''
    if summary:
        divider("ABOUT", FG_MAGENTA)
        wrap_print(summary)
        print()

    # ── From the Diocese ──────────────────────────────────────────────────────
    excerpt = data.get('website_excerpt') or diocese.get('website_excerpt') or ''
    if excerpt and excerpt[:80] not in (summary or '')[:80]:
        divider("FROM THE DIOCESE", FG_MAGENTA)
        wrap_print(excerpt)
        print()

    # ── Sources ───────────────────────────────────────────────────────────────
    divider("SOURCES", FG_DKGRAY)
    if diocese.get('wikipedia'):
        slug_disp = diocese['wikipedia']
        print(c("  Wikipedia  ", FG_DKGRAY) + c(f"en.wikipedia.org/wiki/{slug_disp}", FG_CYAN))
    site = data.get('url') or diocese.get('url') or ''
    if site:
        domain = re.sub(r'^https?://(www\.)?', '', site).rstrip('/')
        print(c("  Website    ", FG_DKGRAY) + c(domain, FG_CYAN))
    print()

    # ── Footer ────────────────────────────────────────────────────────────────
    footer  = rpad(
        c(" L ", BG_AMBER, FG_BLACK, BOLD) + c(" LUCKY  ", BG_DKGRAY, FG_LTGRAY) +
        c(" P ", BG_AMBER, FG_BLACK, BOLD) + c(" PRESENT  ", BG_DKGRAY, FG_LTGRAY) +
        c(" ANY KEY ", BG_AMBER, FG_BLACK, BOLD) + c(" RETURN  ", BG_DKGRAY, FG_LTGRAY) +
        c(f"  {visited}/{total} visited", FG_DKGRAY),
        WIDTH
    )
    print(c(footer, BG_DKGRAY))
    if toast:
        print(c(f"  {toast}", FG_CYAN))

# ── Status line ───────────────────────────────────────────────────────────────

def status(msg):
    os.system('clear')
    print()
    print(c(f"  {msg}", FG_DKGRAY))

# ── Main ──────────────────────────────────────────────────────────────────────

def load_diocese(conn):
    diocese = pick_random(conn)

    status(f"Loading {diocese['name']}...")

    url = diocese.get('url', '')
    if not diocese.get('url_verified'):
        print(c("  Validating URL...", FG_DKGRAY))
        url = validate_url(url) or url

    data = {'url': url}

    if diocese.get('wikipedia'):
        print(c("  Fetching Wikipedia...", FG_DKGRAY))
        data.update(fetch_wikipedia(diocese['wikipedia']))

    print(c("  Fetching diocese website...", FG_DKGRAY))
    data['website_excerpt'] = fetch_website_excerpt(url)

    save_result(conn, diocese['id'], data)

    # Merge fresh data over the db row for display
    diocese.update({k: v for k, v in data.items() if v})
    return diocese, data


STAT_FIELDS = (
    ('catholics',  'Catholics'),
    ('population', 'Total Population'),
    ('parishes',   'Parishes'),
    ('priests',    'Priests'),
    ('deacons',    'Deacons'),
    ('area',       'Area'),
)

FORMAT_KEYS = {
    'l': ['landscape'],
    'p': ['portrait'],
    's': ['square'],
    'm': ['mobile'],
    'a': ['landscape', 'portrait', 'square', 'mobile'],
}


def prompt_overrides(diocese, data):
    """Cooked-mode text prompts for the stat fields Wikipedia's infobox often
    leaves out. Enter keeps the current value; anything typed replaces it."""
    print()
    print(c("  Adjust figures — Enter keeps the current value.", FG_DKGRAY))
    print()
    overrides = {}
    for key, label in STAT_FIELDS:
        current = data.get(key) or diocese.get(key) or ''
        try:
            val = input(c(f"  {label} [{current or '—'}]: ", FG_AMBER))
        except (EOFError, KeyboardInterrupt):
            break
        val = val.strip()
        if val:
            overrides[key] = val
    return overrides


def main():
    conn  = init_db()
    total = conn.execute("SELECT COUNT(*) FROM dioceses").fetchone()[0]

    diocese = data = None
    toast = ''
    while True:
        if diocese is None:
            diocese, data = load_diocese(conn)

        render(diocese, data, total, count_visited(conn), toast)
        toast = ''

        ch = getch()
        if ch.lower() == 'l':
            diocese = None
            continue
        if ch.lower() == 'p':
            status("Adjust figures before generating? [y/N]")
            resp = getch()
            if resp.lower() == 'y':
                overrides = prompt_overrides(diocese, data)
                if overrides:
                    save_result(conn, diocese['id'], overrides)
                    data.update(overrides)
                    diocese.update(overrides)

            status("Format?  [L]andscape  [P]ortrait  [S]quare  [M]obile  [A]ll four")
            fmt_resp = getch().lower()
            fmts = FORMAT_KEYS.get(fmt_resp, ['landscape'])

            status("Building presentation image...")
            try:
                from presentation import build_presentation
                names = [build_presentation(diocese, data, fmt=f).name for f in fmts]
                toast = f"Saved {', '.join(names)} and opened — press any other key to exit, L to reroll"
            except Exception as e:
                toast = f"Presentation failed: {e}"
            continue
        break

    conn.close()


if __name__ == '__main__':
    main()

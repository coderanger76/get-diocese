# get-diocese

A terminal explorer for the 183 Latin-rite dioceses, archdioceses, and Eastern-rite eparchies of the United States. Press a key and it picks a diocese you haven't seen yet, gathers facts from Wikipedia and the diocese's own website, caches them in SQLite, and renders a styled card in your terminal. Press `P` to turn the card into a shareable PNG.

It is also module of the [Currents](https://github.com/coderanger76/currents) terminal suite.
<img width="672" height="495" alt="image" src="https://github.com/user-attachments/assets/66aebd50-c71b-4131-b527-e9774223f5d9" />

## What you get

Bishop, founding date, cathedral, Catholic and total population, parishes, priests, deacons, area, a Wikipedia summary, and an excerpt from the diocese's own "About" or "History" page. No API keys are needed.
<img width="661" height="544" alt="image" src="https://github.com/user-attachments/assets/69740dba-efbc-4f6a-81cb-9cbadf5f8197" />

## Install

```bash
git clone https://github.com/coderanger76/get-diocese.git
cd get-diocese
python3 -m venv venv
venv/bin/pip install -r requirements.txt
./get-diocese
```

Requires Python 3.9+ on macOS or Linux (it uses `termios` for single-keypress input).

## Keys

| Key | Action |
|-----|--------|
| `L` | Reroll ("feeling lucky") |
| `P` | Present: render the current diocese as a PNG card |
| any other | Quit |

### Present (`P`)

`P` first offers to adjust the figures. Wikipedia infoboxes are often incomplete, so you can type in missing numbers. Corrections are written back to the local cache. Then pick a format:

| Key | Format | Size | Good for |
|-----|--------|------|----------|
| `L` | landscape | 1600×900 | X/Twitter desktop |
| `P` | portrait | 1080×1350 | Instagram feed |
| `S` | square | 1080×1080 | Instagram square |
| `M` | mobile | 1080×1920 | Phone screens |
| `A` | all four | | |

Cards are written to `presentation_<format>.png` next to the script, and open in Preview on macOS. Sample output is in [`examples/`](examples/). The footer handles are set in `presentation.py`; change them to your own.
<img width="1600" height="900" alt="image" src="https://github.com/user-attachments/assets/dd2701a2-a89c-4e36-81be-c63ee15d4aec" />

## Data

- `dioceses.json` is the seed list (name, type, state, city, Wikipedia slug, website). `diocese.db` is created from it on first run.
- Fields already cached are never overwritten with blanks, so data only accumulates.
- Sources are Wikipedia (REST summary plus infobox) and each diocese's own site. Requests identify themselves with an honest User-Agent.

See [NOTES.md](NOTES.md) for design notes and history.

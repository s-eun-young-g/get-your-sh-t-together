# strata

A personal productivity app with layers instead of one long list. Built for a brain that needs the day assembled for it, dreaded tasks handled specially, and structure that grows without nagging.

## Sections

- **Home**: your horizon (a short manifesto composed right on the page), the daily frog, a Today list that assembles itself from each tab's next-up thing (pinned tasks, the most urgent item per work area, what you are learning, whatever life says is due), the frog pen, and one gamified tile per tab. Quick-jot from any page; the inbox is a tile that opens sort mode, which deals unsorted items one at a time.
- **Frogs**: calls, emails, and scheduling live in their own pen so dread cannot contaminate the board. One frog a day on the home page; blitz mode deals the rest one at a time.
- **Work**: add as many work areas as you have lives (kinds: job, school, growth). Every task requires a deadline (exact, approximate, or just "soon", typed in any date format) and gets a computed burden from a time-estimate slider and a dread level. Jobs hold named areas; school holds classes and assignments with Canvas pull-sync; growth holds moves (dated actions with a description) and a monologue. Any area or class hides, shows, archives, or deletes. Meetings (per-workspace bring-up-next-time lists, dateable) attach to jobs and schools.
- **Life**: sections you add and remove in place. Routines (recurring upkeep, no streaks, resurfaces when due), financials (upcoming charges visible, the full recurring list hidden until asked, plus credit cards with what-to-use-it-for and biggest-wins notes), appointments (needs-booking versus booked), grocery lists (reusable lists, fresh checklist per run, mid-run additions offered back), evening plans (time-block lists with computed clock times), and packing (same machinery as groceries, for trips).
- **Model**: boards with nestable buckets (sub-buckets inside buckets) and cards, plus autosaving notes. Boards start empty; the structure is yours.
- **Learn**: curated dependency trees for finance, hardware, software, AI, the startup ecosystem, and biotech. Track pages list everything; clicking an item's title opens its own notes and sources (as many as you want). Mark any number of items "learning now". Day streaks log automatically when you complete items. Import your ChatGPT or Claude data export and map old learning chats into the trees.
- **Pause**: park an impulse (shopping, food, social) behind a wait you pick on a slider, 30 minutes to indefinitely. "Let it go" and "I didn't wait" are always available; the record keeps both lists and your worth-it/regretted verdicts. The stat that matters: how many impulses waiting killed for free.

## Run locally

Double-click `run.command`, or:

```
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
./.venv/bin/python -m strata.app
```

Open http://localhost:8020. Your phone can reach it at your laptop's LAN address on the same wifi.

## Launch (fly.io)

The app ships with a Dockerfile and fly.toml. SQLite lives on a small persistent volume and the machine sleeps when idle, so hosting is cheap (a few dollars a month at most).

```
brew install flyctl
fly auth signup            # or: fly auth login
fly launch --no-deploy     # accept the existing fly.toml, pick a unique app name
fly volumes create strata_data --size 1 --region bos
fly secrets set STRATA_PASSWORD=pick-a-strong-one
fly deploy
```

A password is mandatory before deploying; without it the whole app is public.

Optional secrets, same pattern: `ANTHROPIC_API_KEY` (Claude mapping for imports), `CANVAS_BASE_URL` + `CANVAS_TOKEN` (school sync), `STRATA_CAPTURE_TOKEN` (lets Slack workflows, Zapier/Granola automations, and iOS Shortcuts post into the inbox once the app has a public URL), `GCAL_ICS_URL` (shows Google Calendar events on home and in life; the secret iCal address from calendar settings, several separated by commas).

Bring existing local data along:

```
fly ssh sftp shell
put /Users/you/.strata/strata.db /data/strata.db
```

then `fly apps restart`. Redeploys keep the volume; migrations run automatically at startup.

On a phone, open the app's URL and use "add to home screen".

## Configuration

Copy `.env.example` to `.env`; everything is optional locally. Data lives in `~/.strata`. The server listens on 0.0.0.0, so set `STRATA_PASSWORD` if you do not want your whole wifi network reading your tasks.

Capture API, for feeding the inbox from anywhere:

```
curl -X POST https://your-app.fly.dev/api/capture \
  -H "Authorization: Bearer YOUR_TOKEN" -H "Content-Type: application/json" \
  -d '{"title": "follow up with vendor", "source": "slack", "workspace": "sedona"}'
```

## Personalization

The settings page holds your name, your horizon, and toggles for the life sections and pause. Work areas are added and named on the work page itself. Switching anything off hides it everywhere; nothing is deleted. Learning trees seed from `seeds/learn/*.yaml`; sync never touches your progress or additions, and slugs are permanent identifiers.

## Tests

```
./.venv/bin/python -m pytest
```

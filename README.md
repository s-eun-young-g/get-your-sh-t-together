# strata

A personal productivity app with layers instead of one long list. Built for a brain that needs a live task board, packing lists that regenerate per trip, boards for thinking through projects, a nuisance pen for the tasks you dread, and a learning tracker that tells you what to learn next.

## Sections

- **Home**: your horizon (a short manifesto you write in settings, kept in view for motivation), the daily frog, and one tile per tab: a clickable, gamified summary (today progress, next deadline, upkeep due, learning streak, impulses let go) instead of more lists.
- **Now**: tasks in two layers (Today, Next) plus an Inbox. Quick-capture from any page, triage later. Today shows three things; the rest wait quietly. A sweep button demotes stale Today items instead of anything auto-resetting overnight.
- **Nuisances**: calls, emails, and appointments live in their own pen so they cannot contaminate the rest of the board. The home page serves exactly one per day. Blitz mode deals them one at a time when you have a burst of energy.
- **Work**: a hub with two halves. Job shows every task tagged "job" (tag from the board, add here directly, or let the capture API feed it). School holds classes and assignments sorted by deadline with a burden size (small, medium, big) so heavy things surface early; big assignments due within ten days get a "start now" chip. With `CANVAS_BASE_URL` and `CANVAS_TOKEN` set, one button pulls courses and assignments from Canvas; your burden edits and done states always survive a resync.
- **Life**: routines, evening plans, and packing. Routines are recurring upkeep (meds refills, laundry, dentist, backups) that resurface when due; there are no streaks stored, only "when did I last do this", so being late never accumulates guilt. A starter library of common ones can be added with one click. An evening plan is a loose list of home things with rough time blocks; give it a start time and each item gets a clock time, or skip the start time and it is just an ordered list with a running total.
- **Pack** (inside Life): reusable packing templates (conference, beach, international). Each trip snapshots the templates into a fresh checklist. Things you add mid-trip get offered back to a template when the trip closes.
- **Model**: boards with your own buckets for thinking through a move, a password system, or any reorganization. Cards plus a freeform notes area.
- **Learn**: curated learning trees for finance, hardware, software, AI, the startup ecosystem, and biotech. Each track leads with a headliner (what you marked as learning now, else the last thing you learned, else where to start), a progress bar, and a "..." that expands the unlocked items. Completing items builds a day streak (or log one manually); a per-track resources box records where you learned things (articles, books, PDFs, videos, courses). With an Anthropic API key set, a button asks Claude to propose new items, which you approve or dismiss.

## Run

Double-click `run.command`, or:

```
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
./.venv/bin/python -m strata.app
```

Then open http://localhost:8020. Your phone can reach it at your laptop's LAN address while on the same wifi.

## Configuration

Copy `.env.example` to `.env`. Everything is optional. Data lives in `~/.strata` by default.

Note on network exposure: the server listens on 0.0.0.0, so anyone on your wifi network can open it. Set `STRATA_PASSWORD` if that is not what you want. A password is mandatory before deploying this anywhere public.

The optional `ANTHROPIC_API_KEY` enables the "suggest with Claude" button in Learn. Suggestions are proposals only; nothing joins a tree without your approval.

The optional `STRATA_CAPTURE_TOKEN` enables `POST /api/capture`, so Slack workflows, Granola or Zapier automations, and iOS Shortcuts can drop tasks into your inbox, tagged with where they came from:

```
curl -X POST http://localhost:8020/api/capture \
  -H "Authorization: Bearer YOUR_TOKEN" -H "Content-Type: application/json" \
  -d '{"title": "follow up with vendor", "source": "slack", "context": "job"}'
```

Inbound pushes from cloud services reach the app once it is deployed or tunneled; until then the endpoint works from anything on your machine or wifi.

The optional `CANVAS_BASE_URL` plus `CANVAS_TOKEN` enable Canvas sync in Work > School. Sync is pull-only and works locally. Canvas owns assignment titles and due dates; you own burden sizes and done states.

## Importing your ChatGPT learning history

ChatGPT has no live API for chat history, so Learn > "import from ChatGPT" works from the official export: ChatGPT settings, Data controls, Export data, then upload the emailed zip (or the conversations.json inside it). The export does not say which folder a chat was in, so use the title filter and checkboxes to pick out your learning chats. Then either map them with Claude (proposes marking tree items you already covered as done, plus new items for topics your trees lack; everything lands as suggestions you approve) or add their titles directly to a track of your choice. Re-uploading a newer export replaces the unprocessed list and never duplicates what you already handled.

## Personalization

The settings page (top right) is the onboarding: switch each section on or off (job, school, routines, evening plans, packing) and name the work sections whatever you call them (Job or your company, School or your school). Switching a section off hides it everywhere, including the nav; nothing is deleted. Labels are display-only; nothing in the data model changes when you rename them.

## More modules

Work areas can each switch on two sub-modules: **waiting-on** (things delegated or blocked on other people, with gentle aging and a nudged-them log) and **agendas** (a running "bring up next time" list per recurring meeting or person). A third workspace kind, **growth**, is a pipeline for future plans (someday, researching, in motion, done): applications, moves, big maybes.

Life gained three toggleable sections: **bills and renewals** (date-anchored money things; marking one paid advances its date by its cadence, one-time renewals archive), **appointments** (two lists, needs-booking and booked, so nothing slips between them), and **meals and groceries** (a meal idea bank with this-week stars, plus a grocery list where staples reset each week and bought one-offs clear).

**Rescue** is for anhedonia days: an "I'm so bored I could die" button on the home page opens a list you filled on a good day with things that have ever helped, even once. It serves one suggestion at a time (when nothing appeals, choosing is the broken part), you log honestly whether it helped even if you forced it, and the running record ("forcing it has helped 9 of 13 times") becomes your own evidence against the feeling that nothing will help. Life sections can be added and removed directly on the life page; nothing is deleted when a section is removed.

**Pause** is its own tab for impulse control: park an impulse (shopping, food, social, other) behind a timer you choose. Letting go is allowed anytime; acting is only possible after the timer opens. Acted impulses ask for an honest worth-it or regretted-it verdict, and the stats celebrate what waiting killed for free while regret data stays neutral self-knowledge.

Still on the roadmap: reimbursements and expense chasing, keep-in-touch (birthdays, call cadence per person), home maintenance seasonals, errands, wishlist and gift ideas, pet care.

## Import roadmap

The capture API is the universal adapter: anything that can send an HTTP request can drop tasks into the inbox. Beyond that, imports built or plausible, all pull-based or export-based so they work without hosting:

- Canvas assignments (built): courses and deadlines into School.
- ChatGPT export (built): learning chats mapped into the Learn trees.
- Claude export: same idea as ChatGPT, similar JSON structure.
- Calendar (ICS URL): subscribe to a Google/Apple/Outlook calendar feed and show today's events on Home.
- Linear or GitHub issues assigned to you, into the job list.
- Todoist / Things / Apple Reminders exports: one-time migration into the board.
- Read-later and YouTube Watch Later exports: into Learn as items.
- Email: a forward-to-inbox address (needs hosting) or starred-mail polling (needs OAuth).

## Seeds

Learning trees live in `seeds/learn/*.yaml` and sync into the database at startup. Sync never touches your progress, your own added items, or accepted AI items. Slugs are permanent identifiers; rename items by changing titles, never slugs.

## Launch (fly.io)

The app ships with a Dockerfile and fly.toml. SQLite lives on a small persistent volume, and the machine sleeps when idle, so hosting costs are minimal (roughly a couple of dollars a month, often less).

One-time setup:

```
brew install flyctl
fly auth signup            # or: fly auth login
fly launch --no-deploy     # accept the existing fly.toml, pick a unique app name
fly volumes create strata_data --size 1 --region bos
fly secrets set STRATA_PASSWORD=pick-a-strong-one
fly deploy
```

A password is mandatory before deploying: without it the whole app is public.

Optional secrets, same pattern: `ANTHROPIC_API_KEY`, `CANVAS_BASE_URL`, `CANVAS_TOKEN`, `STRATA_CAPTURE_TOKEN` (setting the capture token is also what lets Slack workflows and Zapier/Granola automations post into the inbox, now that the app has a public URL).

To bring your existing local data along:

```
fly ssh sftp shell
put /Users/you/.strata/strata.db /data/strata.db
```

then restart with `fly apps restart`. Redeploys keep the volume; migrations run automatically at startup.

On your phone, open the app's URL and use "add to home screen" for an app-like icon.

## Tests

```
./.venv/bin/python -m pytest
```

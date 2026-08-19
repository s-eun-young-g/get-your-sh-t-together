# the guide

How to use get your sh*t together, written for someone opening it for the first time. For install and hosting steps, see the end.

## the idea

This is a personal productivity app built for a brain that does better when the day assembles itself. Instead of one long list that grows until you avoid it, everything is split into layers: a place to dump thoughts before you lose them, a home page that picks what matters today, a special pen for the tasks you dread, and separate tabs for work, life admin, thinking, and learning. Nothing nags. Nothing accumulates guilt.

Everything is yours alone: your own copy of the app, your own database, one password.

## home

The top of every page has a capture bar. Type anything, hit enter, and it lands in the inbox so you can stop holding it in your head. Check the "frog" box if the thing you are capturing is a task you dread.

The home page shows:

- **your horizon**: a few lines you write about where all this is going. It stays at the top so the day-to-day connects to something.
- **today**: assembled automatically from everything else: tasks you pinned, the next assignment due, a learn item in progress, bills that need paying, routines that are due, and calendar events if connected. Each has a tick. That is the whole interaction.
- **frog pen**: the dreaded tasks live here (eat the frog). They wait until you tick them, snooze them, or drop them, and the pen shows how long each has been waiting without judgment. "blitz" walks you through them one at a time.
- **tiles**: one per tab, each a one-glance summary. Click through when something needs you.

## inbox and sorting

Captured thoughts sit in the inbox until you sort them. Sorting is one decision per item: pin it to today, send it to a work area, frog it, or drop it. The inbox tile on home tells you how many are waiting.

If something pinned to today sits untouched for days, the app offers to sweep it back to the inbox rather than letting it rot on your list.

## work

Add one work area per job, school, or side gig. School areas hold classes and assignments (with Canvas sync if configured); job areas hold tasks grouped into named areas you define.

Every work task takes a deadline. It can be exact ("sep 12"), approximate, or just "soon", typed in any natural format. Each task also gets a burden estimate computed from a time slider and a dread level, and lists sort by deadline with the heaviest first, so the top of the list is always the honest answer to "what should I start?"

## life

Life is made of sections you can switch on and off in settings. Nothing is deleted when a section is off; it just leaves the screen.

- **routines**: recurring upkeep (laundry, meds refills). Each resurfaces when due. No streaks are kept, so being late never accumulates.
- **financials**: organized by what you have to do, not by category. "to pay" lists bills you pay by hand, with a tick that advances the date. "decide before it renews" surfaces renewals two weeks early so you can keep or cancel on purpose. "on autopilot" is a quiet ledger of autopay charges with your total recurring load per month. Cards are tracked with a name, what to use it for, the payment due date, and whether the card is daily, on occasion, or dead.
- **appointments**: two lists, needs-booking and booked, so nothing slips between them.
- **grocery lists and packing**: reusable templates that stamp out a fresh checklist per run or trip. Things you add mid-run are offered back to the template afterward.
- **evening plans**: loose after-work lists with time blocks; give the plan a start time and every item gets a clock time.

## model

For thinking, not tasks. A model is a page of categories (which nest, with unlimited depth) holding cards, plus a notes box that saves itself. Use it to lay out a decision, a move, a project, anything you need to see spatially. You can also import a Notion export and turn any Notion database into a model with one click.

## learn

Build dependency trees for anything you are learning. Categories start empty; add items by hand, or import your ChatGPT or Claude conversation history and map old learning chats into the trees. Items can require other items, so each category shows a frontier: the things you are ready to learn next. Tick items as you learn them, mark any number as "learning now", and a day streak logs itself. Categories can be renamed, merged, or deleted; items can be dropped.

## pause

Anti-impulsivity. Caught yourself about to buy, order, or send something? Park the impulse behind a timer, from 30 minutes to indefinite. When the timer runs out you decide again, calmly. The record keeps both outcomes, acted-on and let-go, plus your own worth-it verdicts. The stat that matters: how many impulses waiting killed for free.

## rescue

For flat days. A list of things that have ever helped, even once, even forced. It suggests one at a time and keeps an honest count of how often each actually helped, so the list gets smarter about you.

## getting your own copy

You need a Mac or Linux machine with Python 3.11+, or a fly.io account for hosting online.

Run it on your own machine:

```
git clone https://github.com/s-eun-young-g/get-your-sh-t-together.git
cd get-your-sh-t-together
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
./.venv/bin/python -m strata.app
```

Then open http://localhost:8020. On a Mac you can double-click run.command instead; it does all of the above. Your data lives in ~/.strata on your machine and never leaves it.

Host it online (reachable from your phone, about a dollar a month): follow the "Launch" section of the README. Set a password first; it is required before deploying.

Optional connections, each one line in a .env file (copy .env.example): Google Calendar events on your home page, Canvas assignment sync, a capture endpoint for Slack and iOS Shortcuts, and a Claude API key for mapping imports. The settings page shows what is connected and how to turn each one on.

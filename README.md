# 🔥 Dragonfire SEO

**Does Google take you seriously?** Torch any website. See what survives.

Dragonfire runs 40+ checks across five areas, scores each one, ranks what to fix first, and writes
it all up in plain English. The report looks the part, so you can send it to clients as it is.

| Area | What it asks |
|---|---|
| **Technical** | Can Google get in? robots.txt, sitemap, HTTPS, 404s, broken links, image weight, render-blocking files |
| **On-page** | Titles, descriptions, H1s, heading order, alt text, thin pages, share cards, orphan pages |
| **Schema** | Is there a LocalBusiness ID card, and is it filled in? FAQ, breadcrumbs, broken JSON-LD |
| **Local** | Towns in titles, a page per town, tap-to-call, Google Business Profile, reviews |
| **AI search** | Are ChatGPT/Claude/Perplexity bots allowed in? llms.txt, question headings, answer-first writing, dates, articles, sameAs |
| **AI visibility** *(optional)* | Asks the AIs "who's the best ___ in ___?" and checks whether your name comes up |

Every report also hands you a drafted `llms.txt` and a list of articles worth writing.

---

## First-time setup (about 5 minutes)

Do these steps once, in order. Type each command into the VS Code terminal, then press Enter.

**1. Open the project in VS Code.**
In VS Code, go to **File → Open Folder…**, pick `Documents/vscode-projects/dragonfire-seo`, and click **Open**.

**2. Open the terminal.**
In the menu, choose **Terminal → New Terminal**. It opens at the bottom of the window.

**3. Make a virtual environment** (a private box for this project's packages):

```bash
python3 -m venv .venv
```

**4. Switch it on:**

```bash
source .venv/bin/activate
```

✅ **Check:** your terminal prompt now starts with `(.venv)`.

**5. Install the packages:**

```bash
pip install -r requirements.txt
```

**6. Make your settings file:**

```bash
cp .env.example .env
```

Open `.env` in VS Code and change `DJANGO_SECRET_KEY` to any long random string. Leave everything else as it is for now.

**7. Build the database:**

```bash
python manage.py migrate
```

✅ **Check:** the output ends with a column of `OK`s.

**8. Run the tests:**

```bash
python manage.py test
```

✅ **Check:** the last line says `OK`.

---

## Using it

### Option A: the web app (best for clients)

```bash
python manage.py runserver
```

Open **http://127.0.0.1:8000** in your browser. Type a website, fill in the business name, what they
do and their towns, then hit **TORCH IT**.

On the report, **Download report** saves a single HTML file you can email to a client. To make a PDF,
open that file in Chrome and choose **File → Print → Save as PDF**. The print styles switch it to a clean
white layout.

### Option B: the terminal (quick check)

```bash
python manage.py torch https://sarahjhill.com --brand "Sarah J Hill" --service "web designer for tradeswomen" --towns "Cardiff, Birmingham"
```

You get a score card in the terminal, plus a full report saved in the `reports/` folder.

**Checking a site before you deploy it?** Point it at the folder instead of the URL. It works out the domain from the `CNAME` file:

```bash
python manage.py torch ~/Documents/vscode-projects/sarahjhill-redesign --brand "Sarah J Hill" --towns "Cardiff, Birmingham" --no-ai
```

### Switching on "Does AI recommend you?"

Open `.env` and paste in any keys you have, then restart the server:

```
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
PERPLEXITY_API_KEY=pplx-...
```

Each key you add becomes another column in the report. Perplexity is the most useful one, because it
searches the live web. The OpenAI and Anthropic APIs mostly answer from training data, so they lag behind.
Each torch asks about 4–6 questions per AI, which costs a few pence.

---

## 🧲 The free check: your client magnet

**`/free-check/`** is a public page for potential clients. Someone types in their website, first name and email,
ticks consent, and gets their **score, heat rating and top 3 problems** on screen straight away.
Then two things happen:

1. They land in **Leads** (`/admin/` → Leads) with their full report attached. You can change their status
   (New → Contacted → Call booked → Won) and export everyone to CSV.
2. You get an email alert, if email is set up in `.env`.

Their page tells them **you'll send the full report personally within two working days**. That's your opener:
open their report from the Leads list, click **Download report**, add a personal line or two, and email it.
It matches the Doubt Audit promise on your website.

**Try it on your laptop:** run the server, then open http://127.0.0.1:8000/free-check/.
To see the Leads list, first make yourself an admin login (once only):

```bash
python manage.py createsuperuser
```

### Putting it online (Heroku — same as SheQuotes)

Your website is static, so it can't run Python. The free check needs to live on Heroku, and your website links to it.

1. In the terminal, inside `dragonfire-seo`, make it a git repo and commit (with your own message):
   ```bash
   git init
   git branch -M main
   git add .
   git commit -m "your message here"
   ```
2. Create the app and a database:
   ```bash
   heroku create dragonfire-seo
   heroku addons:create heroku-postgresql:essential-0
   ```
3. Set the settings. Paste these one line at a time and change the values:
   ```bash
   heroku config:set DJANGO_DEBUG=0 DRAGONFIRE_PUBLIC=1 DRAGONFIRE_ALLOW_FOLDERS=0
   heroku config:set DJANGO_SECRET_KEY="any-long-random-string"
   heroku config:set DJANGO_ALLOWED_HOSTS=dragonfire-seo.herokuapp.com
   heroku config:set DJANGO_CSRF_TRUSTED_ORIGINS=https://dragonfire-seo.herokuapp.com
   heroku config:set DRAGONFIRE_LEAD_ALERT_TO=sarah@sarahjhill.com
   ```
   (Use the exact app name Heroku gave you in step 2.)
4. Deploy, then make your admin login on the live site:
   ```bash
   git push heroku main
   heroku run python manage.py createsuperuser
   ```
5. ✅ **Check:** open `https://YOUR-APP.herokuapp.com/free-check/`. It should load the form. Going to `/history/` should ask you to log in.
6. On your website, point the **"Get my free website review"** buttons on `website-audit.html` at
   `https://YOUR-APP.herokuapp.com/free-check/`. In `build-pages.py`, search for `Doubt%20Audit%20request` and
   swap that `mailto:` link for the URL, then run `python3 build-pages.py`.

**Want lead alerts by email?** Add an `EMAIL_HOST`, `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD` from your email provider
(most give you "SMTP settings") with `heroku config:set`.

Built-in protection: a hidden spam trap for bots, a limit of 5 checks per hour per person, private addresses refused,
and a crawl capped at 12 pages so it finishes inside Heroku's 30-second limit.

---

## How it's built

```
dragonfire-seo/
├── engine/                 ← the brains (plain Python, no Django needed)
│   ├── sources.py          ← fetches pages: LiveSource (crawler) or FolderSource (local files)
│   ├── page.py             ← turns HTML into facts (title, headings, schema, links…)
│   ├── checks.py           ← every check + the copy for each finding  ← edit the wording here
│   ├── ai_visibility.py    ← asks ChatGPT / Claude / Perplexity about you
│   └── runner.py           ← runs it all, scores it, picks the top 5 fixes
├── audits/                 ← the Django app (form, saved reports, downloads, `torch` command)
├── templates/audits/       ← the branded pages; brand colours live in _styles.html (:root)
└── reports/                ← HTML reports from the terminal command land here
```

**To add a check:** write a function in `engine/checks.py` that takes `c` and returns a `Finding`, then
add it to `ALL_CHECKS` at the bottom. It's scored and shown automatically.

**To rebrand for a client or partner:** change `DRAGONFIRE_AGENCY` and `DRAGONFIRE_AGENCY_URL` in `.env`.

---

## What Dragonfire deliberately doesn't do

The tool that inspired this one also runs a backlink-swap network and auto-posts brand mentions on
Reddit and Quora. Dragonfire leaves both out:

- **Link swap networks** break Google's spam policies ("excessive link exchanges"). A client site can be penalised for them.
- **Planted Reddit/Quora comments** break those sites' rules, get accounts banned, and don't fit a trust-first brand.

If anyone asks, that's the pitch: *the SEO tool that won't get you penalised.*

---

## Ideas for later

- Scheduled monthly re-torch for each client, with a "score went from 62 → 81" email
- A PageSpeed Insights API key for real Core Web Vitals
- Google Search Console connection for real clicks and keywords
- Article drafting in each client's voice, with an approve-before-publish step
- One-click publishing to WordPress through its REST API
- A public "free audit" page on sarahjhill.com as a lead magnet

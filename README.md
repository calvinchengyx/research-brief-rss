# Calvin Research Brief

An email every two weeks with new research from the journals and scholars I follow, organized by topic, laid out like the Nature Portfolio e‑alert.

> Status: **live**. Sent every other Monday at 06:00 UTC (`send_every_days: 14`). `recipe.html` describes the sources, model and the latest run.

## Running it

Everything runs on GitHub Actions (`.github/workflows/brief.yml`):

| How | What happens |
|-----|--------------|
| Any pull request | Builds a preview issue and commits it to `preview/latest.html` on that branch. No email. |
| Actions tab → *Research brief* → *Run workflow* → `preview` | Same, on the chosen branch. |
| … → `test` | Builds the issue and emails everyone in `config/recipients.yaml` with a `[TEST]` subject. Its articles count as sent, so they are not repeated in the next issue. |
| … → `send` | Emails everyone in `config/recipients.yaml`, archives the issue in `archive/`, and records sent articles in `state/seen.json` so they are never repeated. |
| Monday 06:00 UTC schedule | `send`, but only when `send_every_days` (14) have passed since the last issue in `archive/`; otherwise the run stops at once. |

Repository secrets used: `ANTHROPIC_API_KEY`, `BREVO_API_KEY`, `SENDER_EMAIL`, and optionally `OPENALEX_API_KEY`.

Locally: `pip install -r requirements.txt` then `python -m brief --mode preview` (tests: `python -m pytest`).

After every run, `state/following.md` lists what each journal, scholar, coauthor group and institution name was matched to in OpenAlex. Fix a wrong match by adding `issn:` (journals) or `openalex:` (scholars) to the entry.

**Deep dives by reply.** Every paper in the email has an ID (A1, B2 …; one letter per section in reading order). Readers reply with the IDs they want. A Google Apps Script in the receiving Gmail account (`docs/gmail-replies.gs`, setup steps at the top of the file) saves the top of each reply to `inbox/` every hour. The next run matches the IDs to the issue they answer (`state/issues/<date>.json`), writes a deep dive for each paper (research questions, methods, main findings; full text when open access, otherwise the abstract; cached in `state/deep_dives.json`) and puts those papers at the top of the issue. Handled replies are logged in `state/requests.json` and removed from `inbox/`. A paper comes back for as long as someone keeps asking for it.

**Code:** `brief/openalex.py` (lookups and fetching), `brief/resolve.py` (names → IDs, coauthor groups), `brief/classify.py` (social‑science filter, topics, relevance), `brief/select.py` (20‑article cap), `brief/render.py` + `templates/` (email), `brief/send.py` (Brevo/SMTP), `brief/deepdive.py` (reply IDs and deep dives), `brief/recipe.py` (recipe.html), `brief/pipeline.py` (one run end to end).

**v1 scope:** all fetching goes through OpenAlex (journals, conferences, scholars, and preprints from arXiv, SSRN, PsyArXiv, SocArXiv and OSF, all indexed there), with Semantic Scholar filling missing abstracts. Direct RSS and ACL Anthology feeds from §4 are not used yet.

---

## 1. What it does

Every week the brief:

1. **Journal watch**: collects every new article published in the journals on my journal list.
2. **Scholar watch**: checks whether any scholar on my scholar list published something new, in any venue.
3. **Overlap = Top priority**: an article that shows up in *both* (a listed scholar publishing in a listed journal) is flagged ⭐ and put at the top of the email.
4. Renders one newsletter, grouped by my three topics, and emails it to everyone in `recipients.yaml`.

## 2. The three topics

| # | Topic | What belongs here |
|---|-------|-------------------|
| 1 | Computational Social Science | Interdisciplinary journals and CSS research |
| 2 | Computational Linguistics | LLMs, NLP, and iSchool / information science journals |
| 3 | Communication & Science Communication | Communication, media, journalism, sci‑comm |

Every journal sits under exactly one topic. Scholar articles in a journal that is not on my list are placed under the scholar's default topic.

My own research areas, used only to highlight extra‑relevant papers (optional, see §6): online feminist discourse on Chinese platforms, LLM‑based content coding, gendered disinformation and narrative diffusion.

## 3. Editable files

All lists live in `config/` as plain YAML. To change the brief I edit a file and commit; no code changes.

```
config/
  topics.yaml       # the three topics, their order and display names
  journals.yaml     # journal list, each tagged with a topic
  scholars.yaml     # scholar list
  recipients.yaml   # who gets the email
  institutions.yaml # QS top 100 universities + top AI labs, for the preprint filter
  settings.yaml     # send day/time, look-back window, abstract length, keywords, preprint cap
```

**recipients.yaml**
```yaml
recipients:
  - owencheng1992930@gmail.com
  # - a.colleague@uni.edu
```

**topics.yaml**
```yaml
topics:
  - id: css
    name: Computational Social Science
  - id: cl
    name: Computational Linguistics
  - id: comm
    name: Communication & Science Communication
```

**journals.yaml** (`issn` is what the fetcher matches on; `filter: social-science` is for huge general journals and CL venues so they don't flood the brief)
```yaml
journals:
  - name: Nature Human Behaviour
    issn: 2397-3374
    topic: css
  - name: Nature Communications
    issn: 2041-1723
    topic: css
    filter: social-science  # keep only social-science-relevant papers
  - name: Journal of Communication
    issn: 0021-9916
    topic: comm
```

**scholars.yaml** (the OpenAlex ID / ORCID pins the right person, since names are ambiguous; a helper script looks these up and I confirm)
```yaml
scholars:
  - name: Jennifer Pan
    openalex: A5xxxxxxxx
    orcid: 0000-0000-0000-0000
    topic: css              # default topic for papers outside my journal list
```

### Journal list (from my notes, 21 Oct 2026)

My words, verbatim:

> must have
> (1) computational social science - nature, nature human behavior, nature communication, journal of computatioanl social science, natural portfolios except naturan humanities, social sciences and community & natural scientific reports (these two are bad journals); PNAS, and PNAS nexus; Science and Science advances,
> (2) Computational lisguistics: Main CL venues, like EMNLP, ACL, Neurps, and ICWSM, CSCW, WWW, EPJ data science, and related i-school venues (hosted by ACM, AAAI, and other computational linguistics proceedings) but publish social science related topcis (social media, and science, psychology related topics
> (3) communication journals: Journal of communication, News media and society, social media + society, big data and society, journal of communication research, those top tier communication journals.

How that is read below. Items marked *Proposed* were added by Claude to cover "those top tier…" and "related venues"; confirm or drop them.

**1. Computational Social Science**
- Nature
- Nature Human Behaviour
- Nature Communications
- Journal of Computational Social Science
- Other Nature Portfolio research journals (Nature Climate Change, Nature Cities, Nature Computational Science, Nature Machine Intelligence, Nature Sustainability, Nature Medicine, Nature Mental Health, …)
  - **Excluded:** Humanities and Social Sciences Communications; Scientific Reports
- PNAS
- PNAS Nexus
- Science
- Science Advances

The broad journals (Nature, Nature Communications, the wider Nature Portfolio, PNAS, Science, Science Advances) publish mostly natural science, so they get `filter: social-science` and only papers relevant to social science come through (see §4).

**2. Computational Linguistics (CL, CSS and iSchool venues)**
From these venues, only papers on social‑science topics (social media, science, psychology, society) are kept (`filter: social-science`).
- ACL (Annual Meeting of the ACL)
- EMNLP
- NeurIPS
- ICWSM (AAAI)
- CSCW (Proceedings of the ACM on Human‑Computer Interaction)
- The Web Conference (WWW, ACM)
- EPJ Data Science
- *Proposed:* NAACL, Findings of ACL/EMNLP, TACL, Computational Linguistics (journal), ACM CHI, ACM FAccT, AAAI/ACM AIES, ACM Web Science, JASIST, Information Processing & Management

Conferences publish in batches a few times a year, not weekly. This section would be large in those weeks and empty in others, which is why preprints matter here (next section).

### Preprints (topics 1 and 2)

Many CL and CSS papers appear as preprints months before the conference or journal version, so the brief also scans preprint servers for **Computational Social Science** and **Computational Linguistics**.

My words, verbatim:

> these journals as well as those in computational social science ones, you have to scan preprint as well, many of them will publish in preprint first, preprint is very important. But preprints are too many, number is an issue, only include those preprints are from reputable labs and universities (e.g., QS top 100) and top companies (like deepseek, anthropic, etc)

**Servers scanned:** arXiv (cs.CL, cs.SI, cs.CY, cs.HC, cs.AI, cs.LG, econ.GN, physics.soc-ph), SocArXiv, PsyArXiv, OSF Preprints, SSRN (selected networks).

**A preprint is kept only if all of these hold:**

1. **Reputable source:** at least one author is affiliated with an institution in `config/institutions.yaml`:
   - QS World University Rankings top 100 (refreshed once a year)
   - Top AI and tech labs: Anthropic, OpenAI, Google DeepMind / Google Research, Meta AI (FAIR), Microsoft Research, DeepSeek, Alibaba Qwen, Moonshot AI, Zhipu AI, Mistral, Allen Institute for AI (Ai2), Apple, NVIDIA, IBM Research, Hugging Face (editable)
   - Plus research institutes I name (e.g. Oxford Internet Institute, MIT Media Lab, Max Planck institutes)
2. **On topic:** it passes the same social‑science filter as the CL venues (social media, society, science, psychology, communication, politics).
3. **New:** not seen before. When a preprint later appears in a listed journal or conference, it is shown again once, tagged "Now published in …".

**Exception:** a preprint by a scholar on my scholar list is always kept, from any institution, and counts toward ⭐ Top priority only if it is also from a listed institution (preprints alone are not "journal hits").

**Caveat:** arXiv does not record affiliations in its metadata. OpenAlex fills them in for most papers within a few days; for the rest the script reads the first page of the PDF. A few preprints may arrive a week late or be missed.

**Expected volume:** ~1,500–2,500 new preprints/week in those categories → ~150–300 after the institution filter → **~15–40** after the topic filter. If that is still too many, the next lever is a cap (e.g. top 10 per topic, ranked by relevance to my research areas).

**3. Communication & Science Communication**
- Journal of Communication
- New Media & Society
- Social Media + Society
- Big Data & Society
- Communication Research
- Confirmed top‑tier: Human Communication Research, Political Communication, Journal of Computer‑Mediated Communication, Information, Communication & Society, Digital Journalism, Communication Methods and Measures, International Journal of Press/Politics, Communication Monographs
- *Proposed sci‑comm:* Public Understanding of Science, Science Communication, JCOM
- Confirmed, close to my research: Feminist Media Studies, Chinese Journal of Communication, HKS Misinformation Review

### Scholar list (from my notes, 21 Oct 2026)

My words, verbatim:

> author lists, plz include calvin yixiang cheng and all his coauthors,
>
> then scholars from Oxford internet institute, such as mohsen molseh, scott hale, andreu cassas, kobi hankenberg, paul rottiger, Manuel tonneau, hannk rose kirk, Chris Summerfield, L Ibrahim,
>
> scholars from university of washington, an informed public center, like kate starbird, those professors, Emma Spiro, Jevin West, Naomi Oreskes, Harvard University, Geoffrey Supran, University of Miami, Ben Franta, Oxford University, Ryan Calo, University of Washington
>
> * Erik Conway, Purdue University
>
> also works from MIT media lab,
>
> works from MIT sloan business school, David G. Rand, and his coauthor's and students, like Janien allen, cameron Martel, and others, who collaborate together
>
> standford, Diyi Yang's group, jennifer pan and her coauthors
>
> northeast, William brady, yingdan lu
>
> cambridge, Sander van der Linden's group
>
> then communication is mike's group

#### How the list is followed

Each entry in `scholars.yaml` has a `type`:

| type | What it follows | Used for |
|------|-----------------|----------|
| `person` | One scholar, pinned by OpenAlex ID / ORCID | Most names |
| `coauthors` | The anchor scholar **plus** anyone who has co‑authored with them recently (default: ≥2 joint papers in the last 5 years; `min_joint_papers: 1` = every co‑author) | "and his/her coauthors" |
| `group` | The PI **plus** frequent co‑authors at the PI's own institution (their students, postdocs, lab members) | "X's group" |
| `institution` | Any paper with an author affiliated with that unit, passed through the social‑science filter | "works from MIT Media Lab" |

Co‑author and group members are recomputed once a month and written to `config/scholars_resolved.yaml`, so I can see exactly who is being followed and delete anyone.

#### Resolved list (spellings corrected; IDs to look up at build time)

**Me and my co‑authors**
- Calvin Yixiang Cheng (me): `coauthors`, `min_joint_papers: 1` (every co‑author)

**Oxford Internet Institute**
- Mohsen Mosleh
- Scott A. Hale
- Andreu Casas
- Kobi Hackenburg
- Paul Röttger
- Manuel Tonneau
- Hannah Rose Kirk
- Christopher Summerfield
- Lujain Ibrahim

**UW Center for an Informed Public and climate‑disinformation scholars**
- Kate Starbird (UW)
- Emma S. Spiro (UW)
- Jevin D. West (UW)
- Ryan Calo (UW)
- Naomi Oreskes (Harvard)
- Geoffrey Supran (University of Miami)
- Benjamin Franta (Oxford)
- Erik M. Conway (Purdue, as listed)
- Only the people named above are followed (not all CIP faculty)

**MIT**
- MIT Media Lab: `institution`, social‑science filter on
- David G. Rand (MIT Sloan): `group`, plus named members Jennifer Allen and Cameron Martel. Frequent co‑authors such as Gordon Pennycook, Antonio Arechar, Ziv Epstein and Thomas Costello will be picked up automatically.

**Stanford**
- Diyi Yang: `group`
- Jennifer Pan: `coauthors`

**Northwestern**
- William J. Brady
- Yingdan Lu

**Cambridge**
- Sander van der Linden: `group`

**Communication**
- Mike S. Schäfer (IKMZ, University of Zurich): `group`

## 4. How fetching works

Python script, no scraping. Sources in order of preference:

| Source | Used for | Notes |
|--------|----------|-------|
| **OpenAlex API** | Main source for both lists. Journals by ISSN, scholars by author ID | Free; covers nearly all journals; includes abstracts for most |
| **Crossref API** | Fallback for journals missing from OpenAlex that week, and DOI metadata | Free |
| **Journal RSS/eTOC feeds** | Catches "online first" articles a few days before the indexes | Free; feed URL optional per journal |
| **Semantic Scholar API** | Fills in missing abstracts (Elsevier and some others hide them) | Free, rate‑limited |
| **ACL Anthology** | ACL/EMNLP/NAACL papers | Free; conference batches, not weekly |
| **DBLP / OpenAlex proceedings** | NeurIPS, WWW, CSCW, ICWSM | Free; conference batches |
| **arXiv API, OSF API (SocArXiv, PsyArXiv), SSRN** | Preprints for topics 1 and 2 | Free; affiliations from OpenAlex or the PDF's first page |

Pipeline each run:

1. **Collect** new works since the last run (by index date, with a 2‑day overlap so nothing falls in a gap).
2. **Deduplicate** by DOI against `state/seen.json`, so an article is never sent twice even if the window overlaps.
3. **Filter** venues marked `filter: social-science`: keep a paper only if it is about social media, society, science, psychology, communication or politics. First a keyword pass, then Claude Haiku 5.5 (low effort) reads the title + abstract and says keep/drop. Answers are cached in `state/classified.json`, so each paper is screened once. Keywords alone either miss papers or let noise through.
4. **Tag** each article: `journal_hit`, `scholar_hit`, and `top_priority = journal_hit AND scholar_hit`.
5. **Assign topic** from the journal, or from the scholar's default topic.
6. **Render** the HTML email, save a copy to `archive/YYYY-MM-DD.html`, and **send**.

## 5. Newsletter layout (mirrors the Nature e‑alert)

```
Subject: Calvin Research Brief: 26 Oct 2026

Weekly updates · 26 October 2026
This week: 34 journal articles, 5 from scholars you follow, 2 top priority.

⭐ TOP PRIORITY  (listed scholar × listed journal)
   Title (link)
   Journal · date
   Author A, Author B [...] Author Z      ← followed scholar in bold
   Abstract (first ~80 words, "Read more ›")

1. COMPUTATIONAL SOCIAL SCIENCE ›
   Nature Human Behaviour
     Title / Journal · date / Authors / Abstract / link
     ...
   EPJ Data Science
     ...

   Preprints (from top‑100 universities and top labs)
     Title / Server · date / Authors + institution / Abstract / link

2. COMPUTATIONAL LINGUISTICS ›
   ...
   Preprints (from top‑100 universities and top labs)
     ...

3. COMMUNICATION & SCIENCE COMMUNICATION ›
   ...

SCHOLAR WATCH
   Jennifer Pan: 1 new
     Title / Journal · date / Authors / Abstract / link
   Petter Törnberg: 2 new
     ...
   (Scholars with nothing new this week are listed in one line at the end.)
```

Every entry has the five required fields: **title, journal, date, authors, abstract, link** (DOI link). Authors follow the Nature style: first two, `[...]`, last. Clean single‑column HTML that reads well in Gmail on phone and desktop, with a plain‑text fallback. Empty topics are skipped that week.

## 6. Size limit: at most 20 articles per issue

My words, verbatim:

> we have to limit the number of articles in this weekly newsletter, because we include preprint, i worry there will be too many fit our current cretieria, what do you think? i say no more than 20 in the final news letter, and priority list is topic 1, 3, 2, (there won't be many in my topic 1 as they are very pretigious journals) for topic 2 and 3, each keep 3-5. if the total is above 20. for preprint, prioritze those on the author list

**Rule.** If the week has 20 or fewer articles after filtering, all are sent. If it has more:

1. **⭐ Top priority** articles always go in first.
2. **Topic 1 (Computational Social Science)** goes next and keeps everything, as long as Topics 3 and 2 still have room for 3 articles each.
3. **Topic 3 (Communication)** gets 3–5 articles.
4. **Topic 2 (Computational Linguistics)** gets 3–5 articles.
5. Any slots still free go to Topic 3, then Topic 2, until the brief reaches 20.

**Order within a topic when it must be trimmed:**
1. Articles by scholars on my list (journal articles, then preprints)
2. Journal and conference papers
3. Other preprints, ranked by relevance to my research areas (scored by the AI layer below)

Articles cut by the limit are not lost. They are listed in a short **"Also this week"** footer with one line each (title and link), which does not count toward the 20. That footer can be switched off.

```yaml
# settings.yaml
max_articles: 20
topic_priority: [css, comm, cl]
topic_quota:
  comm: {min: 3, max: 5}
  cl:   {min: 3, max: 5}
overflow_footer: true
```

## 7. AI layer

On by default (I approved it). It can be switched off in `settings.yaml`:

- **Relevance highlight**: Claude reads the week's abstracts and marks the 3–5 most relevant to my own research areas ("Editor's picks").
- **One‑line summary** per top‑priority paper.

## 8. Delivery and schedule

**Recommended: GitHub repository + GitHub Actions (free, runs without me or Claude being online).**

- A private GitHub repo holds the code, config and archive.
- A scheduled workflow runs every **Monday at 07:00 CET**, fetches, renders and emails.
- Editing a list = edit the YAML file on github.com (or ask Claude to) and commit.
- I can also trigger a run by hand from the Actions tab.

**Email sending: Brevo** (chosen 21 Oct 2026, because Gmail App Passwords could not be enabled on the new Gmail account). Free tier: 300 emails/day. The sender is my Gmail address, verified in Brevo. The code also supports Gmail SMTP if I switch later (`settings.yaml → email.provider`).

**What I need to set up:**

1. ✓ Connect GitHub to Claude (repo: `calvinchengyx/research-brief-rss`).
2. Brevo account, verified sender, and API key.
3. GitHub repository secrets: `BREVO_API_KEY`, `SENDER_EMAIL`. The secrets are never written in the code.
4. A free OpenAlex API key, and an Anthropic API key (`ANTHROPIC_API_KEY`) for the social‑science filter and the AI layer.

*Alternative:* a weekly Claude scheduled routine runs the same script in a cloud session. It works, but uses my Claude plan's usage every week and still needs an email credential, so GitHub Actions is simpler and cheaper.

## 9. Cost

| Item | Weekly cost |
|------|-------------|
| OpenAlex, Crossref, Semantic Scholar, RSS | Free |
| GitHub Actions (≈3–5 min per run, private repo has 2,000 free min/month) | Free |
| Brevo free tier | Free |
| Claude filter, summaries and Editor's picks. A 10‑day window had about 1,100 papers after the prefilter, which is about 57 requests of 20 papers, roughly 750k input and 150k output tokens (thinking included) | Haiku 5.5: ≈ $0.15–0.25 per run. Sonnet 5.5: ≈ $3–4 per run |
| Reruns and previews (answers cached in `state/classified.json`, so a paper is only screened once) | ≈ $0 |
| Deep dives (Sonnet 5.5 reading the open-access PDF, cached per paper) | ≈ $0.10 per requested paper |
| **Total** | **$0 with keyword filter only; about $1/month with Haiku 5.5; about $12–16/month with Sonnet 5.5** |

The first estimate here ($2–3/month) was too low: it assumed 300–800 papers a week and left out thinking tokens and repeated preview runs, which had no cache at the time.

To cap spend, set a monthly limit in the Claude Console under Settings → Limits. If the limit is hit, the run falls back to the keyword filter instead of failing.

Building it is a one‑time effort in this project.

## 10. Run frequency

**Every other Monday** (changed from weekly on 26 Oct 2026). The cron still fires every Monday and skips the off weeks. Each run looks back 17 days (14 plus indexing lag); the no-repeat rule removes the overlap. The 20-article cap is unchanged, so more papers land in "Also this week".

## 11. Build plan

1. Finalize journal and scholar lists together; resolve ISSNs and scholar IDs (OpenAlex), confirm any ambiguous match with me, and generate the first `scholars_resolved.yaml` for review.
2. Write fetchers (OpenAlex → Crossref/RSS → Semantic Scholar abstracts) and dedupe/state.
3. Write the HTML template and render a **preview issue from last week's real data** for review. No email sent.
4. Send one test email to me only, after my go‑ahead.
5. Set up the GitHub repo, secrets and Monday schedule, after my go‑ahead.
6. First live issue; tune filters after 2–3 weeks.

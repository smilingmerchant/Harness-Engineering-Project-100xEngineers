# Harness-Engineering-Project-100xEngineers
# Self-Improving Briefing Agent (Harness Engineering 2.0)

A small prototype of an **AI agent that gets tested, scored, and improved in a loop**, with a locked grader the agent can never edit.

> **Built during the live masterclass "Harness Engineering 2.0" by [Siddhant Goswami](https://www.linkedin.com/in/siddhantgoswami/) (Co-founder & CTO, 100xEngineers).**
> I followed the session live, built the loop on my own machine, and wrote down what worked and what did not. Credit for the idea and the structure goes to the session and 100xEngineers.

---

## 1. What is Harness Engineering?

An AI model on its own can only produce text. To make it **reliable**, you build things around it. That "everything around the model" is called the **harness**:

| Part of the harness | What it means | Simple example |
| --- | --- | --- |
| **Tools** | What the model can actually do | Read files, run commands, fetch a web page |
| **Environment** | Where it works and how much damage a mistake can do | Your folder, shell, git, network |
| **Rules** | What stops it between "I want to" and "I did it" | Permissions, hooks, instructions in `CLAUDE.md` |

**Analogy:** the AI is a smart new employee. The harness is their desk, tools, and rulebook. A better harness gives better results *without changing the AI model*.

### The idea behind version 2.0

In the earlier session (101), a human had to find each failure and fix the harness by hand. As failures pile up, that person becomes the bottleneck.

In 2.0, a **second agent (the optimizer)** reads the failures and proposes **one change** to the harness. The change stays **only if the score improves**. The agent is never allowed to edit its own grader.

Six ideas from the session that this project uses:

1. **Write the test, not the prompt.** A clear check of what "good" means matters more than a clever prompt.
2. **A harness is tools, environment, and rules.**
3. **Memory is a file.** Every improvement lands in a file you can open and read.
4. **Draft yes, send no.** The agent can suggest risky changes, and only a human approves them.
5. **A loop only sees its score.** If the score can be cheated, the loop will find a way (Goodhart's law). That is why part of the data is hidden.
6. **Use plain code wherever you can.** Only a few steps need an AI model.

---

## 2. What this project does

The example task is a **morning briefing agent**. You save many links on AI and tech. The agent should read them and write a short brief with three parts:

1. **What changed**
2. **Who disagrees with whom**
3. **What to do about it**, if anything

The brief itself is only the practice task. The real goal is the **loop around it**: run the agent, score it, find the failure, add one rule, and keep the rule only if it helps.

---

## 3. How it works

```
links.txt ──► harness/ (agent #1) ──► traces/try/brief.md
                                          │
                                          ▼
                       verifier/score.py  (locked grader, scores the brief
                                          │   against my hindsight labels)
                                          ▼
                       optimizer/ (agent #2) reads FAILURES.md + traces
                                          │   and proposes ONE change
                                          ▼
                       keep the change only if the score improves
                                          │
                                          ▼
                       git commit with a one-line reason
```

### Project structure

```
harness-session/
├── harness/        # Agent #1's setup
│   ├── CLAUDE.md       # instructions and rules (each rule tagged, e.g. (F1))
│   ├── sources.md      # notes on the sources
│   ├── memory.md       # what the agent has learned (a plain file)
│   └── tools/fetch.py  # simple URL fetcher
├── verifier/       # Labels and scoring. No agent may read this folder.
│   ├── links.csv           # my labels: url, date, label
│   ├── hidden_links.csv    # held-back set to catch memorizing
│   ├── decisions.csv       # decisions the brief should get right
│   └── score.py            # the grader
├── optimizer/      # Agent #2
│   ├── CLAUDE.md
│   ├── journal.md      # result of each attempt (kept or dropped)
│   └── proposals.md    # the proposed change and its reason
├── loop.py         # runs the agent, scoring, optimize, and try steps
├── FAILURES.md     # failures written as "Saw / Expected"
└── .gitignore
```

### The scoring rule

A brief is scored like this:

- **+1** for each link that mattered and made the brief
- **+2** for each decision it called right
- **−0.5** for each noise item it called important
- The total is divided by everything there was to find

Example from the session: `(7 + 4 − 1.5) ÷ 13 = 0.73`.

### Safety limits

- The agent can edit its **instructions, skills, and tools**.
- **Permissions and grading stay with the human.** `verifier/score.py` is never edited by an agent.
- Nothing in `harness/` or `optimizer/` may read `verifier/`.
- Every change is a git commit with a one-line reason, so the history is auditable.

---

## 4. How to run it

You need Python 3 and [Claude Code](https://docs.claude.com) (a paid Claude plan or a Console account).

1. Create your own `links.txt` (one URL per line) and your own `verifier/links.csv` with the columns `url,date,label`. These are personal, so they are listed in `.gitignore`.
2. Label the links in `links.csv` using the label words from your scoring setup (I used `mattered`, `maybe`, `ignore`).
3. Run the first agent and score it:

```bash
py loop.py brief 1                 # use python3 on Mac/Linux
py verifier/score.py traces/try
```

4. Read `traces/try/brief.md`. Write one failure in `FAILURES.md`:

```
F1 · week 1
Saw: what the agent actually did
Expected: what you wanted
```

5. Add one tagged rule to `harness/CLAUDE.md`, for example `... (F1)`, and commit it.
6. Let the optimizer propose a change, then test it:

```bash
py loop.py optimize
py loop.py try
```

`loop.py` calls Claude Code in non-interactive mode (`claude -p`), so no API key is needed, but each run uses some of your plan's usage.

---

## 5. Results and what I learned

| Run | Change | Score | Outcome |
| --- | --- | --- | --- |
| Week 1, first setup | none | 0.00 | The brief described links by name and never wrote the URLs, so the scorer matched nothing |
| After rule F1 | "Cite the full URL for every item" | −0.25 | URLs now matched, but the brief flagged a link I had labeled as noise |
| Optimizer proposal (F2) | "Fetch each source before writing" | 0.00 | Proposal tested and dropped, because the brief did not improve |

What I learned:

- **A failed score is useful.** The first 0.00 pointed straight to a missing rule.
- **Keep the grader locked.** Making the scorer easier would have raised the score without improving the agent.
- **Use plain code for plain jobs.** The agent could not fetch pages on its own, so the better design is for `loop.py` to fetch the page text and pass it in.
- **Check the checker.** I found that my keep/drop step compared against `0.00` instead of a real "before" score. That is a bug in the loop, and I listed it below.

---

## 6. Why this is useful

- It gives a **repeatable way to improve any AI agent**: define "good" as a score, run, find failures, add one rule, keep it only if the score rises.
- It replaces "this feels better" with a **number you can compare** before and after.
- It keeps humans in control of **permissions and grading**, while letting a second agent do the repetitive debugging.
- The same loop can be pointed at other agents, such as a chatbot, a summarizer, or a route assistant.

---

## 7. Known limitations (honest status)

This is a **working prototype of the loop**, not a finished product.

- **The briefs are weak.** The first agent only sees the URL text, not the page contents, so it cannot summarize what the pages say. Next step: have `loop.py` fetch page text itself.
- **The keep/drop rule is simplified.** It currently keeps a change when the new score is above 0, instead of comparing against a stored "before" score.
- **Very small test set.** Only 2 links were labeled as "mattered", so scores are noisy.
- **The hidden set is not active yet.** `hidden_links.csv` needs real labeled links before it can catch memorizing.
- **Scores vary between runs.** The model gives different outputs each time, so each version should be run more than once.

## 8. Next steps

- [ ] Fetch page text inside `loop.py` and pass it to the agent
- [ ] Compare against a real "before" score in the keep/drop step
- [ ] Label 20+ links and fill the hidden set
- [ ] Run each version several times and average the scores
- [ ] Point the same loop at another project of mine

---

## Credits

- **Session:** Harness Engineering 2.0, live masterclass by **Siddhant Goswami**, Co-founder & CTO of **100xEngineers**.
- **Built by:** *your name here*

*This repo is a learning project built while following the session. The concept and structure come from the masterclass, and the notes, results, and limitations come from my own run.*

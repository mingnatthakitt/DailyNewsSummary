***

# The Thinking Times: Daily AI Intelligence Dispatch
![Python Version](https://img.shields.io/badge/python-3.10-blue.svg) ![Build Status](https://github.com/mingnatthakitt/DailyNewsSummary/actions/workflows/daily_news.yml/badge.svg) ![AI Engine](https://img.shields.io/badge/AI-Auto%20Detected%20via%20MODEL%20env-orange)
![Framework](https://img.shields.io/badge/Framework-OpenAI%20SDK-green)

<div align="center">
  <a href="https://discord.com/oauth2/authorize?client_id=1499052107180015697&permissions=377957210112&integration_type=0&scope=bot">
    <img src="https://img.shields.io/badge/Discord-Try_our_bot-7289da?logo=discord&logoColor=white&style=for-the-badge" alt="Try our bot on discord">
  </a>
</div>

**The Thinking Times** is an automated news aggregation and intelligence platform. It uses LLMs to fetch, curate, and summarize the most critical daily developments across AI & Tech (60%), Finance (25%), and Global News (15%). Provider and model are auto-detected from the `MODEL` env var — any OpenAI SDK-compatible model works.

The system operates as a "Senior Industry Analyst," transforming raw RSS feeds into a high-density, analytical news digest delivered via a **Hybrid Discord Notification System** (supporting both Webhooks and multi-server Bots) and a classic newspaper-style web interface.

<p align="center">
  <img src="images/discordbot.png" width="37%" />
  <img src="images/website.png" width="61%" />
</p>


## 🚀 System Architecture

The project is divided into an automated backend processing pipeline and a clean "New Times" styled frontend.

### 1. Intelligence Pipeline (`generate_news.py`)

* **Source Aggregation**: Uses `feedparser` to ingest news from 20+ high-authority sources across three domains: AI & Tech, Finance, and General World News.
* **Deduplication**: Near-duplicate stories (Jaccard similarity > 0.7 on normalized titles) are collapsed before stage 1, keeping the first-seen item.
* **Seen-Story Cache**: Stories dispatched in the last 7 days (URL-based) are automatically skipped. Configurable via `STORY_CACHE_DAYS`. Persisted to `story_cache.json`.
* **Stage 1: Weighted Selection** (60/25/15): Nemotron evaluates stories with explicit weighting — AI & Tech at ~60%, Finance ~25%, Global ~15%. A hard minimum ensures Global News is never skipped. Output capped at 20 items max.
* **Stage 2: Per-Article Summarization with Retry**: Uses `MODEL` env (default: Gemma 4 31b — superior rule-following for clean `## ` headers). Falls back to Nemotron on failure. 3 attempts with exponential backoff (2s → 4s → 8s). Final fallback: raw description.
* **LLM Self-Categorization**: The LLM assigns each article to one of **9 canonical categories**: `ARTIFICIAL INTELLIGENCE`, `RESEARCH & ACADEMIC BREAKTHROUGHS`, `PRODUCT LAUNCHES & COMPANY NEWS`, `TECHNOLOGY`, `OPEN SOURCE & COMMUNITY`, `FUNDING & MARKET DYNAMICS`, `POLICY & REGULATION`, `FINANCE`, `GLOBAL NEWS`. The `## ` category header is parsed and stripped from the summary; only the clean summary text is saved to `news.json`.
* **Garbage Output Rejection**: LLM summaries are validated against 13 placeholder/garbage patterns. Output shorter than 50 chars or matching any pattern triggers an automatic retry.
* **Hybrid Dispatch**: Simultaneously broadcasts to a single-channel **Webhook** and a multi-server **Discord Bot**. Discord embeds show the canonical category name in the footer (e.g., `"Category: FUNDING & MARKET DYNAMICS"`).

### 2. Frontend Interface (`index.html` / `script.js`)
* **NYT-Style Layout**: A three-column grid — **Left**: Finance & Markets · **Center**: AI & Tech · **Right**: Global News + Featured article.
* **Dual-Layer Category Detection**: Articles are first classified by the **LLM-chosen canonical category** saved in `news.json`. Regex-based keyword analysis of title + summary acts as a secondary layer for articles where the LLM category falls outside the three display columns (e.g., `RESEARCH & ACADEMIC BREAKTHROUGHS` → Tech column).
* **Clean Summary Rendering**: LLM markdown (`## headers`, `**bold**`, `[links](url)`, orphaned category words) is stripped before display. Summaries are clipped at 280 chars (news items) or 400 chars (featured) with a "Read more" expand/collapse toggle.
* **Short Category Labels**: Each card shows a compact label ("AI", "Markets", "Launches", "OSS", "Research") derived from the canonical category, not the raw RSS group.
* **Live Intelligence Tools**: Real-time world clock with UTC offset selection (UTC−12 to UTC+12).

## 🛠️ Technical Stack

* **Language**: Python 3.10+
* **AI Engine**: Any OpenAI SDK-compatible model — provider auto-detected from `MODEL` env var (NVIDIA NIM, AI Studio, Ollama, etc.)
* **Discord Integration**: `discord.py` (Bot) & `requests` (Webhook)
* **Frontend**: Vanilla HTML5, CSS3, and JavaScript (ES6+)
* **Libraries**: `feedparser`, `openai`, `requests`, `PyYAML`, `discord.py`

## 📋 Configuration (`config.yaml`)

You can customize the "personality" and sources of the bot in `config.yaml`:

* **Model & Endpoint**: Set `llm.base_url` and `llm.model` as fallbacks. The model name (from `MODEL` env var or config) drives automatic provider detection.
* **RSS Feeds**: Add or remove sources in the `feeds` section (AI & Tech, Finance, General).
* **Discord Bot**: Set `discord_bot_channel` for the target channel name.
* **Prompt Engineering**: Adjust `stage1_prompt_template` and `stage2_prompt_template` to change selection criteria, weighting, tone, or summary length.
* **`max_items_per_source`**: Controls how many items per feed are fetched (default: 5).

## ⚙️ Setup & Deployment

### 1. Environment Variables

The **`MODEL` env var is the primary way to select model and provider.** The model name itself determines which endpoint and API key are used:

| `MODEL` value | Provider | Endpoint | API Key |
|---|---|---|---|
| `nvidia/nemotron-3-ultra-550b-a55b` (or any name with "nvidia"/"nemotron") | NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | `NVIDIA_API_KEY` |
| `gemma-4-31b-it` (or any name with "gemma"/"gemini") | Google AI Studio | `https://generativelanguage.googleapis.com/v1beta/openai/` | `GEMINI_API_KEY` |
| Any other model name | Custom | `PROVIDER_BASE_URL` env var (required) | `PROVIDER_API_KEY` (required) |
| Not set | **Hardcoded fallback chain**: tries `NVIDIA_API_KEY` → `GEMINI_API_KEY` | — | — |

**Resolution priority for `MODEL`:**
1. `MODEL` env var (highest) — controls Stage 2 summarization model
2. `llm.model` in `config.yaml`
3. Hardcoded default (`gemma-4-31b-it`)

> **Stage 1 (selection)** always uses Nemotron (hardcoded). **Stage 2 (summarization)** uses `MODEL` env. This split leverages Nemotron's strong selection judgment and Gemma's superior rule-following for clean `## ` header output.

**Examples:**
```bash
MODEL=gemma-4-31b-it                           # Gemma at AI Studio (default — best rule-following)
MODEL=nvidia/nemotron-3-ultra-550b-a55b        # Nemotron at NVIDIA NIM
MODEL=llama-3.1-70b PROVIDER_BASE_URL=https://ollama/v1 PROVIDER_API_KEY=xxx  # Custom endpoint
# (no MODEL set) → defaults to gemma-4-31b-it for summarization
```

**Other env vars:**

| Variable | Required | Notes |
|---|---|---|
| `NVIDIA_API_KEY` | If using NVIDIA model | NVIDIA NIM API key |
| `GEMINI_API_KEY` | If using Gemini model | Google AI Studio key |
| `PROVIDER_API_KEY` | If using custom model | Any OpenAI SDK-compatible key |
| `PROVIDER_BASE_URL` | If using custom model | Full URL to your endpoint |
| `MODEL` | Recommended | Overrides `config.yaml` model; drives provider detection |
| `DISCORD_WEBHOOK_URL` | Optional | Single-channel webhook |
| `DISCORD_BOT_TOKEN` | Optional | Multi-server bot broadcasting |
| `DRY_RUN` | Optional | Set to `1`/`true`/`yes` to skip Discord dispatch (writes `news.json` only) |
| `STORY_CACHE_DAYS` | Optional | Days before a URL can re-appear (default: `7`, `0` to disable) |

### 2. Discord Bot Setup
To use the multi-server bot feature:
1. Create a bot in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Enable **Message Content Intent** and **Server Members Intent**.
3. Invite the bot to your servers and ensure a channel named `#the-thinking-times` exists.

### 3. Installation & Local Execution
```bash
pip install -r requirements.txt
DRY_RUN=1 python generate_news.py        # Local test — no Discord spam
STORY_CACHE_DAYS=0 python generate_news.py  # Skip cache, process everything
```

### 4. GitHub Actions Automation
The repository runs daily at **08:13 HKT** via GitHub Actions. It commits the updated `news.json` to update the website and triggers the Discord dispatch.

---

## 📂 Project Structure
```
.
├── .github/workflows/   # GitHub Workflow Automation
├── config.yaml           # Feed, Prompt & LLM Config
├── generate_news.py      # Python Pipeline Logic
├── index.html            # Web Layout
├── script.js             # Fetching and Rendering
├── news.json             # Digest Output (JSON format)
├── story_cache.json      # Seen-story cache (auto-generated)
└── style.css             # The Style (NYT Inspired)
```

---

## 🔧 Feature Flags

| Feature | Env Var | Default | Description |
|---|---|---|---|
| Summarization model | `MODEL` | `gemma-4-31b-it` | Stage 2 summarization (Stage 1 always Nemotron) |
| Custom endpoint | `PROVIDER_BASE_URL` | — | Required when using a non-NVIDIA/non-Gemini model |
| Dry-run mode | `DRY_RUN` | off | Skip Discord dispatch, write `news.json` only |
| Story cache | `STORY_CACHE_DAYS` | `7` | Skip stories seen within this window |
| Retry attempts | `MAX_RETRIES` | `3` | Per-article LLM call retries |
| Base backoff | `BASE_BACKOFF` | `2s` | Initial backoff interval (doubles each retry) |
| Near-duplicate threshold | `DEDUP_THRESHOLD` | `0.7` | Jaccard similarity above which stories are collapsed |

### Canonical Categories
Articles are self-categorized by the LLM into one of 9 categories, saved to `news.json`:

| Canonical Category | Frontend Column |
|---|---|
| `ARTIFICIAL INTELLIGENCE` | AI & Tech (center) |
| `RESEARCH & ACADEMIC BREAKTHROUGHS` | AI & Tech (center) |
| `PRODUCT LAUNCHES & COMPANY NEWS` | AI & Tech (center) |
| `TECHNOLOGY` | AI & Tech (center) |
| `OPEN SOURCE & COMMUNITY` | AI & Tech (center) |
| `POLICY & REGULATION` | AI & Tech (center) |
| `FUNDING & MARKET DYNAMICS` | Finance (left) |
| `FINANCE` | Finance (left) |
| `GLOBAL NEWS` | Global (right) |

***

Part of this project is inspired by [giftedunicorn/ai-news-bot](https://github.com/giftedunicorn/ai-news-bot)

*&copy; 2026 The Thinking Times.*

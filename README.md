***

# The Thinking Times: Daily AI Intelligence Dispatch
![Python Version](https://img.shields.io/badge/python-3.10-blue.svg) ![Build Status](https://github.com/mingnatthakitt/DailyNewsSummary/actions/workflows/daily_news.yml/badge.svg) ![AI Engine](https://img.shields.io/badge/AI-Gemini%203%20Flash-orange)
![Framework](https://img.shields.io/badge/Framework-OpenAI%20SDK-green)

**The Thinking Times** is an automated news aggregation and intelligence platform. It leverages Large Language Models (LLMs)—specifically **Gemini 3 Flash** or **Kimi K2.5** to fetch, curate, and summarize the most critical daily developments across Artificial Intelligence, Finance, and Global News. 

The system operates as a "Senior Industry Analyst," transforming raw RSS feeds into a high-density, analytical news digest delivered via a Discord webhook and a classic newspaper-style web interface.

## 🚀 System Architecture

The project is divided into an automated backend processing pipeline and a clean "New Times" styled frontend.

### 1. Intelligence Pipeline (`generate_news.py`)
* **Source Aggregation**: Uses `feedparser` to ingest news from 20+ high-authority sources across three domains: AI & Tech, Finance, and General World News.
* **Stage 1: Multi-Criteria Selection**: The LLM evaluates hundreds of raw stories based on sector-defining impact, policy shifts, and technical breakthroughs to select the top 15-20 items.
* **Stage 2: Analytical Summarization**: Generates in-depth summaries (150-200 words) for each selected item, focusing on technical details and business implications.
* **Automated Parsing**: A robust regex-based parser extracts the LLM's structured Markdown output into a machine-readable `news.json` for the web frontend.

### 2. Frontend Interface (`index.html` / `script.js`)
* **NYT-Style Layout**: A three-column grid organizing news into *Tech Intelligence*, *Global Dispatch*, and *Finance & Markets*.
* **Dynamic Filtering**: The JavaScript frontend dynamically categorizes articles from `news.json` using keyword-based domain relevance.
* **Live Intelligence Tools**: Includes a real-time world clock with timezone selection for global analysts.

## 🛠️ Technical Stack

* **Language**: Python 3.10+
* **AI Engine**: Google Gemini (via Google's AI studio API) or  Kimi K2.5 (via Nvidia NIM API)
* **Frontend**: Vanilla HTML5, CSS3 , and JavaScript (ES6+)
* **Libraries**: `feedparser`, `openai`, `requests`, `PyYAML`

## 📋 Configuration (`config.yaml`)

You can customize the "personality" and sources of the bot in the `config.yaml` file:
* **Model Selection**: Toggle between different LLM providers.
* **RSS Feeds**: Add or remove sources from the `feeds` section (currently includes MIT Tech Review, Wired, Financial Times, etc.).
* **Prompt Engineering**: Adjust the `stage1` and `stage2` templates to change the analytical tone or summary length.

## ⚙️ Setup & Deployment

### 1. Environment Variables
The system requires the following keys to be set in your environment or GitHub Secrets:
* `GEMINI_API_KEY`: Your Google AI Studio API key
* `NVIDIA_API_KEY`: Your Nvidia NIM API key if you opt to use the platform
* `DISCORD_WEBHOOK_URL`: The URL for your Discord channel's webhook.

### 2. Installation
```bash
pip install -r requirements.txt
```

### 3. Local Execution
```bash
python generate_news.py
```
This will generate `news.json` and send the intelligence dispatch to your Discord server.

### 4. GitHub Actions Automation
The repository is designed to be fully automated using GitHub Actions. It can be scheduled to run daily, committing the updated `news.json` directly to the repository to update the live website.

---

## 📂 Project Structure
```
.
├── .github/workflows/   # GitHub Workflow Automation
├── config.yaml          # Feed & Prompt Config
├── generate_news.py     # Python Logic
├── index.html           # Web Layout
├── script.js            # Fetching and Rendering
├── news.json            # The Data (JSON format)
└── style.css            # The Style (NYT Inspired)
```
***
*&copy; 2026 The Thinking Times.*
import feedparser
from openai import OpenAI
import json
import os
import requests
import yaml
from datetime import datetime
import re
import logging
import time
import asyncio
import discord

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PROVIDER_API_KEY = os.getenv("PROVIDER_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# ── Provider resolution ──────────────────────────────────────────────────────────
HARDCODED_DEFAULTS = [
    ("gemini",  "https://generativelanguage.googleapis.com/v1beta/openai/", "gemma-4-31b-it", GEMINI_API_KEY),
    ("nvidia",  "https://integrate.api.nvidia.com/v1", "nvidia/nemotron-3-ultra-550b-a55b", NVIDIA_API_KEY),
]

ENDPOINTS = {
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "gemini":  "https://generativelanguage.googleapis.com/v1beta/openai/",
}

def _detect(model_name):
    for provider in ("nvidia", "gemini"):
        if provider in model_name.lower():
            key = NVIDIA_API_KEY if provider == "nvidia" else GEMINI_API_KEY
            if key:
                return provider, ENDPOINTS[provider], key
    return None

_model_env = os.getenv("MODEL")
_yaml_model = config.get("llm", {}).get("model")
MODEL = _model_env or _yaml_model

_active_provider, BASE_URL, API_KEY = None, None, None
if MODEL:
    detected = _detect(MODEL)
    if detected:
        _active_provider, BASE_URL, API_KEY = detected

if not _active_provider:
    if os.getenv("PROVIDER_BASE_URL") and PROVIDER_API_KEY:
        _active_provider, BASE_URL, API_KEY = "provider", os.getenv("PROVIDER_BASE_URL"), PROVIDER_API_KEY
    else:
        for prov, base, model_d, key in HARDCODED_DEFAULTS:
            if key:
                _active_provider, BASE_URL, MODEL, API_KEY = prov, base, model_d, key
                break

if not _active_provider or not API_KEY or not BASE_URL:
    logger.error("Set MODEL env (with nvidia/gemma in name) or PROVIDER_API_KEY + PROVIDER_BASE_URL.")
    exit(1)

logger.info(f"Provider: {_active_provider.upper()} | Model: {MODEL} | Base: {BASE_URL}")

MAX_RETRIES = 3
BASE_BACKOFF = 2
DRY_RUN = os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes")
SUMMARIZE_MODEL = MODEL
STORY_CACHE_DAYS = int(os.getenv("STORY_CACHE_DAYS", "7"))
STORY_CACHE_FILE = "story_cache.json"

# ── Story cache ─────────────────────────────────────────────────────────────────
def _cache_age(date_str):
    try:
        return (datetime.now() - datetime.fromisoformat(date_str)).days
    except Exception:
        return 999

def load_story_cache():
    if not os.path.exists(STORY_CACHE_FILE):
        return {}
    try:
        with open(STORY_CACHE_FILE) as f:
            raw = json.load(f)
        if STORY_CACHE_DAYS > 0:
            cutoff = datetime.now().timestamp() - STORY_CACHE_DAYS * 86400
            raw = {u: ts for u, ts in raw.items()
                   if datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() > cutoff}
        return raw
    except Exception as e:
        logger.warning(f"Could not load story cache: {e}")
        return {}

def save_story_cache(cache):
    try:
        with open(STORY_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        logger.error(f"Could not save story cache: {e}")

# ── Deduplication ───────────────────────────────────────────────────────────────
STOPWORDS = {'the','a','an','and','or','but','in','on','at','to','for','of','with','by','is','are','was','were','be','been','being','has','have','had','do','does','did'}

def _norm(title):
    t = re.sub(r'^(breaking|update|just in|exclusive|announcing):\s*', '', title.lower())
    t = re.sub(r'[^\w\s]', ' ', t)
    return {w for w in t.split() if w not in STOPWORDS and len(w) > 2}

def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / max(len(a | b), 1)

def deduplicate_items(items, threshold=0.7):
    unique, dropped = [], 0
    for item in items:
        n = _norm(item["title"])
        if any(_jaccard(n, _norm(u["title"])) > threshold for u in unique):
            dropped += 1
        else:
            unique.append(item)
    if dropped:
        logger.info(f"Deduplicated {dropped} → kept {len(unique)} unique stories.")
    return unique

# ── News fetch ─────────────────────────────────────────────────────────────────
client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
# Stage 1 always uses Nemotron on NVIDIA endpoint — create a dedicated client if needed
if NVIDIA_API_KEY and BASE_URL != "https://integrate.api.nvidia.com/v1":
    nvidia_client = OpenAI(api_key=NVIDIA_API_KEY, base_url="https://integrate.api.nvidia.com/v1")
else:
    nvidia_client = client

def fetch_all_news():
    all_items = []
    item_id = 0
    for group, sources in config["feeds"].items():
        logger.info(f"Fetching {group}...")
        for name, url in sources.items():
            try:
                feed = feedparser.parse(url)
                if not feed.entries:
                    continue
                for entry in feed.entries[:config["news"]["max_items_per_source"]]:
                    item_id += 1
                    all_items.append({
                        "id": f"ID-{item_id}",
                        "source": name,
                        "title": entry.title,
                        "description": entry.summary if hasattr(entry, "summary") else entry.title,
                        "url": entry.link,
                        "group": group,
                    })
            except Exception as e:
                logger.error(f"Error fetching {name}: {e}")

    logger.info(f"Fetched {len(all_items)} raw items.")
    all_items = deduplicate_items(all_items)
    all_items = [i for i in all_items if not (i["url"] in load_story_cache() and _cache_age(load_story_cache()[i["url"]]) <= STORY_CACHE_DAYS)]
    logger.info(f"After cache filter: {len(all_items)} fresh items.")
    return all_items

# ── Stage 1: selection ──────────────────────────────────────────────────────────
def stage1_selection(news_items):
    logger.info(f"Stage 1: selecting from {len(news_items)} stories...")
    formatted = "\n".join(
        f"[{i['id']}] Category: {i['group']} | {i['title']} - {i['source']}"
        for i in news_items
    )
    prompt = config["news"]["stage1_prompt_template"].format(
        formatted_news=formatted,
        total_items=len(news_items),
    )
    try:
        resp = nvidia_client.chat.completions.create(
            model="nvidia/nemotron-3-ultra-550b-a55b",
            messages=[
                {"role": "system", "content": "Output ONLY a JSON array of IDs like ['ID-1', 'ID-2']."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        content = resp.choices[0].message.content.strip()
        logger.info(f"Stage 1 Raw: {content[:70]}...")
        ids = re.findall(r"ID-\d+", content)
        if not ids:
            logger.warning("No IDs found — using fallback.")
            return news_items[:15]
        selected = [i for i in news_items if i["id"] in ids][:20]
        if len(ids) > 20:
            logger.warning(f"LLM returned {len(ids)} IDs — capped to 20.")
        logger.info(f"Selected {len(selected)} items.")
        return selected
    except Exception as e:
        logger.error(f"Stage 1 error: {e}")
        return news_items[:15]

# ── Validation patterns ─────────────────────────────────────────────────────────
GARBAGE_PATTERNS = [
    re.compile(r"\*No relevant items", re.I),
    re.compile(r"^#+\s*artificial intelligence\s*$", re.I | re.M),
    re.compile(r"^#+\s*finance\s*$", re.I | re.M),
    re.compile(r"^#+\s*global news\s*$", re.I | re.M),
    re.compile(r"^#+\s*research\s*$", re.I | re.M),
    re.compile(r"^#+\s*product launches?\s*$", re.I | re.M),
    re.compile(r"^#+\s*technology\s*$", re.I | re.M),
    re.compile(r"^#+\s*policy\s*$", re.I | re.M),
    re.compile(r"^#+\s*open source\s*$", re.I | re.M),
    re.compile(r"^#+\s*funding\s*$", re.I | re.M),
    re.compile(r"all\s+\d+\s+items?\s+are\s+excluded", re.I),
    re.compile(r"no stories?(?:were)?\s*identified", re.I),
    re.compile(r"the\s+digest\s+contains\s+no\s+items?", re.I),
]

# ── Category canonicalization ──────────────────────────────────────────────────
CANONICAL_KEYS = frozenset({
    "Artificial Intelligence",
    "Research & Academic Breakthroughs",
    "Product Launches & Company News",
    "Technology",
    "Open Source & Community",
    "Funding & Market Dynamics",
    "Policy & Regulation",
    "Finance",
    "Global News",
})

CATEGORY_ALIASES = {
    # Title-case canonical (display format in Discord)
    "Product Launches, Updates & Company News": "Product Launches & Company News",
    "Product Launches and Company News":          "Product Launches & Company News",
    # ALL CAPS variants
    "PRODUCT LAUNCHES, UPDATES & COMPANY NEWS": "Product Launches & Company News",
    "PRODUCT LAUNCHES AND COMPANY NEWS":          "Product Launches & Company News",
    "PRODUCT LAUNCHES & COMPANY NEWS":           "Product Launches & Company News",
    "ARTIFICIAL INTELLIGENCE":                  "Artificial Intelligence",
    "RESEARCH & ACADEMIC BREAKTHROUGHS":         "Research & Academic Breakthroughs",
    "OPEN SOURCE & COMMUNITY":                   "Open Source & Community",
    "FUNDING & MARKET DYNAMICS":                "Funding & Market Dynamics",
    "POLICY & REGULATION":                       "Policy & Regulation",
    "FINANCE":                                   "Finance",
    "GLOBAL NEWS":                               "Global News",
    # lowercase variants
    "product launches, updates & company news":  "Product Launches & Company News",
    "product launches and company news":          "Product Launches & Company News",
    "artificial intelligence":                   "Artificial Intelligence",
    "research & academic breakthroughs":          "Research & Academic Breakthroughs",
    "open source & community":                   "Open Source & Community",
    "funding & market dynamics":                 "Funding & Market Dynamics",
    "policy & regulation":                        "Policy & Regulation",
    "finance":                                    "Finance",
    "global news":                               "Global News",
    # common misspellings / alternate forms
    "Opensource & Community":                    "Open Source & Community",
    "opensource & community":                    "Open Source & Community",
    "Research & Academic breakthroughs":           "Research & Academic Breakthroughs",
    "research & academic breakthroughs":           "Research & Academic Breakthroughs",
}

_STRIP_CATEGORY_RE = re.compile(
    r"^\s*(?:"
    + "|".join(re.escape(k.lower()) for k in CANONICAL_KEYS)
    + r")\s*$",
    re.MULTILINE | re.IGNORECASE,
)

def _parse_article_category(text):
    """Return canonical category name from LLM output, or None."""
    for line in text.split("\n"):
        stripped = line.strip()
        # Also handle ## Category appearing on the same line as </thought>
        for part in stripped.split("</thought>"):
            part = part.strip()
            if part.startswith("## "):
                candidate = part[3:].strip()
                if candidate in CANONICAL_KEYS:
                    return candidate
                if candidate in CATEGORY_ALIASES:
                    return CATEGORY_ALIASES[candidate]
                collapsed = " ".join(candidate.split())
                if collapsed in CATEGORY_ALIASES:
                    return CATEGORY_ALIASES[collapsed]
                if collapsed.upper() in CANONICAL_KEYS:
                    return collapsed.upper()
        if not stripped.startswith("## "):
            continue
        candidate = stripped[3:].strip()
        if candidate in CANONICAL_KEYS:
            return candidate
        if candidate in CATEGORY_ALIASES:
            return CATEGORY_ALIASES[candidate]
        collapsed = " ".join(candidate.split())
        if collapsed in CATEGORY_ALIASES:
            return CATEGORY_ALIASES[collapsed]
        if collapsed.upper() in CANONICAL_KEYS:
            return collapsed.upper()
    return None

def _is_valid(text):
    if not text or len(text.strip()) < 50:
        return False
    for p in GARBAGE_PATTERNS:
        if p.search(text):
            return False
    return True

def _strip_title(title, desc):
    if not desc or not title:
        return desc
    esc = re.escape(title[:80])
    desc = re.sub(r"^Title:\s*" + esc + r"[\s\—\-:]+", "", desc, flags=re.I)
    desc = re.sub(r"^\(" + esc + r"\)[\s\-:]*", "", desc)
    desc = re.sub(r"^" + esc + r"[\s\—\-:]*", "", desc, flags=re.I)
    return desc

def _strip(content):
    """Remove <thought> blocks, ## category headers, and ### title lines."""
    lines = content.split("\n")
    kept, in_thought = [], False
    for line in lines:
        s = line.strip()
        if s.startswith("<thought>") or s.startswith("<thought "):
            in_thought = True
            continue
        if in_thought:
            # Exit thought block — extract any content after </thought> on the same line
            if "</thought>" in s:
                rest = s[s.index("</thought>") + len("</thought>"):].strip()
                in_thought = False
                # Apply same skip rules to rest (## header or ### title → drop)
                if rest and not rest.startswith("## ") and not rest.startswith("### "):
                    kept.append(rest)
            continue
        if not s.startswith("## ") and not s.startswith("### "):
            kept.append(line)
    return re.sub(_STRIP_CATEGORY_RE, "", "\n".join(kept)).strip()

# ── System prompt (shared by primary and Nemotron fallback) ─────────────────────
_SYSTEM_PROMPT = (
    "You are a senior analyst specialising in AI, Technologies, Finance, and Global Situation and News. "
    "CRITICAL FORMAT: Write your summary under a ## header using the EXACT category name from this list: "
    "Artificial Intelligence | Research & Academic Breakthroughs | Product Launches & Company News | "
    "Technology | Open Source & Community | Funding & Market Dynamics | Policy & Regulation | Finance | Global News. "
    'Example: "## Product Launches & Company News\\n### Article Title\\n<summary>\\n[**Source Name**](https://...)\" — '
    "the ## line MUST come first. Do NOT skip the ## header. Do NOT include <thought> or [Summary] blocks. "
    "After the summary, write the source as a markdown link on its own line."
)

# ── Stage 2: per-article summarization with retry ──────────────────────────────
def summarize_single_item(item, category_hint):
    clean_desc = _strip_title(item["title"], item["description"])
    item_text = f"ID: {item['id']}\nTitle: {item['title']}\nSource: {item['source']}\nURL: {item['url']}\nContent: {clean_desc}"
    prompt = config["news"]["stage2_prompt_template"].format(selected_news=item_text, count=1)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=SUMMARIZE_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=2048,
            )
            content = resp.choices[0].message.content.strip()
            if not _is_valid(content):
                logger.warning(f"  Attempt {attempt}/{MAX_RETRIES} invalid — retrying...")
                if attempt < MAX_RETRIES:
                    time.sleep(BASE_BACKOFF * (2 ** (attempt - 1)))
                continue
            cat = _parse_article_category(content) or category_hint
            return True, {
                "title": item["title"],
                "summary": _strip(content),
                "category": cat,
                "url": item["url"],
                "source": item.get("source", ""),
            }
        except Exception as e:
            logger.warning(f"  Attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(BASE_BACKOFF * (2 ** (attempt - 1)))

    # Nemotron fallback
    if NVIDIA_API_KEY:
        logger.info(f"  Primary failed — trying Nemotron...")
        nemo = OpenAI(api_key=NVIDIA_API_KEY, base_url="https://integrate.api.nvidia.com/v1")
        for na in range(1, 3):
            try:
                resp = nemo.chat.completions.create(
                    model="nvidia/nemotron-3-ultra-550b-a55b",
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=2048,
                )
                content = resp.choices[0].message.content.strip()
                if not _is_valid(content):
                    logger.warning(f"  Nemotron attempt {na}/2 invalid.")
                    continue
                cat = _parse_article_category(content) or category_hint
                logger.info(f"  Nemotron fallback succeeded.")
                return True, {
                    "title": item["title"],
                    "summary": _strip(content),
                    "category": cat,
                    "url": item["url"],
                    "source": item.get("source", ""),
                }
            except Exception as e:
                logger.warning(f"  Nemotron attempt {na}/2 failed: {e}")

    logger.error(f"  All attempts failed for '{item['title'][:60]}'. Using raw description.")
    raw = item["description"][:300].strip() if item["description"] else item["title"]
    return False, {
        "title": item["title"],
        "summary": raw,
        "category": category_hint,
        "url": item["url"],
        "source": item.get("source", ""),
    }

def stage2_summarization(selected_items):
    logger.info(f"Stage 2: summarizing {len(selected_items)} items...")
    articles, successes, failures = [], 0, 0
    for i, item in enumerate(selected_items, 1):
        logger.info(f"  [{i}/{len(selected_items)}] {item['title'][:70]}...")
        ok, article = summarize_single_item(item, item["group"])
        if ok:
            successes += 1
        else:
            failures += 1
        articles.append(article)
    logger.info(f"Stage 2 done: {successes} ok, {failures} failed.")

    # Build digest text for webhook fallback path
    digest_lines = ["# The Thinking Times — Daily Digest\n"]
    cur_cat = None
    for a in articles:
        if a["category"] != cur_cat:
            cur_cat = a["category"]
            digest_lines.append(f"\n## {cur_cat}\n")
        digest_lines.append(f"### {a['title']}\n{a['summary']}\n**Source:** [{a.get('source','')}]({a['url']})\n")
    return articles, "\n".join(digest_lines), {"successes": successes, "failures": failures}

def parse_digest_to_articles(digest_or_articles):
    """Return the article list directly — stage2_summarization already returns structured dicts."""
    if isinstance(digest_or_articles, list):
        return digest_or_articles
    logger.error("parse_digest_to_articles received a string — pipeline bug")
    return []

# ── Discord dispatch ─────────────────────────────────────────────────────────────
def create_discord_embeds(articles):
    embeds = []
    for a in articles:
        url = a["url"] if a.get("url", "").startswith("http") else ""
        src = a.get("source", "Source")
        # Strip trailing markdown source link — added back explicitly below
        summary_clean = re.sub(r'\n?\[\*\*[^\]]+\*\]\([^)]+\)\s*$', '', a["summary"].strip())
        embeds.append({
            "title": a["title"],
            "url": url,
            "description": summary_clean + (f"\n[**{src}**]({url})" if url else ""),
            "color": 3447003,
            "footer": {"text": f"Category: {a['category']}"},
            "timestamp": datetime.utcnow().isoformat(),
        })
    return embeds

def send_via_webhook(digest_text, articles):
    if not DISCORD_WEBHOOK_URL:
        return
    logger.info("Dispatching via Webhook...")
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": "📰 **The Thinking Times: Daily AI Intelligence Dispatch**", "username": "The Thinking Times"})
    except Exception as e:
        logger.error(f"Webhook header error: {e}")
    if not articles:
        for chunk in [digest_text[i:i+1900] for i in range(0, len(digest_text), 1900)]:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk, "username": "The Thinking Times"})
        return
    for a in articles:
        try:
            embed = create_discord_embeds([a])[0]
            r = requests.post(DISCORD_WEBHOOK_URL, json={"username": "The Thinking Times", "embeds": [embed]})
            if r.status_code == 429:
                time.sleep(r.json().get("retry_after", 1))
            time.sleep(1)
        except Exception as e:
            logger.error(f"Webhook article error: {e}")

async def send_via_bot(articles):
    if not DISCORD_BOT_TOKEN:
        return
    logger.info("Dispatching via Bot...")
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    bot = discord.Client(intents=intents)
    done = asyncio.Future()

    @bot.event
    async def on_ready():
        try:
            target = config["news"].get("discord_bot_channel", "the-thinking-times")
            logger.info(f"Bot logged in. Scanning {len(bot.guilds)} guilds...")
            for guild in bot.guilds:
                channel = discord.utils.get(guild.text_channels, name=target)
                if not channel:
                    channel = next((c for c in guild.text_channels if target in c.name), None)
                if channel:
                    try:
                        await channel.send("📰 **The Thinking Times: Daily AI Intelligence Dispatch**")
                        for a in articles:
                            embed = discord.Embed.from_dict(create_discord_embeds([a])[0])
                            await channel.send(embed=embed)
                            await asyncio.sleep(0.5)
                        logger.info(f"Sent to {guild.name}.")
                    except Exception as e:
                        logger.error(f"Send error in {guild.name}: {e}")
                else:
                    logger.warning(f"No channel #{target} in {guild.name}.")
        finally:
            if not done.done():
                done.set_result(True)

    async def run():
        try:
            await bot.start(DISCORD_BOT_TOKEN)
        except Exception as e:
            logger.error(f"Bot error: {e}")
            if not done.done():
                done.set_exception(e)

    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(done, timeout=60)
        logger.info("Bot dispatch complete.")
    except asyncio.TimeoutError:
        logger.error("Bot timed out — check Message Content Intent in Discord Portal.")
    finally:
        await bot.close()
        task.cancel()

# ── Main ────────────────────────────────────────────────────────────────────────
async def main():
    logger.info("Starting The Thinking Times...")
    raw = fetch_all_news()
    if not raw:
        logger.error("No news fetched.")
        return

    selected = stage1_selection(raw)
    articles, digest, stats = stage2_summarization(selected)
    logger.info(f"Stage 2: {stats['successes']} ok, {stats['failures']} failed.")

    with open("news.json", "w") as f:
        json.dump({"last_updated": datetime.now().isoformat(), "articles": articles}, f, indent=4)

    if DRY_RUN:
        logger.info("[DRY-RUN] Discord dispatch skipped.")
    else:
        send_via_webhook(digest, articles)
        await send_via_bot(articles)

    cache = load_story_cache()
    now = datetime.now().isoformat()
    for a in articles:
        if a.get("url"):
            cache[a["url"]] = now
    save_story_cache(cache)
    logger.info(f"Done. Story cache updated with {len(articles)} URLs.")

if __name__ == "__main__":
    asyncio.run(main())

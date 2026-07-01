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

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load Config
try:
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
except Exception as e:
    logger.error(f"Failed to load config.yaml: {e}")
    exit(1)

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PROVIDER_API_KEY = os.getenv("PROVIDER_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# ── Provider auto-detection ────────────────────────────────────────────────────
# Model name (from MODEL env > config.yaml) drives everything:
#   - "nvidia"/"nemotron" in model name  → NVIDIA endpoint + NVIDIA_API_KEY
#   - "gemma"/"gemini" in model name    → AI Studio endpoint + GEMINI_API_KEY
#   - unknown model                      → PROVIDER_API_KEY + PROVIDER_BASE_URL (both required)
#   - MODEL env not set                  → try MODEL env, then config.yaml, then hardcoded defaults

HARDCODED_DEFAULTS = [
    ("nvidia", "https://integrate.api.nvidia.com/v1", "nvidia/nemotron-3-ultra-550b-a55b", NVIDIA_API_KEY),
    ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemma-4-31b-it", GEMINI_API_KEY),
]

PROVIDER_MODEL_PATTERNS = {
    "nvidia": lambda m: "nvidia" in m.lower() or "nemotron" in m.lower(),
    "gemini":  lambda m: "gemma" in m.lower() or "gemini" in m.lower(),
}

def _detect_from_model(model_name):
    """Return (provider, base_url, api_key) for a given model name, or None."""
    for provider, matcher in PROVIDER_MODEL_PATTERNS.items():
        if matcher(model_name):
            key = {"nvidia": NVIDIA_API_KEY, "gemini": GEMINI_API_KEY}.get(provider)
            base = {"nvidia": "https://integrate.api.nvidia.com/v1",
                    "gemini":  "https://generativelanguage.googleapis.com/v1beta/openai/"}.get(provider)
            if key:
                return provider, base, key
    return None  # unknown provider — must use PROVIDER_* vars

# Step 1: Resolve MODEL — env > config > hardcoded default
_model_env = os.getenv("MODEL")
_yaml_model = config.get('llm', {}).get('model')
MODEL = _model_env or _yaml_model

# Step 2: Determine provider based on resolved model name
_active_provider = None
BASE_URL = None
API_KEY = None

if MODEL:
    detected = _detect_from_model(MODEL)
    if detected:
        _active_provider, BASE_URL, API_KEY = detected

if _active_provider is None:
    # Unknown model or MODEL not set — require PROVIDER_* vars
    _pb = os.getenv("PROVIDER_BASE_URL")
    _pk = PROVIDER_API_KEY
    if _pb and _pk:
        _active_provider = "provider"
        BASE_URL = _pb
        API_KEY = _pk
        logger.info(f"Using custom provider: MODEL='{MODEL}', BASE_URL from PROVIDER_BASE_URL")
    else:
        # Step 3: Fall back through hardcoded (NVIDIA+Nemotron → AIStudio+Gemma)
        for prov, base, model_d, key in HARDCODED_DEFAULTS:
            if key:
                _active_provider = prov
                BASE_URL = base
                MODEL = model_d
                API_KEY = key
                logger.info(f"No MODEL env/config — using hardcoded default: {prov.upper()} + {model_d}")
                break

if _active_provider is None or not API_KEY or not BASE_URL:
    logger.error("Could not resolve provider. Set MODEL env (with nvidia/gemma in name), or PROVIDER_API_KEY + PROVIDER_BASE_URL.")
    exit(1)

# Step 3: Log what we settled on
logger.info(f"Provider: {_active_provider.upper()}")
logger.info(f"Using base_url: {BASE_URL}")
logger.info(f"Using model: {MODEL}")
logger.info(f"API key source: {_active_provider.upper()}_API_KEY")

MAX_RETRIES = 3
BASE_BACKOFF = 2  # seconds
DRY_RUN = os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes")

STORY_CACHE_DAYS = int(os.getenv("STORY_CACHE_DAYS", "7"))  # don't resend stories seen within this window
STORY_CACHE_FILE = "story_cache.json"

# ── Seen-story cache ────────────────────────────────────────────────────────────

def _cache_age(date_str):
    """Return approximate age of a cache entry in days."""
    try:
        cached = datetime.fromisoformat(date_str)
        return (datetime.now() - cached).days
    except Exception:
        return 999

def load_story_cache():
    """Load the story URL→date cache. Returns dict of {url: iso_date_str}."""
    if not os.path.exists(STORY_CACHE_FILE):
        return {}
    try:
        with open(STORY_CACHE_FILE, "r") as f:
            raw = json.load(f)
        # Prune entries older than STORY_CACHE_DAYS while loading
        cutoff = datetime.now().timestamp() - (STORY_CACHE_DAYS * 86400)
        pruned = {
            url: ts for url, ts in raw.items()
            if datetime.fromisoformat(ts.replace("Z","+00:00")).timestamp() > cutoff
               if STORY_CACHE_DAYS > 0
        }
        return pruned
    except Exception as e:
        logger.warning(f"Could not load story cache: {e}")
        return {}

def save_story_cache(cache):
    """Save the story cache, pruning entries older than STORY_CACHE_DAYS."""
    try:
        with open(STORY_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        logger.error(f"Could not save story cache: {e}")

def filter_seen_stories(items, seen_cache):
    """Drop items whose URL is in the seen_cache within STORY_CACHE_DAYS."""
    skipped = 0
    kept = []
    for item in items:
        url = item.get('url') or ""
        if url and url in seen_cache:
            age = _cache_age(seen_cache[url])
            if age <= STORY_CACHE_DAYS:
                skipped += 1
                logger.debug(f"Skipped (seen {age}d ago): {item['title'][:60]}")
                continue
        kept.append(item)
    if skipped:
        logger.info(f"Story cache: skipped {skipped} already-seen stories (≤{STORY_CACHE_DAYS}d old).")
    return kept
client = OpenAI(
    base_url=BASE_URL,
    api_key=API_KEY
)

def normalize_title(title):
    """Return a set of significant word tokens from a title for similarity comparison."""
    t = title.lower()
    t = re.sub(r'^(breaking|update|just in|exclusive|announcing):\s*', '', t)
    t = re.sub(r'[^\w\s]', ' ', t)
    stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'has', 'have', 'had', 'do', 'does', 'did'}
    tokens = {w for w in t.split() if w not in stopwords and len(w) > 2}
    return tokens

def jaccard_similarity(set_a, set_b):
    """Jaccard similarity between two sets: |A∩B| / |A∪B|."""
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / max(len(set_a | set_b), 1)

def deduplicate_items(items, threshold=0.7):
    """Drop near-duplicate items (by title similarity > threshold), keeping the first-seen."""
    unique = []
    dropped = 0
    for item in items:
        item_norm = normalize_title(item['title'])
        is_dup = any(
            jaccard_similarity(item_norm, normalize_title(u['title'])) > threshold
            for u in unique
        )
        if is_dup:
            dropped += 1
            logger.debug(f"Dropped duplicate: {item['title']}")
        else:
            unique.append(item)
    if dropped:
        logger.info(f"Deduplicated {dropped} items → kept {len(unique)} unique stories.")
    return unique

def fetch_all_news():
    all_items = []
    item_id = 0
    for group, sources in config['feeds'].items():
        logger.info(f"Fetching {group}...")
        for name, url in sources.items():
            try:
                feed = feedparser.parse(url)
                if not feed.entries:
                    logger.warning(f"No entries found for {name}")
                    continue
                
                count = 0
                for entry in feed.entries:
                    if count >= config['news']['max_items_per_source']:
                        break
                    
                    item_id += 1
                    all_items.append({
                        "id": f"ID-{item_id}",
                        "source": name,
                        "title": entry.title,
                        "description": entry.summary if hasattr(entry, 'summary') else entry.title,
                        "url": entry.link,
                        "group": group
                    })
                    count += 1
            except Exception as e:
                logger.error(f"Error fetching {name}: {e}")

    logger.info(f"Fetched {len(all_items)} raw items from all sources.")
    all_items = deduplicate_items(all_items)
    seen_cache = load_story_cache()
    all_items = filter_seen_stories(all_items, seen_cache)
    logger.info(f"After seen-story filter: {len(all_items)} fresh items.")
    return all_items

def stage1_selection(news_items):
    logger.info(f"Stage 1: Selecting top items from {len(news_items)} stories...")
    
    formatted_news = "\n".join([f"[{item['id']}] Category: {item['group']} | {item['title']} - {item['source']}" for item in news_items])
    
    prompt = config['news']['stage1_prompt_template'].format(
        formatted_news=formatted_news,
        total_items=len(news_items)
    )
    
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a professional news editor. Output ONLY a JSON array of IDs like ['ID-1', 'ID-2']."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        content = response.choices[0].message.content.strip()
        logger.info(f"Stage 1 Raw Output: {content[:70]}...")
        
        # Super robust ID extraction
        selected_ids = re.findall(r'ID-\d+', content)
        
        if not selected_ids:
            logger.warning("No IDs found in LLM output. Using fallback.")
            return news_items[:15]
            
        selected_items = [item for item in news_items if item['id'] in selected_ids]

        # Hard cap: never summarize more than 20 items regardless of LLM output
        if len(selected_items) > 20:
            logger.warning(f"LLM returned {len(selected_items)} IDs — capping to 20.")
            selected_items = selected_items[:20]

        logger.info(f"Selected {len(selected_items)} items.")
        return selected_items
    except Exception as e:
        logger.error(f"Stage 1 Error: {e}")
        return news_items[:15]

# Patterns that indicate LLM returned placeholder/invalid output instead of a real summary
GARBAGE_PATTERNS = [
    re.compile(r'\*No relevant items', re.IGNORECASE),
    re.compile(r'^#+\s*artificial intelligence\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^#+\s*finance\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^#+\s*global news\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^#+\s*research\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^#+\s*product launches?\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^#+\s*technology\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^#+\s*policy\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^#+\s*open source\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^#+\s*funding\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'all\s+\d+\s+items?\s+are\s+excluded', re.IGNORECASE),
    re.compile(r'no stories?(?:were)?\s*identified', re.IGNORECASE),
    re.compile(r'the\s+digest\s+contains\s+no\s+items?', re.IGNORECASE),
]

# Canonical category name → normalized key (for matching LLM output headers)
# Canonical category names — only aliases need mapping; canonical forms are stored as-is.
CANONICAL_CATEGORIES = {
    # Aliases → canonical
    "PRODUCT LAUNCHES, UPDATES & COMPANY NEWS": "PRODUCT LAUNCHES & COMPANY NEWS",
    "PRODUCT LAUNCHES AND COMPANY NEWS":         "PRODUCT LAUNCHES & COMPANY NEWS",
    # Canonical forms — stored directly (identity)
    "ARTIFICIAL INTELLIGENCE":         None,
    "RESEARCH & ACADEMIC BREAKTHROUGHS": None,
    "PRODUCT LAUNCHES & COMPANY NEWS":  None,
    "TECHNOLOGY":                      None,
    "OPEN SOURCE & COMMUNITY":          None,
    "FUNDING & MARKET DYNAMICS":       None,
    "POLICY & REGULATION":              None,
    "FINANCE":                          None,
    "GLOBAL NEWS":                      None,
}

def _parse_article_category(llm_output):
    """Extract the canonical category from LLM output. Returns canonical name or None."""
    lines = llm_output.split("\n")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            candidate = stripped[3:].strip()
            if candidate in CANONICAL_CATEGORIES:
                mapped = CANONICAL_CATEGORIES[candidate]
                # Identity entry → value is None; return candidate directly
                # Alias entry → value is the canonical name string
                return mapped if mapped is not None else candidate
            # Fuzzy match: uppercase, collapse whitespace (handles "  PRODUCT LAUNCHES  &  COMPANY NEWS")
            key = " ".join(candidate.upper().split())
            for known in CANONICAL_CATEGORIES:
                if " ".join(known.upper().split()) == key:
                    mapped = CANONICAL_CATEGORIES[known]
                    return mapped if mapped is not None else known
    return None

def _is_valid_summary(text):
    """Return True if text looks like a real summary, False if it's placeholder garbage."""
    if not text or len(text.strip()) < 50:
        return False
    for pattern in GARBAGE_PATTERNS:
        if pattern.search(text):
            return False
    return True

def _strip_category_header(content):
    """Remove the leading ## category header line from LLM output, if present."""
    lines = content.split("\n")
    if lines and lines[0].strip().startswith("## "):
        return "\n".join(lines[1:]).lstrip("\n")
    return content


def summarize_single_item(item, category_hint):
    """Summarize a single news item with exponential-backoff retry. Returns (success, article_dict)."""
    single_item_text = (
        f"ID: {item['id']}\n"
        f"Title: {item['title']}\n"
        f"Source: {item['source']}\n"
        f"URL: {item['url']}\n"
        f"Content: {item['description']}"
    )
    prompt = config['news']['stage2_prompt_template'].format(
        selected_news=single_item_text
    )
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "You are a senior analyst specialising in AI, Technologies, Finance, and Global Situation and News."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1024
            )
            content = response.choices[0].message.content.strip()

            # Validate: reject placeholder/garbage output
            if not _is_valid_summary(content):
                logger.warning(f"  Attempt {attempt}/{MAX_RETRIES} returned invalid output for '{item['title'][:60]}' — retrying...")
                if attempt < MAX_RETRIES:
                    backoff = BASE_BACKOFF * (2 ** (attempt - 1))
                    time.sleep(backoff)
                continue

            # Extract the canonical category the LLM used
            parsed_cat = _parse_article_category(content)
            final_cat = parsed_cat if parsed_cat else category_hint
            # Strip the ## header from the summary — category is saved separately
            clean_summary = _strip_category_header(content)

            return True, {
                "title": item['title'],
                "summary": clean_summary,
                "category": final_cat,
                "url": item['url']
            }
        except Exception as e:
            logger.warning(f"  Attempt {attempt}/{MAX_RETRIES} failed for '{item['title'][:60]}': {e}")
            if attempt < MAX_RETRIES:
                backoff = BASE_BACKOFF * (2 ** (attempt - 1))
                logger.info(f"  Retrying in {backoff}s...")
                time.sleep(backoff)

    # Final fallback: use raw description
    logger.error(f"  All {MAX_RETRIES} attempts failed or returned garbage for '{item['title'][:60]}'. Using fallback.")
    fallback_summary = f"({item['title']}: {item['description'][:250]}...) [LLM summarization unavailable]"
    return False, {
        "title": item['title'],
        "summary": fallback_summary,
        "category": category_hint,
        "url": item['url']
    }

def stage2_summarization(selected_items):
    """Summarize selected items one at a time with retry logic. Returns (articles_list, digest_text, stats)."""
    logger.info(f"Stage 2: Summarizing {len(selected_items)} items (per-article, with retry)...")
    articles = []
    successes = 0
    failures = 0

    for i, item in enumerate(selected_items, 1):
        logger.info(f"  [{i}/{len(selected_items)}] Summarizing: {item['title'][:70]}...")
        ok, article = summarize_single_item(item, item['group'])
        if ok:
            successes += 1
        else:
            failures += 1
        articles.append(article)

    logger.info(f"Stage 2 complete: {successes} successful, {failures} failed out of {len(selected_items)} items.")

    # Rebuild a markdown digest text from the articles for webhook/bot use
    digest_lines = ["# The Thinking Times — Daily Digest\n"]
    current_cat = None
    for article in articles:
        if article['category'] != current_cat:
            current_cat = article['category']
            digest_lines.append(f"\n## {current_cat}\n")
        digest_lines.append(f"### {article['title']}\n{article['summary']}\n**Source:** [{article.get('source','')}]({article['url']})\n")

    return articles, "\n".join(digest_lines), {"successes": successes, "failures": failures}

def parse_digest_to_articles(digest_or_articles):
    """Parse LLM output into a list of article dicts.

    New code path: if input is already a list of dicts (per-article structured results),
    return it directly. If it's a raw text digest string, parse with the original regex logic.
    """
    # New structured path: stage2_summarization now returns per-article results directly
    if isinstance(digest_or_articles, list):
        logger.info(f"parse_digest_to_articles: received {len(digest_or_articles)} structured articles.")
        return digest_or_articles

    # Legacy text-parsing path (kept for backward compatibility)
    # Canonical category names — mirrors CANONICAL_CATEGORIES
    KNOWN_CATEGORIES = {
        "ARTIFICIAL INTELLIGENCE",
        "RESEARCH & ACADEMIC BREAKTHROUGHS",
        "PRODUCT LAUNCHES & COMPANY NEWS",
        "PRODUCT LAUNCHES, UPDATES & COMPANY NEWS",
        "PRODUCT LAUNCHES AND COMPANY NEWS",
        "TECHNOLOGY",
        "OPEN SOURCE & COMMUNITY",
        "FUNDING & MARKET DYNAMICS",
        "POLICY & REGULATION",
        "FINANCE",
        "GLOBAL NEWS",
    }

    def is_category_line(line):
        """Return the canonical category name if line is a category header, else None."""
        stripped = line.strip()
        # Handle ## ARTIFICIAL INTELLIGENCE
        if stripped.startswith("## "):
            candidate = stripped[3:].strip()
        else:
            candidate = stripped
        return candidate if candidate in KNOWN_CATEGORIES else None

    digest_text = digest_or_articles
    articles = []
    current_category = None  # None until first recognized category

    # Line-by-line parser: handles both ## headers and plain category names
    lines = digest_text.split("\n")
    i = 0
    while i < len(lines):
        # Check for category header
        cat_match = is_category_line(lines[i])
        if cat_match:
            current_category = cat_match
            i += 1
            continue

        # Check for article title (### Title)
        if lines[i].strip().startswith("### "):
            title = lines[i].strip().replace("### ", "").strip()
            summary_parts = []
            url = None
            i += 1
            # Collect summary lines and URL until next ### or category or end
            while i < len(lines):
                line = lines[i]
                # Stop at next article or category
                if is_category_line(line) or line.strip().startswith("### "):
                    break
                link_match = re.search(r'https?://[^\s\)\>]+', line)
                if link_match and not url:
                    url = link_match.group(0).rstrip('.,')
                # Skip blank lines and section/ruler lines
                if line.strip() and not line.startswith("#") and line.strip() not in ("---", "***"):
                    summary_parts.append(line.strip())
                i += 1

            summary = " ".join(summary_parts)
            if title and summary:
                articles.append({
                    "title": title,
                    "summary": summary[:4000],
                    "category": current_category if current_category else "GLOBAL NEWS",
                    "url": url if url else "",
                })
        else:
            i += 1

    logger.info(f"Successfully parsed {len(articles)} articles.")
    return articles

def create_discord_embeds(articles):
    embeds = []
    for article in articles:
        embed = {
            "title": article['title'],
            "description": article['summary'],
            "color": 3447003,
            "footer": {"text": f"Category: {article['category']}"},
            "timestamp": datetime.utcnow().isoformat()
        }
        if article['url'] and article['url'].startswith("http"):
            embed["url"] = article['url']
        embeds.append(embed)
    return embeds

def send_via_webhook(digest_text, articles):
    if not DISCORD_WEBHOOK_URL:
        return
    
    logger.info("Dispatching via Webhook...")
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={
            "content": "📰 **The Thinking Times: Daily AI Intelligence Dispatch**",
            "username": "The Thinking Times"
        })
    except Exception as e:
        logger.error(f"Webhook header error: {e}")

    if not articles:
        chunks = [digest_text[i:i+1900] for i in range(0, len(digest_text), 1900)]
        for chunk in chunks:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk, "username": "The Thinking Times"})
        return

    for article in articles:
        try:
            embed = create_discord_embeds([article])[0]
            payload = {"username": "The Thinking Times", "embeds": [embed]}
            r = requests.post(DISCORD_WEBHOOK_URL, json=payload)
            if r.status_code == 429:
                retry_after = r.json().get('retry_after', 1)
                time.sleep(retry_after)
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
    
    client_bot = discord.Client(intents=intents)

    # Use a Future to signal when we're done
    done = asyncio.Future()

    @client_bot.event
    async def on_ready():
        try:
            target_channel_name = config['news'].get('discord_bot_channel', 'the-thinking-times')
            logger.info(f"Bot logged in as {client_bot.user}")
            logger.info(f"Connected to {len(client_bot.guilds)} guilds.")
            
            for guild in client_bot.guilds:
                logger.info(f"Scanning Guild: {guild.name}")
                channel = discord.utils.get(guild.text_channels, name=target_channel_name)
                if not channel:
                    channel = next((c for c in guild.text_channels if target_channel_name in c.name), None)
                
                if channel:
                    try:
                        logger.info(f"Found channel #{channel.name}. Sending...")
                        await channel.send("📰 **The Thinking Times: Daily AI Intelligence Dispatch**")
                        for article in articles:
                            embed_data = create_discord_embeds([article])[0]
                            embed = discord.Embed.from_dict(embed_data)
                            await channel.send(embed=embed)
                            await asyncio.sleep(0.5)
                        logger.info(f"Sent to {guild.name}")
                    except Exception as e:
                        logger.error(f"Send error in {guild.name}: {e}")
                else:
                    logger.warning(f"No channel #{target_channel_name} found in {guild.name}")
        finally:
            if not done.done():
                done.set_result(True)

    async def run_bot():
        try:
            await client_bot.start(DISCORD_BOT_TOKEN)
        except Exception as e:
            logger.error(f"Bot start error: {e}")
            if not done.done():
                done.set_exception(e)

    # Run bot with timeout
    bot_task = asyncio.create_task(run_bot())
    try:
        await asyncio.wait_for(done, timeout=60)
        logger.info("Bot dispatch finished successfully.")
    except asyncio.TimeoutError:
        logger.error("Bot dispatch timed out! (Check if 'Message Content Intent' is enabled in Discord Portal)")
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        await client_bot.close()
        bot_task.cancel()

async def main():
    logger.info("Starting The Thinking Times news generation...")
    raw_news = fetch_all_news()
    if not raw_news:
        logger.error("No news fetched. Exiting.")
        return
    
    selected = stage1_selection(raw_news)
    articles, digest, stage2_stats = stage2_summarization(selected)
    logger.info(f"Stage 2 stats: {stage2_stats['successes']} succeeded, {stage2_stats['failures']} failed.")
    
    output_data = {
        "last_updated": datetime.now().isoformat(),
        "articles": articles
    }
    
    with open("news.json", "w") as f:
        json.dump(output_data, f, indent=4)
        
    # Hybrid Dispatch
    if DRY_RUN:
        logger.info("[DRY-RUN] Discord dispatch skipped.")
    else:
        send_via_webhook(digest, articles)
        await send_via_bot(articles)

    # Update seen-story cache with the URLs dispatched this run
    seen_cache = load_story_cache()
    now = datetime.now().isoformat()
    for article in articles:
        url = article.get('url') or ""
        if url:
            seen_cache[url] = now
    save_story_cache(seen_cache)
    logger.info(f"Story cache updated with {len(articles)} URLs (window: {STORY_CACHE_DAYS}d).")

    logger.info("Process complete.")

if __name__ == "__main__":
    asyncio.run(main())

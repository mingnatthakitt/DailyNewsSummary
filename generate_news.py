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
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY not found in environment.")
    exit(1)

client = OpenAI(
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key=GEMINI_API_KEY
)

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
            model=config['llm']['model'],
            messages=[
                {"role": "system", "content": "You are a professional news editor. Output ONLY a JSON array of IDs like ['ID-1', 'ID-2']."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        content = response.choices[0].message.content.strip()
        logger.info(f"Stage 1 Raw Output: {content[:100]}...")
        
        # Super robust ID extraction
        selected_ids = re.findall(r'ID-\d+', content)
        
        if not selected_ids:
            logger.warning("No IDs found in LLM output. Using fallback.")
            return news_items[:15]
            
        selected_items = [item for item in news_items if item['id'] in selected_ids]
        logger.info(f"Selected {len(selected_items)} items.")
        return selected_items
    except Exception as e:
        logger.error(f"Stage 1 Error: {e}")
        return news_items[:15]

def stage2_summarization(selected_items):
    logger.info("Stage 2: Generating detailed summaries...")
    
    formatted_selected = "\n".join([
        f"ID: {item['id']}\nTitle: {item['title']}\nSource: {item['source']}\nURL: {item['url']}\nContent: {item['description']}\n---" 
        for item in selected_items
    ])
    
    prompt = config['news']['stage2_prompt_template'].format(
        count=len(selected_items),
        selected_news=formatted_selected
    )
    
    try:
        response = client.chat.completions.create(
            model=config['llm']['model'],
            messages=[
                {"role": "system", "content": "You are a senior analyst specialising in AI, Technologies, Finance, and Global Situation and News. Follow the Markdown format strictly (## Category, ### Headline)."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=15000
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Stage 2 Error: {e}")
        return "Error generating digest."

def parse_digest_to_articles(digest_text):
    articles = []
    current_category = "General Intelligence"
    
    # Split by categories (##)
    sections = re.split(r'\n(?=## )', digest_text)
    
    for section in sections:
        section = section.strip()
        if not section: continue
        
        lines = section.split("\n")
        if lines[0].startswith("## "):
            current_category = lines[0].replace("## ", "").strip()
 
        # Split by articles (###)
        raw_articles = re.split(r'\n(?=### )', section)
        for raw_art in raw_articles:
            raw_art = raw_art.strip()
            if not raw_art or not raw_art.startswith("### "): continue
                
            art_lines = raw_art.split("\n")
            title = art_lines[0].replace("### ", "").strip()
            summary_parts = []
            url = None
            
            for line in art_lines[1:]:
                # More robust URL extraction: looks for any http link in the line
                link_match = re.search(r'https?://[^\s\)\>]+', line)
                if link_match and not url:
                    url = link_match.group(0).rstrip('.,')
                
                # If it's not a category/header line, treat it as summary text
                if line.strip() and not line.startswith("#"):
                    summary_parts.append(line.strip())
            
            summary = " ".join(summary_parts)
            
            if title and summary:
                articles.append({
                    "title": title, 
                    "summary": summary[:4000], # Discord limit safety
                    "category": current_category, 
                    "url": url if url else "" # Use empty string instead of '#'
                })
 
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
    intents.message_content = True  # Required for sending certain types of content
    intents.guilds = True
    
    client_bot = discord.Client(intents=intents)

    @client_bot.event
    async def on_ready():
        target_channel_name = config['news'].get('discord_bot_channel', 'the-thinking-times')
        logger.info(f"Bot logged in as {client_bot.user}")
        logger.info(f"Connected to {len(client_bot.guilds)} guilds.")
        
        if not client_bot.guilds:
            logger.warning("Bot is not in any guilds! Invite it to a server first.")

        for guild in client_bot.guilds:
            logger.info(f"Checking Guild: {guild.name} (ID: {guild.id})")
            channel = discord.utils.get(guild.text_channels, name=target_channel_name)
            
            if not channel:
                # Fallback: look for a channel that contains the name
                channel = next((c for c in guild.text_channels if target_channel_name in c.name), None)
            
            if channel:
                try:
                    logger.info(f"Found channel #{channel.name} in {guild.name}. Sending...")
                    await channel.send("📰 **The Thinking Times: Daily AI Intelligence Dispatch**")
                    for article in articles:
                        embed_data = create_discord_embeds([article])[0]
                        embed = discord.Embed.from_dict(embed_data)
                        await channel.send(embed=embed)
                        await asyncio.sleep(0.5)
                    logger.info(f"Successfully sent to {guild.name}")
                except Exception as e:
                    logger.error(f"Error sending to {guild.name}: {e}")
            else:
                logger.warning(f"Could not find channel #{target_channel_name} in {guild.name}. Available channels: {[c.name for c in guild.text_channels]}")
        
        await client_bot.close()

    try:
        # Using wait_for or similar might be safer, but start() is okay for single-run
        await client_bot.start(DISCORD_BOT_TOKEN)
    except Exception as e:
        logger.error(f"Bot execution error: {e}")

async def main():
    logger.info("Starting The Thinking Times news generation...")
    raw_news = fetch_all_news()
    if not raw_news:
        logger.error("No news fetched. Exiting.")
        return
    
    selected = stage1_selection(raw_news)
    digest = stage2_summarization(selected)
    articles = parse_digest_to_articles(digest)
    
    output_data = {
        "last_updated": datetime.now().isoformat(),
        "articles": articles
    }
    
    with open("news.json", "w") as f:
        json.dump(output_data, f, indent=4)
        
    # Hybrid Dispatch
    send_via_webhook(digest, articles)
    await send_via_bot(articles)
    
    logger.info("Process complete.")

if __name__ == "__main__":
    asyncio.run(main())

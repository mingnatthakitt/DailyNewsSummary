import feedparser
from openai import OpenAI
import json
import os
import requests
import yaml
from datetime import datetime
import re
import logging
import yfinance as yf

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
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

if not NVIDIA_API_KEY:
    logger.error("NVIDIA_API_KEY not found in environment.")
    exit(1)

client = OpenAI(
    base_url=config['llm']['base_url'],
    api_key=NVIDIA_API_KEY
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
    
    formatted_news = "\n".join([f"[{item['id']}] {item['title']} - {item['source']}" for item in news_items])
    
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
                {"role": "system", "content": "You are a senior AI industry analyst. Follow the Markdown format strictly (## Category, ### Headline)."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=4000
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Stage 2 Error: {e}")
        return "Error generating digest."

def parse_digest_to_articles(digest_text):
    articles = []
    current_category = "General Intelligence"
    
    sections = re.split(r'\n(?=## )', digest_text)
    
    for section in sections:
        section = section.strip()
        if not section: continue
        
        lines = section.split("\n")
        if lines[0].startswith("## "):
            current_category = lines[0].replace("## ", "").strip()
            if "### " not in section: continue 

        raw_articles = re.split(r'\n(?=### )', section)
        for raw_art in raw_articles:
            raw_art = raw_art.strip()
            if not raw_art or not raw_art.startswith("### "): continue
                
            art_lines = raw_art.split("\n")
            title = art_lines[0].replace("### ", "").strip()
            summary = ""
            url = "#"
            
            for line in art_lines[1:]:
                if "Source:" in line:
                    match = re.search(r'\((https?://.*?)\)', line)
                    if match: url = match.group(1)
                    else:
                        match = re.search(r'(https?://[^\s]+)', line)
                        if match: url = match.group(0)
                elif line.strip() and not line.startswith("##"):
                    summary += line.strip() + " "
            
            if title and summary:
                articles.append({"title": title, "summary": summary.strip(), "category": current_category, "url": url})

    logger.info(f"Successfully parsed {len(articles)} articles.")
    return articles

def send_discord_notification(digest_text, articles):
    if not DISCORD_WEBHOOK_URL: return
        
    logger.info(f"Sending dispatch to Discord (Parsed: {len(articles)})")
    requests.post(DISCORD_WEBHOOK_URL, json={"content": "📰 **The Thinking Times: Daily AI Intelligence Dispatch**", "username": "The Thinking Times"})

    if not articles:
        chunks = [digest_text[i:i+1900] for i in range(0, len(digest_text), 1900)]
        for chunk in chunks:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk, "username": "The Thinking Times"})
        return

    for i in range(0, len(articles), 5):
        batch = articles[i:i+5]
        embeds = []
        for article in batch:
            embeds.append({
                "title": article['title'],
                "description": article['summary'][:1000] + "...",
                "url": article['url'],
                "color": 3447003,
                "footer": {"text": f"Category: {article['category']}"}
            })
        requests.post(DISCORD_WEBHOOK_URL, json={"embeds": embeds, "username": "The Thinking Times"})

def fetch_stock_data():
    symbols = ["NVDA", "AAPL", "MSFT", "TSLA", "GOOGL"]
    stock_data = []
    logger.info("Fetching stock data...")
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="2d")
            if len(hist) >= 2:
                price = hist['Close'].iloc[-1]
                prev_price = hist['Close'].iloc[-2]
                change = ((price - prev_price) / prev_price) * 100
                stock_data.append({"symbol": symbol, "price": round(price, 2), "change": round(change, 2)})
        except Exception as e:
            logger.error(f"Error fetching stock {symbol}: {e}")
    return stock_data

def main():
    logger.info("Starting The Thinking Times news generation...")
    raw_news = fetch_all_news()
    if not raw_news:
        logger.error("No news fetched. Exiting.")
        return
    
    stocks = fetch_stock_data()
    selected = stage1_selection(raw_news)
    digest = stage2_summarization(selected)
    
    articles = parse_digest_to_articles(digest)
    output_data = {
        "last_updated": datetime.now().isoformat(),
        "articles": articles,
        "stocks": stocks
    }
    
    with open("news.json", "w") as f:
        json.dump(output_data, f, indent=4)
        
    send_discord_notification(digest, articles)
    logger.info("Process complete.")

if __name__ == "__main__":
    main()

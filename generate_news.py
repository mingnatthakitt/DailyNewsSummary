import feedparser
from openai import OpenAI
import json
import os
import requests
from datetime import datetime

# Configuration
FEEDS = {
    "Tech": [
        "https://techcrunch.com/feed/",
        "https://www.theverge.com/rss/index.xml"
    ],
    "Finance": [
        "https://finance.yahoo.com/news/rssindex",
        "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best"
    ],
    "General": [
        "https://www.reutersagency.com/feed/?best-topics=general-news&post_type=best",
        "https://feeds.bbci.co.uk/news/world/rss.xml"
    ]
}

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=NVIDIA_API_KEY
)


def fetch_rss_news():
    news_items = []
    for category, urls in FEEDS.items():
        print(f"Fetching {category} news...")
        for url in urls:
            feed = feedparser.parse(url)
            # Take top 3 from each source to avoid overload
            for entry in feed.entries[:3]:
                news_items.append({
                    "title": entry.title,
                    "description": entry.summary if hasattr(entry, 'summary') else entry.title,
                    "url": entry.link,
                    "category": category
                })
    return news_items

def summarize_news(news_items):
    summarized_articles = []
    
    for item in news_items:
        prompt = f"""
        Summarize the following news article into exactly 2 sentences. 
        Focus on the 'what happened' and 'why it matters'.
        Keep the tone professional yet engaging.
        
        Title: {item['title']}
        Content: {item['description']}
        """
        try:
            response = client.chat.completions.create(
                model="moonshotai/kimi-k2-instruct",
                messages=[
                    {"role": "system", "content": "You are a professional news summarizer."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.6,
                top_p=0.9,
                max_tokens=150
            )
            summary = response.choices[0].message.content.strip()
            summarized_articles.append({
                "title": item['title'],
                "summary": summary,
                "url": item['url'],
                "category": item['category']
            })
            print(f"Summarized: {item['title'][:50]}...")
        except Exception as e:
            print(f"Error summarizing {item['title']}: {e}")
            
    return summarized_articles

def send_discord_notification(articles):
    if not DISCORD_WEBHOOK_URL:
        print("No Discord Webhook URL provided. Skipping notification.")
        return

    # Create a nice embed with the top 5 stories
    embeds = []
    for article in articles[:5]:
        embeds.append({
            "title": article['title'],
            "description": article['summary'],
            "url": article['url'],
            "color": 3447003, # Blue
            "footer": {"text": f"Category: {article['category']}"}
        })

    payload = {
        "content": "🚀 **Daily Pulse: Your AI-Summarized News is Ready!**",
        "embeds": embeds,
        "username": "Pulse AI"
    }

    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        response.raise_for_status()
        print("Discord notification sent!")
    except Exception as e:
        print(f"Failed to send Discord notification: {e}")

def main():
    print("Starting news aggregation...")
    raw_news = fetch_rss_news()
    
    if not raw_news:
        print("No news found.")
        return

    summarized = summarize_news(raw_news)
    
    # Save to news.json
    output_data = {
        "last_updated": datetime.now().isoformat(),
        "articles": summarized
    }
    
    with open("news.json", "w") as f:
        json.dump(output_data, f, indent=4)
    
    print(f"Saved {len(summarized)} articles to news.json")
    
    # Send notification
    send_discord_notification(summarized)

if __name__ == "__main__":
    main()

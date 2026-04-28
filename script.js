document.addEventListener('DOMContentLoaded', () => {
    const featuredContainer = document.getElementById('featured-news');
    const techContainer = document.getElementById('tech-news');
    const generalContainer = document.getElementById('general-news');
    const dateDisplay = document.getElementById('date-display');
    const discordBtn = document.getElementById('discord-btn');

    // Set current date (NYT style)
    const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
    dateDisplay.textContent = new Date().toLocaleDateString('en-US', options);

    async function fetchNews() {
        try {
            const response = await fetch('news.json');
            if (!response.ok) throw new Error('Failed to fetch news');
            
            const data = await response.json();
            renderLayout(data.articles);
        } catch (error) {
            console.error('Error:', error);
            featuredContainer.innerHTML = `<p style="padding: 2rem; text-align: center;">Unable to load news. Please ensure the GitHub Action has run successfully.</p>`;
        }
    }

    function renderLayout(articles) {
        if (!articles || articles.length === 0) return;

        // 1. Featured Article (First one)
        const featured = articles[0];
        featuredContainer.innerHTML = `
            <article class="featured-article">
                <span class="live-label">Featured Story</span>
                <h2>${featured.title}</h2>
                <div class="featured-image">
                    <div class="watch-overlay">AI ANALYST INSIGHT</div>
                </div>
                <p>${featured.summary}</p>
                <a href="${featured.url}" target="_blank" class="read-more">Read Full Article</a>
            </article>
        `;

        // 2. Left Column (Tech Intelligence)
        const techArticles = articles.filter(a => a.category.toLowerCase().includes('tech') || a.category.toLowerCase().includes('model')).slice(0, 5);
        techContainer.innerHTML += techArticles.map(article => `
            <div class="news-item">
                <span class="live-label">LIVE</span>
                <h4 onclick="window.open('${article.url}', '_blank')">${article.title}</h4>
                <ul class="bullet-points">
                    <li>${article.summary.split('. ')[0]}.</li>
                    <li>Industry Impact: High</li>
                </ul>
            </div>
        `).join('');

        // 3. Right Column (World & Market)
        const generalArticles = articles.filter(a => !techArticles.includes(a) && a !== featured).slice(0, 5);
        generalContainer.innerHTML += generalArticles.map(article => `
            <div class="news-item">
                <h4 onclick="window.open('${article.url}', '_blank')">${article.title}</h4>
                <p style="font-size: 0.85rem; color: #444;">${article.summary.slice(0, 100)}...</p>
                <a href="${article.url}" target="_blank" style="font-size: 0.7rem; color: #666; text-decoration: none;">[${article.category}] Source &rarr;</a>
            </div>
        `).join('');
    }

    discordBtn.addEventListener('click', () => {
        const message = `
HOW TO DISPATCH TO DISCORD:
1. Open your GitHub Actions page.
2. Select 'Daily News Update'.
3. Click 'Run workflow' (Green button).

The AI will generate the latest report and post it to Discord instantly.
        `;
        if (confirm(message)) {
            window.open('https://github.com/mingnatthakitt/DailyNewsSummary/actions', '_blank');
        }
    });

    fetchNews();
});

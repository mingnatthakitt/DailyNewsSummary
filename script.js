document.addEventListener('DOMContentLoaded', () => {
    const featuredContainer = document.getElementById('featured-news');
    const techContainer = document.getElementById('tech-news');
    const generalContainer = document.getElementById('general-news');
    const financeContainer = document.getElementById('finance-news');
    const dateDisplay = document.getElementById('date-display');


    // Set current date (NYT style)
    const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
    dateDisplay.textContent = new Date().toLocaleDateString('en-US', options);

    const liveTime = document.getElementById('live-time');
    const tzSelect = document.getElementById('tz-select');
    
    function updateClock() {
        const now = new Date();
        const offset = parseInt(tzSelect.value);
        
        // Calculate UTC time then apply offset
        const utc = now.getTime() + (now.getTimezoneOffset() * 60000);
        const newDate = new Date(utc + (3600000 * offset));
        
        const h = String(newDate.getHours()).padStart(2, '0');
        const m = String(newDate.getMinutes()).padStart(2, '0');
        const s = String(newDate.getSeconds()).padStart(2, '0');
        
        if (liveTime) liveTime.textContent = `${h}:${m}:${s}`;
    }

    if (tzSelect) {
        tzSelect.addEventListener('change', updateClock);
    }

    setInterval(updateClock, 1000);
    updateClock();

    async function fetchNews() {
        try {
            const response = await fetch(`news.json?t=${new Date().getTime()}`);
            if (!response.ok) throw new Error('Failed to fetch news');
            const data = await response.json();
            renderLayout(data.articles);
        } catch (error) {
            console.error('Error:', error);
            featuredContainer.innerHTML = `<p style="padding: 2rem; text-align: center;">Unable to load news.</p>`;
        }
    }

    function renderLayout(articles) {
        if (!articles || articles.length === 0) return;

        // 1. Featured Article (Fills the 'global-news' div in your center column)
        const globalContainer = document.getElementById('global-news');
        const featured = articles[0];
        
        globalContainer.innerHTML = `
            <article class="featured-article">
                <span class="live-label">Top Intelligence</span>
                <h2>${featured.title}</h2>
                <p>${featured.summary}</p>
                <a href="${featured.url}" target="_blank" class="read-more">Read Full Article</a>
            </article>
        `;

        // Clear the other containers
        techContainer.innerHTML = '';
        generalContainer.innerHTML = '';
        financeContainer.innerHTML = '';

        // Keep track of what we've shown so we don't repeat the featured story
        const displayedTitles = new Set([featured.title]);

        // 2. Tech Intelligence (Left Column: id="tech-news")
        const techArticles = articles.filter(a => {
            const cat = a.category.toLowerCase();
            return (cat.includes('tech') || cat.includes('model') || cat.includes('ai')) 
                   && !displayedTitles.has(a.title);
        }).slice(0, 5);
        
        techArticles.forEach(a => displayedTitles.add(a.title));
        techContainer.innerHTML = techArticles.map(article => createNewsHTML(article)).join('');

        // 3. Finance & Markets (Right Column: id="finance-news")
        const financeArticles = articles.filter(a => {
            const cat = a.category.toLowerCase();
            return (cat.includes('finance') || cat.includes('market') || cat.includes('business'))
                   && !displayedTitles.has(a.title);
        }).slice(0, 5);
        
        financeArticles.forEach(a => displayedTitles.add(a.title));
        financeContainer.innerHTML = financeArticles.map(article => createNewsHTML(article)).join('');

        // 4. Global Dispatch (Center Column - below the line: id="general-news")
        // Everything else goes here!
        const catchAllArticles = articles.filter(a => !displayedTitles.has(a.title)).slice(0, 5);
        generalContainer.innerHTML = catchAllArticles.map(article => createNewsHTML(article)).join('');
    }

    // Keep this helper function outside or inside renderLayout
    function createNewsHTML(article) {
        return `
            <div class="news-item">
                <h4 onclick="window.open('${article.url}', '_blank')">${article.title}</h4>
                <p>${article.summary.slice(0, 200)}...</p>
                <a href="${article.url}" target="_blank" class="source-link">Source: ${article.category}</a>
            </div>
        `;
    }
document.addEventListener('DOMContentLoaded', () => {
    // 1. SELECTORS - Matched exactly to your index.html IDs
    const featuredContainer = document.getElementById('featured-news');
    const techContainer = document.getElementById('tech-news');
    const generalContainer = document.getElementById('general-news');
    const financeContainer = document.getElementById('finance-news');
    const dateDisplay = document.getElementById('date-display');
    const liveTime = document.getElementById('live-time');
    const tzSelect = document.getElementById('tz-select');

    // 2. CLOCK LOGIC
    const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
    if (dateDisplay) dateDisplay.textContent = new Date().toLocaleDateString('en-US', options);

    function updateClock() {
        const now = new Date();
        const offset = parseInt(tzSelect.value || 8);
        const utc = now.getTime() + (now.getTimezoneOffset() * 60000);
        const newDate = new Date(utc + (3600000 * offset));
        const h = String(newDate.getHours()).padStart(2, '0');
        const m = String(newDate.getMinutes()).padStart(2, '0');
        const s = String(newDate.getSeconds()).padStart(2, '0');
        if (liveTime) liveTime.textContent = `${h}:${m}:${s}`;
    }

    if (tzSelect) tzSelect.addEventListener('change', updateClock);
    setInterval(updateClock, 1000);
    updateClock();

    // 3. HELPER FUNCTION
    function createNewsHTML(article) {
        const summary = article.summary || "";
        const cleanSummary = summary.length > 200 ? summary.slice(0, 200) + "..." : summary;
        return `
            <div class="news-item">
                <h4 onclick="window.open('${article.url}', '_blank')" style="cursor:pointer">${article.title}</h4>
                <p>${cleanSummary}</p>
                <a href="${article.url}" target="_blank" class="source-link">category: ${article.category}</a>
            </div>
        `;
    }

    // 4. FETCH AND RENDER
    async function fetchNews() {
        try {
            const response = await fetch(`news.json?t=${new Date().getTime()}`);
            if (!response.ok) throw new Error('Failed to fetch news');
            const data = await response.json();
            renderLayout(data.articles);
        } catch (error) {
            console.error('Fetch Error:', error);
            if (featuredContainer) featuredContainer.innerHTML = `<p>Unable to load news.</p>`;
        }
    }

    function renderLayout(articles) {
        if (!articles || articles.length === 0) return;

        // A. Featured Story (First article goes into #featured-news)
        const featured = articles[0];
        if (featuredContainer) {
            featuredContainer.innerHTML = `
                <article class="featured-article">
                    <span class="live-label">Top Intelligence</span>
                    <h2>${featured.title}</h2>
                    <p>${featured.summary}</p>
                    <a href="${featured.url}" target="_blank" class="read-more">Read Full Article</a>
                </article>
            `;
        }

        const displayedTitles = new Set([featured.title]);

        // B. Tech Column (#tech-news)
        const techArticles = articles.filter(a => {
            const cat = a.category.toLowerCase();
            return (cat.includes('artificial') || cat.includes('research') || cat.includes('product') || 
                    cat.includes('technology') || cat.includes('open source'))
                   && !displayedTitles.has(a.title);
        }).slice(0, 5);
        techArticles.forEach(a => displayedTitles.add(a.title));
        if (techContainer) techContainer.innerHTML = techArticles.map(createNewsHTML).join('');

        // C. Finance Column (#finance-news)
        const financeArticles = articles.filter(a => {
            const cat = a.category.toLowerCase();
            return (cat.includes('finance') || cat.includes('funding') || cat.includes('policy') || cat.includes('regulation'))
                   && !displayedTitles.has(a.title);
        }).slice(0, 5);
        financeArticles.forEach(a => displayedTitles.add(a.title));
        if (financeContainer) financeContainer.innerHTML = financeArticles.map(createNewsHTML).join('');

        // D. General Column (#general-news) - Catch all remaining
        const catchAll = articles.filter(a => !displayedTitles.has(a.title)).slice(0, 5);
        if (generalContainer) generalContainer.innerHTML = catchAll.map(createNewsHTML).join('');
    }

    fetchNews();
});

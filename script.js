document.addEventListener('DOMContentLoaded', () => {
    // ── 1. SELECTORS ────────────────────────────────────────────────────────────
    const featuredContainer = document.getElementById('featured-news');
    const techContainer     = document.getElementById('tech-news');
    const generalContainer  = document.getElementById('general-news');
    const financeContainer  = document.getElementById('finance-news');
    const dateDisplay      = document.getElementById('date-display');
    const liveTime         = document.getElementById('live-time');
    const tzSelect         = document.getElementById('tz-select');

    // ── 2. CLOCK ────────────────────────────────────────────────────────────────
    const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
    if (dateDisplay) dateDisplay.textContent = new Date().toLocaleDateString('en-US', options);

    function updateClock() {
        const now    = new Date();
        const offset = parseInt(tzSelect.value || 8);
        const utc    = now.getTime() + (now.getTimezoneOffset() * 60000);
        const nd     = new Date(utc + (3600000 * offset));
        const h = String(nd.getHours()).padStart(2, '0');
        const m = String(nd.getMinutes()).padStart(2, '0');
        const s = String(nd.getSeconds()).padStart(2, '0');
        if (liveTime) liveTime.textContent = `${h}:${m}:${s}`;
    }
    if (tzSelect) tzSelect.addEventListener('change', updateClock);
    setInterval(updateClock, 1000);
    updateClock();

    // ── 3. MARKDOWN STRIPPER ───────────────────────────────────────────────────
    // Removes markdown headers, emphasis, links, bullets — returns plain text
    function stripMarkdown(text) {
        if (!text) return '';
        return text
            // Remove ATX headers (## ### etc.)
            .replace(/^#{1,6}\s+(?:[🏦-🟥🔴]?\s*)?\*?[^*]*\*?\s*$/gm, '')
            // Remove blockquotes
            .replace(/^>\s*/gm, '')
            // Remove horizontal rules
            .replace(/^[-*_]{3,}\s*$/gm, '')
            // Remove inline bold/italic
            .replace(/\*\*([^*]+)\*\*/g, '$1')
            .replace(/\*([^*]+)\*/g, '$1')
            .replace(/__([^_]+)__/g, '$1')
            .replace(/_([^_]+)_/g, '$1')
            // Remove link syntax — keep link text
            .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
            // Remove image syntax
            .replace(/!\[[^\]]*\]\([^)]+\)/g, '')
            // Remove list markers (-, *, 1.)
            .replace(/^[\-\*\+]\s+/gm, '')
            .replace(/^\d+\.\s+/gm, '')
            // Remove "No relevant items" placeholders
            .replace(/\*No relevant items for this digest\.\*/gi, '')
            .replace(/\*No [^\n]+for this digest\.\*/gi, '')
            // Collapse 2+ newlines into one paragraph break
            .replace(/\n{2,}/g, '\n')
            .trim();
    }

    // ── 4. NEWS ITEM HTML ──────────────────────────────────────────────────────
    function createNewsHTML(article) {
        const raw      = article.summary || '';
        const plain    = stripMarkdown(raw);
        const catLabel = (article.category || 'General').split(' ')[0]; // first word only
        return `
            <div class="news-item">
                <h4 onclick="window.open('${article.url}', '_blank')" style="cursor:pointer">${article.title}</h4>
                <p class="summary-text">${plain}</p>
                <a href="${article.url}" target="_blank" class="source-link">${catLabel}</a>
            </div>
        `;
    }

    // ── 5. FEATURED ARTICLE HTML ───────────────────────────────────────────────
    function createFeaturedHTML(article) {
        const raw   = article.summary || '';
        const plain = stripMarkdown(raw);
        return `
            <article class="featured-article">
                <span class="live-label">Top Intelligence</span>
                <h2>${article.title}</h2>
                <p>${plain}</p>
                <a href="${article.url}" target="_blank" class="read-more">Read Full Article</a>
            </article>
        `;
    }

    // ── 6. CATEGORY MATCHERS ───────────────────────────────────────────────────
    // Returns true if the article text (title + summary) matches the given domain.
    function isTech(article) {
        const t = (article.title + ' ' + article.summary).toLowerCase();
        return /\b(ai|artificial intelligen|model|llm|gpt|gemini|claude|openai|anthropic|deepmind|google ai|microsoft ai|meta ai|neural network|machine learning|deep learning|research paper|arxiv|benchmark|open.?source|github|framework|library|algorithm|robot|agentic|rag|token| GPU |cuda|inference|train|data center|infrastructure)\b/.test(t);
    }

    function isFinance(article) {
        const t = (article.title + ' ' + article.summary).toLowerCase();
        const cat = (article.category || '').toLowerCase();
        return /\b(finance|market|stocks|equity|bond|interest rate|fed|central bank|inflation| earnings |revenue|profit|loss|funding|investment|investor|ipo|merger|acquisition|debt|loan|bank|credit|portfolio|valuation|dividend|etf|hedge fund|quarterly|sec|regulatory)\b/.test(t)
            || cat.includes('finance') || cat.includes('market');
    }

    function isGlobal(article) {
        const t = (article.title + ' ' + article.summary).toLowerCase();
        const cat = (article.category || '').toLowerCase();
        return /\b(geopolitic|war|conflict|diplomat|embargo|sanction|climate|energy| treaty |summit|g20|nato|un |security council|human right|refugee|terrorism|nuclear|iran|china|russia|ukraine|middle east|africa|asia|europe|americas|world|international|global)\b/.test(t)
            || cat.includes('general') || cat.includes('world');
    }

    // ── 7. FETCH & RENDER ─────────────────────────────────────────────────────
    async function fetchNews() {
        try {
            const response = await fetch(`news.json?t=${Date.now()}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            renderLayout(data.articles || []);
        } catch (err) {
            console.error('Fetch error:', err);
            [featuredContainer, techContainer, generalContainer, financeContainer].forEach(el => {
                if (el) el.innerHTML = '<p>Unable to load news.</p>';
            });
        }
    }

    function renderLayout(articles) {
        if (!articles || articles.length === 0) return;

        // ── A. Featured: first article ─────────────────────────────────────────
        const featured = articles[0];
        if (featuredContainer) featuredContainer.innerHTML = createFeaturedHTML(featured);

        const shown = new Set([featured.title, featured.url]);

        // ── B. Tech column ─────────────────────────────────────────────────────
        const tech = articles
            .filter(a => !shown.has(a.title) && !shown.has(a.url) && isTech(a))
            .slice(0, 6);
        tech.forEach(a => shown.add(a.title));
        if (techContainer) techContainer.innerHTML = tech.length
            ? tech.map(createNewsHTML).join('')
            : '<p class="empty-note">No tech articles today.</p>';

        // ── C. Finance column ─────────────────────────────────────────────────
        const finance = articles
            .filter(a => !shown.has(a.title) && !shown.has(a.url) && isFinance(a))
            .slice(0, 6);
        finance.forEach(a => shown.add(a.title));
        if (financeContainer) financeContainer.innerHTML = finance.length
            ? finance.map(createNewsHTML).join('')
            : '<p class="empty-note">No finance articles today.</p>';

        // ── D. General / Global column (catch-all remaining) ───────────────────
        const general = articles
            .filter(a => !shown.has(a.title) && !shown.has(a.url))
            .slice(0, 6);
        if (generalContainer) generalContainer.innerHTML = general.length
            ? general.map(createNewsHTML).join('')
            : '<p class="empty-note">No general news today.</p>';
    }

    fetchNews();
});

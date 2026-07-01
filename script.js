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
    // Strips all markdown noise — headers, bold, links, bullets, placeholders — returns clean prose
    function stripMarkdown(text) {
        if (!text) return '';
        return text
            // Remove ATX headers (single-line, any level)
            .replace(/^#{1,6}[ \t]+[^\n]*/gm, '')
            // Remove setext-style underlines
            .replace(/^={3,}[ \t]*$/gm, '')
            .replace(/^-{3,}[ \t]*$/gm, '')
            // Remove blockquotes
            .replace(/^>[ \t]*/gm, '')
            // Remove horizontal rules
            .replace(/^[-*_]{3,}[ \t]*$/gm, '')
            // Bold/italic markers — keep text
            .replace(/\*\*\s*([^*]+?)\s*\*\*/g, '$1')
            .replace(/\*\s*([^*]+?)\s*\*/g, '$1')
            .replace(/__\s*([^_]+?)\s*__/g, '$1')
            .replace(/_\s*([^_]+?)_\s*/g, '$1')
            // Standalone bold lines that are really headlines
            .replace(/^\*\*([^*]+)\*\*[ \t]*$/gm, '$1')
            .replace(/^__([^_]+)__[ \t]*$/gm, '$1')
            // Remove link syntax — keep link text
            .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
            // Remove image syntax
            .replace(/!\[[^\]]*\]\([^)]+\)/g, '')
            // Remove list markers
            .replace(/^[\-\*\+][ \t]+/gm, '')
            .replace(/^\d+\.[ \t]+/gm, '')
            // Remove placeholder/garbage patterns
            .replace(/\*No relevant items for this digest\.\*/gi, '')
            .replace(/\*No [^\n]+for this digest\.\*/gi, '')
            .replace(/no relevant items.*/gi, '')
            .replace(/all \d+ items are excluded.*/gi, '')
            .replace(/no stories?(?:were)? identified.*/gi, '')
            .replace(/the digest contains no items?.*/gi, '')
            // Remove orphaned category header words that survive the above
            .replace(/^ARTIFICIAL INTELLIGENCE$/gim, '')
            .replace(/^FINANCE$/gim, '')
            .replace(/^GLOBAL NEWS$/gim, '')
            .replace(/^RESEARCH[ &]ACADEMIC[ &]BREAKTHROUGHS$/gim, '')
            .replace(/^PRODUCT LAUNCHES[ ,]?UPDATES[, &]* ?COMPANY NEWS$/gim, '')
            .replace(/^TECHNOLOGY$/gim, '')
            .replace(/^OPEN SOURCE[ &]COMMUNITY$/gim, '')
            .replace(/^FUNDING[ &]MARKET DYNAMICS$/gim, '')
            .replace(/^POLICY[ &]REGULATION$/gim, '')
            // Collapse multiple blank lines
            .replace(/\n{3,}/g, '\n\n')
            .trim();
    }

    // ── 4. NEWS ITEM HTML ──────────────────────────────────────────────────────
    function escAttr(str) {
        return String(str).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function createNewsHTML(article) {
        const raw     = article.summary || '';
        const plain   = stripMarkdown(raw);
        const clipped = plain.length > 280
            ? plain.slice(0, 280).replace(/\s\S+$/, '') + '…'
            : plain;
        return `
            <div class="news-item" data-full="${escAttr(plain)}" data-clipped="${escAttr(clipped)}">
                <h4 onclick="window.open('${escAttr(article.url)}', '_blank')" style="cursor:pointer">${article.title}</h4>
                <p class="summary-text clipped">${clipped}</p>
                <a href="${escAttr(article.url)}" target="_blank" class="source-link">${catLabel(article.category || 'General')}</a>
                <button class="expand-btn" onclick="toggleExpand(this)">Read more</button>
            </div>
        `;
    }

    // ── 5. FEATURED ARTICLE HTML ───────────────────────────────────────────────
    function createFeaturedHTML(article) {
        const raw   = article.summary || '';
        const plain = stripMarkdown(raw);
        const clipped = plain.length > 400
            ? plain.slice(0, 400).replace(/\s\S+$/, '') + '…'
            : plain;
        return `
            <div class="news-item" data-full="${escAttr(plain)}" data-clipped="${escAttr(clipped)}">
                <h4 onclick="window.open('${escAttr(article.url)}', '_blank')" style="cursor:pointer">${article.title}</h4>
                <p class="summary-text clipped">${clipped}</p>
                <a href="${escAttr(article.url)}" target="_blank" class="source-link">Source</a>
                <button class="expand-btn" onclick="toggleExpand(this)">Read more</button>
            </div>
        `;
    }

    // ── 5b. EXPAND / COLLAPSE ─────────────────────────────────────────────────
    // Stored as plain text (already HTML-attribute-safe via escAttr) — never encode/decode.
    window.toggleExpand = function(btn) {
        const item = btn.closest('.news-item');
        const p    = item.querySelector('.summary-text');
        if (p.classList.contains('clipped')) {
            p.textContent = item.dataset.full || '';
            p.classList.remove('clipped');
            btn.textContent = 'Show less';
        } else {
            p.textContent = item.dataset.clipped || '';
            p.classList.add('clipped');
            btn.textContent = 'Read more';
        }
    };

    // ── 6. CATEGORY MATCHERS ───────────────────────────────────────────────────
    // Canonical category names saved by generate_news.py via LLM self-categorization.
    const FINANCE_CATS = new Set(['finance', 'funding & market dynamics']);
    const GLOBAL_CATS  = new Set(['global news', 'general', 'world']);
    const TECH_CATS    = new Set(['artificial intelligence', 'research & academic breakthroughs',
                                   'product launches & company news', 'technology',
                                   'open source & community', 'policy & regulation']);

    // Short labels shown as the source-link text on each news card.
    const CAT_LABELS = {
        'artificial intelligence':              'AI',
        'research & academic breakthroughs':    'Research',
        'product launches & company news':      'Launches',
        'technology':                          'Tech',
        'open source & community':             'OSS',
        'funding & market dynamics':           'Markets',
        'policy & regulation':                 'Policy',
        'finance':                             'Finance',
        'global news':                         'Global',
    };

    function catLabel(cat) {
        return CAT_LABELS[cat.toLowerCase()] || cat.split(' ')[0];
    }

    function isTech(article) {
        const cat = (article.category || '').toLowerCase();
        if (TECH_CATS.has(cat)) return true;
        const t = (article.title + ' ' + article.summary).toLowerCase();
        return /\b(ai|artificial intelligen|model|llm|gpt|gemini|claude|openai|anthropic|deepmind|google ai|microsoft ai|meta ai|neural network|machine learning|deep learning|research paper|arxiv|benchmark|open.?source|github|framework|library|algorithm|robot|agentic|rag|token| gpu |cuda|inference|train|data center|infrastructure)\b/.test(t);
    }

    function isFinance(article) {
        const cat = (article.category || '').toLowerCase();
        if (FINANCE_CATS.has(cat)) return true;
        const t = (article.title + ' ' + article.summary).toLowerCase();
        // Trailing (?: |$) makes space optional — handles end-of-sentence with no trailing space
        return /\b(stocks?|equities?|bonds?|interest rates?|federal reserve|fed(?: |$)|central bank|inflation|deflation|earnings report|quarterly results|ipo(?: |$)|stock price|share price|market cap|wall street|dow jones|s&p(?: |$)|nasdaq|nyse(?: |$)|trading session|traded (?:up|down)(?: |$)|fell(?: |$)|rose(?: |$)|slumped(?: |$)|surged(?: |$)|market rout|market crash)\b/.test(t);
    }

    function isGlobal(article) {
        const cat = (article.category || '').toLowerCase();
        if (GLOBAL_CATS.has(cat)) return true;
        const t = (article.title + ' ' + article.summary).toLowerCase();
        return /\b(geopolitic|war\b|conflict|diplomat|embargo|sanction|climate|energy policy| treaty(?:\b| )|summit|g20|nato\b|un(?:\b| )|security council|human rights?\b|refugee|terrorism|nuclear program|iran\b|china\b|russia\b|ukraine\b|middle east|africa\b|asia pacific|europe\b|americas\b|world\b|international|global\b)\b/.test(t);
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

        // Featured = first article (right column)
        const featured = articles[0];
        if (featuredContainer) featuredContainer.innerHTML = createFeaturedHTML(featured);

        const shown = new Set([featured.title, featured.url]);

        // Finance — left column
        const finance = articles
            .filter(a => !shown.has(a.title) && !shown.has(a.url) && isFinance(a))
            .slice(0, 6);
        finance.forEach(a => shown.add(a.title));
        if (financeContainer) financeContainer.innerHTML = finance.length
            ? finance.map(createNewsHTML).join('')
            : '<p class="empty-note">No finance today.</p>';

        // Tech — center column
        const tech = articles
            .filter(a => !shown.has(a.title) && !shown.has(a.url) && isTech(a))
            .slice(0, 6);
        tech.forEach(a => shown.add(a.title));
        if (techContainer) techContainer.innerHTML = tech.length
            ? tech.map(createNewsHTML).join('')
            : '<p class="empty-note">No tech today.</p>';

        // General / Global — right column (catch-all)
        const general = articles
            .filter(a => !shown.has(a.title) && !shown.has(a.url))
            .slice(0, 6);
        if (generalContainer) generalContainer.innerHTML = general.length
            ? general.map(createNewsHTML).join('')
            : '<p class="empty-note">No global news today.</p>';
    }

    fetchNews();
});

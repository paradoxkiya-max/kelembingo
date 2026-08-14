// Page Loader System for Kelem Bingo
// Dynamically loads HTML pages and components into the shell game.html

const PAGE_ASSET_VERSION = 'rtw-1';

const PageLoader = {
    cache: {},
    componentsLoaded: false,
    
    // Map screen names to page file names
    pageMap: {
        'home': 'home',
        'game': 'game-board',
        'history': 'history',
        'wallet': 'wallet',
        'profile': 'profile'
    },
    
    // Load a page HTML file into a screen div
    async loadPage(screenName) {
        const targetId = `screen-${screenName}`;
        const target = document.getElementById(targetId);
        if (!target) return;
        
        const pageName = this.pageMap[screenName] || screenName;
        
        // Check cache first
        if (this.cache[`page:${pageName}`]) {
            target.innerHTML = this.cache[`page:${pageName}`];
            target.setAttribute('data-page-loaded', screenName);
            this.dispatchLoadEvent(screenName);
            return;
        }
        
        try {
            const response = await fetch(`pages/${pageName}.html?v=${PAGE_ASSET_VERSION}`);
            if (!response.ok) throw new Error(`Failed to load ${pageName}`);
            const html = await response.text();
            this.cache[`page:${pageName}`] = html;
            target.innerHTML = html;
            target.setAttribute('data-page-loaded', screenName);
            this.dispatchLoadEvent(screenName);
        } catch (err) {
            console.error(`PageLoader: Error loading ${pageName}:`, err);
            target.innerHTML = `<div class="p-4 text-center text-white/50">Failed to load page</div>`;
        }
    },
    
    // Load a component HTML file into a target element
    async loadComponent(targetId, componentPath) {
        const target = document.getElementById(targetId);
        if (!target) return;
        
        const cacheKey = `component:${componentPath}`;
        if (this.cache[cacheKey]) {
            target.innerHTML = this.cache[cacheKey];
            return;
        }
        
        try {
            const response = await fetch(`components/${componentPath}?v=${PAGE_ASSET_VERSION}`);
            if (!response.ok) throw new Error(`Failed to load ${componentPath}`);
            const html = await response.text();
            this.cache[cacheKey] = html;
            target.innerHTML = html;
        } catch (err) {
            console.error(`PageLoader: Error loading component ${componentPath}:`, err);
        }
    },
    
    // Load all shared components (header, nav, modals)
    async initComponents() {
        if (this.componentsLoaded) return;
        
        const componentMap = {
            'telegram-header': 'header.html',
            'bottom-nav': 'bottom-nav.html',
            'win-modal': 'win-modal.html',
            'rules-modal': 'rules-modal.html',
            'transfer-modal': 'transfer-modal.html',
            'depositModal': 'deposit-modal.html',
            'withdrawModal': 'withdraw-modal.html',
            'registerModal': 'register-modal.html',
            'card-select-screen': 'card-select.html',
            'loading-overlay': 'loading-overlay.html',
            'toast': 'toast.html'
        };
        
        const promises = Object.entries(componentMap).map(([id, path]) => 
            this.loadComponent(id, path)
        );
        
        await Promise.all(promises);
        this.componentsLoaded = true;
    },
    
    // Dispatch custom event after page load
    dispatchLoadEvent(screenName) {
        document.dispatchEvent(new CustomEvent('pageLoaded', { 
            detail: { screen: screenName } 
        }));
    },
    
    // Load a specific page on demand (uses data-page-loaded attribute)
    async loadOnDemand(screenName) {
        const targetId = `screen-${screenName}`;
        const target = document.getElementById(targetId);
        if (!target) return;
        
        // Only load if not already loaded
        if (!target.getAttribute('data-page-loaded')) {
            await this.loadPage(screenName);
        }
    },
    
    // Pre-load all pages (optional)
    async preloadAll() {
        const pages = ['home', 'game', 'history', 'wallet', 'profile'];
        await Promise.all(pages.map(p => this.loadPage(p)));
    }
};

// Make globally available
window.PageLoader = PageLoader;

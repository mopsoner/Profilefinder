// Shared site navigation. Keep the menu and active-page state in one place.
(() => {
  const path = location.pathname;
  const current = document.body.dataset.page || (path === '/' ? 'home' : path.startsWith('/video-ads') || /^\/leads\/\d+\/video-ads/.test(path) ? 'video' : path.startsWith('/search') ? 'search' : path.startsWith('/sites') || /\/leads\/\d+\/web/.test(path) ? 'sites' : path.startsWith('/leads') ? 'leads' : path.startsWith('/jobs') ? 'jobs' : path.startsWith('/ops') ? 'ops' : 'ads');
  const leadId=path.match(/^\/leads\/(\d+)/)?.[1]||new URLSearchParams(location.search).get('lead_id');
  const contextLead=/^\d+$/.test(leadId||'')?leadId:null;
  const pages = [
    { id: 'home', href: '/', icon: '⌂', label: 'Dashboard' },
    { id: 'search', href: '/search', icon: '⌕', label: 'Recherche' },
    { id: 'leads', href: '/leads', icon: '◇', label: 'Prospects' },
    { id: 'sites', href: '/sites', icon: '▧', label: 'Sites IA' },
    { id: 'ads', href: contextLead?'/ads?lead_id='+contextLead:'/ads', icon: '◉', label: 'Ads', badge: 'STUDIO' },
    { id: 'video', href: contextLead?'/leads/'+contextLead+'/video-ads':'/video-ads', icon: '▸', label: 'Video Ads', badge: 'HD' },
    { id: 'jobs', href: '/jobs', icon: '≋', label: 'Jobs' },
    { id: 'ops', href: '/ops', icon: '⚙', label: 'Opérations' },
  ];
  const sidebar = document.querySelector('[data-site-sidebar]');
  if (sidebar) sidebar.innerHTML = `
    <a class="brand" href="/" aria-label="ProfileFinder — accueil"><span class="brand-icon" aria-hidden="true">◈</span> Profile<span>finder</span></a>
    <div class="workspace"><span class="avatar" aria-hidden="true">P</span><div>Mon espace<small>Workspace personnel</small></div></div>
    <div class="nav-label">WORKSPACE</div>
    <nav aria-label="Navigation principale">${pages.map(page => `<a href="${page.href}" ${current === page.id ? 'class="active" aria-current="page"' : ''}><span aria-hidden="true">${page.icon}</span>${page.label}${page.badge ? `<em>${page.badge}</em>` : ''}</a>`).join('')}</nav>
    <div class="side-note"><span aria-hidden="true">✦</span><h4>Donnez vie à vos idées.</h4><p>Une entreprise. Des idées.<br>Un nouvel horizon.</p><div class="mini-bars" aria-hidden="true">${Array.from({length:30},(_,i)=>`<i style="height:${5+Math.abs(Math.sin(i*1.7)*Math.cos(i*.31))*20}px"></i>`).join('')}</div></div>
    <div class="side-bottom"><span class="avatar small" aria-hidden="true">PF</span><div>ProfileFinder<small>Votre espace de création</small></div></div>`;
  const header = document.querySelector('[data-site-header]');
  if (header) header.innerHTML = `<div class="breadcrumb"><a href="/">Workspace</a><span aria-hidden="true">/</span><strong>${current === 'ads' ? 'Ads Studio' : (pages.find(page => page.id === current)?.label || 'Workspace')}</strong></div><span class="status"><i aria-hidden="true"></i> Espace créatif</span>`;
  const footer = document.querySelector('[data-site-footer]');
  if (footer) footer.innerHTML = `<span>PROFILEFINDER <span class="footer-dot">/</span> ${current === 'ads' ? 'ADS STUDIO' : 'WORKSPACE'}</span><span>Vos idées, une nouvelle dimension. ✦</span>`;
})();

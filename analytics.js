window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('js', new Date());
gtag('config', 'G-KX3WW4Q3NG');
(function(){var s=document.createElement('script');s.async=true;
  s.src='https://www.googletagmanager.com/gtag/js?id=G-KX3WW4Q3NG';document.head.appendChild(s);})();
// Custom action tracking — one delegated listener for the whole site.
(function(){
  function ev(name, params){ try{ gtag('event', name, params||{}); }catch(e){} }
  function slug(h){ return (h.split('#')[0].split('?')[0].split('/').pop()||'').replace(/\.[^.]+$/,''); }
  document.addEventListener('click', function(e){
    var a = e.target.closest && e.target.closest('a'); if(!a) return;
    if(a.hasAttribute('download')){
      var href = a.getAttribute('href') || '';
      if(/\.svg(?:[?#]|$)/i.test(href)) ev('download_svg', {mark: slug(href), file: href});
      else if(/\.png(?:[?#]|$)/i.test(href)) ev('download_png', {mark: slug(href), file: href});
      return;
    }
    if(a.classList.contains('pdflink')){ ev('download_pdf', {file: a.getAttribute('href') || ''}); return; }
    if(a.classList.contains('font-get')){ ev('get_font', {font: a.getAttribute('data-font') || '', link_url: a.href, link_domain: a.hostname}); return; }
    if(a.classList.contains('contrib-link')){ ev('contributor_link', {contributor: a.getAttribute('data-contrib') || '', link_url: a.href, link_domain: a.hostname}); return; }
  }, true);
})();

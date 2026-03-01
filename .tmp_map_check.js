const { chromium } = require('playwright');
const path = require('path');
(async()=>{
  const target = 'file:///' + path.resolve('output/combined/site/zemljevid.html').replace(/\\/g,'/');
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage({viewport:{width:1400,height:900}});
  const logs=[];
  page.on('console', m => logs.push('CONSOLE '+m.type()+': '+m.text()));
  page.on('pageerror', e => logs.push('PAGEERROR: '+e.toString()));
  await page.goto(target, {waitUntil:'load'});
  await page.waitForTimeout(2500);
  const stats = await page.evaluate(() => {
    const mapPane = document.querySelector('.leaflet-overlay-pane');
    const markerPane = document.querySelector('.leaflet-marker-pane');
    return {
      leafletLoaded: typeof window.L !== 'undefined',
      mapDiv: !!document.querySelector('.folium-map'),
      svgCount: document.querySelectorAll('svg').length,
      pathCount: document.querySelectorAll('path').length,
      markerIcons: document.querySelectorAll('.leaflet-marker-icon').length,
      hasTiles: document.querySelectorAll('.leaflet-tile').length,
      mapPaneChildren: mapPane ? mapPane.children.length : -1,
      markerPaneChildren: markerPane ? markerPane.children.length : -1,
      bodyText: (document.body && document.body.innerText || '').slice(0,200)
    };
  });
  await page.screenshot({path:'output/combined/site/_debug_map.png', fullPage:true});
  console.log('STATS', JSON.stringify(stats));
  if (logs.length) {
    console.log('LOGS_START');
    logs.forEach(l=>console.log(l));
    console.log('LOGS_END');
  }
  await browser.close();
})();

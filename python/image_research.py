"""Numbered previews and exact selected images from already loaded page resources."""
import base64
import io
import uuid
from pathlib import Path

from PIL import Image,ImageDraw,ImageFont,ImageOps
from .huoyan_browser import dom_script,atomic_json,load_json,stamp,product_identity

OPERATIONS={'product_image_overview','read_product_image'}


def inventory(page):
    rows=page.evaluate(dom_script('imageResearchDom.js'));groups={s:[] for s in ('sku','gallery','description')}
    for row in rows:
        old=next((r for r in groups[row['source']] if r['src']==row['src']),None)
        if old:
            if row.get('skuOption') and row['skuOption'] not in old['skuOptions']:old['skuOptions'].append(row['skuOption'])
            # Main gallery images are usually larger than their duplicate thumbnails.
            if row['renderedWidth']*row['renderedHeight']>old['renderedWidth']*old['renderedHeight']:
                options=old['skuOptions'];old.update(row);old['skuOptions']=options
        else:groups[row['source']].append({**row,'skuOptions':[row['skuOption']] if row.get('skuOption') else []})
    # Interleave sources so an initial sheet is not filled by only SKU options.
    return [row for i in range(max((len(v) for v in groups.values()),default=0)) for rows in groups.values() for row in rows[i:i+1]]


def context(c,page):
    c.guard(page);c.focus.require(page)
    return {'tabId':c.tab_id(page),'productId':product_identity(page.url)['productId'],
            'selectedSku':page.evaluate(dom_script('productSnapshotDom.js')).get('selectedSku',[])}


def require_context(c,page,expected):
    if context(c,page)!=expected:raise RuntimeError('PRODUCT_CHANGED: image overview product, tab or selected SKU changed. Create a new overview.')


def png(image):
    image=ImageOps.exif_transpose(image).convert('RGB');out=io.BytesIO();image.save(out,format='PNG');return out.getvalue(),image


def capture(c,page,row,session,frame,expected,allow_screenshot=False):
    require_context(c,page,expected)
    if not row['ready']:raise ValueError('IMAGE_NOT_READY: source has not successfully loaded.')
    loc=page.locator(row['elementPath'])
    actual=loc.evaluate('e=>({src:e.currentSrc||e.src,ready:e.complete&&e.naturalWidth>0})')
    if actual['src']!=row['src'] or not actual['ready']:raise RuntimeError('STALE_IMAGE: image source changed or failed to load.')
    try:
        resource=session.send('Page.getResourceContent',{'frameId':frame,'url':row['src']})
    except Exception:
        resource=None
    if resource:
        raw=base64.b64decode(resource['content']) if resource.get('base64Encoded') else resource['content'].encode()
        if len(raw)>25*1024*1024:raise ValueError('IMAGE_TOO_LARGE: loaded resource exceeds 25 MiB.')
        try:
            image=Image.open(io.BytesIO(raw))
            if image.width*image.height>40_000_000:raise ValueError('IMAGE_TOO_LARGE: more than 40 million pixels.')
            image.load();data,image=png(image)
            require_context(c,page,expected)
            return data,image,'loaded-resource'
        except (OSError,SyntaxError):pass
    if not allow_screenshot:
        raise ValueError('IMAGE_RESOURCE_UNAVAILABLE: loaded image resource cannot be read; visible screenshot fallback is disabled. No page movement was performed.')
    c.focus.prepare_action(page)
    # Cached resource may be unavailable (for example SVG). Fall back to the
    # existing rendered node, restoring both nested and document scroll state.
    positions=loc.evaluate('''e=>{const a=[];for(let n=e.parentElement;n;n=n.parentElement){if(n.scrollHeight>n.clientHeight||n.scrollWidth>n.clientWidth){const p=[];for(let x=n;x&&x!==document.documentElement;x=x.parentElement)p.unshift(x.tagName.toLowerCase()+':nth-child('+([...x.parentElement.children].indexOf(x)+1)+')');a.push({path:n===document.documentElement?'html':'html > '+p.join(' > '),top:n.scrollTop,left:n.scrollLeft});}}return {nodes:a,x:scrollX,y:scrollY}}''')
    try:
        loc.scroll_into_view_if_needed(timeout=2000);require_context(c,page,expected)
        if loc.evaluate('e=>e.currentSrc||e.src')!=row['src']:raise RuntimeError('STALE_IMAGE: source changed while scrolling.')
        if not loc.evaluate('''e=>{const r=e.getBoundingClientRect(),h=document.elementFromPoint(Math.max(0,Math.min(innerWidth-1,r.left+r.width/2)),Math.max(0,Math.min(innerHeight-1,r.top+r.height/2)));return h===e||e.contains(h)}'''):raise ValueError('IMAGE_BLOCKED: rendered image is covered; no misleading screenshot returned.')
        raw=loc.screenshot(type='png',timeout=3000);data,image=png(Image.open(io.BytesIO(raw)))
    finally:
        c.focus.require(page)
        page.evaluate('''s=>{for(const n of s.nodes){const e=document.querySelector(n.path);if(e)e.scrollTo(n.left,n.top);}scrollTo(s.x,s.y)}''',positions)
    require_context(c,page,expected)
    return data,image,'rendered-screenshot'


def public(row):return {k:v for k,v in row.items() if k not in ('elementPath','file')}


def run(c,page,operation):
    from .shopping_research import read,publish
    c.focus.allow(page,'section');before=read(c,page);expected=context(c,page)
    file=c.out/'image-research.json';db=load_json(file,{})
    if db.get('endpoint')!=c.endpoint:db={'endpoint':c.endpoint,'overviews':{}}
    if operation=='read_product_image':
        overview=db['overviews'].get(c.args.get('overviewId'))
        if not overview:raise RuntimeError('STALE_IMAGE: unknown or expired overviewId.')
        if overview['context']!=expected:raise RuntimeError('PRODUCT_CHANGED: overview belongs to another tab, product or SKU.')
        index=c.args.get('index')
        if not isinstance(index,int) or isinstance(index,bool):raise ValueError('Choose an integer image index shown in the overview.')
        row=next((r for r in overview['images'] if r['index']==index),None)
        if not row:raise ValueError('Choose an index actually returned in this overview page.')
        live=inventory(page)
        if not any(r['source']==row['source'] and r['src']==row['src'] and r['skuOptions']==row['skuOptions'] and r['ready'] for r in live):raise RuntimeError('STALE_IMAGE: source or SKU option changed; create a new overview.')
        if not row.get('file'):raise RuntimeError('IMAGE_UNAVAILABLE: overview could not capture this image; no fabricated image.')
        require_context(c,page,expected);image_path=Path(row['file']).resolve()
        root=(c.out/'images'/'overviews').resolve()
        if not image_path.is_relative_to(root):raise RuntimeError('Invalid stored image path.')
        return {'overviewId':c.args['overviewId'],'image':public(row),'observedAt':overview['observedAt'],
                'imageBase64':base64.b64encode(image_path.read_bytes()).decode('ascii'),
                'note':'Exact individual image saved during overview; source is still present. No new request or SKU click.',
                'state':publish(c,read(c,page))}
    offset=c.args.get('offset',0);limit=c.args.get('maxImages',24);sources=c.args.get('imageSources',['sku','gallery','description'])
    allow_screenshot=c.args.get('allowScreenshot',False)
    if not isinstance(allow_screenshot,bool):raise ValueError('allowScreenshot must be boolean.')
    if not isinstance(offset,int) or isinstance(offset,bool) or offset<0:raise ValueError('offset must be a nonnegative integer.')
    if not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=48:raise ValueError('maxImages must be 1..48.')
    if not isinstance(sources,list) or not sources or set(sources)-{'sku','gallery','description'}:raise ValueError('Choose actual image sources: sku, gallery, description.')
    rows=[r for r in inventory(page) if r['source'] in sources]
    if offset>=len(rows):raise ValueError('No loaded images at this offset; read current detail state or use an earlier offset.')
    overview_id=uuid.uuid4().hex;folder=c.out/'images'/'overviews'/overview_id;folder.mkdir(parents=True,exist_ok=True)
    session=page.context.new_cdp_session(page);captured=[];tiles={}
    try:
        session.send('Page.enable');frame=session.send('Page.getFrameTree')['frameTree']['frame']['id']
        for i,row in enumerate(rows[offset:offset+limit],offset+1):
            require_context(c,page,expected);row={**row,'index':i}
            try:
                data,image,method=capture(c,page,row,session,frame,expected,allow_screenshot)
                image_path=folder/f'{i}.png';image_path.write_bytes(data);tiles[i]=image
                row.update(file=str(image_path),captureMethod=method,capturedWidth=image.width,capturedHeight=image.height,
                    clarity='small-image' if min(image.size)<300 else 'loaded-image' if method=='loaded-resource' else 'rendered-image')
            except ValueError as e:row.update(error=str(e))
            captured.append(row)
    finally:session.detach()
    if not tiles:raise RuntimeError('IMAGE_UNAVAILABLE: no readable image resources to preview; no image fabricated. Visible screenshots require explicit allowScreenshot=true.')
    cols=min(4,len(captured));w,h=360,360;canvas=Image.new('RGB',(cols*w,70+((len(captured)+cols-1)//cols)*h),'white');draw=ImageDraw.Draw(canvas)
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',17)
    draw.text((12,12),f"商品 {expected['productId']} | 编号概览 {offset+1}–{offset+len(captured)}/{len(rows)}",font=font,fill='black')
    draw.text((12,38),'按编号取单图；缩略图不是完整SKU组合证明；未切换规格。',font=font,fill='black')
    labels={'sku':'SKU缩略图','gallery':'主图/图库','description':'图文详情'}
    for n,row in enumerate(captured):
        x,y=(n%cols)*w,70+(n//cols)*h
        if row['index'] in tiles:
            tile=ImageOps.contain(tiles[row['index']],(340,270));canvas.paste(tile,(x+(w-tile.width)//2,y+(270-tile.height)//2))
        else:draw.text((x+12,y+100),'未能读取图片',font=font,fill='red')
        title=f"#{row['index']} {labels[row['source']]}";draw.text((x+10,y+275),title,font=font,fill='black')
        text=' / '.join(row['skuOptions']) or row['label']
        for j in range(2):draw.text((x+10,y+301+j*23),text[j*18:(j+1)*18],font=font,fill='black')
    overview_file=folder/'overview.png';canvas.save(overview_file);observed=stamp()
    require_context(c,page,expected)
    # Keep a bounded registry; older page results expire instead of accumulating forever.
    db['overviews'][overview_id]={'context':expected,'observedAt':observed,'images':captured}
    db['overviews']=dict(list(db['overviews'].items())[-10:]);atomic_json(file,db)
    return {'overviewId':overview_id,'images':[public(r) for r in captured],'imageCount':len(tiles),'totalLoadedImages':len(rows),
            'offset':offset,'nextOffset':offset+len(captured) if offset+len(captured)<len(rows) else None,'hasMore':offset+len(captured)<len(rows),
            'sourceCounts':{s:sum(r['source']==s for r in rows) for s in sources},'selectedSku':expected['selectedSku'],'inventoryLimit':160,
            'allowScreenshot':allow_screenshot,'screenshotCount':sum(r.get('captureMethod')=='rendered-screenshot' for r in captured),'unavailableCount':sum('error' in r for r in captured),
            'observedAt':observed,'file':str(overview_file),'imageBase64':base64.b64encode(overview_file.read_bytes()).decode('ascii'),
            'note':'Default uses loaded image resources only: no scrolling, screenshots, page rewrite, navigation or explicit download. Unreadable images are labelled. Only explicit allowScreenshot=true enables visible screenshot fallback and normal site lazy rendering. Read one returned index using read_product_image.',
            'state':publish(c,read(c,page))}

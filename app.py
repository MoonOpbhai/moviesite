import re, json, os, logging, traceback
from urllib.parse import urljoin, quote
from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('movieengine')

app = Flask(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.5',
}

BASE_BF = 'new.bollyflix.gd'
BASE_AF = 'https://animeflix.dad'
TMDB_KEY = os.environ.get('TMDB_API_KEY', '')
TMDB_BASE = 'https://api.themoviedb.org/3'
TMDB_IMG  = 'https://image.tmdb.org/t/p'

session = requests.Session()
session.headers.update(HEADERS)


def get(url, timeout=15):
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def soup(url):
    return BeautifulSoup(get(url), 'html.parser')


def detect_quality_from_text(text):
    if not text: return 'N/A'
    t = str(text).lower()
    if '2160' in t or '4k' in t: return '2160p 4K'
    if '1080' in t: return '1080p'
    if '720' in t: return '720p'
    if '480' in t: return '480p'
    if '360' in t: return '360p'
    return 'N/A'


def detect_quality_label(tag):
    quality_sources = []
    quality_sources.append(tag.get_text(strip=True))
    parent = tag.parent
    for _ in range(5):
        if not parent: break
        quality_sources.append(parent.get_text(strip=True))
        parent = parent.parent
    sibling = tag.next_sibling
    for _ in range(3):
        if not sibling: break
        if hasattr(sibling, 'get_text'):
            quality_sources.append(sibling.get_text(strip=True))
        sibling = sibling.next_sibling
    for text in quality_sources:
        q = detect_quality_from_text(text)
        if q != 'N/A':
            return q
    return 'N/A'


def detect_size_from_parent(tag):
    parent = tag.parent
    for _ in range(6):
        if not parent: break
        text = parent.get_text(strip=True)
        m = re.search(r'(\d+\.?\d*\s*[MGT]B)', text, re.I)
        if m:
            return m.group(1).strip()
        sib = parent.next_sibling
        for _ in range(3):
            if not sib: break
            if hasattr(sib, 'get_text'):
                sib_text = sib.get_text(strip=True)
                m2 = re.search(r'(\d+\.?\d*\s*[MGT]B)', sib_text, re.I)
                if m2: return m2.group(1).strip()
            sib = sib.next_sibling
        parent = parent.parent
    return 'N/A'


def quality_label(tag):
    return detect_quality_label(tag)


def size_label(tag):
    return detect_size_from_parent(tag)


def is_suggestion_link(a_tag, text):
    """
    Returns True if this link is a suggestion/category/label, NOT an actual download link.
    Filters out: How To Download, 300MB MOVIES, similar category boxes.
    """
    txt = (text or a_tag.get_text(strip=True)).lower()
    href = a_tag.get('href', '').lower()
    
    # Skip "how to download" type suggestions
    suggestion_patterns = [
        'how to download',
        'download links',      # The category label row
        '300mb movies',
        '500mb movies',
        '700mb movies',
        '900mb movies',
        '1gb movies',
        '1.5gb movies',
        '2gb movies',
        'short movies',
        'web series',
        'webseries',
        'watch online',
        'trailer',
        'teaser',
    ]
    
    for pattern in suggestion_patterns:
        if pattern in txt or pattern in href:
            return True
    
    # Pure number+MB/GB without a real filename = likely a suggestion label
    if re.match(r'^\d+[mgt]b$', txt.strip()):
        return True
    
    # Links pointing to same page or home = suggestion
    if not href or href.startswith('#') or href in ('/', '#', ''):
        return True
    
    return False


def is_actual_download_link(a_tag, text):
    """
    Returns True if this is a real download link.
    Checks: fastdlserver, drive.google, direct video hosts.
    """
    href = a_tag.get('href', '').lower()
    txt = (text or a_tag.get_text(strip=True)).lower()
    
    actual_domains = [
        'fastdlserver.site',
        'drive.google.com',
        'drive.google.co.in',
        'mega.nz',
        'mediafire.com',
        'zippyshare.com',
        'upload.ee',
        'openload.co',
        'streamtape.com',
        'mixdrop.co',
        'mp4upload.com',
        'bdupload.asia',
        'uploadbaz.com',
    ]
    
    for domain in actual_domains:
        if domain in href:
            return True
    
    # Links with 'download' in text that also have file extension in text
    if 'download' in txt or 'fastdl' in href:
        # Make sure it's not "Download Links" as a category
        if 'download links' in txt:
            return False
        # Check if the link text looks like a real file URL
        if any(ext in txt for ext in ['.mkv', '.mp4', '.avi', '.rar', '.zip']):
            return True
        if any(ext in href for ext in ['.mkv', '.mp4', '.avi', '.rar', '.zip']):
            return True
        # If href has actual file-like content
        if re.search(r'/file|/dl|/download|fileid=', href):
            return True
    
    return False


def tmdb_search(query):
    if not TMDB_KEY or not query: return None
    try:
        r = session.get(f'{TMDB_BASE}/search/movie', params={'api_key': TMDB_KEY, 'query': query}, timeout=10)
        if not r.ok: return None
        data = r.json()
        results = data.get('results', [])
        if results:
            m = results[0]
            return {
                'id': m['id'],
                'title': m.get('title', ''),
                'overview': m.get('overview', ''),
                'poster': f"{TMDB_IMG}/w500{m['poster_path']}" if m.get('poster_path') else '',
                'year': (m.get('release_date') or '').split('-')[0],
                'rating': m.get('vote_average', 0),
                'genres': [g['name'] for g in m.get('genres', [])],
            }
    except Exception: pass
    return None


def tmdb_details(mid):
    if not TMDB_KEY or not mid: return None
    try:
        r = session.get(f"{TMDB_BASE}/movie/{mid}", params={'api_key': TMDB_KEY, 'append_to_response': 'credits'}, timeout=10)
        if not r.ok: return None
        d = r.json()
        genres = [g['name'] for g in d.get('genres', [])]
        cast = [c['name'] for c in d.get('credits', {}).get('cast', [])[:5]]
        return {'overview': d.get('overview', ''), 'rating': d.get('vote_average', 0), 'genres': genres, 'cast': cast}
    except Exception: pass
    return None


@app.route('/search', methods=['GET'])
def search():
    q = request.args.get('q', '').strip()
    t  = request.args.get('type', 'movie')
    if not q: return jsonify([])
    results = []
    try:
        pg = soup(f"{BASE_BF}/?s={quote(q)}")
        for art in pg.select('article')[:30]:
            a = art.select_one('h2 a, h3 a')
            if not a: continue
            href, title = a['href'], a.get_text(strip=True)
            img = art.select_one('img')['src'] if art.select_one('img') else ''
            meta = art.select_one('.entry-meta')
            quality = detect_quality_from_text(f"{title} {meta.get_text(strip=True) if meta else ''}")
            results.append({'title': title, 'href': href, 'img': img, 'meta': meta.get_text(strip=True) if meta else '', 'source': 'BollyFlix', 'quality': quality})
    except Exception as e:
        log.warning(f'BollyFlix search error: {e}')
    try:
        if t == 'anime':
            pg = soup(f"{BASE_AF}/?s={quote(q)}")
            for art in pg.select('article')[:30]:
                a = art.select_one('h2 a, h3 a')
                if not a or 'animeflix.dad' not in a.get('href', ''): continue
                href, title = a['href'], a.get_text(strip=True)
                img = art.select_one('img')['src'] if art.select_one('img') else ''
                results.append({'title': title, 'href': href, 'img': img, 'meta': '', 'source': 'AnimeFlix'})
    except Exception as e:
        log.warning(f'AnimeFlix search error: {e}')
    return jsonify(results)


@app.route('/tmdb', methods=['GET'])
def tmdb():
    q = request.args.get('q', '').strip()
    if not q or not TMDB_KEY: return jsonify(None)
    return jsonify(tmdb_search(q))


@app.route('/tmdb-details', methods=['GET'])
def tmdb_details_api():
    mid = request.args.get('id')
    if not mid or not TMDB_KEY: return jsonify(None)
    return jsonify(tmdb_details(int(mid)))


@app.route('/details', methods=['GET'])
def details():
    src = request.args.get('source')
    url  = request.args.get('url')
    if not src or not url: return jsonify({'error': 'missing params'}), 400
    downloads = []
    try:
        pg = soup(url)
        page_title = pg.title.string if pg.title else ''
        movie_name = re.sub(r'\s*\[BollyFlix\].*', '', page_title).strip()
        
        if src == 'BollyFlix':
            title_el = pg.select_one('h1.entry-title')
            title = title_el.get_text(strip=True) if title_el else page_title or ''
            seen_urls = set()
            for a in pg.find_all('a', href=True):
                href = a['href']
                if href in seen_urls: continue
                
                link_text = a.get_text(strip=True)
                
                # ===== FILTER OUT SUGGESTIONS =====
                txt_lower = link_text.lower()
                # Skip empty links
                if not txt_lower or not href or href == '#':
                    continue
                # Skip suggestion links
                if is_suggestion_link(a, link_text):
                    continue
                # Must be an actual download link
                if not is_actual_download_link(a, link_text):
                    continue
                # ===================================
                
                q, s = 'N/A', 'N/A'
                label_el = None
                nxt = a.next_sibling
                for _ in range(5):
                    if not nxt: break
                    if hasattr(nxt, 'get_text'):
                        txt = nxt.get_text(strip=True)
                        if txt and ('p' in txt or 'K' in txt or 'GB' in txt or 'MB' in txt):
                            label_el = txt
                            break
                    nxt = nxt.next_sibling
                
                if label_el:
                    parts = re.split(r'\s*[·|–-]\s*', label_el)
                    q = parts[0].strip()
                    s = parts[1].strip() if len(parts) > 1 else 'N/A'
                
                if q == 'N/A':
                    parent = a.parent
                    for _ in range(6):
                        if not parent: break
                        full_text = parent.get_text(strip=True)
                        q = detect_quality_from_text(full_text)
                        if q != 'N/A': break
                        parent = parent.parent
                
                filename = f"{movie_name} - {link_text}" if movie_name else link_text
                if not filename.lower().endswith(('.mkv', '.mp4', '.avi', '.zip', '.rar')):
                    filename += ' [BollyFlix].mkv'
                
                downloads.append({
                    'name': filename,
                    'size': s,
                    'quality': q,
                    'url': href
                })
                seen_urls.add(href)
                
        elif src == 'AnimeFlix':
            title_el = pg.select_one('h1.entry-title')
            title = title_el.get_text(strip=True) if title_el else page_title or ''
            seen_urls = set()
            for a in pg.find_all('a', href=True):
                href = a['href']
                txt  = a.get_text(strip=True)
                if ('episodes.animeflix.dad' in href and 'getlink' in href):
                    if href in seen_urls: continue
                    seen_urls.add(href)
                    ep = re.search(r'Episode\s*(\d+)', txt, re.I)
                    q = detect_quality_label(a)
                    downloads.append({'name': txt or 'Unknown', 'episode': int(ep.group(1)) if ep else 0, 'quality': q, 'url': href, 'size': size_label(a)})
    except Exception as e:
        log.error(f'Details error [{src}]: {e}')
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    return jsonify({'title': page_title or movie_name, 'downloads': downloads})


@app.route('/debug')
def debug():
    import sys, platform
    return jsonify({
        'python': sys.version,
        'platform': platform.platform(),
        'tmdb_key_set': bool(TMDB_KEY),
        'tmdb_key_prefix': TMDB_KEY[:6] + '...' if TMDB_KEY else 'none',
    })


@app.route('/')
def home():
    return render_template('index.html')


@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def internal_error(e):
    tb = traceback.format_exc()
    log.error(f'500 error: {tb}')
    return jsonify({'error': 'Internal Server Error', 'traceback': tb.split('\n')[-3:]}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    log.info(f'Starting on port {port}')
    app.run(host='0.0.0.0', port=port)

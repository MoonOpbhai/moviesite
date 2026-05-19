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


def detect_quality(text):
    if not text: return 'N/A'
    t = text.lower()
    if '2160' in t or '4k' in t: return '2160p 4K'
    if '1080' in t: return '1080p'
    if '720' in t: return '720p'
    if '480' in t: return '480p'
    if '360' in t: return '360p'
    return 'N/A'


def detect_size(text):
    if not text: return 'N/A'
    m = re.search(r'(\d+\.?\d*\s*[MgtbGBMB]+)', text, re.I)
    return m.group(1).strip() if m else 'N/A'


def find_row_container(a):
    """Find the row/container element that groups the link with its quality/size label"""
    # Walk up to find a row-like element (div, li, tr, p with multiple children)
    parent = a.parent
    for _ in range(8):
        if not parent: break
        # Check if this parent has siblings that look like quality labels
        if parent.name in ('div', 'li', 'tr', 'p', 'span'):
            return parent
        parent = parent.parent
    return a.parent  # fallback


def get_quality_size(a):
    """Find quality + size by searching the row container and nearby elements"""
    q, s = 'N/A', 'N/A'
    
    # Method 1: Check next sibling elements
    nxt = a.next_sibling
    for _ in range(5):
        if not nxt: break
        if hasattr(nxt, 'get_text'):
            txt = nxt.get_text(strip=True)
            if txt and ('p' in txt or 'GB' in txt or 'MB' in txt):
                parts = re.split(r'\s*[·|–-]\s*', txt)
                q_candidate = parts[0].strip()
                s_candidate = parts[1].strip() if len(parts) > 1 else ''
                if detect_quality(q_candidate) != 'N/A':
                    q = q_candidate
                    s = detect_size(s_candidate) if detect_size(s_candidate) != 'N/A' else s_candidate
                    return q, s
        nxt = nxt.next_sibling
    
    # Method 2: Search in parent container + next siblings of parent
    container = find_row_container(a)
    if container:
        # Check all text in this container for quality/size patterns
        container_text = container.get_text(strip=True)
        q = detect_quality(container_text)
        s = detect_size(container_text)
        
        # Method 3: Check next sibling of the container
        if q == 'N/A':
            container_next = container.next_sibling
            for _ in range(5):
                if not container_next: break
                if hasattr(container_next, 'get_text'):
                    txt = container_next.get_text(strip=True)
                    if 'p' in txt or 'GB' in txt or 'MB' in txt:
                        q = detect_quality(txt)
                        s = detect_size(txt)
                        if q != 'N/A' or s != 'N/A':
                            break
                container_next = container_next.next_sibling
        
        # Method 4: Check previous sibling (quality label might be before link)
        if q == 'N/A':
            container_prev = container.previous_sibling
            for _ in range(5):
                if not container_prev: break
                if hasattr(container_prev, 'get_text'):
                    txt = container_prev.get_text(strip=True)
                    if 'p' in txt or 'GB' in txt or 'MB' in txt:
                        q = detect_quality(txt)
                        s = detect_size(txt)
                        if q != 'N/A' or s != 'N/A':
                            break
                container_prev = container_prev.previous_sibling
    
    # Method 5: Walk up parents looking for quality/size
    if q == 'N/A':
        parent = a.parent
        for _ in range(6):
            if not parent: break
            full_text = parent.get_text(strip=True)
            q = detect_quality(full_text)
            if q != 'N/A':
                s = detect_size(full_text)
                break
            parent = parent.parent
    
    return q, s


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
        pg = soup(f"https://{BASE_BF}/?s={quote(q)}")
        for art in pg.select('article')[:30]:
            a = art.select_one('h2 a, h3 a')
            if not a: continue
            href, title = a['href'], a.get_text(strip=True)
            img = art.select_one('img')['src'] if art.select_one('img') else ''
            meta = art.select_one('.entry-meta')
            quality = detect_quality(f"{title} {meta.get_text(strip=True) if meta else ''}")
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
                txt = a.get_text(strip=True)
                txt_lower = txt.lower()
                href_lower = href.lower()
                
                # Skip only obvious non-download links
                if (not href or href in ('#', '/') or
                    'how to download' in txt_lower or
                    'watch online' in txt_lower or
                    ('300mb' in href_lower and 'movies' in href_lower) or
                    ('500mb' in href_lower and 'movies' in href_lower) or
                    ('700mb' in href_lower and 'movies' in href_lower) or
                    ('900mb' in href_lower and 'movies' in href_lower) or
                    '1gb movies' in href_lower):
                    continue
                
                # Get quality + size
                q, s = get_quality_size(a)
                
                # Filename
                filename = f"{movie_name} - {txt}" if movie_name else txt
                if not filename.lower().endswith(('.mkv', '.mp4', '.avi', '.zip', '.rar', '.mk')):
                    filename += ' [BollyFlix].mkv'
                
                downloads.append({'name': filename, 'size': s, 'quality': q, 'url': href})
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
                    q, s = get_quality_size(a)
                    downloads.append({'name': txt or 'Unknown', 'episode': int(ep.group(1)) if ep else 0, 'quality': q, 'url': href, 'size': s})
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
    

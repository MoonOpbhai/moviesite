import re, json, os
from urllib.parse import urljoin, quote
from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.5',
}

BASE_BF = 'https://new.bollyflix.gd'
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

# Pehle:
return BeautifulSoup(get(url), 'lxml')

# Ab:
return BeautifulSoup(get(url), 'html.parser')


def quality_label(text):
    t = str(text).lower()
    if '2160p' in t or '4k' in t: return '2160p 4K'
    if '1080p' in t: return '1080p'
    if '720p' in t: return '720p'
    if '480p' in t: return '480p'
    return 'N/A'

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
                'genres': m.get('genre_ids', []),
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
        return {
            'overview': d.get('overview', ''),
            'rating': d.get('vote_average', 0),
            'genres': genres,
            'cast': cast,
            'url': f"https://www.themoviedb.org/movie/{mid}",
        }
    except Exception: pass
    return None

# ── BollyFlix ──
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
            results.append({
                'title': title, 'href': href,
                'img': img, 'meta': meta.get_text(strip=True) if meta else '',
                'source': 'BollyFlix'
            })
    except Exception: pass
    try:
        if t == 'anime':
            pg = soup(f"{BASE_AF}/?s={quote(q)}")
            for art in pg.select('article')[:30]:
                a = art.select_one('h2 a, h3 a')
                if not a or 'animeflix.dad' not in a['href']: continue
                href, title = a['href'], a.get_text(strip=True)
                img = art.select_one('img')['src'] if art.select_one('img') else ''
                results.append({
                    'title': title, 'href': href, 'img': img, 'meta': '',
                    'source': 'AnimeFlix'
                })
    except Exception: pass
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
        if src == 'BollyFlix':
            title = pg.select_one('h1.entry-title')
            title = title.get_text(strip=True) if title else ''
            for a in pg.find_all('a', href=True):
                href = a['href']
                txt  = a.get_text(strip=True)
                if 'fastdlserver.site' in href or 'drive.google' in href or 'download' in txt.lower():
                    dl = {
                        'name': txt, 'size': 'N/A',
                        'quality': quality_label(txt), 'url': href
                    }
                    parent = a.parent
                    if parent:
                        nxt = parent.next_sibling
                        if nxt:
                            dl['size'] = nxt.get_text(strip=True).strip('[]') if hasattr(nxt,'get_text') else str(nxt).strip('[]')
                    downloads.append(dl)
        elif src == 'AnimeFlix':
            title = pg.select_one('h1.entry-title')
            title = title.get_text(strip=True) if title else ''
            for a in pg.find_all('a', href=True):
                href = a['href']
                txt  = a.get_text(strip=True)
                if 'episodes.animeflix.dad' in href and 'getlink' in href:
                    ep = re.search(r'Episode\s*(\d+)', txt, re.I)
                    downloads.append({
                        'name': txt or 'Unknown',
                        'episode': int(ep.group(1)) if ep else 0,
                        'quality': quality_label(txt), 'url': href,
                        'size': 'N/A'
                    })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'title': title, 'downloads': downloads})

@app.route('/')
def home(): return render_template('index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

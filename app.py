import re, os
from urllib.parse import quote
from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.5',
    'Referer': 'https://www.google.com/',
}

# BollyFlix domains - tries each one until one works
BF_DOMAINS = [
    'https://new.bollyflix.gd',
    'https://bollyflix.show',
    'https://www.bollyflix.boats',
    'https://bollyflix.ind.in',
]

TMDB_KEY  = os.environ.get('TMDB_API_KEY', '')
TMDB_BASE = 'https://api.themoviedb.org/3'
TMDB_IMG  = 'https://image.tmdb.org/t/p'

session = requests.Session()
session.headers.update(HEADERS)


def get_working_domain():
    for domain in BF_DOMAINS:
        try:
            r = session.get(domain + '/', timeout=8, allow_redirects=True)
            if r.ok:
                return domain
        except Exception:
            continue
    return BF_DOMAINS[0]


def get(url, timeout=20):
    r = session.get(url, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.text


def soup(url):
    return BeautifulSoup(get(url), 'html.parser')


def quality_label(text):
    t = str(text).lower()
    if '2160p' in t or '4k' in t: return '2160p 4K'
    if '1080p' in t: return '1080p'
    if '720p'  in t: return '720p'
    if '480p'  in t: return '480p'
    return 'N/A'


def tmdb_search(query):
    if not TMDB_KEY or not query: return None
    try:
        r = session.get(
            f'{TMDB_BASE}/search/movie',
            params={'api_key': TMDB_KEY, 'query': query, 'language': 'en-US'},
            timeout=10
        )
        if not r.ok: return None
        results = r.json().get('results', [])
        if not results: return None
        m = results[0]
        return {
            'id':       m['id'],
            'title':    m.get('title', ''),
            'overview': m.get('overview', ''),
            'poster':   f"{TMDB_IMG}/w500{m['poster_path']}" if m.get('poster_path') else '',
            'year':     (m.get('release_date') or '').split('-')[0],
            'rating':   m.get('vote_average', 0),
            'genres':   [],
        }
    except Exception:
        pass
    return None


def tmdb_details(mid):
    if not TMDB_KEY or not mid: return None
    try:
        r = session.get(
            f'{TMDB_BASE}/movie/{mid}',
            params={'api_key': TMDB_KEY, 'append_to_response': 'credits'},
            timeout=10
        )
        if not r.ok: return None
        d = r.json()
        return {
            'overview': d.get('overview', ''),
            'rating':   d.get('vote_average', 0),
            'genres':   [g['name'] for g in d.get('genres', [])],
            'cast':     [c['name'] for c in d.get('credits', {}).get('cast', [])[:5]],
        }
    except Exception:
        pass
    return None


@app.route('/search')
def search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])

    results = []
    base = get_working_domain()

    try:
        pg = soup(f"{base}/?s={quote(q)}")
        for art in pg.select('article')[:30]:
            a = art.select_one('h2 a, h3 a, .entry-title a')
            if not a: continue
            href  = a.get('href', '')
            title = a.get_text(strip=True)
            if not href or not title: continue
            img_el = art.select_one('img')
            img = ''
            if img_el:
                img = img_el.get('data-src') or img_el.get('src') or ''
            meta_el = art.select_one('.entry-meta, .post-meta, time')
            meta = meta_el.get_text(strip=True) if meta_el else ''
            results.append({
                'title':  title,
                'href':   href,
                'img':    img,
                'meta':   meta,
                'source': 'BollyFlix',
            })
    except Exception as e:
        print(f"[search error] {e}")

    return jsonify(results)


@app.route('/tmdb')
def tmdb_route():
    q = request.args.get('q', '').strip()
    if not q or not TMDB_KEY:
        return jsonify(None)
    return jsonify(tmdb_search(q))


@app.route('/tmdb-details')
def tmdb_details_route():
    mid = request.args.get('id')
    if not mid or not TMDB_KEY:
        return jsonify(None)
    try:
        return jsonify(tmdb_details(int(mid)))
    except Exception:
        return jsonify(None)


@app.route('/details')
def details():
    src = request.args.get('source', '')
    url = request.args.get('url', '')
    if not url:
        return jsonify({'error': 'missing url'}), 400

    title     = ''
    downloads = []

    try:
        pg = soup(url)

        for sel in ['h1.entry-title', 'h1.post-title', 'h1']:
            el = pg.select_one(sel)
            if el:
                title = el.get_text(strip=True)
                break

        for a in pg.find_all('a', href=True):
            href = a.get('href', '').strip()
            txt  = a.get_text(strip=True)

            if not href or href.startswith('#') or 'javascript' in href:
                continue

            # Skip junk links
            combined = (href + txt).lower()
            skip = ['how to', 'howto', 'tutorial', 'facebook', 'twitter',
                    'instagram', 'telegram', 'whatsapp', 'youtube',
                    'category/', '/tag/', '/page/', 'mailto:',
                    'privacy', 'contact', 'about', 'dmca']
            if any(w in combined for w in skip):
                continue

            # Match download links
            is_dl = any(x in href for x in [
                'fastdlserver', 'gdflix', 'gofile', 'drive.google',
                'mega.nz', 'mediafire', 'pixeldrain', 'send.cm',
                'uploadhaven', 'filedot', 'buzzheavier', 'driveseed',
                'hubdrive', 'filepress', 'dropbox.com',
            ]) or (
                'download' in txt.lower() and len(txt) > 8 and
                any(q in txt.lower() for q in ['480p','720p','1080p','2160p','4k','bluray','webrip','web-dl','hdrip'])
            )

            if is_dl:
                dl = {
                    'name':    txt or 'Download',
                    'url':     href,
                    'quality': quality_label(txt + href),
                    'size':    'N/A',
                }
                nxt = a.next_sibling
                if nxt:
                    st = nxt.get_text(strip=True) if hasattr(nxt, 'get_text') else str(nxt).strip()
                    st = st.strip('[]()').strip()
                    if st and len(st) < 20:
                        dl['size'] = st
                downloads.append(dl)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    # Deduplicate
    seen, unique = set(), []
    for d in downloads:
        if d['url'] not in seen:
            seen.add(d['url'])
            unique.append(d)

    return jsonify({'title': title, 'downloads': unique})


@app.route('/')
def home():
    return render_template('index.html')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))


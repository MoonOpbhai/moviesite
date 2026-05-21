import re, os
from urllib.parse import quote, urlparse
from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.5',
    'Referer': 'https://www.google.com/',
}

BF_DOMAINS = [
    'https://new.bollyflix.gd',
    'https://bollyflix.show',
    'https://www.bollyflix.boats',
    'https://bollyflix.ind.in',
]

TMDB_KEY  = os.environ.get('TMDB_API_KEY', '')
TMDB_BASE = 'https://api.themoviedb.org/3'
TMDB_IMG  = 'https://image.tmdb.org/t/p'

# Known download hosting domains — sirf inke links real download links hain
DL_HOSTS = [
    'drive.google.com', 'mega.nz', 'mediafire.com', 'pixeldrain.com',
    'send.cm', 'gofile.io', 'uploadhaven.com', 'filedot.to',
    'buzzheavier.com', 'driveseed.org', 'hubdrive.me', 'filepress.me',
    'dropbox.com', 'fastdlserver.site', 'gdflix.dad', 'gdflix.pro',
    'gdflix.in', 'gdtot.men', 'gdtot.cfd', 'drivehub.in',
    'appdrive.info', 'driveace.in', 'drivebot.eu.org',
]

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
    url = request.args.get('url', '')
    if not url:
        return jsonify({'error': 'missing url'}), 400

    title     = ''
    downloads = []
    page_domain = urlparse(url).netloc  # e.g. new.bollyflix.gd

    try:
        pg = soup(url)

        # Title
        for sel in ['h1.entry-title', 'h1.post-title', 'h1']:
            el = pg.select_one(sel)
            if el:
                title = el.get_text(strip=True)
                break

        # Sirf main post content ke andar dekhenge
        content_area = (
            pg.select_one('.entry-content')
            or pg.select_one('.post-content')
            or pg.select_one('article')
            or pg
        )

        # Related posts / sidebar / nav hatao content se
        for junk in content_area.select(
            '.related-posts, .related, #related-posts, .post-related, '
            '.yarpp-related, .jp-relatedposts, .sidebar, #sidebar, '
            '.widget, nav, footer, header, .navigation, .post-navigation'
        ):
            junk.decompose()

        for a in content_area.find_all('a', href=True):
            href = a.get('href', '').strip()
            txt  = a.get_text(strip=True)

            if not href or href.startswith('#') or 'javascript' in href:
                continue

            # Same-site links skip — yeh navigation/related post links hain
            link_domain = urlparse(href).netloc
            if not link_domain or link_domain == page_domain:
                continue

            # Sirf known download hosts allow karo
            is_dl = any(host in link_domain for host in DL_HOSTS)
            if not is_dl:
                continue

            # Quality detect karo — parent heading se
            quality = 'N/A'

            # 1. Pehle link ke previous sibling headings check karo
            prev = a.find_previous(['h2', 'h3', 'h4', 'h5'])
            if prev:
                quality = quality_label(prev.get_text())

            # 2. Parent elements mein quality dhundo (max 4 levels up)
            if quality == 'N/A':
                level = 0
                for parent in a.parents:
                    if level > 4:
                        break
                    q = quality_label(parent.get_text()[:200])
                    if q != 'N/A':
                        quality = q
                        break
                    level += 1

            # 3. Link text ya URL se try karo
            if quality == 'N/A':
                quality = quality_label(txt + ' ' + href)

            downloads.append({
                'name':    txt or 'Download',
                'url':     href,
                'quality': quality,
                'size':    'N/A',
            })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    # Deduplicate by URL
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
    

# 🚀 GitHub → Render Deploy Guide
### Flask (Python) App — MoonVault

---

## Render kya hai?

Render ek hosting platform hai jo **Python/Flask apps directly** run kar sakta hai — Cloudflare Workers ki tarah convert karne ki zaroorat nahi. Yahan original `app.py` waise hi kaam karta hai.

---

## Repo Structure (jo hona chahiye)

```
moviesite-main/
├── app.py               ← Flask app (kuch change nahi)
├── requirements.txt     ← Python dependencies
├── render.yaml          ← Render config (Procfile ki jagah)
└── templates/
    └── index.html       ← Frontend
```

---

## Step 1 — GitHub pe repo banao

```bash
cd moviesite-main
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/TUMHARA_USERNAME/moviesite.git
git push -u origin main
```

---

## Step 2 — render.yaml banao (Procfile replace karo)

Repo mein `Procfile` hai jo **galat format** mein hai. Uski jagah `render.yaml` banao:

```yaml
services:
  - type: web
    name: moonvault
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: waitress-serve --listen=0.0.0.0:$PORT app:app
    envVars:
      - key: TMDB_API_KEY
        sync: false
```

> ❌ Original Procfile mein `startCommand:web:` galat tha — colon extra tha  
> ✅ `render.yaml` use karo — yeh sahi aur recommended hai

---

## Step 3 — Render Dashboard pe deploy karo

1. **https://render.com** pe jao → Sign up / Login
2. **New → Web Service**
3. **Connect GitHub** → apna repo select karo
4. Yeh settings verify karo:

| Setting | Value |
|---------|-------|
| Runtime | **Python 3** |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `waitress-serve --listen=0.0.0.0:$PORT app:app` |
| Plan | Free |

5. **Environment Variables** section mein add karo:
```
TMDB_API_KEY = tumhari_tmdb_key
```

6. **Create Web Service** button dabao

---

## Step 4 — Auto Deploy (GitHub se)

Render by default **har git push pe auto-deploy** karta hai. Koi extra setup nahi chahiye.

```bash
# Code change karo, push karo — automatic deploy!
git add .
git commit -m "Update"
git push
```

---

## requirements.txt (sahi wala)

```
flask==2.3.0
beautifulsoup4==4.12.0
requests==2.28.0
waitress==3.0.0
```

> Yeh sab sahi hain — kuch change karne ki zaroorat nahi

---

## Environment Variables

| Variable | Value | Zaruri? |
|----------|-------|---------|
| `TMDB_API_KEY` | TMDB se milega | Optional (posters/ratings ke liye) |
| `PORT` | Render khud set karta hai | Auto |

TMDB key kahan se milegi: **https://www.themoviedb.org/settings/api** (free)

---

## Free Plan Limitations

| Limitation | Details |
|-----------|---------|
| **Sleep** | 15 min inactivity ke baad service so jaati hai |
| **Wake time** | Pehli request 30-60 sec lag sakti hai |
| **Hours** | 750 free hours/month |
| **RAM** | 512 MB |

> Free plan pe pehli request slow hogi — yeh normal hai

---

## Render vs Cloudflare Workers

| | Render | Cloudflare Workers |
|---|--------|-------------------|
| Language | Python direct | JavaScript only |
| Flask support | ✅ Native | ❌ Convert karna padta hai |
| Setup | Easy | Complex |
| Cold start | ~30-60 sec | Instant |
| Free tier | 750 hrs/month | 100K req/day |
| Custom domain | ✅ | ✅ |

---

## Common Errors aur Fix

| Error | Cause | Fix |
|-------|-------|-----|
| `No module named flask` | requirements.txt nahi mila | File root mein hai check karo |
| `Address already in use` | PORT issue | `$PORT` env variable use ho raha hai check karo |
| `Build failed` | Python version mismatch | render.yaml mein `pythonVersion: 3.11.0` add karo |
| Site nahi khul raha | Free plan sleep | 30 sec wait karo |
| TMDB data nahi | Key missing | Dashboard → Environment → `TMDB_API_KEY` add karo |

---

## Python Version fix (agar build fail ho)

`render.yaml` mein add karo:

```yaml
services:
  - type: web
    name: moonvault
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: waitress-serve --listen=0.0.0.0:$PORT app:app
    pythonVersion: "3.11.0"
    envVars:
      - key: TMDB_API_KEY
        sync: false
```

---

## Deploy ke baad URL

Render ek URL deta hai jaise:
```
https://moonvault.onrender.com
```

Custom domain lagane ke liye: **Dashboard → Settings → Custom Domains**

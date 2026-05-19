services:
  - type: web
    name: movie-engine
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand:web: waitress-serve --listen=0.0.0.0:$PORT app:app
    envVars:
      - key: NODE_ENV
        value: production
      - key: TMDB_API_KEY
        value: YOUR_TMDB_API_KEY

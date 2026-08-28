# Agentic CRM — Frontend

Vite + React + TypeScript + Tailwind CSS UI for the FastAPI CRM agents.

## Develop

Start the backend first (`cd backend && uvicorn main:app --reload --port 8000`), then:

```bash
npm install
npm run dev
```

App: http://localhost:5173  
API calls are proxied to `http://127.0.0.1:8000`.

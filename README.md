# RepLit – Reporting Emergencies in Real Time

A real-time emergency incident reporting and dispatch coordination system.

## Stack
- **Backend**: FastAPI (Python 3.11)
- **Database**: Supabase (PostgreSQL + PostGIS)
- **Auth**: Supabase Auth + JWT
- **Storage**: Supabase Storage
- **Realtime**: WebSockets (FastAPI)
- **AI**: Claude Sonnet (Anthropic)
- **Notifications**: Firebase Cloud Messaging (FCM)
- **Deployment**: DigitalOcean + Docker + Nginx

## Quickstart

```bash
cp .env.example .env        # Fill in your credentials
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Docs
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Phases
- [x] Phase 1 – Repository Setup
- [x] Phase 2 – Supabase Database Setup
- [x] Phase 3 – FastAPI Initialization
- [ ] Phase 4 – Authentication
- [ ] Phase 5 – Incident Management
- [ ] Phase 6 – Realtime & Notifications
- [ ] Phase 7 – AI Integration
- [ ] Phase 8 – CI/CD & Deployment
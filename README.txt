# FlowDesk — Team Task Manager

A full-stack team task management application with role-based access control.

## Features

- Authentication — JWT-based signup/login, token persisted in localStorage
- Projects — Create, update, delete projects; each creator becomes Admin
- Team Management — Invite members by search, assign Admin/Member roles, remove members
- Tasks — Create, assign, update, delete tasks with priority/status/due date
- Kanban Board — Visual To Do / In Progress / Done columns per project
- Dashboard — Stats overview, recent activity, overdue tasks
- Role-Based Access Control:
  - Admin: Full project control (manage members, all tasks, delete project)
  - Member: View all tasks, edit own assigned/created tasks

## Tech Stack

- Backend: Flask (Python), SQLAlchemy ORM
- Database: SQLite (dev) / PostgreSQL (production via Railway)
- Auth: JWT (flask-jwt-extended)
- Frontend: Vanilla HTML/CSS/JS (single file, no build step)
- Deployment: Railway with Gunicorn

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
# Visits http://localhost:5000
```

## Deploy to Railway

### Option 1: Railway CLI (Fastest)

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Create project and deploy
railway init
railway up

# Add PostgreSQL database
railway add --plugin postgresql

# Set environment variables
railway variables set JWT_SECRET_KEY="your-super-secret-key-here"

# Open your live app
railway open
```

### Option 2: GitHub + Railway Dashboard

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Select your repository
4. Railway auto-detects Python and deploys
5. Add a PostgreSQL plugin: Dashboard → New → Database → PostgreSQL
6. Set environment variable: `JWT_SECRET_KEY` = any long random string
7. Railway auto-injects `DATABASE_URL` — the app handles it automatically

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `JWT_SECRET_KEY` | Yes | Secret key for JWT signing (use a long random string) |
| `DATABASE_URL` | Auto (Railway) | PostgreSQL URL — auto-set by Railway PostgreSQL plugin |
| `PORT` | Auto (Railway) | Port — auto-set by Railway |

## API Reference

### Auth
- `POST /api/auth/signup` — `{name, email, password}` → `{token, user}`
- `POST /api/auth/login` — `{email, password}` → `{token, user}`
- `GET /api/auth/me` — Returns current user

### Projects
- `GET /api/projects` — List user's projects
- `POST /api/projects` — `{name, description}`
- `GET /api/projects/:id`
- `PUT /api/projects/:id` — Admin only
- `DELETE /api/projects/:id` — Owner only

### Members
- `POST /api/projects/:id/members` — `{user_id, role}` — Admin only
- `DELETE /api/projects/:id/members/:uid` — Admin only
- `PUT /api/projects/:id/members/:uid/role` — `{role}` — Admin only

### Tasks
- `GET /api/projects/:id/tasks`
- `POST /api/projects/:id/tasks` — `{title, description, priority, status, assignee_id, due_date}`
- `PUT /api/projects/:id/tasks/:tid`
- `DELETE /api/projects/:id/tasks/:tid`

### Dashboard
- `GET /api/dashboard` — Stats, recent & overdue tasks

## Project Structure

```text
task-manager/
├── app.py              # Flask app + all API routes + frontend serving
├── frontend/
│   └── index.html      # Complete SPA frontend
├── requirements.txt    # Python dependencies
├── Procfile            # Railway/Heroku process definition
├── railway.json        # Railway config
├── nixpacks.toml       # Build config
└── README.md
```
